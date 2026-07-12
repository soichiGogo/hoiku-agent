"""指定した Google アカウントの workspace を即時消去してデフォルト seed のみの状態に戻す（デバッグ用）。

UI の「データを初期化して始める」（`POST /api/account/reset`）と同じ実体（`harness.demo_seed.reset_workspace`）
を、サインインなしでメール指定からコマンドラインで呼ぶ。ローカル DB に対する動作確認や、特定の開発用
アカウントを毎回同じ初期状態へ戻したいときに使う。

対象の user 行がまだ無い場合は `touch_user` が新規 workspace を作るだけで、消去するデータは無い
（初回ログインと同じ扱い）。既存アカウントの実データを消すため、`--yes` を明示しない限り何もしない。

接続先は `DATABASE_URL`（config＝env が唯一の出所）。未設定・未接続は何もせず終了する:
    DATABASE_URL='postgresql+psycopg://USER:PASS@127.0.0.1:5432/hoiku' \
        uv run python scripts/reset_account.py --email soichinaka.sn@gmail.com --yes
"""

from __future__ import annotations

import argparse
from datetime import datetime


def main() -> None:
    parser = argparse.ArgumentParser(
        description="指定メールの workspace をデフォルト seed のみの初期状態にリセットする（デバッグ用）"
    )
    parser.add_argument("--email", required=True, help="対象アカウントの email")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="実データの消去を確認済みとして実行する（未指定なら内容の確認だけ行い実行しない）",
    )
    args = parser.parse_args()

    from hoiku_agent.harness import demo_seed, record_store

    status = record_store.store_status()
    if status != "ok":
        raise SystemExit(
            f"書類アーカイブへ接続できません（store_status={status}）。"
            "DATABASE_URL を設定し、マイグレーション適用済みの DB を指してください。"
        )

    now = datetime.now()
    user = record_store.touch_user(args.email, now=now)
    if user.get("status") != "ok":
        raise SystemExit(f"ユーザーの解決に失敗しました: {user}")

    workspace_id = user["workspace_id"]
    if user.get("workspace_created"):
        print(
            f"[{args.email}] は新規アカウントです（workspace={workspace_id}）。消去対象のデータはありません。"
        )

    if not args.yes:
        print(
            f"[{args.email}] の workspace（{workspace_id}）の書類・園児・クラス・フィードバック・"
            "指針/表記のカスタムを消去し、デフォルト seed を再投入します。"
            "実行するには --yes を付けて再実行してください。"
        )
        return

    result = demo_seed.reset_workspace(workspace_id, now=now)
    print(f"リセット結果: {result}")
    if result.get("status") != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
