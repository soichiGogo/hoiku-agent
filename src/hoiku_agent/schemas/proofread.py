"""校正AI（日本語チェック・言い換え提案）の提案スキーマ。

設計コンテキスト §6（agentic）/ ヒアリング 2026-07（表記DX・言い換え・開示前提の表現）。保育日誌を
AI で全生成する代わりに、保育士が手入力した叙述文へ **校正の提案**（誤り・不自然さ・言い換え）を返す
＝AI は著者でなく校正者。**提案のみ**（保育士が accept/reject）で自動書換はしない・**事実は変えない**
（数値/仮名/日付/タグは触らない）。決定的な表記統一（子供→子ども）は finalize の notation が別途担うので、
校正AI は notation で機械化できない「文法・不自然さ・言い換え・開示前提の表現」に集中する（役割分担・§5）。

提案は書類種別に依存しない（diary 先行だが doc_type 非依存に設計）＝叙述文の id を鍵に web が
entry のフィールドパスへ写像して反映する。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# 提案の分類（UI の色分け・保育士の判断の手がかり）。閉じた語彙にしない（AI の揺れを許容し表示は既定へ寄せる）。
PROOFREAD_KINDS = ("grammar", "phrasing", "expression")


class ProofreadSuggestion(BaseModel):
    """1つの叙述文への校正提案（対象は id で示し、web が entry のパスへ写像する）。"""

    id: int = Field(description="対象叙述文の識別子（web が付番し、パスへ写像する）")
    original: str = Field(default="", description="元の文（参照用・照合に使う）")
    suggestion: str = Field(description="提案文（保育士が accept すると反映される）")
    reason: str = Field(default="", description="なぜ（誤り/不自然/言い換え/開示前提の表現）")
    kind: str = Field(default="phrasing", description="grammar / phrasing / expression")


class ProofreadResult(BaseModel):
    """校正AI の出力（提案の集合）。web が ```json フェンスから復元して検証する。"""

    suggestions: list[ProofreadSuggestion] = Field(default_factory=list)
