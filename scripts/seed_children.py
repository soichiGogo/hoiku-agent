"""児童マスタ（children）へ園名簿を事前登録する seed スクリプト（書類アーカイブ・Phase 1）。

配布 UI の対象児選択は入力式コンボボックス（前方一致＋Tab補完＝`web/static/app.js` の `childCombo`）で、
候補ソースは児童マスタ（`/api/children`＝`record_store.list_children`）。園の実運用（30人規模）を想定した
名簿をあらかじめ入れておくためのデモ/検証用 seed。書込は `record_store.upsert_child`（表示名で upsert・
冪等・既存の誕生日は上書きしない）に一本化する（children 書込の SSOT は record_store＝§5）。

**実名は扱わない（§14）**：登録するのは実在しない仮名（下の名前＋ちゃん/くん）のみ。誕生日は
年齢帯（0-2/3-5）自動判定の材料として現実的に散らす（0-2 と 3-5 が混在＝コンボボックスの年齢帯
自動判定が現場同様に効くデモになる）。前方一致が効くことが見えるよう、先頭が重なる名前
（はると/はるき・りく/りくと・ゆい/ゆいと・そうた/そうすけ）も入れてある。

接続先は `DATABASE_URL`（config＝env が唯一の出所）。未設定は降格（何もせず終了）。本番 Cloud SQL へ
入れるときは Auth Proxy 経由の TCP URL を渡す（手順は docs/ライブ実行手順.md）:
    DATABASE_URL='postgresql+psycopg://USER:PASS@127.0.0.1:5432/hoiku' \
        uv run python scripts/seed_children.py
一覧の確認だけなら:
    uv run python scripts/seed_children.py --dry-run
"""

from __future__ import annotations

import argparse
from datetime import date, datetime

# 実在しない仮名の固定名簿（§14）。実体は harness の demo_seed_data（初回ログインの
# デフォルト seed と同じ名簿＝二重管理しない）。
from hoiku_agent.harness.demo_seed_data import ROSTER as _ROSTER


def _age_band(birth: date, today: date) -> str:
    """満年齢で年齢帯を返す（3歳以上=3-5／未満=0-2）。UI 側 `ageBandOf` と同じ簡略判定。"""
    age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    return "3-5" if age >= 3 else "0-2"


def main() -> None:
    parser = argparse.ArgumentParser(description="児童マスタへ園名簿（仮名）を事前登録する seed")
    parser.add_argument(
        "--dry-run", action="store_true", help="DB へ書かず、名簿と年齢帯だけ表示する"
    )
    args = parser.parse_args()

    today = date.today()
    bands = {"0-2": 0, "3-5": 0}
    for name, bd in _ROSTER:
        bands[_age_band(date.fromisoformat(bd), today)] += 1
    print(f"名簿 {len(_ROSTER)} 人（{today} 時点で 0-2:{bands['0-2']} 人 / 3-5:{bands['3-5']} 人）")

    if args.dry_run:
        for name, bd in _ROSTER:
            band = _age_band(date.fromisoformat(bd), today)
            print(f"  {name}\t誕生日 {bd}\t年齢帯 {band}")
        print("[dry-run] DB へは書き込んでいません。")
        return

    from hoiku_agent.harness import record_store

    status = record_store.store_status()
    if status != "ok":
        raise SystemExit(
            f"児童マスタへ接続できません（store_status={status}）。"
            "DATABASE_URL を設定し、マイグレーション適用済みの DB を指してください。"
        )

    now = datetime.now()
    created = existing = errors = 0
    for name, bd in _ROSTER:
        res = record_store.upsert_child(name, birthdate=date.fromisoformat(bd), now=now)
        status = res.get("status")
        if status == "created":
            created += 1
        elif status == "exists":
            existing += 1
        else:
            errors += 1
        print(f"  [{status}] {name}\t誕生日 {res.get('birthdate')}")

    print(f"\n完了: 新規 {created} / 既存 {existing} / 失敗 {errors}（計 {len(_ROSTER)}）")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
