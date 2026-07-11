"""harness：月⇄日の集積（決定的）。

設計コンテキスト §4「L2 月次PDCA」/ §10「月⇄日の集積連携（L2 還流）」に対応。
集積本体は決定的：当月の個別記録（individual_notes）を child_id 別に集約する
（件数・タグ頻度・特記の連結）。要約（前月の子どもの姿／評価・反省）の "生成" は
月案 author の gather 段階（LlmAgent）に委ね、ここでは "集計" のみ行う。

集積単位＝child_id（0–2 個別前提）。生データは git 管理せず、session state の候補を
fetch_reference 経由でその場で集計する（§10）。LLM は呼ばない。
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from ..schemas import ChildRecord, ClassMonthlyPlan, DiaryEntry


def aggregate_by_child(
    entries: list[DiaryEntry], covered_by_child: dict[str, date] | None = None
) -> dict[str, dict]:
    """当月の日誌群を child_id 別に集約する（月案の前月集積の素データ）。

    Args:
        entries: 当月の日誌（DiaryEntry）のリスト。
        covered_by_child: 児童別の「経過記録に反映済みの最終日」（クラス月案のみ・§19）。渡すと、
            その児にとって反映済み（`entry.date <= 境界`）の note を集約から外す＝記録が遅れている児
            （途中入園児等）は境界が無い＝全 note を残す。クラス一律 max 境界で日誌が丸ごと落ちる欠陥の是正。

    Returns:
        {child_id: {"note_count", "tag_freq", "observed_states"}} の決定的集約。
        tag_freq は Counter。state へ載せる serializable 版は prev_month_digest を使う。

    評価・反省の双方向（予想ねらいと実際の姿の照合＝§10）は child_id 別でなく日次のクラス全体所見なので、
    ここ（child_id 別集約）でなく `collect_reflections` が日付順に別チャネルで集める（クラス月案が使う）。
    """
    digest: dict[str, dict] = {}
    for entry in entries:
        for note in entry.individual_notes:
            if covered_by_child is not None:
                cov = covered_by_child.get(note.child_id)
                if cov is not None and entry.date <= cov:
                    continue  # その児にとって経過記録に反映済み＝クラス月案 seed から外す（児童別境界）
            slot = digest.setdefault(
                note.child_id,
                {"note_count": 0, "tag_freq": Counter(), "observed_states": []},
            )
            slot["note_count"] += 1
            slot["tag_freq"].update(t.value for t in note.tags)
            slot["observed_states"].append(note.observed_state)
    return digest


def prev_month_digest(
    entries: list[DiaryEntry], covered_by_child: dict[str, date] | None = None
) -> dict[str, dict]:
    """aggregate_by_child の結果を state へ載せられる serializable 形に正規化する（L2 還流）。

    Counter は JSON 化できる素の dict にし、タグ頻度は多い順に並べる（要約 author が読みやすい順）。
    fetch_reference が候補取得時にこれを呼び、月案 author が「前月の子どもの姿／評価・反省」の
    要約生成に使う（§10）。

    Args:
        entries: 前月の日誌（DiaryEntry）のリスト。
        covered_by_child: 児童別の反映済み最終日（クラス月案のみ）。`aggregate_by_child` へ委譲する。

    Returns:
        {child_id: {"note_count", "tag_freq"(dict・降順), "observed_states"}} の serializable 集約。
    """
    raw = aggregate_by_child(entries, covered_by_child)
    return {
        child_id: {
            "note_count": slot["note_count"],
            "tag_freq": dict(slot["tag_freq"].most_common()),
            "observed_states": list(slot["observed_states"]),
        }
        for child_id, slot in raw.items()
    }


def format_digest_for_prompt(digest: dict[str, dict], label: str = "前月") -> str:
    """serializable な集積を、後段 author が読む人間可読テキストへ整形する（決定的・要約しない）。

    要約（子どもの姿／評価・反省・総合所見の文章化）は author（LlmAgent）の責務（§10）。ここは集計の
    "事実" を列挙するだけで解釈を加えない。空（データ無し）なら降格メッセージを返す。
    label は集積の見出し（月案＝「前月」（L2）／保育経過記録＝「期間」（L3）。§10/§19）。
    """
    if not digest:
        return (
            f"【{label}の集積】{label}の日誌データがありません（初回、または{label}記録未提供）。"
        )
    lines = [
        f"【{label}の集積（child_id 別）】要約は子どもの姿/評価反省・総合所見を書くときに用いる:"
    ]
    for child_id, slot in digest.items():
        tags = "、".join(f"{name}×{count}" for name, count in slot["tag_freq"].items())
        lines.append(
            f"- {child_id}: 記録{slot['note_count']}件" + (f" / 多い姿: {tags}" if tags else "")
        )
        for state_text in slot["observed_states"]:
            lines.append(f"    ・{state_text}")
    return "\n".join(lines)


def collect_reflections(entries: list[DiaryEntry]) -> list[dict]:
    """前月日誌の「評価・反省」（2視点）を日付順に集める（クラス月案の L2 還流の一部・§10）。

    評価・反省は個別記録（child_id 別）でなく**その日のクラス全体の振り返り**（(a)子どもに焦点／
    (b)自分の保育の適否）なので、child_id 別の `aggregate_by_child` とは別チャネルで日付順に集約する。
    (a)/(b) のどちらかでも記入があれば拾う（両空＝未記入の日は含めない＝プロンプトを膨らませない）。
    クラス月案 author が「先月の子どもの姿／今月のねらい」を書くとき、前月の振り返りを踏まえる素にする
    （要約・反映は author の責務＝§10・ここは集計のみ）。日付は isoformat 文字列（state へ serializable）。

    Args:
        entries: 前月の日誌（DiaryEntry）のリスト。

    Returns:
        [{"date": "YYYY-MM-DD", "child_focus": str, "self_review": str}] の日付昇順リスト。
    """
    rows: list[dict] = []
    for entry in entries:
        child_focus = (entry.evaluation.child_focus or "").strip()
        self_review = (entry.evaluation.self_review or "").strip()
        if not child_focus and not self_review:
            continue  # 両視点とも空＝未記入の日は集めない
        rows.append(
            {
                "date": entry.date.isoformat(),
                "child_focus": child_focus,
                "self_review": self_review,
            }
        )
    rows.sort(key=lambda r: r["date"])
    return rows


def format_reflections_for_prompt(reflections: list[dict], label: str = "前月") -> str:
    """前月の振り返り集積（collect_reflections）を、後段 author が読む人間可読テキストへ整形する。

    要約・今月の計画への反映は author（LlmAgent）の責務（§10）。ここは日付ごとの (a)/(b) を列挙するだけ
    （解釈を加えない）。空（記入された振り返りが無い）なら降格メッセージを返す。
    """
    if not reflections:
        return (
            f"【{label}の振り返り（評価・反省）】{label}の日誌に記入済みの評価・反省がありません"
            f"（未記入、またはデータ未提供）。"
        )
    lines = [
        f"【{label}の振り返り（評価・反省・日付順）】今月のねらい／先月の子どもの姿を書くときに踏まえる:"
    ]
    for r in reflections:
        parts = []
        if r.get("child_focus"):
            parts.append(f"(a)子どもの姿: {r['child_focus']}")
        if r.get("self_review"):
            parts.append(f"(b)保育の適否: {r['self_review']}")
        lines.append(f"- {r['date']}: " + " ／ ".join(parts))
    return "\n".join(lines)


# ──────────────────── 保育要録（L4）＝最終年度の保育経過記録の集積 ────────────────────
# §19 が予告した集積階層の最終段。月案（L2＝前月日誌）・保育経過記録（L3＝期間日誌）が日誌を集計するのに対し、
# 要録（L4）は**最終年度の保育経過記録（期の経過記録）**を child_id 別に決定的集計する（集計の実体はここに1つ）。
# 保育経過記録は叙述型（点数化されたタグは development_notes に付く）＝期順に並べ、領域頻度・発達叙述・総合所見を
# 事実として列挙する。要約（保育の展開と子どもの育ち／個人の重点）の生成は要録 author の責務（§10/§19）。


def child_record_digest(records: list[ChildRecord]) -> dict[str, dict]:
    """最終年度の保育経過記録群を child_id 別に集計し state へ載せられる serializable 形にする（L4 還流）。

    要録は児童別なので通常は1児の複数期ぶんの保育経過記録が入る。期は seed 順（呼び出し側が期順に渡す）で
    保持し、発達叙述・総合所見・領域タグ頻度・配慮特記・次期に向けてを "事実" として集約する。
    解釈・要約は author（LlmAgent）が行う（ここは集計のみ・§10）。

    Args:
        records: 最終年度の保育経過記録（ChildRecord）のリスト（期順を想定）。

    Returns:
        {child_id: {"record_count", "periods", "tag_freq"(降順), "development", "overall_notes",
        "care_notes", "next_aims"}} の serializable 集約。
    """
    slots: dict[str, dict] = {}
    for rec in records:
        slot = slots.setdefault(
            rec.child_id,
            {
                "record_count": 0,
                "periods": [],
                "tag_freq": Counter(),
                "development": [],
                "overall_notes": [],
                "care_notes": [],
                "next_aims": [],
            },
        )
        slot["record_count"] += 1
        slot["periods"].append(rec.period)
        for note in rec.development_notes:
            slot["tag_freq"].update(t.value for t in note.tags)
            slot["development"].append(f"（{rec.period}）{note.description}")
        if rec.overall_note.strip():
            slot["overall_notes"].append(f"（{rec.period}）{rec.overall_note}")
        if rec.care_notes.strip():
            slot["care_notes"].append(f"（{rec.period}）{rec.care_notes}")
        if rec.next_aims.strip():
            slot["next_aims"].append(f"（{rec.period}）{rec.next_aims}")
    return {
        child_id: {
            "record_count": slot["record_count"],
            "periods": list(slot["periods"]),
            "tag_freq": dict(slot["tag_freq"].most_common()),
            "development": list(slot["development"]),
            "overall_notes": list(slot["overall_notes"]),
            "care_notes": list(slot["care_notes"]),
            "next_aims": list(slot["next_aims"]),
        }
        for child_id, slot in slots.items()
    }


def format_record_digest_for_prompt(digest: dict[str, dict], label: str = "これまで") -> str:
    """保育経過記録集積を、後段 author が読む人間可読テキストへ整形する（決定的・要約しない）。

    要録（L4＝これまでの全期）に加え、保育経過記録の「前回まで」・クラス月案の「クラス児童の
    これまで」でも共用する（label で見出し切替）。要約（育ちの線としての文章化）は author の責務
    （§10/§19）。ここは集計の "事実" を列挙するだけ。空（データ無し）なら降格メッセージを返す。
    """
    if not digest:
        return (
            f"【{label}の保育経過記録 集積】{label}の保育経過記録データがありません"
            f"（アーカイブ未接続、または期の保育経過記録が未作成）。"
        )
    lines = [
        f"【{label}の保育経過記録 集積（child_id 別・期順）】"
        "これまでの育ちの経過・連続性を踏まえるときに用いる:"
    ]
    for child_id, slot in digest.items():
        tags = "、".join(f"{name}×{count}" for name, count in slot["tag_freq"].items())
        periods = "・".join(slot["periods"]) if slot["periods"] else "（期不明）"
        lines.append(
            f"- {child_id}: 保育経過記録{slot['record_count']}件（{periods}）"
            + (f" / 多い領域: {tags}" if tags else "")
        )
        for text in slot["development"]:
            lines.append(f"    ・発達: {text}")
        for text in slot["overall_notes"]:
            lines.append(f"    ・総合所見: {text}")
        for text in slot["care_notes"]:
            lines.append(f"    ・配慮: {text}")
        for text in slot["next_aims"]:
            lines.append(f"    ・次期: {text}")
    return "\n".join(lines)


# ──────────────────── クラス月案の自己履歴＝それまでの作成済みクラス月案の集積 ────────────────────
# 依存モデル（2026-07 確定）：クラス月案は「クラス児童の保育経過記録すべて＋それまでのクラス月案すべて＋
# 経過記録に未反映の期間の日誌」を入力にする。ここは自己履歴（過去のクラス月案）の決定的集計＝
# 月順に目標・領域別ねらい・月末の評価（記入済みのみ）を "事実" として列挙する。計画の連続性
# （ねらいの発展・前月の評価の反映）の解釈は author の責務（§10/§18）。


def class_plan_history_digest(plans: list[ClassMonthlyPlan]) -> list[dict]:
    """それまでのクラス月案群を月順の serializable 履歴に集計する（クラス月案の自己履歴還流）。

    各月から目標・区分×領域のねらい（記入行のみ）・月末の評価系欄（保育士が記入済みのときのみ＝
    PDCA の評価）を拾う。month の辞書順ソート＝ゼロ埋め YYYY-MM なので時系列（年度跨ぎも自然）。

    Args:
        plans: それまでのクラス月案（ClassMonthlyPlan）のリスト。

    Returns:
        [{"month", "monthly_goal", "aims"(domain→ねらい・記入のみ), "teacher_evaluation",
        "children_evaluation", "notable_children"}] の月昇順リスト（評価系は空なら空文字のまま）。
    """
    rows: list[dict] = []
    for plan in plans:
        rows.append(
            {
                "month": plan.month,
                "monthly_goal": plan.monthly_goal,
                "aims": {row.domain: row.aim for row in plan.grid if row.aim.strip()},
                "teacher_evaluation": plan.teacher_evaluation.strip(),
                "children_evaluation": plan.children_evaluation.strip(),
                "notable_children": plan.notable_children.strip(),
            }
        )
    rows.sort(key=lambda r: r["month"])
    return rows


def format_class_plan_history_for_prompt(history: list[dict], label: str = "これまで") -> str:
    """クラス月案の自己履歴集積を、後段 author が読む人間可読テキストへ整形する（決定的・要約しない）。

    計画の連続性（ねらいの発展・月末の評価の次月への反映）の解釈は author の責務。ここは月ごとの
    目標・ねらい・記入済みの評価を列挙するだけ。空（初回・データ無し）なら降格メッセージを返す。
    """
    if not history:
        return (
            f"【{label}のクラス月案】{label}の作成済みクラス月案がありません"
            f"（初回、またはアーカイブ未接続）。"
        )
    lines = [
        f"【{label}のクラス月案（月順）】計画の連続性（ねらいの発展・評価の反映）を踏まえるときに用いる:"
    ]
    for row in history:
        lines.append(f"- {row['month']}: 目標「{row['monthly_goal']}」")
        for domain, aim in row["aims"].items():
            lines.append(f"    ・{domain}: {aim}")
        if row["teacher_evaluation"]:
            lines.append(f"    ・保育者の評価: {row['teacher_evaluation']}")
        if row["children_evaluation"]:
            lines.append(f"    ・子どもの評価: {row['children_evaluation']}")
        if row["notable_children"]:
            lines.append(f"    ・気になる子どもへの対応: {row['notable_children']}")
    return "\n".join(lines)


def format_class_roster_for_prompt(roster: list[dict]) -> str:
    """クラスの在籍児名簿（クラス・園児マスタ）を、後段 author が読む人間可読テキストへ整形する。

    0–2 の個人目標は**名簿の在籍児全員**が基準（記録がまだ無い新入園児も落とさない・§18）。ここは
    名簿の事実（呼び名・月齢・組名）を列挙するだけで解釈しない。空（名簿未整備・未接続・該当なし）
    なら「名簿なし」を正直に返し、author は過去記録に登場した子どもでの作成へ降格できる。
    """
    rows = [r for r in roster if isinstance(r, dict) and str(r.get("child_id") or "").strip()]
    if not rows:
        return (
            "【クラスの在籍児名簿】名簿にこのクラス（年齢帯）の在籍児が登録されていません"
            "（園児未登録・名簿未整備、またはアーカイブ未接続）。個人目標（0–2）は蓄積に登場した"
            "子どもで作成してください。"
        )
    lines = ["【クラスの在籍児名簿】個人目標（0–2）はこの名簿の在籍児全員を基準に書く:"]
    for r in rows:
        detail = "・".join(
            s for s in (str(r.get("age_months") or ""), str(r.get("class_name") or "")) if s
        )
        lines.append(f"- {r['child_id']}" + (f"（{detail}）" if detail else ""))
    return "\n".join(lines)
