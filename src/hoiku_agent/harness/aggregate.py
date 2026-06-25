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

from ..schemas import DiaryEntry


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
    これを月案パイプラインの先頭（MonthlyPrepAgent）が `state["prev_month_digest"]` に格納し、
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


def format_digest_for_prompt(digest: dict[str, dict]) -> str:
    """serializable な前月集積を、月案 author が読む人間可読テキストへ整形する（決定的・要約しない）。

    要約（前月の子どもの姿／評価・反省の文章化）は author（LlmAgent）の責務（§10）。ここは集計の
    "事実" を列挙するだけで解釈を加えない。空（前月データ無し）なら降格メッセージを返す。
    """
    if not digest:
        return "【前月の集積（L2）】前月の日誌データがありません（初月、または前月記録未提供）。"
    lines = ["【前月の集積（L2・child_id 別）】要約は前月の姿/評価反省欄を書くときに用いる:"]
    for child_id, slot in digest.items():
        tags = "、".join(f"{name}×{count}" for name, count in slot["tag_freq"].items())
        lines.append(
            f"- {child_id}: 記録{slot['note_count']}件" + (f" / 多い姿: {tags}" if tags else "")
        )
        for state_text in slot["observed_states"]:
            lines.append(f"    ・{state_text}")
    return "\n".join(lines)
