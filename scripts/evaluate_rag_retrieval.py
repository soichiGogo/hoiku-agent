"""Vertex RAG の検索品質を、公式資料への到達度で比較する運用スクリプト。

静的ナレッジは、保育所保育指針の告示・解説と保育所児童保育要録関係資料で構成する。
本スクリプトは本番コーパスを書き換えない。一時コーパスに同じ資料を投入し、
`tests/fixtures/rag_retrieval_cases.json` の質問に対して次を決定的に採点する。

- 期待する公式資料が何位に返るか（reciprocal rank）
- 期待する根拠フレーズを検索結果が含むか（term coverage）

評価後の一時コーパスは既定で削除する。`--keep-corpora` は障害調査時だけ使う。
PDF 原本と `.env` は gitignore 対象であり、コミットしない。
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import vertexai
from vertexai import rag

from hoiku_agent.config import settings

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SOURCE_DIR = _ROOT / "knowledge" / "保育所保育指針"
_DEFAULT_CASE_PATH = _ROOT / "tests" / "fixtures" / "rag_retrieval_cases.json"
_SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".html", ".docx"}
_EMBEDDING_MODEL = "text-multilingual-embedding-002"


@dataclass(frozen=True)
class RetrievalCase:
    """期待する公式資料と根拠フレーズを持つ検索評価ケース。"""

    id: str
    query: str
    expected_source: str
    required_terms: tuple[str, ...]


@dataclass(frozen=True)
class ChunkProfile:
    """比較するインデックス分割設定。"""

    name: str
    chunk_size: int
    chunk_overlap: int


@dataclass(frozen=True)
class RetrievedChunk:
    """Vertex RAG が返した最小限の検索結果。"""

    source: str
    text: str


def load_cases(path: Path) -> list[RetrievalCase]:
    """JSON の検索評価ケースを読み、重複や空欄を早期に検出する。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = [
        RetrievalCase(
            id=item["id"],
            query=item["query"],
            expected_source=item["expected_source"],
            required_terms=tuple(item["required_terms"]),
        )
        for item in raw
    ]
    ids = [case.id for case in cases]
    if not cases or len(ids) != len(set(ids)):
        raise ValueError("検索評価ケースが空、または id が重複しています")
    if any(not case.query or not case.expected_source or not case.required_terms for case in cases):
        raise ValueError("検索評価ケースに query / expected_source / required_terms の空欄があります")
    return cases


def _normalized(value: str) -> str:
    """PDF 抽出時の改行・空白差を吸収してフレーズ照合する。"""
    return "".join(value.replace("\u3000", " ").split())


def score_case(case: RetrievalCase, results: list[RetrievedChunk]) -> dict[str, Any]:
    """1ケースを資料順位と根拠語の網羅率で決定的に採点する。"""
    expected_rank = next(
        (index for index, result in enumerate(results, start=1) if result.source == case.expected_source),
        None,
    )
    source_rr = 1 / expected_rank if expected_rank else 0.0
    combined = _normalized("\n".join(result.text for result in results))
    matched_terms = [term for term in case.required_terms if _normalized(term) in combined]
    term_coverage = len(matched_terms) / len(case.required_terms)
    # 期待資料が出ても、不要に多数のチャンクを返す設定を過大評価しない。
    source_precision = (1 / len(results)) if expected_rank else 0.0
    score = 0.65 * source_rr + 0.25 * term_coverage + 0.10 * source_precision
    return {
        "id": case.id,
        "expected_source": case.expected_source,
        "expected_rank": expected_rank,
        "source_rr": source_rr,
        "term_coverage": term_coverage,
        "matched_terms": matched_terms,
        "score": score,
        "sources": [result.source for result in results],
        "context_characters": sum(len(result.text) for result in results),
    }


def aggregate_case_scores(case_scores: list[dict[str, Any]]) -> dict[str, float]:
    """設定を比較するための平均指標を返す。"""
    if not case_scores:
        raise ValueError("検索結果がありません")
    count = len(case_scores)
    return {
        "mean_score": sum(item["score"] for item in case_scores) / count,
        "source_hit_rate": sum(item["expected_rank"] is not None for item in case_scores) / count,
        "mean_source_rr": sum(item["source_rr"] for item in case_scores) / count,
        "mean_term_coverage": sum(item["term_coverage"] for item in case_scores) / count,
        "mean_context_characters": sum(item["context_characters"] for item in case_scores) / count,
    }


def choose_winner(results: list[dict[str, Any]]) -> dict[str, Any]:
    """品質を最優先し、同点なら短い文脈を返す設定を選ぶ。"""
    if not results:
        raise ValueError("比較結果がありません")
    return max(
        results,
        key=lambda item: (
            item["metrics"]["mean_score"],
            item["metrics"]["source_hit_rate"],
            item["metrics"]["mean_source_rr"],
            -item["metrics"]["mean_context_characters"],
        ),
    )


def _source_files(source_dir: Path) -> list[Path]:
    files = sorted(
        path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() in _SUPPORTED_SUFFIXES
    )
    if not files:
        raise ValueError(f"投入できる公式資料がありません: {source_dir}")
    return files


def _backend_config() -> rag.RagVectorDbConfig:
    return rag.RagVectorDbConfig(
        rag_embedding_model_config=rag.RagEmbeddingModelConfig(
            vertex_prediction_endpoint=rag.VertexPredictionEndpoint(
                publisher_model=f"publishers/google/models/{_EMBEDDING_MODEL}"
            )
        )
    )


def _is_active(rag_file: Any) -> bool:
    state = getattr(getattr(rag_file, "file_status", None), "state", None)
    return getattr(state, "name", str(state)) == "ACTIVE"


def _wait_for_active(corpus_name: str, expected_count: int, timeout_seconds: int) -> None:
    """全ファイルの索引完了を待つ。未完了のまま採点して偽の低スコアを出さない。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        files = list(rag.list_files(corpus_name=corpus_name))
        if len(files) == expected_count and all(_is_active(item) for item in files):
            return
        time.sleep(5)
    raise TimeoutError(f"RAG ファイルが ACTIVE になりませんでした: {corpus_name}")


def _create_corpus(profile: ChunkProfile) -> str:
    suffix = uuid.uuid4().hex[:8]
    corpus = rag.create_corpus(
        display_name=f"hoiku-rag-eval-{profile.name}-{suffix}",
        description="一時的な検索品質評価用コーパス。評価終了後に削除する。",
        backend_config=_backend_config(),
    )
    return corpus.name


def _upload_sources(corpus_name: str, files: list[Path], profile: ChunkProfile) -> None:
    transformation_config = rag.TransformationConfig(
        chunking_config=rag.ChunkingConfig(
            chunk_size=profile.chunk_size,
            chunk_overlap=profile.chunk_overlap,
        )
    )
    for path in files:
        rag.upload_file(
            corpus_name=corpus_name,
            path=str(path),
            display_name=path.name,
            description="保育所保育指針の公式資料（RAG 検索品質評価用）",
            transformation_config=transformation_config,
        )


def _retrieve(corpus_name: str, query: str, top_k: int) -> list[RetrievedChunk]:
    response = rag.retrieval_query(
        rag_resources=[rag.RagResource(rag_corpus=corpus_name)],
        text=query,
        rag_retrieval_config=rag.RagRetrievalConfig(top_k=top_k),
    )
    contexts = getattr(getattr(response, "contexts", None), "contexts", None) or []
    return [
        RetrievedChunk(
            source=getattr(context, "source_uri", None) or "",
            text=getattr(context, "text", "") or "",
        )
        for context in contexts
        if getattr(context, "text", "")
    ]


def evaluate_profile(
    profile: ChunkProfile,
    top_ks: list[int],
    cases: list[RetrievalCase],
    files: list[Path],
    timeout_seconds: int,
    keep_corpora: bool,
) -> list[dict[str, Any]]:
    """1つの分割設定を作成・検索・削除し、top_k ごとの結果を返す。"""
    corpus_name = _create_corpus(profile)
    try:
        _upload_sources(corpus_name, files, profile)
        _wait_for_active(corpus_name, expected_count=len(files), timeout_seconds=timeout_seconds)
        evaluations: list[dict[str, Any]] = []
        for top_k in top_ks:
            case_scores = [score_case(case, _retrieve(corpus_name, case.query, top_k)) for case in cases]
            evaluations.append(
                {
                    "profile": asdict(profile),
                    "top_k": top_k,
                    "metrics": aggregate_case_scores(case_scores),
                    "cases": case_scores,
                }
            )
        return evaluations
    finally:
        if not keep_corpora:
            rag.delete_corpus(name=corpus_name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Vertex RAG のチャンク設定を公式資料の検索到達度で比較")
    parser.add_argument("--source-dir", type=Path, default=_DEFAULT_SOURCE_DIR)
    parser.add_argument("--case-path", type=Path, default=_DEFAULT_CASE_PATH)
    parser.add_argument("--top-k", type=int, nargs="+", default=[3, 4, 6])
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--output", type=Path, help="比較結果JSONの出力先（省略時は標準出力）")
    parser.add_argument("--keep-corpora", action="store_true", help="障害調査用に一時コーパスを削除しない")
    args = parser.parse_args()

    if not settings.google_cloud_project:
        raise SystemExit("GOOGLE_CLOUD_PROJECT が未設定です")
    if any(value < 1 for value in args.top_k):
        raise SystemExit("top_k は1以上で指定してください")

    vertexai.init(project=settings.google_cloud_project, location=settings.google_cloud_location)
    cases = load_cases(args.case_path)
    files = _source_files(args.source_dir)
    profiles = [
        ChunkProfile("compact", chunk_size=384, chunk_overlap=96),
        ChunkProfile("balanced", chunk_size=512, chunk_overlap=128),
        ChunkProfile("broad", chunk_size=768, chunk_overlap=192),
    ]

    results: list[dict[str, Any]] = []
    for profile in profiles:
        print(f"評価中: {profile.name} ({profile.chunk_size}/{profile.chunk_overlap})", flush=True)
        results.extend(
            evaluate_profile(
                profile,
                top_ks=sorted(set(args.top_k)),
                cases=cases,
                files=files,
                timeout_seconds=args.timeout_seconds,
                keep_corpora=args.keep_corpora,
            )
        )

    report = {
        "source_file_count": len(files),
        "case_count": len(cases),
        "results": results,
        "winner": choose_winner(results),
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"結果を書き出しました: {args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
