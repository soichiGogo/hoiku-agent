"""改善エージェント（二階）固有のツール。

設計コンテキスト §8 ツール表。一階の tools/ とは混ぜず improver/ に同居させる（層を自己完結に）。
- propose_policy_change … 修正差分から指針更新を構造化編集で提案＋競合検出（文字列一致＝v0）。
- run_eval … 評価ゲート（eval/run_gate.py）を呼ぶ（採点の実体は eval 層・決定的）。
- open_pr … harness/git_ops.open_pr（決定的実体）を、LLM が呼びやすいフラット引数で包む薄いラッパ。
- 競合時の保育士への二択は一階と同じ `tools.ask_caregiver` を共用する（人に訊く口は1つ）。

決定的ロジックの実体は harness/eval に1つ（§5）。ここで subprocess や採点ロジックを再実装しない。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from ..harness.git_ops import StructuredEdit, list_section_bullets
from ..harness.git_ops import open_pr as _harness_open_pr
from ..tools import ask_caregiver as ask_caregiver  # noqa: PLC0414  人に訊く口は一階と共用

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _build_edit(
    target_heading: str, after: str, op: str, before: str, rationale: str
) -> StructuredEdit:
    return {
        "target_heading": target_heading,
        "op": op,
        "before": before,
        "after": after,
        "rationale": rationale,
    }


def _detect_conflicts(target_heading: str, after: str) -> list[str]:
    """既存の同見出し項目と競合しうる項目を文字列一致レベルで検出する（v0・§8）。

    競合＝完全一致（重複）／ 一方が他方を包含（上書き・細分化のすり合わせが要る）。
    """
    after_body = after.strip().lstrip("-").strip()
    conflicts: list[str] = []
    for existing in list_section_bullets(target_heading):
        if not existing:
            continue
        if existing == after_body or after_body in existing or existing in after_body:
            conflicts.append(existing)
    return conflicts


def propose_policy_change(
    target_heading: str,
    after: str,
    op: str = "add",
    before: str = "",
    rationale: str = "",
) -> dict:
    """保育士の修正差分から導いた指針更新を構造化編集として提案し、競合を検出する（§8）。

    LLM は修正差分・👍👎 を読み、更新すべき見出しと項目本文（after）を判断してこのツールを呼ぶ。
    ツールは編集を構造化（StructuredEdit）し、既存項目との競合を文字列一致で検出して返す。

    Returns:
        {"edit": StructuredEdit, "conflicts": [...], "has_conflict": bool, "guidance": str}
    """
    edit = _build_edit(target_heading, after, op, before, rationale)
    conflicts = _detect_conflicts(target_heading, after) if op == "add" else []
    guidance = (
        "競合あり：ask_caregiver で保育士に二択を仰ぎ正を確定してから open_pr へ。"
        if conflicts
        else "競合なし：run_eval で回帰チェック → open_pr（既定 dry_run）で起票。"
    )
    return {
        "edit": edit,
        "conflicts": conflicts,
        "has_conflict": bool(conflicts),
        "guidance": guidance,
    }


def _load_run_gate():
    gate_path = _REPO_ROOT / "eval" / "run_gate.py"
    spec = importlib.util.spec_from_file_location("hoiku_eval_run_gate", gate_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"run_gate を読み込めません: {gate_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_eval(evalset: str | None = None) -> dict:
    """評価ゲート（eval/run_gate.py）を呼び、回帰判定を返す（§12）。

    緑/赤の確定条件＝main 平均非劣化 & must_fix 0。ただし v0 は 3軸 judge の ADK 接続が未配線（§18）の
    ため、run_gate は採点できても passed=None（判定不能）で返す（偽の緑を出さない）。資格情報/ケースが
    無い場合も passed=None で降格。judges 連携の整備後に passed=True/False が返るようになる。

    Returns:
        run_gate の判定 dict（status / passed / mean / must_fix_violations / detail）。
    """
    try:
        gate = _load_run_gate()
    except (OSError, ImportError) as e:
        return {"status": "error", "passed": None, "detail": f"run_gate ロード失敗: {e}"}
    return gate.run_gate()


def open_pr(
    target_heading: str,
    after: str,
    title: str,
    body: str,
    op: str = "add",
    before: str = "",
    rationale: str = "",
    dry_run: bool = True,
) -> dict:
    """構造化編集を適用して branch/PR を起票する（決定的実体は harness/git_ops.open_pr）。

    既定 dry_run=True は安全側（実 commit/PR なし）。「閉じる1事例」を回すときに dry_run=False にする。
    採否は CI 評価ゲートが決める（保育士OK≠マージOK＝§8/§12）。
    """
    edit = _build_edit(target_heading, after, op, before, rationale)
    return _harness_open_pr(edit, title=title, body=body, dry_run=dry_run)
