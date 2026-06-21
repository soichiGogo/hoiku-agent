"""ルートエージェント。

ADK CLI（`adk run` / `adk web`）はこのモジュールの `root_agent` を探す。
中身は workflow 層のパイプライン（型の保証）＝作成AI → レビューループ。
"""

from __future__ import annotations

from .workflow import build_document_pipeline

root_agent = build_document_pipeline()
