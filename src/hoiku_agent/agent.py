"""ルートエージェント。

ADK CLI（`adk run` / `adk web`）はこのモジュールの `root_agent` を探す。
中身は harness 層のパイプライン（型の保証）＝作成AI → レビューループ。
唯一トップレベルでインスタンス化してよいエージェント（他は build_xxx() ファクトリで返す）。
"""

from __future__ import annotations

from .harness import build_document_pipeline

root_agent = build_document_pipeline()
