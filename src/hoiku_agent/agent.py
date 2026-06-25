"""ルートエージェント。

ADK CLI（`adk run` / `adk web`）はこのモジュールの `root_agent` を探す。
中身は harness 層の doc_type 分岐ルータ（型の保証）：state["doc_type"] で日誌／月案パイプラインを
振り分ける（既定＝保育日誌＝§3 日誌先行。doc_type=="月案" のときだけ月案パイプライン）。
唯一トップレベルでインスタンス化してよいエージェント（他は build_xxx() ファクトリで返す）。
"""

from __future__ import annotations

from .harness import build_root_agent

root_agent = build_root_agent()
