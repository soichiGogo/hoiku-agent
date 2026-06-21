"""作成AI（中身の決定＝エージェント層）。

プロダクト方針 §2/§3：書類作成に足りない情報を自分で判断し、
- 不足は保育士に問い合わせる（質問生成）
- 必要な情報源（指針・過去資料・園のルール）を自分で取りに行く（Agentic RAG）
- 文書作成指針（育つ勘所）に沿って中身を埋める

"型"（書式・必須項目の充足）は上位のワークフロー層（workflow/）が保証するので、
ここは「中身」に集中する。
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from ..config import settings
from ..tools import load_writing_guideline, search_guideline

AUTHOR_INSTRUCTION = """\
あなたは保育士の書類作成を補助するアシスタントです。最終的な応答主体は保育士であり、
あなたは「保育士が編集・確定する下書き」を作ります。

手順:
1. 与えられた書類要件（DocumentSpec）と過去資料・雛形を確認する。
2. 書類を埋めるのに足りない情報があれば、推測で埋めず保育士に簡潔に質問する。
   - 質問は「実装の可否を分ける重要な点」に絞り、保育士の負荷を上げない。
3. `search_guideline` で保育所保育指針・10の姿など根拠を取りに行く。
4. `load_writing_guideline` の文書作成指針（現場の勘所）に必ず沿う。
   例: 個人名は書かない等の園ルールを守る。
5. 各記述がどの「ねらい」「10の姿」に対応するかを意識して下書きを作る。
"""


def build_author_agent() -> LlmAgent:
    return LlmAgent(
        name="author",
        model=settings.gemini_model,
        instruction=AUTHOR_INSTRUCTION,
        tools=[search_guideline, load_writing_guideline],
        output_key="draft",  # 生成した下書きを state["draft"] に格納
    )
