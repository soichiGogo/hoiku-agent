"""設定。.env / 環境変数から読み込む。"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # GCP / Vertex
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    google_genai_use_vertexai: bool = True

    # モデル（最新の Gemini モデルIDに合わせる）
    gemini_model: str = "gemini-2.5-pro"

    # 静的ナレッジ＝Vertex RAG corpus（保育所保育指針・10の姿）。空なら search_guideline は降格。
    rag_corpus: str = ""
    # 子ども長期記憶＝Agent Engine Memory Bank の ID（recall_child_history が使う）。
    # 用途は Memory Bank に限定する（Runtime 名残と混同しない＝設計コンテキスト §9）。
    agent_engine_id: str = ""

    # 過去書類アーカイブ（search_past_documents が引くローカルディレクトリ）。空なら repo の data/records。
    # 実データは置かない＝架空児のみ（gitignore 済み・§14）。
    records_dir: str = ""

    # 配布デモUI（B-full）の簡易共有パスコード。設定すると LLM を回す口（/run・/run_sse・
    # /run_live・/api/improve）が要パスコードになり、無認証の公開リンクで Gemini 課金が
    # 野放しになるのを防ぐ。空なら無効＝ローカル開放（src/hoiku_agent/web）。
    demo_passcode: str = ""

    @property
    def memory_service_uri(self) -> str | None:
        """Memory Bank の接続 URI（ADK の --memory_service_uri 互換）。

        設計コンテキスト §9：Memory Bank は Agent Engine Runtime に載せ替えず、マネージドの
        メモリサービスとして "呼ぶだけ"。ADK は `agentengine://<id>` を渡せば
        `VertexAiMemoryBankService` を自動構築して Runner に挿す（自前 Runner は組まない）。
        ここが agent_engine_id → URI の唯一の変換点。未設定なら None＝ADK が InMemory に降格する。
        """
        return f"agentengine://{self.agent_engine_id}" if self.agent_engine_id else None


settings = Settings()
