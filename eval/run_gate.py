"""層B 評価ゲートの実体（決定的な合否判定）。

設計コンテキスト §12：評価ゲート＝AI版回帰テスト。緑（auto-merge 可）の条件は
**PR の eval 平均が main 比で低下なし、かつ must_fix 違反0**。v0 は「main 平均を下回らない」のみを
ゲートにする（軸別閾値は 15 ケース貯まってから調整）。

採点は ADK の評価（`AgentEvaluator`）に委ねる（§11「ADK eval 内蔵」）。3軸の LLM-judge
（judges/*.md：①指針整合 ②10の姿 ③保護者向け表現）は judge プロンプト資産として持ち、ADK の
評価設定（test_config.json / rubric）から参照する想定（接続は §18 未決の整備事項）。

このモジュールは「ゲートの決定ロジック」を1箇所に集約し、improver の run_eval と
tests/test_eval.py の双方から呼ばれる（実装を二重化しない）。LLM 資格情報・評価ケースが無い環境
では採点はできないため、`passed=None`（判定不能＝スキップ相当）で安全に降格する。

CLI: `python eval/run_gate.py` でローカル実行できる。
"""

from __future__ import annotations

from pathlib import Path

_EVAL_DIR = Path(__file__).resolve().parent
_CASES_DIR = _EVAL_DIR / "cases"


def find_cases(cases_dir: Path = _CASES_DIR) -> list[Path]:
    """評価ケース（ADK evalset JSON）の一覧を返す。"""
    return sorted(cases_dir.glob("*.evalset.json"))


def run_gate(
    cases_dir: Path = _CASES_DIR,
    agent_module: str = "hoiku_agent",
    baseline_mean: float | None = None,
) -> dict:
    """評価ゲートを実行し、合否判定 dict を返す（§12）。

    Returns:
        {
          "status": "no_cases" | "skipped" | "evaluated_no_scoring",
          "passed": bool | None,        # None＝判定不能（採点不可・未配線で降格）
          "mean": float | None,         # 3軸ケース平均（採点できた場合）
          "must_fix_violations": int,
          "baseline_mean": float | None,
          "detail": str,
        }

    v0 の挙動（重要）：3軸 LLM-judge（judges/*.md）を ADK 評価設定へ接続する配線は §18 未決のため、
    実 mean・main 比較・must_fix 集計は行えない。ADK 評価が例外なく完了しても、それは ADK 既定基準
    （tool_trajectory / response_match）の通過に過ぎず §12 の3軸非劣化ではない。よって **passed は
    採点できた場合でも None（判定不能）で返し、偽の緑を出さない**。資格情報・ケースが無い場合も None。
    緑/赤の確定は judges 連携を整備し §12 の判定式（mean が baseline_mean 以上 かつ must_fix 0）を
    実装してから（その時に passed=True/False を返すよう本関数を拡張する）。
    """
    cases = find_cases(cases_dir)
    if not cases:
        return {
            "status": "no_cases",
            "passed": None,
            "mean": None,
            "must_fix_violations": 0,
            "baseline_mean": baseline_mean,
            "detail": "評価ケース未整備（eval/cases/*.evalset.json を追加すると有効化）。",
        }

    try:
        from google.adk.evaluation import AgentEvaluator  # noqa: F401
    except ImportError as e:
        return {
            "status": "skipped",
            "passed": None,
            "mean": None,
            "must_fix_violations": 0,
            "baseline_mean": baseline_mean,
            "detail": f"google-adk evaluation 未利用: {e}",
        }

    # 実採点は LLM 資格情報（Vertex/Gemini）が必要。無い環境では例外になるため降格する。
    try:
        import asyncio

        from google.adk.evaluation import AgentEvaluator

        async def _run() -> None:
            for case in cases:
                await AgentEvaluator.evaluate(
                    agent_module=agent_module,
                    eval_dataset_file_path_or_dir=str(case),
                    num_runs=1,  # v0 はコスト優先で1回（安定化が要るなら §12 と併せて増やす）
                    print_detailed_results=False,
                )

        asyncio.run(_run())
    except Exception as e:  # noqa: BLE001  資格情報なし等は判定不能として降格（ゲートを落とさない）
        return {
            "status": "skipped",
            "passed": None,
            "mean": None,
            "must_fix_violations": 0,
            "baseline_mean": baseline_mean,
            "detail": f"採点を実行できませんでした（資格情報/モデル未設定の可能性）: {type(e).__name__}: {e}",
        }

    # ここに来れば AgentEvaluator は例外なく完了したが、これは ADK 既定基準（tool_trajectory /
    # response_match）の通過に過ぎず、§12 の3軸（指針整合/10の姿/保護者向け表現）平均でも main 比
    # 非劣化でもない。judges/*.md を ADK 評価設定へ接続し軸別 mean を算出する配線は §18 未決。
    # よって緑（passed=True）とは断定せず、判定不能（passed=None）で降格する（偽の合格を出さない）。
    return {
        "status": "evaluated_no_scoring",
        "passed": None,
        "mean": None,
        "must_fix_violations": 0,
        "baseline_mean": baseline_mean,
        "detail": (
            f"{len(cases)} ケースで ADK 既定評価は完了したが、§12 の3軸採点・main 比較は未接続（§18）。"
            "緑判定は judges 連携の整備後に行う。"
        ),
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_gate(), ensure_ascii=False, indent=2))
