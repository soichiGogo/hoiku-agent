"""生成モデルの構築（location 分離）。

Gemini 3.x（例: gemini-3.5-flash）は Vertex の **global エンドポイント専用**で、リージョン
（us-central1 等）では 404 になる。一方 **Vertex RAG Engine はリージョン専用**（global 不可）で、
Memory Bank（Agent Engine）も既存コーパス/エンジンは us-central1 にある。両者を同じ location に
同居できないため、**モデルだけ `model_location`（既定 global）に固定**し、RAG/Memory は
`google_cloud_location`（us-central1）のまま分離する（設計コンテキスト §9/§11）。

実装は ADK の `Gemini` を継承して `api_client` を上書きする公式パターン（`google_llm.py` の
docstring 記載）に従う。既定の `api_client` は `GOOGLE_CLOUD_LOCATION`（＝RAG/Memory のリージョン）を
読むため、location だけ差し替える（ヘッダ・retry・base_url・api_version は既定踏襲）。
"""

from __future__ import annotations

from functools import cached_property
from typing import Union

from google.adk.models.google_llm import Gemini
from google.genai import types

from .config import settings


class LocationPinnedGemini(Gemini):
    """生成用 Gemini を `settings.model_location`（既定 global）に固定する。

    既定の `Gemini.api_client` は env（`GOOGLE_CLOUD_LOCATION`）から location を解決するため、
    global 専用モデルが regional に飛んで 404 になる。ここを上書きして location のみ差し替える。
    """

    @cached_property
    def api_client(self):  # type: ignore[override]
        from google.genai import Client

        base_url, api_version = self._base_url_and_api_version
        http_kwargs: dict = {
            "headers": self._tracking_headers(),
            "retry_options": self.retry_options,
            "base_url": base_url,
        }
        if api_version:
            http_kwargs["api_version"] = api_version
        return Client(
            vertexai=True,
            project=settings.google_cloud_project or None,
            location=settings.model_location or settings.google_cloud_location,
            http_options=types.HttpOptions(**http_kwargs),
        )


def build_model(model_name: str | None = None) -> Union[str, Gemini]:
    """生成モデルを返す。

    Vertex かつ `model_location` 指定時は location 固定の `LocationPinnedGemini` を返し、
    モデルだけ別エンドポイント（global）へ振る。それ以外（AI Studio／model_location 空）は
    素の文字列を返し ADK が env から解決する（従来動作・後方互換）。
    """
    name = model_name or settings.gemini_model
    if settings.google_genai_use_vertexai and settings.model_location:
        return LocationPinnedGemini(model=name)
    return name
