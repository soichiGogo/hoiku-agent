"""層B 評価ゲートの CI 統合（ADK evaluation を pytest から回す）。

設計コンテキスト §12/§16：LLM 出力の品質回帰は eval ゲートで担保し、CI のテストゲート（決定的）と
役割を分ける。ゲートの決定ロジックの実体は eval/run_gate.py に1つ置き、ここと improver.run_eval の
双方がそれを呼ぶ（二重化しない）。

判定:
- passed is True  → 緑（回帰なし）。
- passed is False → 赤（回帰）→ テスト失敗。
- passed is None  → 採点不能（ケース未整備 / LLM 資格情報なし）→ skip。
  CI で実採点する場合は資格情報（Vertex/Gemini）を入れた上でこのテストを有効化する。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_run_gate():
    gate_path = _REPO_ROOT / "eval" / "run_gate.py"
    spec = importlib.util.spec_from_file_location("hoiku_eval_run_gate", gate_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_eval_cases_regression():
    pytest.importorskip("google.adk", reason="google-adk 未インストール（uv sync 後に有効化）")

    gate = _load_run_gate()
    result = gate.run_gate()

    if result["passed"] is None:
        pytest.skip(f"採点不能のため skip（{result['status']}）: {result['detail']}")
    assert result["passed"] is True, f"評価ゲート赤（回帰）: {result['detail']}"
