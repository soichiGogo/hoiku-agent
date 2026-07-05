"""harness：月⇄日の集積（決定的）。

設計コンテキスト §4「L2 月次PDCA」/ §10「月⇄日の集積連携（L2 還流）」に対応。
集積本体は決定的：当月の個別記録（individual_notes）を child_id 別に集約する
（件数・タグ頻度・特記の連結）。要約（前月の子どもの姿／評価・反省）の "生成" は
月案 author の gather 段階（LlmAgent）に委ね、ここでは "集計" のみ行う。

集積単位＝child_id（0–2 個別前提）。生データは git 管理せず、セッション state
（state["prev_month_digest"]）／必要なら Memory Bank に置く（§10）。LLM は呼ばない。
"""

from __future__ import annotations

from collections import Counter

from ..schemas import ChildRecord, DiaryEntry


def aggregate_by_child(entries: list[DiaryEntry]) -> dict[str, dict]:
    """当月の日誌群を child_id 別に集約する（月案の前月集積の素データ）。

    Args:
        entries: 当月の日誌（DiaryEntry）のリスト。

    Returns:
        {child_id: {"note_count", "tag_freq", "observed_states"}} の決定的集約。
        tag_freq は Counter。state へ載せる serializable 版は prev_month_digest を使う。

    TODO(設計):
    - 評価・反省の双方向（予想ねらいと実際の姿の照合）を集計に織り込む（§10）。
    """
    digest: dict[str, dict] = {}
    for entry in entries:
        for note in entry.individual_notes:
            slot = digest.setdefault(
                note.child_id,
                {"note_count": 0, "tag_freq": Counter(), "observed_states": []},
            )
            slot["note_count"] += 1
            slot["tag_freq"].update(t.value for t in note.tags)
            slot["observed_states"].append(note.observed_state)
    return digest


def prev_month_digest(entries: list[DiaryEntry]) -> dict[str, dict]:
    """aggregate_by_child の結果を state へ載せられる serializable 形に正規化する（L2 還流）。

    Counter は JSON 化できる素の dict にし、タグ頻度は多い順に並べる（要約 author が読みやすい順）。
    これを月案パイプラインの先頭（DigestPrepAgent＝monthly_prep）が `state["prev_month_digest"]` に格納し、
    月案 author の gather 段階が「前月の子どもの姿／評価・反省」の要約生成に使う（§10）。

    Args:
        entries: 前月の日誌（DiaryEntry）のリスト。

    Returns:
        {child_id: {"note_count", "tag_freq"(dict・降順), "observed_states"}} の serializable 集約。
    """
    raw = aggregate_by_child(entries)
    return {
        child_id: {
            "note_count": slot["note_count"],
            "tag_freq": dict(slot["tag_freq"].most_common()),
            "observed_states": list(slot["observed_states"]),
        }
        for child_id, slot in raw.items()
    }


def format_digest_for_prompt(digest: dict[str, dict], label: str = "前月") -> str:
    """serializable な集積を、後段 author が読む人間可読テキストへ整形する（決定的・要約しない）。

    要約（子どもの姿／評価・反省・総合所見の文章化）は author（LlmAgent）の責務（§10）。ここは集計の
    "事実" を列挙するだけで解釈を加えない。空（データ無し）なら降格メッセージを返す。
    label は集積の見出し（月案＝「前月」（L2）／児童票＝「期間」（L3）。§10/§19）。
    """
    if not digest:
        return (
            f"【{label}の集積】{label}の日誌データがありません（初回、または{label}記録未提供）。"
        )
    lines = [
        f"【{label}の集積（child_id 別）】要約は子どもの姿/評価反省・総合所見を書くときに用いる:"
    ]
    for child_id, slot in digest.items():
        tags = "、".join(f"{name}×{count}" for name, count in slot["tag_freq"].items())
        lines.append(
            f"- {child_id}: 記録{slot['note_count']}件" + (f" / 多い姿: {tags}" if tags else "")
        )
        for state_text in slot["observed_states"]:
            lines.append(f"    ・{state_text}")
    return "\n".join(lines)


# ──────────────────── 保育要録（L4）＝最終年度の児童票の集積 ────────────────────
# §19 が予告した集積階層の最終段。月案（L2＝前月日誌）・児童票（L3＝期間日誌）が日誌を集計するのに対し、
# 要録（L4）は**最終年度の児童票（期の経過記録）**を child_id 別に決定的集計する（集計の実体はここに1つ）。
# 児童票は叙述型（点数化されたタグは development_notes に付く）＝期順に並べ、領域頻度・発達叙述・総合所見を
# 事実として列挙する。要約（保育の展開と子どもの育ち／個人の重点）の生成は要録 author の責務（§10/§19）。


def child_record_digest(records: list[ChildRecord]) -> dict[str, dict]:
    """最終年度の児童票群を child_id 別に集計し state へ載せられる serializable 形にする（L4 還流）。

    要録は児童別なので通常は1児の複数期ぶんの児童票が入る。期は seed 順（呼び出し側が期順に渡す）で
    保持し、発達叙述・総合所見・領域タグ頻度・配慮特記・次期に向けてを "事実" として集約する。
    解釈・要約は author（LlmAgent）が行う（ここは集計のみ・§10）。

    Args:
        records: 最終年度の児童票（ChildRecord）のリスト（期順を想定）。

    Returns:
        {child_id: {"record_count", "periods", "tag_freq"(降順), "development", "overall_notes",
        "care_notes", "next_aims"}} の serializable 集約。
    """
    slots: dict[str, dict] = {}
    for rec in records:
        slot = slots.setdefault(
            rec.child_id,
            {
                "record_count": 0,
                "periods": [],
                "tag_freq": Counter(),
                "development": [],
                "overall_notes": [],
                "care_notes": [],
                "next_aims": [],
            },
        )
        slot["record_count"] += 1
        slot["periods"].append(rec.period)
        for note in rec.development_notes:
            slot["tag_freq"].update(t.value for t in note.tags)
            slot["development"].append(f"（{rec.period}）{note.description}")
        if rec.overall_note.strip():
            slot["overall_notes"].append(f"（{rec.period}）{rec.overall_note}")
        if rec.care_notes.strip():
            slot["care_notes"].append(f"（{rec.period}）{rec.care_notes}")
        if rec.next_aims.strip():
            slot["next_aims"].append(f"（{rec.period}）{rec.next_aims}")
    return {
        child_id: {
            "record_count": slot["record_count"],
            "periods": list(slot["periods"]),
            "tag_freq": dict(slot["tag_freq"].most_common()),
            "development": list(slot["development"]),
            "overall_notes": list(slot["overall_notes"]),
            "care_notes": list(slot["care_notes"]),
            "next_aims": list(slot["next_aims"]),
        }
        for child_id, slot in slots.items()
    }


def format_record_digest_for_prompt(digest: dict[str, dict], label: str = "最終年度") -> str:
    """児童票集積（L4）を、後段 author が読む人間可読テキストへ整形する（決定的・要約しない）。

    要約（保育の展開と子どもの育ち／個人の重点／最終年度に至るまでの育ちの文章化）は author の責務
    （§10/§19）。ここは集計の "事実" を列挙するだけ。空（データ無し）なら降格メッセージを返す。
    """
    if not digest:
        return (
            f"【{label}の児童票 集積】{label}の児童票データがありません"
            f"（アーカイブ未接続、または期の児童票が未作成）。"
        )
    lines = [
        f"【{label}の児童票 集積（child_id 別・期順）】"
        "要約は保育の展開と子どもの育ち／個人の重点を書くときに用いる:"
    ]
    for child_id, slot in digest.items():
        tags = "、".join(f"{name}×{count}" for name, count in slot["tag_freq"].items())
        periods = "・".join(slot["periods"]) if slot["periods"] else "（期不明）"
        lines.append(
            f"- {child_id}: 児童票{slot['record_count']}件（{periods}）"
            + (f" / 多い領域: {tags}" if tags else "")
        )
        for text in slot["development"]:
            lines.append(f"    ・発達: {text}")
        for text in slot["overall_notes"]:
            lines.append(f"    ・総合所見: {text}")
        for text in slot["care_notes"]:
            lines.append(f"    ・配慮: {text}")
        for text in slot["next_aims"]:
            lines.append(f"    ・次期: {text}")
    return "\n".join(lines)
