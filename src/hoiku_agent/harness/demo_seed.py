"""デモ用デフォルト seed の投入・初期化ロジック（決定的・LLM 非依存）。

新規ユーザーの初回ログイン時（web/workspace.py）と「データを初期化」（web `/api/account/reset`）、
および CLI（scripts/seed_children.py・scripts/seed_documents.py）から呼ばれる。データの実体は
`demo_seed_data.py`、確定処理は `finalize.finalize_entry`、永続化は `record_store` に一本化する
（配布UIの確定と同じ経路＝二重実装しない・§5）。

- `seed_workspace` は冪等：児童/クラスは upsert、書類は同一（種別×児×期間）が既にあれば
  スキップする（scripts/seed_documents.py の --skip-existing と同じ判定）＝並行リクエストや
  途中失敗後の再実行で版が二重に積まれない。
- `reset_workspace` は workspace のデータ（書類・園児・クラス・フィードバック・指針/表記の
  カスタム）を即時消去してから seed を再投入する。User/Workspace/利用枠は残す＝ログイン継続。
- 未接続（`DATABASE_URL` なし）は skipped 降格（本流＝ログイン・API を壊さない）。
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from . import demo_seed_data as data
from . import record_store
from .finalize import finalize_entry

logger = logging.getLogger(__name__)

# 監査証跡に残す既定の担当者名（seed は運営でなくアプリが用意する初期データであることを明示する）
DEFAULT_ACTOR = "初期データ"


def validate_all() -> list[str]:
    """全 seed 書類を finalize_entry に通して型成立を確認する（DB 不要・creds 不要）。違反一覧を返す。"""
    failures: list[str] = []
    for kind, entries in data.JOBS:
        for entry in entries:
            fd = finalize_entry(entry, kind=kind)
            label = data.entry_label(kind, entry)
            if fd.parse_error:
                failures.append(f"[parse] {label}: {fd.parse_error}")
            for p in fd.problems:
                failures.append(f"[type] {label}: {p}")
    return failures


def seed_workspace(
    workspace_id: str | None,
    *,
    actor: str = DEFAULT_ACTOR,
    now: datetime,
    approve: bool = True,
    skip_existing: bool = True,
) -> dict:
    """workspace へデフォルト seed（名簿30人・クラス2・確定書類チェーン）を冪等に投入する。

    書類は `data.UNAPPROVED` 以外を承認済みにする（Memory Bank 同期は web の承認 API 専用＝
    ここからは発火しない・memory_status は既定の "skipped"）。approve=False で全件確定止まり、
    skip_existing=False で既存書類にも版を積んで上書き投入（いずれも scripts の CLI 互換）。
    未接続は skipped、途中の DB 障害は error を返す（呼び出し側＝ログイン本流を壊さない）。
    """
    if record_store.store_status() != "ok":
        return {"status": "skipped", "reason": "書類アーカイブ未接続（seed 降格）"}
    result = {"status": "ok", "children": 0, "classes": 0, "documents": 0, "approved": 0}
    errors: list[str] = []

    # ── 名簿（仮名30人・誕生日つき）とクラス（組×2）→ 年齢帯で割当 ──
    for name, bd in data.ROSTER:
        res = record_store.upsert_child(
            name, birthdate=date.fromisoformat(bd), workspace_id=workspace_id, now=now
        )
        if res.get("status") in ("created", "exists"):
            result["children"] += 1
        else:
            errors.append(f"child {name}: {res}")
    class_ids: dict[str, str] = {}
    for class_name, band in data.CLASSES:
        res = record_store.upsert_class(
            class_name, data.FISCAL_YEAR, workspace_id=workspace_id, now=now
        )
        if res.get("id"):
            class_ids[band] = str(res["id"])
            result["classes"] += 1
        else:
            errors.append(f"class {class_name}: {res}")
    fiscal_start = record_store.fiscal_year_start_for_year(data.FISCAL_YEAR)
    for name, bd in data.ROSTER:
        band = record_store.roster_age_band(date.fromisoformat(bd), fiscal_start)
        class_id = class_ids.get(band or "")
        if class_id is None:
            continue
        res = record_store.assign_child_to_class(name, class_id, workspace_id=workspace_id, now=now)
        if res.get("status") != "ok":
            errors.append(f"assign {name}: {res}")

    # ── 確定書類チェーン（既存の 種別×児×期間 はスキップ＝冪等・skip-existing と同じ判定） ──
    existing: set[tuple[str, str, str]] = set()
    if skip_existing:
        for kind, _ in data.JOBS:
            for d in record_store.list_documents(kind, limit=5000, workspace_id=workspace_id):
                existing.add((d["doc_type"], d.get("child", ""), d.get("target", "")))
    for kind, entries in data.JOBS:
        for entry in entries:
            key = (kind, data.child_of(kind, entry), data.target_of(kind, entry))
            if key in existing:
                continue
            fd = finalize_entry(entry, kind=kind)
            if not fd.ok:
                # データ部のバグ＝validate_all（テスト常設）で先に落ちる想定。ここでは正直に報告だけ。
                errors.append(
                    f"finalize {data.entry_label(kind, entry)}: {fd.parse_error or fd.problems}"
                )
                continue
            normalized = fd.entry.model_dump(mode="json")
            res = record_store.save_document(
                kind,
                normalized,
                rendered_text=fd.formatted or "",
                author_kind="ai",
                actor=actor,
                workspace_id=workspace_id,
                now=now,
            )
            if res.get("status") != "saved":
                errors.append(f"save {data.entry_label(kind, entry)}: {res}")
                continue
            result["documents"] += 1
            if approve and key not in data.UNAPPROVED:
                ares = record_store.approve_document(
                    kind, normalized, actor=actor, workspace_id=workspace_id, now=now
                )
                if ares.get("status") == "approved":
                    result["approved"] += 1
                else:
                    errors.append(f"approve {data.entry_label(kind, entry)}: {ares}")

    if errors:
        logger.warning("デフォルト seed で %d 件の失敗: %s", len(errors), "; ".join(errors[:5]))
        result["status"] = "error"
        result["errors"] = errors
    return result


def reset_workspace(workspace_id: str | None, *, actor: str = DEFAULT_ACTOR, now: datetime) -> dict:
    """workspace のデータを即時消去してデフォルト seed へ戻す（「データを初期化」の実体）。

    消すのは書類（版・監査・フィードバック含む）・園児・クラス・指針/表記のカスタム行のみで、
    User/Workspace/利用枠は残す（ログイン・コスト管理は継続＝アカウント削除とは別物）。
    """
    purged = record_store.purge_workspace_data(workspace_id)
    if purged.get("status") != "ok":
        return purged
    seeded = seed_workspace(workspace_id, actor=actor, now=now)
    return {**seeded, "purged": True}
