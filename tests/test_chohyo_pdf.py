"""帳票PDF レンダラ（web/chohyo_pdf）の単体テスト（LLM 非依存・§11）。

描画の健全性だけを見る（必須欄・年齢分岐等の型検査は harness の責務＝ここでは検査しない）。
日本語・XML 特殊文字・空欄・欠席を含む entry で例外なく %PDF を返すこと、kind/型の異常を弾くことを確認。
"""

from __future__ import annotations

import pytest

from hoiku_agent.web.chohyo_pdf import render_pdf

_DIARY = {
    "date": "2026-06-25",
    "age_band": "0-2",
    "weather": "晴れ",
    "daily_aim": "夏の自然に触れ感触を楽しむ",
    "attendance": [
        {"child_id": "はるとくん", "present": True, "reason": None},
        {"child_id": "ゆいちゃん", "present": False, "reason": "発熱"},
    ],
    "practice_record": "園庭の砂場で感触遊び<&特殊文字>",
    "individual_notes": [
        {
            "child_id": "はるとくん",
            "age_months": "1歳3か月",
            "observed_state": "スコップで砂をすくって繰り返した",
            "tags": ["身近なものと関わり感性が育つ"],
            "life_record": {
                "meal": "完了期を8割・麦茶80ml",
                "sleep": "12:15〜14:20",
                "toilet": "排尿4回・排便1回",
                "mood_health": "体温36.5℃・機嫌よい",
            },
            "individual_aim": "感触を存分に",
        }
    ],
    "evaluation": {
        "child_focus": "感触に繰り返し関わっていた",
        "self_review": "素材を十分用意できた",
    },
    "parent_contact": "水分をしっかり",
}

_MONTHLY = {
    "month": "2026-07",
    "age_band": "0-2",
    "child_id": "はるとくん",
    "age_months": "1歳3か月",
    "prev_child_state": "前月は感触遊びに集中していた",
    "nurturing_life": "安全と生理的欲求の充足",
    "nurturing_emotion": "応答的関わりで安心を支える",
    "education": [{"aim": "素材に親しむ", "tags": ["身近なものと関わり感性が育つ"]}],
    "monthly_goals": "夏の遊びを楽しむ",
    "environment_support": "水遊びの環境を整える",
    "events_family_food": None,
    "evaluation_reflection": "翌月へつなげる",
}


_CHILD_RECORD = {
    "period": "2026-04〜2026-06",
    "age_band": "0-2",
    "child_id": "はるとくん",
    "age_months": "1歳3か月",
    "development_notes": [
        {
            "description": "伝い歩きから一人歩きへ移行し、探索範囲が広がった",
            "tags": ["健やかに伸び伸びと育つ"],
        },
        {
            "description": "指さしと発声で保育者へ伝えようとする姿が増えた",
            "tags": ["身近な人と気持ちが通じ合う"],
        },
    ],
    "care_notes": "特になし",
    "family_liaison": "連絡帳で歩行の様子を共有した",
    "overall_note": "安心できる関係を土台に自分から環境へ関わる姿が増えた",
    "next_aims": "言葉のやりとりを広げる",
}


def test_render_diary_pdf():
    b = render_pdf("diary", _DIARY)
    assert b[:4] == b"%PDF"
    # フォント埋め込みで一定サイズ以上（サブセット同梱の目安）。
    assert len(b) > 10_000


def test_render_monthly_pdf():
    b = render_pdf("monthly", _MONTHLY)
    assert b[:4] == b"%PDF"


def test_render_diary_with_temperature_and_class():
    """気温・組名（標準様式ヘッダの任意欄）を含む entry でも例外なく %PDF を返す。"""
    entry = {**_DIARY, "temperature": "26℃", "class_name": "ひよこ組"}
    b = render_pdf("diary", entry)
    assert b[:4] == b"%PDF"
    # 確認印欄（担任/主任/園長）を末尾に描くため、最小 entry より確実に大きい。
    assert len(b) > 10_000


def test_render_child_record_pdf():
    """児童票（期ごとの保育経過記録）も帳票PDF に描ける（欄順は write_child_record_draft と一致・§19）。"""
    b = render_pdf("child_record", _CHILD_RECORD)
    assert b[:4] == b"%PDF"
    assert len(b) > 10_000


def test_render_diary_3_5_without_life_record():
    """3–5 は生活記録が全欄空なら4列表を描かない（全年齢対応・§19）。例外なく %PDF を返す。"""
    entry = {
        "date": "2026-07-01",
        "age_band": "3-5",
        "weather": "晴れ",
        "individual_notes": [
            {
                "child_id": "さくらちゃん",
                "observed_state": "鬼ごっこを楽しんだ",
                "tags": ["人間関係"],
                "life_record": {},
            }
        ],
        "evaluation": {"child_focus": "友だちとの関わり", "self_review": "見守りが適切"},
    }
    b = render_pdf("diary", entry)
    assert b[:4] == b"%PDF"


def test_render_sparse_entry_does_not_raise():
    """空欄多め・タグ空・個別記録空 dict でも描画は落ちない（型検査は harness の責務）。"""
    b = render_pdf("diary", {"age_band": "0-2", "individual_notes": [{}], "evaluation": {}})
    assert b[:4] == b"%PDF"
    b2 = render_pdf("monthly", {"age_band": "0-2", "education": []})
    assert b2[:4] == b"%PDF"
    b3 = render_pdf("child_record", {"age_band": "0-2", "development_notes": []})
    assert b3[:4] == b"%PDF"


def test_invalid_kind_raises():
    with pytest.raises(ValueError):
        render_pdf("weekly", _DIARY)


def test_non_dict_entry_raises():
    with pytest.raises(ValueError):
        render_pdf("diary", "not-a-dict")
