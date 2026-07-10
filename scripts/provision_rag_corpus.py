"""Vertex RAG Engine（保育所保育指針コーパス）の作成・取り込みスクリプト（手動運用・要 GCP 資格情報）。

設計コンテキスト §6 ツール表 / §9 メモリ3分類 / §11 技術スタック：静的ナレッジ（保育所保育指針の
告示・解説、10の姿・3つの視点、保育所児童保育要録関係資料）は Vertex RAG に置き、作成AI／レビューAI が
`search_guideline` で「中身を決定」する際に自分で取りに行く（Agentic RAG）。本スクリプトはその接続先
コーパスを用意する、再現可能な provisioning エントリ（root_agent からは呼ばない。
`provision_memory_bank.py` と対をなす運用ツール）。

何をするか:
- RagCorpus を作成（または既存 `RAG_CORPUS` を再利用）し、`knowledge/保育所保育指針/` 配下の文書
  （PDF/TXT 等）を埋め込み・チャンク分割して取り込む。最後に `.env` に入れる `RAG_CORPUS` を表示する。
- 埋め込みは日本語に強い `text-multilingual-embedding-002` を既定にする（指針の日本語本文向け）。
- 取り込み（embedding/indexing）はサーバ側で非同期に進む。完了確認は `search_guideline` の往復、または
  `--verify` で簡易検索して確認する。

ソース文書（gitignore 済み・§14。実データではなく公的刊行物）:
- `knowledge/保育所保育指針/` に、保育所保育指針の告示本文・全章の解説・保育所児童保育要録の
  通知／記載事項／参考様式を置く。取得元とファイル名は `docs/ライブ実行手順.md` を正とする。
  告示本体は法令類（著作権法13条）で利用可、解説・要録関係資料も公式の無償公開物。リポジトリには
  コミットしない。

使い方（要 ADC＝`gcloud auth application-default login` 済み・`.env` に PROJECT/LOCATION）:
    uv run python scripts/provision_rag_corpus.py --create     # 新規コーパス作成＋取り込み
    uv run python scripts/provision_rag_corpus.py              # 既存 RAG_CORPUS に新規分のみ追加（未設定なら新規作成にフォールバック）
    uv run python scripts/provision_rag_corpus.py --verify "1歳児 言葉 ねらい"   # 取り込み後の検索確認

設定後は `.env` に `RAG_CORPUS=<corpus resource name>` を記入 → `adk web src` / `uvicorn server:app` で
`search_guideline` が実コーパスを引く（`docs/ライブ実行手順.md`）。
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import google.auth
import google.auth.transport.requests
import vertexai
from vertexai import rag

from hoiku_agent.config import settings

# 既定のソース文書置き場（gitignore 済み）。ここに告示・解説・要録関係 PDF 等を置く。
_DEFAULT_SOURCE_DIR = Path(__file__).resolve().parents[1] / "knowledge" / "保育所保育指針"
# 取り込み対象の拡張子（Vertex RAG がサーバ側でパースできる形式に限る）。
_SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".html", ".docx"}
# 既定の埋め込みモデル：日本語本文の検索精度のため多言語版を使う（§11）。
_DEFAULT_EMBEDDING_MODEL = "text-multilingual-embedding-002"


def _backend_config(embedding_model: str) -> rag.RagVectorDbConfig:
    """埋め込みモデルを指定した RagManagedDb バックエンド設定を返す。"""
    return rag.RagVectorDbConfig(
        rag_embedding_model_config=rag.RagEmbeddingModelConfig(
            vertex_prediction_endpoint=rag.VertexPredictionEndpoint(
                publisher_model=f"publishers/google/models/{embedding_model}"
            )
        )
    )


def _collect_docs(source_dir: Path) -> list[Path]:
    """ソースディレクトリから取り込み対象ファイルを集める（gitkeep 等は除外）。"""
    if not source_dir.exists():
        raise SystemExit(f"ソースディレクトリが無い: {source_dir}")
    docs = sorted(
        p for p in source_dir.iterdir() if p.is_file() and p.suffix.lower() in _SUPPORTED_SUFFIXES
    )
    if not docs:
        raise SystemExit(
            f"取り込めるファイルが無い: {source_dir}（{sorted(_SUPPORTED_SUFFIXES)} を置く）"
        )
    return docs


def _ensure_serverless_mode(project: str, location: str) -> None:
    """RagManagedDb をプロジェクト単位で Serverless モードに切り替える（冪等）。

    新規プロジェクトは Spanner モード既定で、us-central1/us-east1/us-east4 では allowlist 制限のため
    `create_corpus` が INVALID_ARGUMENT で弾かれる（実機で確定）。Serverless モードは vertexai 1.158.0 の
    SDK では未対応（`Basic`/`Scaled` は Spanner 内のティアで `Serverless` 不在）なので、REST の
    UpdateRagEngineConfig（`ragManagedDbConfig.serverless={}`）で設定する。
    """
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    session = google.auth.transport.requests.AuthorizedSession(creds)
    url = (
        f"https://{location}-aiplatform.googleapis.com/v1beta1/"
        f"projects/{project}/locations/{location}/ragEngineConfig"
    )
    # updateMask はこの singleton エンドポイントでは query パラメータとして拒否される（実機確認:
    # ?updateMask=... は "Cannot bind query parameter" で 400）。body のみで serverless に切り替わる。
    resp = session.patch(url, json={"ragManagedDbConfig": {"serverless": {}}})
    resp.raise_for_status()
    print("RagManagedDb モード: serverless（プロジェクト設定・REST UpdateRagEngineConfig）")


# create_corpus が「伝播待ち」で一時的に失敗するときのメッセージ目印（serverless 切替・API 有効化の遅延）。
# create_corpus は内部の InvalidArgument 等を RuntimeError に包むため、型ではなくメッセージで判定する。
_TRANSIENT_CREATE_MARKERS = (
    "Spanner mode",
    "allowlist",
    "restricted",
    "Serverless",
    "Vector Search API has not been used",
    "vectorsearch.googleapis.com",
    "wait a few minutes",
)


def _is_transient_create_error(exc: Exception) -> bool:
    """create_corpus の失敗が「伝播待ち」（後でリトライすれば直る）一過性のものか。"""
    return any(marker in str(exc) for marker in _TRANSIENT_CREATE_MARKERS)


def _create_corpus_with_retry(
    embedding_model: str, retries: int = 12, wait_seconds: int = 30
) -> rag.RagCorpus:
    """RagCorpus を作成する。serverless 切替・API 有効化の直後は伝播待ちで一時的に失敗し得るためリトライ。

    create_corpus は内部の例外を RuntimeError 等に包んで投げるため、メッセージで「伝播待ち」と判定した
    ときだけリトライし、それ以外の失敗は即座に投げ直す（誤って握り潰さない）。対象は (1) serverless 切替の
    伝播（Spanner mode / allowlist 制限）、(2) serverless が内部で使う Vector Search API 有効化の伝播。
    """
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return rag.create_corpus(
                display_name="hoiku-hoikushishin",
                description="保育所保育指針（告示・解説）・要録関係資料（静的ナレッジ／Agentic RAG ソース）",
                backend_config=_backend_config(embedding_model),
            )
        except Exception as e:  # noqa: BLE001  SDK は InvalidArgument を RuntimeError に包む
            if not _is_transient_create_error(e):
                raise
            last_err = e
            print(
                f"  作成リトライ {attempt}/{retries}（serverless 切替の伝播待ち {wait_seconds}s）…"
            )
            time.sleep(wait_seconds)
    raise SystemExit(f"RagCorpus 作成に失敗（serverless 切替の伝播待ちタイムアウト）: {last_err}")


def provision(
    create: bool,
    source_dir: Path,
    chunk_size: int,
    chunk_overlap: int,
    embedding_model: str,
) -> str:
    """RagCorpus を作成/再利用し、ソース文書を取り込んで corpus resource name を返す。"""
    project = settings.google_cloud_project
    location = settings.google_cloud_location
    if not project:
        raise SystemExit("GOOGLE_CLOUD_PROJECT が未設定です（.env を確認）。")

    vertexai.init(project=project, location=location)

    if create or not settings.rag_corpus:
        _ensure_serverless_mode(project, location)
        corpus = _create_corpus_with_retry(embedding_model)
        print(f"作成: {corpus.name}（埋め込み: {embedding_model}）")
    else:
        corpus = rag.get_corpus(name=settings.rag_corpus)
        print(f"再利用: {corpus.name}")

    docs = _collect_docs(source_dir)
    transformation_config = rag.TransformationConfig(
        chunking_config=rag.ChunkingConfig(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    )
    # 冪等性：upload_file は同名 display_name でも重複登録する（dedup しない）ので、既に取り込み済みの
    # ファイルはスキップする（再実行で全件二重登録＝チャンク重複・埋め込みコスト浪費を防ぐ。文書を更新
    # したいときは手動で rag.delete_file してから再実行する）。
    existing = {getattr(f, "display_name", "") for f in rag.list_files(corpus_name=corpus.name)}
    uploaded = skipped = failed = 0
    print(f"取り込み対象 {len(docs)} 件（chunk_size={chunk_size}, overlap={chunk_overlap}）:")
    for doc in docs:
        if doc.name in existing:
            print(f"  - {doc.name}（取り込み済み・スキップ）")
            skipped += 1
            continue
        try:
            rag.upload_file(
                corpus_name=corpus.name,
                path=str(doc),
                display_name=doc.name,
                description="保育所保育指針（静的ナレッジ）",
                transformation_config=transformation_config,
            )
            print(f"  ✓ {doc.name}")
            uploaded += 1
        except Exception as e:  # noqa: BLE001  1件の失敗で全体を止めない（残りは継続・最後に要約）
            print(f"  ✗ {doc.name}: {type(e).__name__}: {e}")
            failed += 1

    print(
        f"取り込み登録: 新規 {uploaded} / スキップ {skipped} / 失敗 {failed}"
        "（embedding/indexing はサーバ側で非同期）。\n"
        f".env に設定: RAG_CORPUS={corpus.name}"
    )
    return corpus.name


def verify(query: str, top_k: int = 4) -> None:
    """取り込み後の検索確認（search_guideline と同じ retrieval_query で往復を見る）。"""
    if not settings.rag_corpus:
        raise SystemExit("RAG_CORPUS 未設定（.env に設定してから --verify）。")
    vertexai.init(
        project=settings.google_cloud_project or None,
        location=settings.google_cloud_location or None,
    )
    response = rag.retrieval_query(
        rag_resources=[rag.RagResource(rag_corpus=settings.rag_corpus)],
        text=query,
        rag_retrieval_config=rag.RagRetrievalConfig(top_k=top_k),
    )
    contexts = getattr(getattr(response, "contexts", None), "contexts", None) or []
    print(f"クエリ『{query}』→ {len(contexts)} 件")
    for i, c in enumerate(contexts, 1):
        text = (getattr(c, "text", "") or "").replace("\n", " ")
        print(f"  [{i}] {text[:120]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Vertex RAG Engine（保育所保育指針）の作成・取り込み")
    ap.add_argument("--create", action="store_true", help="新規に RagCorpus を作成する")
    ap.add_argument(
        "--source-dir", default=str(_DEFAULT_SOURCE_DIR), help="取り込むソース文書のディレクトリ"
    )
    ap.add_argument("--chunk-size", type=int, default=512, help="チャンクサイズ（トークン）")
    ap.add_argument("--chunk-overlap", type=int, default=128, help="チャンクオーバーラップ")
    ap.add_argument(
        "--embedding-model",
        default=_DEFAULT_EMBEDDING_MODEL,
        help="埋め込みモデル（publisher model）",
    )
    ap.add_argument(
        "--verify", metavar="QUERY", help="取り込み確認: このクエリで検索して結果を表示"
    )
    args = ap.parse_args()

    if args.verify:
        verify(args.verify)
        return

    provision(
        create=args.create,
        source_dir=Path(args.source_dir),
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        embedding_model=args.embedding_model,
    )


if __name__ == "__main__":
    main()
