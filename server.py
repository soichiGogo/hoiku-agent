"""本番（Cloud Run）/ ローカル共通のアプリ入口。

設計コンテキスト §9（メモリ二分）/ §11（Cloud Run 直ホスト）。ADK の `get_fast_api_app` を
そのまま使い、子ども別長期メモリ＝Agent Engine Memory Bank を config 由来の URI で配線する。
**自前 Runner は組まない**：ADK は `--memory_service_uri=agentengine://<id>` を受け取ると
`VertexAiMemoryBankService` を自動構築して Runner に挿す。ここで手組みすると ADK CLI/deploy と
二重化・乖離し、§9「マネージドメモリを呼ぶだけ」に反する。

エントリは agents dir＝`src/` を指す（`adk web src` と同じ）。本ファイルを `src/` の外（repo root）に
置くのは、(1) ADK の agent-loader が `src/` をスキャンする対象に混ざらない、(2) `uvicorn server:app`
の import パスが単純、の2点のため。

起動:
    ローカル: `uvicorn server:app`（dev は従来どおり `adk web src` も可）。
    Cloud Run: `uvicorn server:app --host 0.0.0.0 --port $PORT`。

`AGENT_ENGINE_ID` 未設定なら `settings.memory_service_uri` は None ＝ ADK が InMemory に降格する
（落ちない・既存ツールの降格哲学と一致）。実 Memory Bank へのライブ接続は Agent Engine の
プロビジョニングと `.env` の `AGENT_ENGINE_ID` 設定が前提（docs/ライブ実行手順.md）。
"""

from __future__ import annotations

from google.adk.cli.fast_api import get_fast_api_app

from hoiku_agent.config import settings

app = get_fast_api_app(
    agents_dir="src",
    memory_service_uri=settings.memory_service_uri,  # agentengine://<id> or None→InMemory
    web=True,
)
