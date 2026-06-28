"""保育士向け配布 Web UI（B-full）の配線（設計コンテキスト §11 配信・層A）。

北極星＝「保育士が手間をかけず子と向き合う」を、審査員が触れる1枚の UI で見せる。3責務の
どれも作り直さない：

- 日誌/月案の生成は ADK の `get_fast_api_app` が出す **ネイティブ REST**（`/run_sse`・session API）を
  フロント SPA が直接叩く＝**自前 Runner を組まない**（§9・server.py の方針順守）。harness/agents は不変。
- improver（二階）だけは discoverable app でない（root_agent を持たない＝improver/CLAUDE.md）ので、
  ここで専用ルート `/api/improve` が InMemoryRunner で駆動する（run_improver.py と同型・別エントリの原則は保つ）。
- 配布リンクのコスト/濫用対策として、LLM を回す口に簡易パスコードゲートを噛ませる（`config.demo_passcode`）。

`register_web_ui(app)` を `server.py` が `get_fast_api_app(...)` の直後に1回呼ぶだけ。dev UI（`/dev-ui/`）は
温存し、保育士 UI は `/app/`、自前 API は `/api/*` に同居する。静的資産は `src` 配下なので Dockerfile は不変。
"""

from __future__ import annotations

from .routes import register_web_ui

__all__ = ["register_web_ui"]
