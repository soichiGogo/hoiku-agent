"""代表児の書類チェーン（日誌→クラス月案→保育経過記録→保育要録）を書類アーカイブへ投入する seed。

データとロジックの実体は harness へ昇格済み（`hoiku_agent.harness.demo_seed_data`＝entry dict・
`hoiku_agent.harness.demo_seed`＝finalize_entry→save_document の投入）。本スクリプトはローカル
既定領域（workspace 未指定）へ CLI から投入する薄いラッパ（§5＝決定的実体は harness に1つ）。
新規ユーザーの workspace への自動投入（初回ログイン）と「データを初期化」は web 側が同じ
`demo_seed.seed_workspace` を呼ぶ。

接続先は `DATABASE_URL`（config＝env が唯一の出所）。未設定/未マイグレーションは降格（何もせず終了）。本番
Cloud SQL へ入れるときは Auth Proxy 経由の TCP URL を渡す（手順は docs/ライブ実行手順.md）:
    DATABASE_URL='postgresql+psycopg://USER:PASS@127.0.0.1:5432/hoiku' \
        uv run python scripts/seed_documents.py
型の妥当性だけ確認する（DB へ書かない・creds 不要）:
    uv run python scripts/seed_documents.py --dry-run
"""

from __future__ import annotations

import argparse
from datetime import datetime

from hoiku_agent.harness import demo_seed
from hoiku_agent.harness import demo_seed_data as data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="代表児の書類チェーン（日誌→クラス月案→保育経過記録→要録）を書類アーカイブへ投入する seed"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB へ書かず、全書類の型成立（finalize_entry）だけ検査して結果を表示する",
    )
    parser.add_argument(
        "--approve",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="保存後に承認済み（approved）にする（既定 True・--no-approve で確定止まり。"
        "承認フロー体感用の一部書類＝UNAPPROVED は常に確定止まり）",
    )
    parser.add_argument("--actor", default="seed", help="監査証跡の担当者名（自己申告・既定 seed）")
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="アーカイブに既にある書類（同一 種別×児×期間）はスキップする＝再実行安全"
        "（既定 True・--no-skip-existing で全件を版として上書き投入）",
    )
    args = parser.parse_args()

    total = sum(len(entries) for _, entries in data.JOBS)
    print(
        f"書類 {total} 件（"
        + " / ".join(f"{data.KIND_LABEL[k]}:{len(e)}" for k, e in data.JOBS)
        + "）／対象児は実在しない仮名のみ（§14）"
    )

    # ── まず全書類の型成立を確認（ここが赤なら手書きデータのバグ＝投入前に必ず落とす） ──
    failures = demo_seed.validate_all()
    if failures:
        print(f"\n型検査で {len(failures)} 件の違反（投入を中止します）:")
        for f in failures:
            print(f"  {f}")
        raise SystemExit(1)
    print("型検査: 全書類が型成立（必須欄・年齢分岐・様式整形 OK）")

    if args.dry_run:
        print("[dry-run] DB へは書き込んでいません。")
        return

    from hoiku_agent.harness import record_store

    status = record_store.store_status()
    if status != "ok":
        raise SystemExit(
            f"\n書類アーカイブへ接続できません（store_status={status}）。"
            "DATABASE_URL を設定し、マイグレーション適用済みの DB を指してください"
            "（手順は docs/ライブ実行手順.md）。型検査は上で通過しています。"
        )

    result = demo_seed.seed_workspace(
        None,  # ローカル既定領域（record_store のローカル固定 workspace）
        actor=args.actor,
        now=datetime.now(),
        approve=args.approve,
        skip_existing=args.skip_existing,
    )
    print(
        f"\n完了: 名簿 {result.get('children', 0)} / クラス {result.get('classes', 0)} / "
        f"保存 {result.get('documents', 0)} / 承認 {result.get('approved', 0)}（status={result.get('status')}）"
    )
    for e in result.get("errors", []):
        print(f"  [error] {e}")
    if result.get("status") != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
