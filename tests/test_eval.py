"""層B 評価ゲートの CI 統合（ADK evaluation を pytest から回す）。

設計コンテキスト §12/§16：LLM 出力の品質回帰は eval ゲートで担保し、CI のテストゲート（決定的）と
役割を分ける。ここは cases/*.evalset.json を ADK の AgentEvaluator で回す入口。

依存（google-adk）未インストール時・評価ケース未整備時は skip する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"


def test_eval_cases_regression():
    pytest.importorskip("google.adk", reason="google-adk 未インストール（uv sync 後に有効化）")

    evalsets = sorted(_CASES_DIR.glob("*.evalset.json"))
    if not evalsets:
        pytest.skip("評価ケース未整備（eval/cases/*.evalset.json を追加したら有効化）")

    # TODO(設計): AgentEvaluator.evaluate(agent_module="hoiku_agent", eval_dataset_file_path_or_dir=...)
    # を呼び、3軸平均が main 比で低下なし & must_fix 違反0 をゲートにする（§12）。構文は公式 docs で要確認。
    pytest.skip("TODO(設計): AgentEvaluator による回帰判定を実装する")
