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

    # B独自DB / 長期メモリ
    rag_corpus: str = ""
    agent_engine_id: str = ""


settings = Settings()
