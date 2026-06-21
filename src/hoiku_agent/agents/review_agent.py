"""レビューAI（別視点の評価＝二軸の片方）。

プロダクト方針 §3：作成AIとは別の視点で下書きを評価し、OKを出すまで巡回する。
レビューは作成の各段階に散らさず「最終段階で一括」評価するのが効率的（§1）。

評価基準＝育つ文書作成指針（現場の勘所）＋保育所保育指針の整合＋ユーザーが追加した
レビュー項目（ReviewCriteria）。指摘（ReviewFinding）と保育士の修正差分は eval（層B）
へ還元し「回す」の証拠にする。
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from ..config import settings
from ..tools import load_writing_guideline, search_guideline

REVIEW_INSTRUCTION = """\
あなたは作成された保育書類の下書き（state["draft"]）を、作成者とは別の視点で点検する
レビュアーです。

評価観点:
1. 文書作成指針（load_writing_guideline）に反していないか（園ルール・先輩の勘所）。
2. 保育所保育指針・10の姿との整合（必要に応じ search_guideline で確認）。
3. ユーザーが追加したレビュー項目（前年データ準拠か等）。
4. 月齢・発達段階に照らして不自然な表現がないか。

出力:
- 問題がなければ「APPROVED」とだけ述べる。
- 問題があれば、指摘を ReviewFinding 形式（criterion / severity / message / suggestion）で列挙する。
  保育士が直せるよう具体的に。修正は保育士が行う（HITL）。
"""


def build_review_agent() -> LlmAgent:
    return LlmAgent(
        name="reviewer",
        model=settings.gemini_model,
        instruction=REVIEW_INSTRUCTION,
        tools=[load_writing_guideline, search_guideline],
        output_key="review",  # 指摘結果を state["review"] に格納
    )
