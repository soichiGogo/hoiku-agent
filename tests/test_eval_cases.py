"""eval ケース集合の健全性テスト（LLM 非依存・§12/§14）。

設計コンテキスト §12：評価セットは 15–30 ケース（数より質）。§14：架空の子のみ・実名禁止。
ここでは「ケースが ADK evalset として整形されている／参照ドラフトが harness の型を通る／件数が下限以上／
実名を埋め込んでいない」を決定的に検査する（採点の品質は層B eval＝要 LLM とは別）。

§14 の PII ガードレール：eval ケースの子どもは**実在しない仮名の固定ロスター**（下の名前＋ちゃん/くん）で
表す。「架空児A」のような記号名でなく現場の日誌に近い書き方にしつつ、child_id を下の `_FICTIONAL_ROSTER`
allowlist に限定することで、実名の混入を機械的に落とす（ロスター外＝必ず fail＝実名/未知名を弾く）。
新しい架空の子を eval に足すときは、実在し得ない仮名をこのロスターに追加してから使う。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hoiku_agent.harness import (
    validate_child_record_fields,
    validate_fields,
    validate_nursery_record_fields,
)
from hoiku_agent.harness.finalize import (
    parse_draft_to_child_record,
    parse_draft_to_entry,
    parse_draft_to_nursery_record,
)

_CASES_DIR = Path(__file__).resolve().parents[1] / "eval" / "cases"
_EVALSETS = sorted(_CASES_DIR.glob("*.evalset.json"))


# evalset ファイル名 → 書類種別（参照ドラフトの型）。保育経過記録/要録は diary と検査を分岐する。
def _kind_of(path: Path) -> str:
    if path.name.startswith("child_record"):
        return "child_record"
    if path.name.startswith("nursery_record"):
        return "nursery_record"
    return "diary"


# §14 allowlist：eval ケース／月案 seed で使ってよい架空の子（実在しない仮名）の固定ロスター。
# ここに無い child_id は実名/未知名の疑いとして test_cases_use_only_fictional_children が落とす。
_FICTIONAL_ROSTER: frozenset[str] = frozenset(
    {
        "はるとくん",
        "ゆいちゃん",
        "そうたくん",
        "めいちゃん",
        "りくくん",
        "こはるちゃん",
        "あおいちゃん",
        "ゆうまくん",
        "さくらちゃん",
        "れんくん",
        "ももかちゃん",
        "かえでちゃん",
        "みおちゃん",
        "そうすけくん",
        "ひなたちゃん",
        "いっとくん",
    }
)


def _all_cases() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for path in _EVALSETS:
        data = json.loads(path.read_text(encoding="utf-8"))
        for case in data["eval_cases"]:
            case["_kind"] = _kind_of(path)  # 検査分岐用のメタ（evalset 本体には無いテスト内キー）
            out.append((case["eval_id"], case))
    return out


def test_evalset_files_exist():
    assert _EVALSETS, "eval/cases に *.evalset.json が無い"


def test_case_count_meets_minimum():
    """§12：ケースの下限（数より質）。保育日誌の AI 生成を退役したため eval は下流文書中心
    （保育経過記録6＋要録3＝9件）。母集団が痩せていないかの安全網＝8件以上を要求する
    （現場データが増えたら引き上げる。クラス月案の evalset 追加は残課題）。"""
    assert len(_all_cases()) >= 8


def test_eval_ids_are_unique():
    ids = [eid for eid, _ in _all_cases()]
    assert len(ids) == len(set(ids)), "eval_id が重複している"


@pytest.mark.parametrize("eval_id,case", _all_cases(), ids=[c[0] for c in _all_cases()])
def test_reference_draft_passes_type_check(eval_id: str, case: dict):
    """各ケースの参照ドラフト（final_response）が harness の型（必須欄・年齢分岐）を通る good 例である。"""
    text = case["conversation"][0]["final_response"]["parts"][0]["text"]
    if case["_kind"] == "child_record":
        record = parse_draft_to_child_record(text)
        assert validate_child_record_fields(record) == [], f"{eval_id}: 参照ドラフトが型違反"
    elif case["_kind"] == "nursery_record":
        rec = parse_draft_to_nursery_record(text)
        assert validate_nursery_record_fields(rec) == [], f"{eval_id}: 参照ドラフトが型違反"
    else:
        entry = parse_draft_to_entry(text)
        assert validate_fields(entry) == [], f"{eval_id}: 参照ドラフトが型違反"


def _child_ids_of(case: dict) -> list[str]:
    """参照ドラフト＋seed（session_input.state）に現れる child_id を書類種別に応じて集める。"""
    text = case["conversation"][0]["final_response"]["parts"][0]["text"]
    if case["_kind"] == "child_record":
        ids = [parse_draft_to_child_record(text).child_id]
        # 保育経過記録は期間日誌を seed するため、seed 側の仮名も検査対象にする（§14）。
        state = (case.get("session_input") or {}).get("state") or {}
        for e in state.get("period_entries") or []:
            ids.extend(n.get("child_id", "") for n in e.get("individual_notes") or [])
            ids.extend(a.get("child_id", "") for a in e.get("attendance") or [])
        return ids
    if case["_kind"] == "nursery_record":
        ids = [parse_draft_to_nursery_record(text).child_id]
        # 要録は最終年度の保育経過記録を seed するため、seed 側の仮名も検査対象にする（§14）。
        state = (case.get("session_input") or {}).get("state") or {}
        ids.extend(r.get("child_id", "") for r in state.get("record_entries") or [])
        return ids
    entry = parse_draft_to_entry(text)
    return [a.child_id for a in entry.attendance] + [n.child_id for n in entry.individual_notes]


@pytest.mark.parametrize("eval_id,case", _all_cases(), ids=[c[0] for c in _all_cases()])
def test_cases_use_only_fictional_children(eval_id: str, case: dict):
    """§14：架空の子のみ（全 child_id が実在しない仮名の固定ロスター＝実名を埋め込まない）。"""
    for cid in _child_ids_of(case):
        assert cid in _FICTIONAL_ROSTER, (
            f"{eval_id}: ロスター外の child_id={cid}（実名/未知名の疑い＝§14）。"
            "架空の子なら実在しない仮名を _FICTIONAL_ROSTER に追加してから使う"
        )
