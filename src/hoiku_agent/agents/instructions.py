"""作成AI・レビューAIの動的 instruction（InstructionProvider）＝文書作成指針・集積の前置注入。

設計コンテキスト §5（決定的に用意できるものは harness）/ §6（作成AI）/ §8・§9（育つ指針）。

doc_type は router で確定済み＝どの指針・どの集積が要るかも確定済みなので、文書作成指針の "提示" は
harness が決定的に用意する（探索を LLM の自発的な read_policy 呼び出しに委ねない＝旧 read_policy
ツールは撤去）。本モジュールは author/reviewer の `instruction` を **callable（ADK の
InstructionProvider）** にし、prompt の冒頭へ「この書類に適用する文書作成指針（共通＋当該書類の勘所）」と
「踏まえる集積」を決定的に差し込む。これにより作成/レビューAI は指針を**与件**として動き始める
（前提理解 → 情報収集 → 文書作成の流れ）。

集積は書類ごとに複数系統ある（依存モデル 2026-07）：
- 月案（個別）＝前月日誌の集積（L2）
- クラス月案＝クラス児童の保育経過記録すべて＋それまでのクラス月案＋経過記録に未反映の期間の
  日誌集積・評価反省（決定B）
- 保育経過記録＝該当期間の日誌集積（L3）＋前回までの保育経過記録すべて
- 保育要録＝それまでの保育経過記録すべて（L4・全期）
このため digest は (state キー, 見出しラベル, formatter) の **spec 列**で扱い、順に前置する。

責務境界：ここは prompt 文字列の**組み立て（presentation）**だけを行い、指針テキストの再生
（`harness.policy_store.render_for_doc`）と集積の整形（`harness.aggregate.format_*_for_prompt`）
という決定ロジックの実体は harness に置く（tools/ が harness を呼ぶ薄いラッパなのと同じ流儀＝§5）。
ストア未整備/障害は「指針なし」へ降格して素通りする（偽の中身を出さない・生成を止めない＝§9）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from ..harness.aggregate import (
    format_class_plan_history_for_prompt,
    format_digest_for_prompt,
    format_record_digest_for_prompt,
    format_reflections_for_prompt,
)
from ..harness.policy_store import load_book, render_for_doc
from ..schemas.policy import PolicyScope

if TYPE_CHECKING:
    from google.adk.agents.readonly_context import ReadonlyContext

# 集積 digest（state 値）を prompt 用テキストへ整形する formatter。日誌集積は format_digest_for_prompt、
# 保育経過記録集積（要録 L4・保育経過記録の前回まで・クラス月案のクラス児童）は
# format_record_digest_for_prompt、クラス月案の自己履歴は format_class_plan_history_for_prompt を使う
# （集積の実体は harness/aggregate・ここは組み立てのみ）。
_Formatter = Callable[[object, str], str]

# 集積1系統の前置指定＝（state キー, 見出しラベル, formatter）。書類ごとに複数持てる。
_DigestSpec = tuple[str, str, _Formatter]

# 振り返り（評価・反省）の前置指定＝（state キー, 見出しラベル）。クラス月案のみ（決定B・他は None）。
_ReflectionsSpec = tuple[str, str]

# 依存モデル（2026-07）の集積 spec 列。author factory と reviewer（doc_type 解決）で共用する
# （公開名＝各 author factory が build_author_instruction に渡す・二重定義しない）。
MONTHLY_DIGESTS: list[_DigestSpec] = [("prev_month_digest", "前月", format_digest_for_prompt)]
CLASS_MONTHLY_DIGESTS: list[_DigestSpec] = [
    ("class_records_digest", "クラス児童のこれまで", format_record_digest_for_prompt),
    ("class_plan_digest", "これまで", format_class_plan_history_for_prompt),
    ("class_diary_digest", "保育経過記録に未反映の期間", format_digest_for_prompt),
]
CLASS_MONTHLY_REFLECTIONS: _ReflectionsSpec = ("class_diary_reflections", "未反映期間")
CHILD_RECORD_DIGESTS: list[_DigestSpec] = [
    ("period_digest", "期間", format_digest_for_prompt),
    ("prev_records_digest", "前回まで", format_record_digest_for_prompt),
]
NURSERY_RECORD_DIGESTS: list[_DigestSpec] = [
    ("record_digest", "これまで", format_record_digest_for_prompt),
]

# state["doc_type"] → (指針 scope, 集積 spec 列, 振り返り spec)。router の doc_type 値
# （月案/クラス月案/保育経過記録/保育要録）に一致させる。**保育日誌は AI 生成を退役**したため作成/レビューAI
# では routed されないが、PolicyScope.保育日誌 は指針カード（policy_store）で有効な scope なので語彙として残す
# （保育士が日誌向けの勘所を育て、将来の校正AI が参照できる）。
_DOC_TYPE_ROUTING: dict[str, tuple[PolicyScope, list[_DigestSpec], _ReflectionsSpec | None]] = {
    "保育日誌": (PolicyScope.保育日誌, [], None),
    "月案": (PolicyScope.月案, MONTHLY_DIGESTS, None),
    # クラス月案（園の実様式・§18）は個別月案と同じ scope（月案）を流用しつつ、依存モデル 2026-07 の
    # 3系統（クラス児童の経過記録／自己履歴／未反映期間の日誌）＋評価・反省（決定B）を前置する。
    "クラス月案": (PolicyScope.月案, CLASS_MONTHLY_DIGESTS, CLASS_MONTHLY_REFLECTIONS),
    "保育経過記録": (PolicyScope.保育経過記録, CHILD_RECORD_DIGESTS, None),
    "保育要録": (PolicyScope.保育要録, NURSERY_RECORD_DIGESTS, None),
}
# doc_type 未設定時の既定（router の既定＝クラス月案＝§18。保育日誌は AI 生成を退役したため既定にしない）。
_DEFAULT_ROUTING = _DOC_TYPE_ROUTING["クラス月案"]


def _policy_text(scope: PolicyScope) -> str:
    """作る書類（scope）向けの文書作成指針（共通＋当該書類）を再生する。障害は空へ降格（§9）。"""
    try:
        return render_for_doc(load_book(), scope) or ""
    except Exception:  # noqa: BLE001  ストア未整備/壊れ/障害は降格（生成を止めない）
        return ""


def _compose(
    base: str,
    scope: PolicyScope,
    state,
    digests: list[_DigestSpec],
    reflections: _ReflectionsSpec | None = None,
) -> str:
    """指針（＋集積＋振り返り）を prompt 冒頭に前置し、base instruction を続ける（与件→手順の順）。"""
    parts: list[str] = []
    policy = _policy_text(scope)
    if policy:
        parts.append(policy)
    for digest_key, label, formatter in digests:
        digest = state.get(digest_key)
        if digest:  # 空 digest（初回・未供給）は前置しない
            parts.append(formatter(digest, label))
    if reflections:
        rows = state.get(reflections[0])
        if rows:  # 記入済みの振り返りが無ければ前置しない（クラス月案・決定B）
            parts.append(format_reflections_for_prompt(rows, reflections[1]))
    parts.append(base)
    return "\n\n".join(parts)


def build_author_instruction(
    base: str,
    scope: PolicyScope,
    digests: list[_DigestSpec] | None = None,
    reflections: _ReflectionsSpec | None = None,
) -> Callable[[ReadonlyContext], str]:
    """作成AI の InstructionProvider を作る（scope・集積 spec は書類ごとに確定＝factory 時に固定）。

    digests は書類の依存モデルに合わせた spec 列（`MONTHLY_DIGESTS` 等をそのまま渡す）。
    reflections はクラス月案のみ（`CLASS_MONTHLY_REFLECTIONS`＝評価・反省の別チャネル・決定B）。
    """
    digest_specs = digests or []

    def provider(ctx: ReadonlyContext) -> str:
        return _compose(base, scope, ctx.state, digest_specs, reflections)

    return provider


def build_review_instruction(base: str) -> Callable[[ReadonlyContext], str]:
    """レビューAI（日誌/月案/保育経過記録/保育要録で共用）の InstructionProvider を作る。

    reviewer は書類共用なので scope・集積 spec は runtime の state["doc_type"] から解決する
    （未設定は既定＝クラス月案）。作成AI と同じ指針・集積を評価基準として prompt 冒頭に前置する。
    """

    def provider(ctx: ReadonlyContext) -> str:
        scope, digests, reflections = _DOC_TYPE_ROUTING.get(
            ctx.state.get("doc_type"), _DEFAULT_ROUTING
        )
        return _compose(base, scope, ctx.state, digests, reflections)

    return provider
