"""層B 評価ゲートの対話的な実採点確認（ADK evaluation を pytest から回す）。

設計コンテキスト §12/§16：LLM 出力の品質回帰は eval ゲートで担保し、CI のテストゲート（決定的）と
役割を分ける。ゲートの決定ロジックの実体は eval/run_gate.py に1つ置き、ここと improver.run_eval の
双方がそれを呼ぶ（二重化しない）。

判定:
- passed is True  → 緑（回帰なし）。
- passed is False → 赤（回帰）→ テスト失敗。
- passed is None  → 対話的なローカル実行では理由を表示してskip。
  GitHubの本ゲートはこのskip経路を使わず、`run_gate.py --strict` が判定不能も非0終了にする。
"""

from __future__ import annotations

import importlib.util
import os
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
    if os.getenv("RUN_LIVE_EVAL") != "1":
        pytest.skip("実LLM採点は RUN_LIVE_EVAL=1 を明示したときだけ実行（課金・creds要）")
    pytest.importorskip("google.adk", reason="google-adk 未インストール（uv sync 後に有効化）")

    gate = _load_run_gate()
    result = gate.run_gate()

    if result["passed"] is None:
        pytest.skip(f"採点不能のため skip（{result['status']}）: {result['detail']}")
    assert result["passed"] is True, f"評価ゲート赤（回帰）: {result['detail']}"
