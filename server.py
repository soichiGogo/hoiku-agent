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

import logging

from google.adk.cli.fast_api import get_fast_api_app

from hoiku_agent.config import settings
from hoiku_agent.harness import db
from hoiku_agent.logging_config import configure_logging, install_trace_middleware
from hoiku_agent.web import register_web_ui

# 構造化ログを最初に据える（Cloud Run が stdout の1行 JSON を Cloud Logging へ昇格＝logging_config）。
# 以降 import される ADK/uvicorn のログもこの設定に揃う。
configure_logging()

app = get_fast_api_app(
    agents_dir="src",
    memory_service_uri=settings.memory_service_uri,  # agentengine://<id> or None→InMemory
    session_service_uri=settings.session_service_uri,  # 同上：Cloud Run のインスタンス跨ぎでセッション保持
    web=True,
)

# 保育士向け配布 UI（B-full）を同居させる：保育士 UI＝/app/、自前 API＝/api/*、dev UI＝/dev-ui/。
# 日誌/月案の生成は ADK ネイティブ REST をフロントが直接叩く（自前 Runner を組まない＝§9）。
register_web_ui(app)

# リクエストの X-Cloud-Trace-Context をログに相関させる（同一リクエストのログを Logs Explorer で束ねる）。
install_trace_middleware(app)

# 起動時に DB スキーマの drift（未適用 migration＝欠落テーブル）を観測してログに残す。CD が deploy 前に
# `alembic upgrade head` を当てるので通常は空だが、手動 gcloud 等で経路が外れた場合の早期検知（§ drift）。
# 未接続（DATABASE_URL 未設定）や到達不能は空リスト＝起動は止めない（best-effort な可観測性）。
_missing_tables = db.schema_drift()
if _missing_tables:
    logging.getLogger("hoiku_agent.startup").warning(
        "DB schema drift を検知: 未整備テーブル %s（本番 DB に alembic upgrade head 未適用の可能性）",
        _missing_tables,
    )
