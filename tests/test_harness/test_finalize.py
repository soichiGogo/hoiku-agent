"""harness.finalize（確定処理）の単体テスト（LLM 非依存）。

設計コンテキスト §6：ドラフト復元→確定 validate/write の純ロジックを検証する。
"""

from __future__ import annotations

from hoiku_agent.harness.finalize import (
    extract_json_block,
    finalize_document,
    parse_draft_to_entry,
)

_VALID_JSON = """\
{
  "date": "2026-06-25",
  "age_band": "0-2",
  "weather": "晴れ",
  "attendance": [{"child_id": "架空児A", "present": true}],
  "practice_record": "砂遊び",
  "individual_notes": [
    {"child_id": "架空児A", "observed_state": "砂の感触を確かめた", "tags": ["身近なものと関わり感性が育つ"]}
  ],
  "evaluation": {"child_focus": "集中していた", "self_review": "道具が適切"}
}
"""


def _fenced(json_text: str) -> str:
    return f"説明文。\n```json\n{json_text}\n```\n後書き。"


def test_extract_json_block_from_fence():
    assert extract_json_block(_fenced(_VALID_JSON)).strip().startswith("{")


def test_extract_prefers_last_json_fence():
    text = _fenced('{"a": 1}') + "\n" + _fenced('{"b": 2}')
    assert '"b"' in extract_json_block(text)


def test_extract_json_block_bare_object():
    assert extract_json_block("前置き " + _VALID_JSON + " 後置き").strip().startswith("{")


def test_parse_draft_to_entry_resolves_tag_union():
    entry = parse_draft_to_entry(_fenced(_VALID_JSON))
    # union tag が ThreeViewpoint として解決される
    from hoiku_agent.schemas import ThreeViewpoint

    assert isinstance(entry.individual_notes[0].tags[0], ThreeViewpoint)


def test_finalize_document_ok_path():
    result = finalize_document(_fenced(_VALID_JSON))
    assert result.ok is True
    assert result.parse_error is None
    assert result.problems == []
    assert "保育の実践記録" in result.formatted


def test_finalize_document_reports_validation_problems():
    bad = _VALID_JSON.replace('["身近なものと関わり感性が育つ"]', "[]")
    result = finalize_document(_fenced(bad))
    assert result.parse_error is None
    assert result.ok is False
    assert any("3つの視点" in p for p in result.problems)


def test_finalize_document_parse_error_when_no_json():
    result = finalize_document("JSON を含まないただの文章です。")
    assert result.parse_error is not None
    assert result.ok is False
    assert result.formatted is None


def test_finalize_document_parse_error_on_schema_violation():
    """必須フィールド欠落（evaluation 欠落）は parse_error になる。"""
    broken = _VALID_JSON.replace(
        '"evaluation": {"child_focus": "集中していた", "self_review": "道具が適切"}', '"x": 1'
    )
    result = finalize_document(_fenced(broken))
    assert result.parse_error is not None
