"""校正AI（日本語チェック・言い換え提案）＝agentic「中身の決定」（責務②・§11）。

保育日誌を AI で全生成する代わりに、保育士が手入力した叙述文へ**校正の提案**を返す単一 LlmAgent
（ヒアリング 2026-07：日誌は自分の言葉で打つ／AI は校正者に回る）。「書類を作る」の手入力フォームから
**別エントリ**で起こす（root_agent には載せない＝upload_parser・improver と同じ別エントリの原則）。

設計判断:
- **単一 LlmAgent**（内部を多層化しない・§6）。tools なし（外部情報を取りに行かず、与えられた叙述文だけを
  校正する）。巡回・レビューは付けない＝1パスの gather→propose で、採否は保育士が UI で決める（HITL）。
- **output_schema は使わない**：作成AI/抽出AI と同じ **```json フェンス出力**に統一し、web が堅牢抽出で
  復元する（union の responseSchema は Gemini で不安定＝既存方式に合わせる）。
- **提案のみ・事実は変えない**（数値/仮名/日付/タグは触らない）。表記の機械的統一（子供→子ども）は
  finalize の notation が別途決定的に行うので、ここは文法/不自然さ/言い換え/開示前提の表現に集中する（§5）。
- doc_type 非依存（diary 先行）＝instruction は kind で開示前提の観点だけ出し分ける。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from google.adk.agents import LlmAgent

from ..models import build_model
from .prompts import build_proofread_instruction

if TYPE_CHECKING:
    from google.adk.models import BaseLlm

# 校正結果（```json フェンスを含むテキスト）を置く state キー。web/proofread が読んで復元する。
PROOFREAD_OUTPUT_KEY = "proofread_raw"


def build_proofreader_agent(kind: str = "diary", model: str | BaseLlm | None = None) -> LlmAgent:
    """校正AI（単一 LlmAgent）を構築して返す。

    Args:
        kind: 校正対象の書類種別（"diary" / "child_record" / "nursery_record" 等）。開示前提の書類
            （保育経過記録/保育要録）のとき instruction に「開示前提の表現」観点を足す（§19）。
        model: 使用モデル。既定（None）は build_model()（§11）。決定論テストで FakeLlm 等を注入する差込口。
    """
    return LlmAgent(
        name="proofreader",
        model=model if model is not None else build_model(),
        instruction=build_proofread_instruction(kind),
        # tools なし＝与えられた叙述文だけを校正する（外部情報収集はしない）。
        output_key=PROOFREAD_OUTPUT_KEY,
    )
