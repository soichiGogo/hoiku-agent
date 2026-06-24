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

    TODO(設計):
    - 評価・反省の双方向（予想ねらいと実際の姿の照合）を集計に織り込む（§10）。
    - 集約結果を state["prev_month_digest"] に載せる呼び出し側を pipeline に配線。
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
