"""テンプレ駆動化のパリティ基準に使う代表エントリ（4種別・LLM 非依存）。

golden 捕獲（現行 write_* の出力固定）と、テンプレ駆動レンダラのパリティテストの**両方**が
同じ入力を使うための共有 fixture。実在しない仮名のみ（§14）。年齢分岐・任意欄の有無・生活記録の
出し分けなど、レイアウトの分岐が golden に現れるよう variant を用意する。

キー（`FIXTURES` の名前）はそのまま golden ファイル名（`golden/<name>.txt`）になる。
"""

from __future__ import annotations

from datetime import date

from hoiku_agent.schemas import (
    AgeBand,
    ChildAttendance,
    ChildRecord,
    DevelopmentNote,
    DiaryEntry,
    DiaryEvaluation,
    FiveDomains,
    IndividualNote,
    LifeRecord,
    MonthlyEducationNote,
    MonthlyPlan,
    NurseryRecord,
    ThreeViewpoint,
)


def diary_0_2() -> DiaryEntry:
    """0–2 日誌（生活記録あり・気温/組の任意欄あり・複数児）。"""
    return DiaryEntry(
        date=date(2026, 6, 25),
        age_band=AgeBand.零から二歳,
        weather="晴れ",
        temperature="26℃",
        class_name="ひよこ組",
        daily_aim="安心できる大人のもとで好きな遊びにじっくり関わる",
        attendance=[
            ChildAttendance(child_id="はるとくん", present=True),
            ChildAttendance(child_id="めいちゃん", present=False, reason="発熱"),
        ],
        health_notes="全員検温済み・特記なし",
        practice_record="園庭で砂遊び。保育者が言葉を添えながら感触を一緒に楽しんだ",
        individual_notes=[
            IndividualNote(
                child_id="はるとくん",
                age_months="1歳5か月",
                observed_state="砂の感触を手のひらで確かめ、繰り返し握って感触を味わった",
                tags=[ThreeViewpoint.身近なものと関わり感性が育つ],
                life_record=LifeRecord(
                    meal="完食", sleep="午睡2時間", toilet="排尿3回", mood_health="機嫌よし"
                ),
                individual_aim="素材に十分触れて満足感を得る",
            ),
            IndividualNote(
                child_id="そうたくん",
                age_months="2歳0か月",
                observed_state="保育者に「見て」と手を引いて発見を伝えようとした",
                tags=[ThreeViewpoint.身近な人と気持ちが通じ合う],
                life_record=LifeRecord(meal="八分", sleep="寝つき良好", toilet="", mood_health=""),
            ),
        ],
        evaluation=DiaryEvaluation(
            child_focus="感触遊びに集中し、満足するまで繰り返す姿が見られた",
            self_review="素材の量と動線は適切だったが、もう少し言葉かけを待つ余地があった",
        ),
        parent_contact="日中は元気に過ごしました",
    )


def diary_0_2_minimal() -> DiaryEntry:
    """0–2 日誌（任意欄なし＝気温/組/個人のねらい/家庭連絡なし・生活記録は一部空）。"""
    return DiaryEntry(
        date=date(2026, 6, 26),
        age_band=AgeBand.零から二歳,
        weather="くもり",
        daily_aim="",
        attendance=[ChildAttendance(child_id="はるとくん", present=True)],
        practice_record="室内でわらべうた遊び",
        individual_notes=[
            IndividualNote(
                child_id="はるとくん",
                observed_state="保育者の歌に合わせて体を揺らした",
                tags=[ThreeViewpoint.健やかに伸び伸びと育つ],
                life_record=LifeRecord(meal="完食", sleep="", toilet="", mood_health=""),
            ),
        ],
        evaluation=DiaryEvaluation(child_focus="リズムを楽しんだ", self_review="選曲は適切"),
    )


def diary_3_5() -> DiaryEntry:
    """3–5 日誌（5領域タグ・生活記録は記入時のみ＝空なので出さない）。"""
    return DiaryEntry(
        date=date(2026, 6, 25),
        age_band=AgeBand.三から五歳,
        weather="晴れ",
        class_name="ぞう組",
        daily_aim="友だちと協力して遊びを進める楽しさを味わう",
        attendance=[
            ChildAttendance(child_id="ゆいちゃん", present=True),
            ChildAttendance(child_id="かなたくん", present=True),
        ],
        practice_record="積み木で街づくり。役割を相談しながら進めた",
        individual_notes=[
            IndividualNote(
                child_id="ゆいちゃん",
                age_months="4歳3か月",
                observed_state="友だちに『ここは道にしよう』と提案し、役割を調整した",
                tags=[FiveDomains.人間関係, FiveDomains.言葉],
                individual_aim="考えを言葉で伝え合う",
            ),
        ],
        evaluation=DiaryEvaluation(
            child_focus="意見の食い違いを言葉で乗り越えようとした",
            self_review="見守りの距離感は適切だった",
        ),
        parent_contact="友だちと街づくりを楽しみました",
    )


def monthly() -> MonthlyPlan:
    """個別月案（0–2・養護2本柱・教育2件）。"""
    return MonthlyPlan(
        month="2026-07",
        age_band=AgeBand.零から二歳,
        child_id="はるとくん",
        age_months="1歳6か月",
        prev_child_state="前月は歩行が安定し、探索活動が活発になった",
        nurturing_life="夏の水分補給と体調管理を丁寧に行い、快適に過ごせるようにする",
        nurturing_emotion="甘えを受けとめ、安心の拠点となる関わりを重ねる",
        education=[
            MonthlyEducationNote(
                aim="水や砂の感触を全身で楽しむ",
                tags=[ThreeViewpoint.身近なものと関わり感性が育つ],
            ),
            MonthlyEducationNote(
                aim="保育者と一緒に簡単な言葉のやりとりを楽しむ",
                tags=[ThreeViewpoint.身近な人と気持ちが通じ合う],
            ),
        ],
        monthly_goals="夏ならではの感触遊びを通して探索意欲を満たす",
        environment_support="水遊びの動線と日陰を確保し、少人数で関われるようにする",
        events_family_food="七夕・水遊び開始。家庭に着替えの補充を依頼",
        evaluation_reflection="前月の探索意欲を踏まえ、感触遊びの幅を広げられた",
    )


def child_record() -> ChildRecord:
    """児童票（3–5・発達の経過2件・身体測定あり）。"""
    return ChildRecord(
        period="2026-04〜2026-06",
        age_band=AgeBand.三から五歳,
        child_id="ゆいちゃん",
        age_months="4歳2か月",
        development_notes=[
            DevelopmentNote(
                description="進級当初の緊張がほぐれ、好きな遊びに自分から関わる姿が増えた",
                tags=[FiveDomains.健康],
            ),
            DevelopmentNote(
                description="友だちの思いに気づき、順番を待つ場面が見られるようになった",
                tags=[FiveDomains.人間関係],
            ),
        ],
        care_notes="食物アレルギーへの配慮を継続（除去食・誤配防止）",
        family_liaison="家庭での午睡リズムを共有し、園と揃えるようにした",
        overall_note="安心できる関係を土台に、遊びの世界を広げている時期",
        next_aims="友だちと考えを出し合う遊びへ橋渡しする",
        height_cm="102.5",
        weight_kg="16.4",
    )


def nursery_record() -> NurseryRecord:
    """保育要録（年長・5領域・就学先/保育期間あり・特に配慮すべき事項あり）。"""
    return NurseryRecord(
        fiscal_year="2026",
        age_band=AgeBand.三から五歳,
        child_id="かなたくん",
        age_months="6歳1か月",
        final_year_focus="共通の目的に向かって思いや考えを出し合いながら活動を楽しむ",
        individual_focus="自分の力を発揮しつつ、友だちと協力して物事をやり遂げる",
        development_notes=[
            DevelopmentNote(
                description="鉄棒や縄跳びに繰り返し挑戦し、できたことを喜ぶ姿が育った",
                tags=[FiveDomains.健康],
            ),
            DevelopmentNote(
                description="話し合いで自分の考えを伝え、友だちの意見も受け入れるようになった",
                tags=[FiveDomains.人間関係, FiveDomains.言葉],
            ),
        ],
        special_notes="就学先と連携し、集団での見通しの持ち方を引き継ぐ",
        growth_until_final="入園当初は不安が大きかったが、生活のリズムが身につき、生き生きと表現を楽しむ姿へ育った",
        school_name="市立ひがし小学校",
        enrollment_period="2023-04〜2027-03",
    )


# golden ファイル名 → (write 関数のキー, ビルダ)。write のキーは Phase 2 のパリティで解決する。
FIXTURES = {
    "diary_0_2": ("diary", diary_0_2),
    "diary_0_2_minimal": ("diary", diary_0_2_minimal),
    "diary_3_5": ("diary", diary_3_5),
    "monthly": ("monthly", monthly),
    "child_record": ("child_record", child_record),
    "nursery_record": ("nursery_record", nursery_record),
}
