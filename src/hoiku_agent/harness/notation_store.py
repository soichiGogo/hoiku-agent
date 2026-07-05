"""harness：ひらがな表記DX＝表記ルール辞書ストア＋決定的な正規化器。

設計コンテキスト §5（決定的ロジック＝型/表記の保証の唯一実装）。保育書類の表記慣行
（「子供→子ども」「友達→友だち」・Word 保存時に混入するスペースの除去 等）を、確定時に
**取りこぼしなく決定的に整える**（LLM を呼ばない）。育つ指針カード（policy_store）が agentic な
"中身の勘所" であるのに対し、こちらは決定的な "表記の統一"＝別の道具（責務の線を混ぜない）。

責務境界:
- 純関数（CRUD・正規化）と IO（load_book/save_book）を分ける。正規化は叙述系フィールドに限定し、
  child_id（架空児の仮名）・タグ・日付・年齢帯など**表記変換してはいけない欄には触れない**（誤変換の抑制）。
- 暴発するルールは保育士が `enabled=False` で止められる（silent lock はしない＝§5 の設計判断）。
- clock を持たない＝日時は呼び出し側（web ルート境界）が注入する。
- 置き場は IO 節で解決＝明示 path ＞ `DATABASE_URL`（Cloud SQL＝書類アーカイブ/policy と同じ DB・
  `notation_books` 1行に book 丸ごと JSONB・version 楽観ロック） ＞ ローカル `knowledge/表記ルール.json`
  （git はシード）。純関数は置き場を知らない（policy_store と同じ哲学）。
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from . import db
from ..schemas.notation import NotationBook, NotationKind, NotationRule

_REPO_ROOT = Path(__file__).resolve().parents[3]
_NOTATION_PATH = _REPO_ROOT / "knowledge" / "表記ルール.json"

# 正規化を適用する叙述系フィールド（書類種別ごと）。ここに無い欄（child_id＝仮名・tags・date・
# age_band・age_months・height/weight 等）は**表記変換してはいけない**＝誤変換を型で防ぐ（§5/§14）。
# path 記法: "a"（キー）/ "a.b"（ネスト）/ "a[].b"（オブジェクト配列の各要素）。
NARRATIVE_FIELDS: dict[str, list[str]] = {
    "diary": [
        "daily_aim",
        "practice_record",
        "health_notes",
        "parent_contact",
        "attendance[].reason",
        "individual_notes[].observed_state",
        "individual_notes[].individual_aim",
        "individual_notes[].life_record.meal",
        "individual_notes[].life_record.sleep",
        "individual_notes[].life_record.toilet",
        "individual_notes[].life_record.mood_health",
        "evaluation.child_focus",
        "evaluation.self_review",
    ],
    "monthly": [
        "prev_child_state",
        "nurturing_life",
        "nurturing_emotion",
        "monthly_goals",
        "environment_support",
        "events_family_food",
        "evaluation_reflection",
        "education[].aim",
    ],
    "class_monthly": [
        "monthly_goal",
        "prev_month_state",
        "events",
        "parent_support",
        "grid[].aim",
        "grid[].environment",
        "grid[].child_state",
        "grid[].support",
        "syokuiku",
        "health_safety",
        "family_liaison",
        "staff_liaison",
        "individual_goals[].child_state",
        "individual_goals[].aim_support",
        "individual_goals[].evaluation",
        "teacher_evaluation",
        "children_evaluation",
        "notable_children",
    ],
    "child_record": [
        "development_notes[].description",
        "care_notes",
        "family_liaison",
        "overall_note",
        "next_aims",
    ],
    "nursery_record": [
        "final_year_focus",
        "individual_focus",
        "development_notes[].description",
        "special_notes",
        "growth_until_final",
    ],
}

_SPACE_RULE_ID = "_space"  # スペース除去の擬似ルール id（変更点の集計表示用）


# ──────────────────────────── 正規化器（純関数・LLM 非依存） ────────────────────────────
#
# 変更点の型: {"rule_id": str, "pattern": str, "replacement": str, "count": int}

# 「日本語文字」＝ASCII でも空白でもない文字。日本語文字どうしの間の空白（半角/全角）を混入とみなし
# 除去する（"子ども　の"→"子どもの"）。ASCII 側（"36.5 ℃" の数字と単位、英単語間）の空白は保つ。
_JP_CHAR = r"[^\x00-\x7F\s]"
_STRAY_SPACE = re.compile(rf"(?<={_JP_CHAR})[ 　]+(?={_JP_CHAR})")


def _ws_count(text: str) -> int:
    """半角/全角スペースの数（除去件数の集計用）。"""
    return text.count(" ") + text.count("　")


def _strip_stray_spaces(text: str) -> tuple[str, int]:
    """日本語文字どうしの間の混入スペースを除去し、前後の空白を落とす（除去件数も返す）。"""
    new = _STRAY_SPACE.sub("", text).strip()
    removed = _ws_count(text) - _ws_count(new)
    return new, max(0, removed)


def enabled_rules(book: NotationBook) -> list[NotationRule]:
    """有効（enabled）かつ pattern 非空のルールを挿入順で返す（正規化に使う集合）。"""
    return [r for r in book.rules if r.enabled and r.pattern]


def normalize_text(text: str, rules: list[NotationRule]) -> tuple[str, list[dict]]:
    """1つのテキストにルール置換＋混入スペース除去を決定的に適用する（純関数）。

    ルールは挿入順にリテラル部分一致で置換する。変更があった分だけ変更点を返す
    （UI 提示は現状しないが、テスト・ログ・将来の「こう整えました」表示のために保持する）。
    """
    changes: list[dict] = []
    out = text
    for r in rules:
        if not r.enabled or not r.pattern:
            continue
        cnt = out.count(r.pattern)
        if cnt:
            out = out.replace(r.pattern, r.replacement)
            changes.append(
                {
                    "rule_id": r.id,
                    "pattern": r.pattern,
                    "replacement": r.replacement,
                    "count": cnt,
                }
            )
    out, space_removed = _strip_stray_spaces(out)
    if space_removed:
        changes.append(
            {
                "rule_id": _SPACE_RULE_ID,
                "pattern": "（混入した空白）",
                "replacement": "",
                "count": space_removed,
            }
        )
    return out, changes


def _tokenize(path: str) -> list[str]:
    """ "individual_notes[].life_record.meal" → ["individual_notes","[]","life_record","meal"]。"""
    toks: list[str] = []
    for part in path.split("."):
        if part.endswith("[]"):
            toks.append(part[:-2])
            toks.append("[]")
        else:
            toks.append(part)
    return toks


def _leaf_refs(data, tokens: list[str]):
    """path トークンに沿って (container, key) の可変参照を辿る（存在しない枝は静かに飛ばす）。"""
    if not tokens:
        return
    tok, rest = tokens[0], tokens[1:]
    if tok == "[]":
        if isinstance(data, list):
            for item in data:
                yield from _leaf_refs(item, rest)
        return
    if not isinstance(data, dict) or tok not in data:
        return
    if not rest:
        yield data, tok
    else:
        yield from _leaf_refs(data[tok], rest)


def _merge_changes(changes: list[dict]) -> list[dict]:
    """(rule_id, pattern, replacement) 単位で count を合算し、決定的な順序で返す。"""
    acc: dict[tuple, dict] = {}
    for ch in changes:
        key = (ch["rule_id"], ch["pattern"], ch["replacement"])
        if key in acc:
            acc[key]["count"] += ch["count"]
        else:
            acc[key] = dict(ch)
    return list(acc.values())


def normalize_entry_dict(
    data: dict, kind: str, rules: list[NotationRule]
) -> tuple[dict, list[dict]]:
    """書類エントリ dict の**叙述系フィールドだけ**を正規化する（純関数・非破壊）。

    Args:
        data: 書類エントリの dict（DiaryEntry / MonthlyPlan / ChildRecord の model_dump 相当）。
        kind: "diary" / "monthly" / "child_record"（NARRATIVE_FIELDS のキー）。
        rules: 適用する表記ルール（enabled 判定は normalize_text 側）。

    Returns:
        (正規化後の dict, 変更点リスト)。対象外の欄（仮名・タグ・日付等）には触れない。
    """
    result = copy.deepcopy(data)
    changes: list[dict] = []
    for path in NARRATIVE_FIELDS.get(kind, []):
        for container, key in _leaf_refs(result, _tokenize(path)):
            val = container[key]
            if not isinstance(val, str) or not val:
                continue
            new_val, ch = normalize_text(val, rules)
            if new_val != val:
                container[key] = new_val
                changes.extend(ch)
    return result, _merge_changes(changes)


# ──────────────────────────── 採番・検索・CRUD（純関数・新 NotationBook を返す） ────────────────────────────


def next_rule_id(book: NotationBook) -> str:
    """既存 id（"rule-NNNN"）の最大連番 +1 を決定的に採番する。空なら rule-0001。"""
    max_n = 0
    for r in book.rules:
        if r.id.startswith("rule-"):
            try:
                max_n = max(max_n, int(r.id[len("rule-") :]))
            except ValueError:
                continue
    return f"rule-{max_n + 1:04d}"


def find_rule(book: NotationBook, rule_id: str) -> NotationRule | None:
    """id でルールを引く（無ければ None）。"""
    return next((r for r in book.rules if r.id == rule_id), None)


def _find_by_pattern(book: NotationBook, pattern: str) -> NotationRule | None:
    target = pattern.strip()
    return next((r for r in book.rules if r.pattern == target), None)


def add_rule(book: NotationBook, rule: NotationRule) -> NotationBook:
    """ルールを追加する（純関数・新 NotationBook を返す）。

    pattern 空・id 重複・pattern 重複は ValueError（fail-loud＝1 pattern＝1 変換先を保つ）。
    """
    if not rule.pattern.strip():
        raise ValueError("変換元（pattern）が空です")
    if find_rule(book, rule.id) is not None:
        raise ValueError(f"ルール id が重複しています: {rule.id}")
    if _find_by_pattern(book, rule.pattern) is not None:
        raise ValueError(f"同じ変換元のルールが既にあります: {rule.pattern!r}")
    return book.model_copy(update={"rules": [*book.rules, rule]})


def update_rule(
    book: NotationBook,
    *,
    rule_id: str,
    when,
    pattern: str | None = None,
    replacement: str | None = None,
    kind: NotationKind | None = None,
    note: str | None = None,
    enabled: bool | None = None,
) -> NotationBook:
    """既存ルールを編集する（純関数・新 NotationBook を返す）。`when`＝外部注入 datetime。

    None の引数は据え置き。pattern 変更時は空・他ルールとの重複を弾く（fail-loud）。
    """
    target = find_rule(book, rule_id)
    if target is None:
        raise ValueError(f"編集対象のルールが見つかりません: {rule_id}")
    changes: dict = {"updated_at": when}
    if pattern is not None:
        if not pattern.strip():
            raise ValueError("変換元（pattern）が空です")
        dup = _find_by_pattern(book, pattern)
        if dup is not None and dup.id != rule_id:
            raise ValueError(f"同じ変換元のルールが既にあります: {pattern!r}")
        changes["pattern"] = pattern.strip()
    if replacement is not None:
        changes["replacement"] = replacement
    if kind is not None:
        changes["kind"] = kind
    if note is not None:
        changes["note"] = note
    if enabled is not None:
        changes["enabled"] = enabled
    rules = [r.model_copy(update=changes) if r.id == rule_id else r for r in book.rules]
    return book.model_copy(update={"rules": rules})


def remove_rule(book: NotationBook, *, rule_id: str) -> NotationBook:
    """ルールを削除する（純関数・新 NotationBook を返す）。対象不在は ValueError。"""
    if find_rule(book, rule_id) is None:
        raise ValueError(f"削除対象のルールが見つかりません: {rule_id}")
    return book.model_copy(update={"rules": [r for r in book.rules if r.id != rule_id]})


# ──────────────────────────── IO（降格 / fail-loud） ────────────────────────────
# 置き場の解決順序は policy_store と同一（明示 path ＞ DATABASE_URL ＞ ローカルシード）。

_BOOK_ROW_ID = "default"
_CONFLICT_MESSAGE = (
    "表記ルールが他の場所で先に更新されています（競合）。最新を読み直してからやり直してください。"
)


class NotationBookRecord(db.Base):
    """表記ルールブックの DB 行（book 丸ごと JSON が SSOT・1行・version は楽観ロック用）。"""

    __tablename__ = "notation_books"

    id: Mapped[str] = mapped_column(sa.String(20), primary_key=True)
    book: Mapped[dict] = mapped_column(db.JSON_VARIANT)
    version: Mapped[int] = mapped_column(sa.Integer)


def _db_active(path: Path | None) -> bool:
    return path is None and bool(db.database_url())


def _load_local(path: Path) -> NotationBook:
    if not path.exists():
        return NotationBook()
    data = json.loads(path.read_text(encoding="utf-8"))
    return NotationBook.model_validate(data)


def load_book_meta(path: Path | None = None) -> tuple[NotationBook, int | None]:
    """ルールストアと書き込み前提条件（version）を読む（policy_store.load_book_meta と対称）。

    DB（DATABASE_URL 設定・path 未指定）で行不在なら 0＝create-only＋ローカルシードを返す。
    ローカルは None（precondition なし）。壊れ JSON は例外（read 側が降格して握る）。
    """
    if _db_active(path):
        eng = db.engine()
        with Session(eng) as session:
            row = session.get(NotationBookRecord, _BOOK_ROW_ID)
        if row is None:
            return _load_local(_NOTATION_PATH), 0
        return NotationBook.model_validate(row.book), row.version
    return _load_local(path or _NOTATION_PATH), None


def load_book(path: Path | None = None) -> NotationBook:
    """ルールストアを読む（読み手用。書き手は load_book_meta で version も取る）。"""
    return load_book_meta(path)[0]


def save_book(
    book: NotationBook, path: Path | None = None, *, if_version: int | None = None
) -> None:
    """ルールストアを書き出す（DB は if_version の compare-and-swap で楽観ロック＝policy と同一）。"""
    payload = book.model_dump(mode="json")
    if _db_active(path):
        eng = db.engine()
        try:
            with Session(eng) as session, session.begin():
                if if_version is None:
                    row = session.get(NotationBookRecord, _BOOK_ROW_ID)
                    if row is None:
                        session.add(NotationBookRecord(id=_BOOK_ROW_ID, book=payload, version=1))
                    else:
                        row.book = payload
                        row.version += 1
                elif if_version == 0:
                    session.add(NotationBookRecord(id=_BOOK_ROW_ID, book=payload, version=1))
                else:
                    updated = session.execute(
                        sa.update(NotationBookRecord)
                        .where(
                            NotationBookRecord.id == _BOOK_ROW_ID,
                            NotationBookRecord.version == if_version,
                        )
                        .values(book=payload, version=if_version + 1)
                    )
                    if updated.rowcount != 1:
                        raise ValueError(_CONFLICT_MESSAGE)
        except IntegrityError as e:
            raise ValueError(_CONFLICT_MESSAGE) from e
        return

    path = path or _NOTATION_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_rules_or_empty() -> list[NotationRule]:
    """正規化用にルールを読む（降格safe＝未整備/壊れ/DB 到達不能は空＝正規化を no-op に）。

    finalize（確定処理）はこれを使い、表記ストアが無くても確定を落とさない（§5 降格方針）。
    """
    try:
        return load_book().rules
    except Exception:  # noqa: BLE001  ストア未整備/壊れ/到達不能は正規化 no-op へ降格
        return []


def store_status(path: Path | None = None) -> str:
    """ストアの永続性を正直に表す（UI が偽の永続を出さないため・policy_store と対称）。"""
    if _db_active(path):
        try:
            load_book()
        except Exception:  # noqa: BLE001
            return "unavailable"
        return "persistent"
    path = path or _NOTATION_PATH
    if not path.exists():
        return "unavailable"
    try:
        load_book(path)
    except (OSError, ValueError):
        return "unavailable"
    return "ephemeral" if os.environ.get("K_SERVICE") else "persistent"


# ──────────────────────────── view（API/UI 用の決定的マッピング） ────────────────────────────


def rule_view(rule: NotationRule) -> dict:
    """ルール1件をフロント/API 用の JSON-serializable dict に変換する（決定的）。"""
    return {
        "id": rule.id,
        "pattern": rule.pattern,
        "replacement": rule.replacement,
        "kind": rule.kind.value,
        "note": rule.note,
        "enabled": rule.enabled,
        "source": rule.source,
        "updated_at": rule.updated_at.date().isoformat(),
    }


def book_view(book: NotationBook) -> dict:
    """ストア全体を /api/notation 契約の {rules} に変換する（挿入順）。"""
    return {"rules": [rule_view(r) for r in book.rules]}
