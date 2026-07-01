"""本番（Cloud Run）/ ローカル共通のアプリ入口。

設計コンテキスト §9（メモリ二分）/ §11（Cloud Run 直ホスト）。ADK の `get_fast_api_app` を
そのまま使い、子ども別長期メモリ＝Agent Engine Memory Bank を config 由来の URI で配線する。
**自前 Runner は組まない**：ADK は `--memory_service_uri=agentengine://<id>` を受け取ると
`VertexAiMemoryBankService` を自動構築して Runner に挿す。ここで手組みすると ADK CLI/deploy と
二重化・乖離し、§9「マネージドメモリを呼ぶだけ」に反する。

同じ理由でセッションの保存先も ADK ネイティブに委ねる：`session_service_uri` 未指定だと ADK は
InMemorySessionService＝各インスタンスのメモリ内に降格し、Cloud Run（複数インスタンス＋
scale-to-zero でメモリ揮発）だと作成したセッションが別インスタンス／再起動で失われ
`/apps/.../sessions/{id}` が 404 になる。子ども長期記憶と同じ Agent Engine を共有セッションストアに
流用し（`agentengine://<id>`＝ADK が `VertexAiSessionService` を自動構築）、インスタンス跨ぎでも
セッションを保持する。

エントリは agents dir＝`src/` を指す（`adk web src` と同じ）。本ファイルを `src/` の外（repo root）に
置くのは、(1) ADK の agent-loader が `src/` をスキャンする対象に混ざらない、(2) `uvicorn server:app`
の import パスが単純、の2点のため。

起動:
    ローカル: `uvicorn server:app`（dev は従来どおり `adk web src` も可）。
    Cloud Run: `uvicorn server:app --host 0.0.0.0 --port $PORT`。

`AGENT_ENGINE_ID` 未設定なら `settings.memory_service_uri` / `settings.session_service_uri` は
共に None ＝ ADK が InMemory に降格する（落ちない・既存ツールの降格哲学と一致）。実 Memory Bank／
共有セッションストアへのライブ接続は Agent Engine のプロビジョニングと `.env` の `AGENT_ENGINE_ID`
設定が前提（docs/ライブ実行手順.md）。
"""

from __future__ import annotations

from google.adk.cli.fast_api import get_fast_api_app

from hoiku_agent.config import settings
from hoiku_agent.web import register_web_ui

app = get_fast_api_app(
    agents_dir="src",
    memory_service_uri=settings.memory_service_uri,  # agentengine://<id> or None→InMemory
    session_service_uri=settings.session_service_uri,  # 同上：Cloud Run のインスタンス跨ぎでセッション保持
    web=True,
)

# 保育士向け配布 UI（B-full）を同居させる：保育士 UI＝/app/、自前 API＝/api/*、dev UI＝/dev-ui/。
# 日誌/月案の生成は ADK ネイティブ REST をフロントが直接叩く（自前 Runner を組まない＝§9）。
register_web_ui(app)
