"""改善エージェント（二階）固有のツール。

設計コンテキスト §8 ツール表。一階の tools/ とは混ぜず improver/ に同居させる（層を自己完結に）。
- propose_policy_change … 修正差分から指針更新を構造化編集で提案（Agentic）。
- run_eval … 評価セットで採点（呼ぶ判断は Agentic／中身は決定的＝eval 層）。
- open_pr … harness/git_ops.open_pr（決定的）を呼ぶ。branch/PR の実体は harness に1つ。
- 競合時の保育士への二択は一階と同じ `tools.ask_caregiver` を共用する（人に訊く口は1つ）。
"""

from __future__ import annotations

from ..harness.git_ops import StructuredEdit
from ..harness.git_ops import open_pr as open_pr  # noqa: PLC0414  決定的実体は harness に1つ
from ..tools import ask_caregiver as ask_caregiver  # noqa: PLC0414  人に訊く口は一階と共用


def propose_policy_change(diff: str, feedback: str | None = None) -> StructuredEdit:
    """保育士の修正差分から、指針更新の構造化編集を提案する（§8）。

    Returns:
        {target_heading, op, before, after, rationale}（v0 は op="add" のみ）。

    TODO(設計):
    - 差分→対象見出しの特定と after 文面の生成。
    - 競合検出（v0 は文字列一致レベル）。競合時は ask_caregiver で二択を仰ぐ。
    """
    raise NotImplementedError("TODO(設計): 構造化編集の提案（§8）")


def run_eval(evalset: str | None = None) -> dict:
    """評価セットで回帰チェックを行い、スコアを返す（採点は決定的・eval 層）。

    Returns:
        {"case_scores", "mean", "must_fix_violations"} 等のスコア（§12）。

    TODO(設計):
    - eval/ の評価ゲートを呼ぶ（adk eval / pytest）。緑条件＝main 平均非劣化 & must_fix 0。
    """
    raise NotImplementedError("TODO(設計): 評価ゲートの呼び出し（§12）")
