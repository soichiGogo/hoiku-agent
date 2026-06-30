"""harness.finalize（確定処理）の単体テスト（LLM 非依存）。

設計コンテキスト §6：ドラフト復元→確定 validate/write の純ロジックを検証する。
"""

from __future__ import annotations

import json
from datetime import date

from hoiku_agent.harness.finalize import (
    extract_json_block,
    finalize_document,
    finalize_entry,
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
    {"child_id": "架空児A", "observed_state": "砂の感触を確かめた", "tags": ["身近なものと関わり感性が育つ"], "life_record": {"meal": "完食", "sleep": "午睡2時間", "toilet": "3回", "mood_health": "機嫌よし"}}
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


def test_extract_prefers_json_fence_over_trailing_bare_example():
    """正規の ```json ドラフトの後に説明用の素フェンスが付いても、json フェンスを選ぶ（回帰防止）。"""
    text = _fenced(_VALID_JSON) + '\nJSONの構造例:\n```\n{"これは": "説明用サンプル"}\n```\n'
    result = finalize_document(text)
    assert result.ok is True
    assert result.parse_error is None


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
    assert "主な活動" in result.formatted


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


# ──────────── 自由記述の必須欄は null/欠落でもクラッシュさせず「不足」で報告（B 修正の回帰防止） ────────────


def test_finalize_tolerates_null_weather_as_validation_problem():
    """author が weather を null で出しても parse は通り、validate が「天候が未記入」を不足報告する。

    以前は DiaryEntry.weather が必須 str で null が parse 段の ValidationError → 確定中止になっていた
    （author が天候を聞き漏らすと日誌が完成しない）。設計意図（validate_fields が空欄を不足として報告）に
    整合させ、ハードクラッシュさせない（§10）。
    """
    null_weather = _VALID_JSON.replace('"weather": "晴れ",', '"weather": null,')
    result = finalize_document(_fenced(null_weather))
    assert result.parse_error is None  # parse は落ちない
    assert result.ok is False  # 不足ありで確定は未完了扱い
    assert any("天候" in p for p in result.problems)
    assert result.formatted is not None  # 整形は出る
    assert "（未記入）" in result.formatted


def test_finalize_tolerates_missing_weather_key():
    """weather キーごと欠落でも parse は通り validate が「天候が未記入」を報告する。"""
    no_weather = _VALID_JSON.replace('  "weather": "晴れ",\n', "")
    result = finalize_document(_fenced(no_weather))
    assert result.parse_error is None
    assert any("天候" in p for p in result.problems)


# ──────────── 記録日（date）は harness が所有・注入する（§5・本バグの回帰防止） ────────────


def test_finalize_injects_doc_date_over_placeholder():
    """雛形 echo（YYYY-MM-DD）でも harness が記録日を注入して確定が通る（本バグの回帰防止）。"""
    placeholder = _VALID_JSON.replace('"date": "2026-06-25"', '"date": "YYYY-MM-DD"')
    result = finalize_document(_fenced(placeholder), doc_date=date(2026, 6, 27))
    assert result.ok is True
    assert result.parse_error is None
    assert result.entry.date == date(2026, 6, 27)


def test_finalize_injects_doc_date_when_author_omits_date():
    """author が date を出さない（新プロンプト準拠）でも harness が補完して確定が通る。"""
    no_date = _VALID_JSON.replace('  "date": "2026-06-25",\n', "")
    result = finalize_document(_fenced(no_date), doc_date=date(2026, 6, 27))
    assert result.ok is True
    assert result.entry.date == date(2026, 6, 27)


def test_finalize_doc_date_overrides_author_date():
    """記録日は harness が所有：author が日付を書いても doc_date で上書きする（§5）。"""
    result = finalize_document(_fenced(_VALID_JSON), doc_date=date(2026, 6, 27))
    assert result.ok is True
    assert result.entry.date == date(2026, 6, 27)


def test_finalize_placeholder_date_without_doc_date_still_parse_error():
    """doc_date 未指定 + 雛形 echo は従来どおり parse_error（注入が効いている証跡＝本バグ再現）。"""
    placeholder = _VALID_JSON.replace('"date": "2026-06-25"', '"date": "YYYY-MM-DD"')
    result = finalize_document(_fenced(placeholder))
    assert result.parse_error is not None


def test_parse_draft_to_entry_injects_doc_date():
    """parse 単体でも doc_date 指定で date を上書き復元できる。"""
    placeholder = _VALID_JSON.replace('"date": "2026-06-25"', '"date": "YYYY-MM-DD"')
    entry = parse_draft_to_entry(_fenced(placeholder), doc_date=date(2026, 6, 27))
    assert entry.date == date(2026, 6, 27)


# ──────────── finalize_entry：編集UI（保育士の編集フォーム）から dict を直接確定処理する（§6） ────────────


def test_finalize_entry_diary_roundtrip_and_validates():
    """編集後の dict を直接 finalize（検査→整形）できる。記録日は doc_date で上書きする（機械メタ）。"""
    data = json.loads(_VALID_JSON)
    result = finalize_entry(data, kind="diary", doc_date=date(2026, 6, 27))
    assert result.ok is True
    assert result.entry.date == date(2026, 6, 27)
    assert "主な活動" in result.formatted


def test_finalize_entry_surfaces_validation_problems():
    """編集で生活記録を空にしたら不足を報告する（編集後も型成立ゲートが効く）。"""
    data = json.loads(_VALID_JSON)
    data["individual_notes"][0]["life_record"] = {
        "meal": "",
        "sleep": "",
        "toilet": "",
        "mood_health": "",
    }
    result = finalize_entry(data, kind="diary", doc_date=date(2026, 6, 27))
    assert result.parse_error is None
    assert any("生活記録" in p for p in result.problems)
    assert not result.ok


def test_finalize_entry_monthly():
    """月案の編集 dict も finalize_entry(kind=monthly) で養護2本柱の様式に整形される。"""
    plan = {
        "month": "2026-07",
        "age_band": "0-2",
        "child_id": "架空児A",
        "prev_child_state": "前月は砂遊びを楽しんだ",
        "nurturing_life": "睡眠・授乳のリズムを整える",
        "nurturing_emotion": "情緒の安定を図る",
        "education": [{"aim": "感覚を働かせる", "tags": ["身近なものと関わり感性が育つ"]}],
        "monthly_goals": "感触遊びを広げる",
        "environment_support": "素材を用意する",
        "evaluation_reflection": "おおむね沿っていた",
    }
    result = finalize_entry(plan, kind="monthly")
    assert result.ok is True
    assert "養護：生命の保持" in result.formatted


def test_finalize_entry_rejects_non_dict():
    result = finalize_entry("文字列は不可", kind="diary")  # type: ignore[arg-type]
    assert result.parse_error is not None
    assert not result.ok
