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

    # 静的ナレッジ＝Vertex RAG corpus（保育所保育指針・10の姿）
    rag_corpus: str = ""
    # 子ども長期記憶＝Agent Engine Memory Bank の ID（get_child_memory が使う）。
    # 用途は Memory Bank に限定する（Runtime 名残と混同しない＝設計コンテキスト §9）。
    agent_engine_id: str = ""


settings = Settings()
