"""harness：必須欄の充足・年齢分岐チェック（決定的）。

設計コンテキスト §5/§10。validate_fields の "実体" はここに1つだけ置く。tools/validate_fields.py
は FunctionTool としてこれを呼ぶ薄いラッパに留める（二重実装しない＝§5/§6）。

年齢分岐は必須（§10）：
- 0–2（AgeBand.零から二歳） … 個別 note のタグ要件＝ThreeViewpoint。
- 3–5（AgeBand.三から五歳） … タグ要件＝FiveDomains。
評価・反省は2視点（child_focus / self_review）が必須（§10・DiaryEvaluation で型担保済）。

LLM は呼ばない。判定は純粋関数で、tests/test_harness/ から LLM 非依存・高速に検証できる。
"""

from __future__ import annotations

from ..schemas import AgeBand, DiaryEntry, ThreeViewpoint


def validate_fields(entry: DiaryEntry) -> list[str]:
    """日誌ドラフトの必須欄・年齢分岐を検査し、違反メッセージの一覧を返す（空＝充足）。

    Args:
        entry: 検査対象の日誌ドラフト（DiaryEntry）。

    Returns:
        違反メッセージのリスト。空リストなら "型" として成立。

    TODO(設計):
    - 必須欄の網羅（月案側スキーマ・required_sections との突き合わせ）。
    - 0–2/3–5 のタグ要件の本実装（下は 0–2 の最小チェックの骨格）。
    - 越谷市様式末尾「など」に倣い、園差の拡張欄を弾かない緩さを担保（§10）。
    """
    problems: list[str] = []

    # 年齢分岐（0–2 は個別 note に ThreeViewpoint タグを要求）
    if entry.age_band is AgeBand.零から二歳:
        for note in entry.individual_notes:
            if not any(isinstance(t, ThreeViewpoint) for t in note.tags):
                problems.append(
                    f"child_id={note.child_id}: 0–2歳は3つの視点（ThreeViewpoint）のタグが必要"
                )
    # TODO: 3–5（FiveDomains 要件）・必須欄の網羅をここに追加。

    return problems
