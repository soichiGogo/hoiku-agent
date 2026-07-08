"""設定。.env / 環境変数から読み込む。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # GCP / Vertex。google_cloud_location は RAG corpus / Memory Bank のリージョン（regional 専用）。
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    google_genai_use_vertexai: bool = True

    # モデル（最新の Gemini モデルIDに合わせる）。
    gemini_model: str = "gemini-3.5-flash"
    # 生成モデルだけを別エンドポイントへ固定する location（Gemini 3.x は Vertex global 専用＝
    # RAG/Memory の google_cloud_location と同居不可なので分離する。§11／models.build_model）。
    # 空にすると google_cloud_location を使う＝従来動作（regional モデル向け）。
    model_location: str = "global"

    # 静的ナレッジ＝Vertex RAG corpus（保育所保育指針・10の姿）。空なら search_guideline は降格。
    rag_corpus: str = ""
    # 子ども長期記憶＝Agent Engine Memory Bank の ID（recall_child_history が使う）。
    # 用途は Memory Bank に限定する（Runtime 名残と混同しない＝設計コンテキスト §9）。
    agent_engine_id: str = ""

    # 過去書類アーカイブ（search_past_documents が引くローカルディレクトリ）。空なら repo の data/records。
    # 実データは置かない＝架空児のみ（gitignore 済み・§14）。
    records_dir: str = ""

    # ストレージ DB（Cloud SQL PostgreSQL）＝書類アーカイブ（harness/record_store）と
    # 育つ指針カードブック（harness/policy_store・Phase 2 で GCS から統合）が共有する。
    # SQLAlchemy URL（例: postgresql+psycopg://user:pass@host/db。Cloud Run は
    # `?host=/cloudsql/<PROJECT:REGION:INSTANCE>` の unix ソケット直結）。未設定は降格＝
    # アーカイブは永続化しない・指針はローカルファイル（knowledge/文書作成指針.json）＝
    # RAG_CORPUS / AGENT_ENGINE_ID と同じ「未設定は降格」パターン。
    database_url: str = ""

    # 配布デモUI（B-full）の簡易共有パスコード。設定すると LLM を回す口（/run・/run_sse・
    # /run_live・/api/improve）が要パスコードになり、無認証の公開リンクで Gemini 課金が
    # 野放しになるのを防ぐ。空なら無効＝ローカル開放（src/hoiku_agent/web）。
    demo_passcode: str = ""

    # 可観測性＝Cloud Trace へのスパンエクスポート（ADK ネイティブの trace_to_cloud を server.py が
    # 中継）。true にすると agent 実行・LLM 呼び出し・ツール呼び出しの OTel スパンが Cloud Trace へ
    # 送られ、1リクエストの軌跡（どのツールを呼び・どこで時間を食ったか）を Trace エクスプローラで
    # 追える（GOOGLE_CLOUD_PROJECT ＋ 書込権限 roles/cloudtrace.agent が前提）。既定 false＝ローカル/
    # CI/テストでは送らない（本番は deploy.yml が TRACE_TO_CLOUD=true を注入する）。ログ相関
    # （logging_config の X-Cloud-Trace-Context）と対になる観測の両輪。
    trace_to_cloud: bool = False

    # IAP for Cloud Run（Phase 3 認証）の JWT audience（IAP 設定画面/ドキュメントの値）。
    # 設定すると web が `x-goog-iap-jwt-assertion` ヘッダを署名検証し、検証済みの Google アカウント
    # email を actor（承認・編集の証跡）に使う。未設定は完全降格＝ヘッダを一切信用しない
    # （actor は従来どおり自己申告。IAP を有効化していない面でヘッダ偽装を防ぐ fail-closed）。
    iap_audience: str = ""

    @property
    def memory_service_uri(self) -> str | None:
        """Memory Bank の接続 URI（ADK の --memory_service_uri 互換）。

        設計コンテキスト §9：Memory Bank は Agent Engine Runtime に載せ替えず、マネージドの
        メモリサービスとして "呼ぶだけ"。ADK は `agentengine://<id>` を渡せば
        `VertexAiMemoryBankService` を自動構築して Runner に挿す（自前 Runner は組まない）。
        ここが agent_engine_id → URI の唯一の変換点。未設定なら None＝ADK が InMemory に降格する。
        """
        return f"agentengine://{self.agent_engine_id}" if self.agent_engine_id else None

    @property
    def session_service_uri(self) -> str | None:
        """セッション永続化の接続 URI（ADK の --session_service_uri 互換）。

        未指定だと ADK は InMemorySessionService＝各インスタンスのメモリ内に降格する。Cloud Run は
        複数インスタンス＋scale-to-zero でメモリが揮発するため、作成したセッションが別インスタンス／
        再起動で失われ `/apps/.../sessions/{id}` が 404 になる（ローカル単一プロセスでは顕在化しない）。
        子ども長期記憶と同じ Agent Engine を共有セッションストアに流用し（`agentengine://<id>`＝ADK が
        `VertexAiSessionService` を自動構築）、インスタンス跨ぎでもセッションを保持する（§9：ADK ネイティブに
        委ね自前 Runner を組まない）。memory_service_uri と同じく agent_engine_id が唯一の変換元。未設定なら
        None＝ADK が InMemory に降格する（ローカルは問題なし）。
        """
        return f"agentengine://{self.agent_engine_id}" if self.agent_engine_id else None


settings = Settings()
