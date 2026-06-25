"""eval ケース集合の健全性テスト（LLM 非依存・§12/§14）。

設計コンテキスト §12：評価セットは 15–30 ケース（数より質）。§14：架空児のみ・実名禁止。
ここでは「ケースが ADK evalset として整形されている／参照ドラフトが harness の型を通る／件数が下限以上／
実名を埋め込んでいない」を決定的に検査する（採点の品質は層B eval＝要 LLM とは別）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hoiku_agent.harness import validate_fields
from hoiku_agent.harness.finalize import parse_draft_to_entry

_CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"
_EVALSETS = sorted(_CASES_DIR.glob("*.evalset.json"))


def _all_cases() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for path in _EVALSETS:
        data = json.loads(path.read_text(encoding="utf-8"))
        for case in data["eval_cases"]:
            out.append((case["eval_id"], case))
    return out


def test_evalset_files_exist():
    assert _EVALSETS, "eval/cases に *.evalset.json が無い"


def test_case_count_meets_minimum():
    """§12：15ケース以上（v0 は 15–30 で十分・数より質）。"""
    assert len(_all_cases()) >= 15


def test_eval_ids_are_unique():
    ids = [eid for eid, _ in _all_cases()]
    assert len(ids) == len(set(ids)), "eval_id が重複している"


@pytest.mark.parametrize("eval_id,case", _all_cases(), ids=[c[0] for c in _all_cases()])
def test_reference_draft_passes_type_check(eval_id: str, case: dict):
    """各ケースの参照ドラフト（final_response）が harness の型（必須欄・年齢分岐）を通る good 例である。"""
    text = case["conversation"][0]["final_response"]["parts"][0]["text"]
    entry = parse_draft_to_entry(text)
    assert validate_fields(entry) == [], f"{eval_id}: 参照ドラフトが型違反"


@pytest.mark.parametrize("eval_id,case", _all_cases(), ids=[c[0] for c in _all_cases()])
def test_cases_use_only_fictional_children(eval_id: str, case: dict):
    """§14：架空児のみ（child_id が「架空児…」で表される＝実名を埋め込まない）。"""
    text = case["conversation"][0]["final_response"]["parts"][0]["text"]
    entry = parse_draft_to_entry(text)
    child_ids = [a.child_id for a in entry.attendance] + [
        n.child_id for n in entry.individual_notes
    ]
    for cid in child_ids:
        assert cid.startswith("架空児"), f"{eval_id}: 架空児以外の child_id={cid}"
