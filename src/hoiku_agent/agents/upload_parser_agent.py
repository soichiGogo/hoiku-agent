"""アップロード取込の抽出AI（agentic「中身の決定」＝責務②・§11）。

「書類を見る」タブのアップロード（`web/upload_parse`）から**別エントリ**で起こす単一 LlmAgent。
既にある保育書類（スキャンPDF/Word/Excel）を読み取り、既存スキーマ（DiaryEntry/MonthlyPlan/
ChildRecord/NurseryRecord）へ**忠実に**書き起こす（作文しない）。root_agent には載せない
（improver と同じ別エントリの原則）。

設計判断:
- **単一 LlmAgent**（内部を多層化しない・§6）。tools なし（外部情報を取りに行かず、与えられたファイル内容
  だけから抽出する）。巡回・レビューは付けない＝取込は1パスの gather→structure で、確認・修正は保育士が
  編集フォーム（docedit.js）で行い、最終確定 validation/整形は harness（finalize_entry）が決定的に担う。
- **output_schema は使わない**：スキーマのタグ欄は `list[ThreeViewpoint|FiveDomains|TenNoSugata]` の
  union で、Gemini の responseSchema（anyOf）は不安定。作成AI と同じ **```json フェンス出力** に統一し、
  harness の堅牢抽出（`finalize.extract_json_block`）で復元する（この方式は既存 author で実証済み）。
- 種別は保育士がアップロード時に選択済み＝1スキーマに固定（instruction を種別で切替）。対象キー・age_band・
  child は与件（保育士入力）を instruction に前置し、システムが最終的に上書きする（LLM の取り違えを封じる）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import LlmAgent

from ..models import build_model
from .prompts import build_upload_extract_instruction

if TYPE_CHECKING:
    from google.adk.models import BaseLlm

# 抽出結果（```json フェンスを含むテキスト）を置く state キー。upload_parse が読んで復元する。
UPLOAD_OUTPUT_KEY = "parsed_entry_raw"


def build_upload_parser_agent(
    kind: str,
    *,
    age_band: str,
    target: str,
    child: str = "",
    model: str | BaseLlm | None = None,
) -> LlmAgent:
    """アップロード取込の抽出AI（単一 LlmAgent）を構築して返す。

    Args:
        kind: "diary" / "monthly" / "child_record" / "nursery_record"（保育士が選択済み＝1スキーマに固定）。
        age_band: 年齢帯（"0-2"/"3-5"）。タグ語彙の枠組みを決める与件（要録は "3-5" 固定）。
        target: 対象キー（日誌=対象日 / 月案=対象月 / 保育経過記録=対象期間 / 要録=対象年度）＝与件。
        child: 対象児の呼び名（月案/保育経過記録/要録の与件・日誌は空＝クラス単位）。
        model: 使用モデル。既定（None）は build_model()（§11）。決定論テストで FakeLlm 等を注入する差込口。
    """
    return LlmAgent(
        name="upload_parser",
        model=model if model is not None else build_model(),
        instruction=build_upload_extract_instruction(
            kind, age_band=age_band, target=target, child=child
        ),
        # tools なし＝与えられたファイル内容だけから抽出する（外部情報収集はしない）。
        output_key=UPLOAD_OUTPUT_KEY,
    )
