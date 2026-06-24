"""harness：git/PR 操作と構造化編集の適用（決定的）。

設計コンテキスト §5/§8。改善エージェント（improver/）が提案した指針更新を、ここで決定的に
適用する：構造化編集を knowledge/文書作成指針.md の該当見出しへ適用 → branch commit →
`gh pr create` → 緑なら `gh pr merge --auto`。subprocess で git/gh を叩く。

重要な区別:
- ここで行う git/PR は「プロダクト自身」が育つ指針を回すための操作。
- 開発者（人）のブランチ/コミット/PR 運用はグローバル CLAUDE.md のブランチ戦略に従う別物。
  両者を混同しない。

構造化編集フォーマット（§8）:
    {target_heading, op: add|modify|remove, before, after, rationale}
v0 スコープ（§8）: 手動起動・1見出しへの追記（add）のみ・競合検出は文字列一致レベル。

TODO(設計):
- apply_structured_edit の本実装（該当見出し配下の箇条書きへ add）。
- branch/commit/gh の subprocess 実装（鍵レス前提・層A）。保育士OK≠マージOK（採否は評価ゲート）。
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

_GUIDELINE_PATH = Path(__file__).resolve().parents[3] / "knowledge" / "文書作成指針.md"


class StructuredEdit(TypedDict):
    """propose_policy_change が返す構造化編集（§8）。"""

    target_heading: str  # 例: "### 書類別の勘所 > 保育日誌"
    op: str  # add | modify | remove（v0 は add のみ）
    before: str
    after: str
    rationale: str


def apply_structured_edit(edit: StructuredEdit, path: Path = _GUIDELINE_PATH) -> str:
    """構造化編集を文書作成指針へ適用し、変更後テキストを返す（commit はしない）。

    TODO(設計): 該当見出しを特定し op に従って箇条書きを add/modify/remove する。
    """
    raise NotImplementedError("TODO(設計): 構造化編集の適用（v0 は add のみ）")


def open_pr(branch: str, title: str, body: str) -> dict:
    """指針更新を branch commit → `gh pr create` で起票する（決定的）。

    TODO(設計): subprocess で git switch -c / commit / gh pr create。
    緑（評価ゲート通過）なら gh pr merge --auto。採否はゲートが決める（§8/§12）。
    """
    raise NotImplementedError("TODO(設計): branch/commit/gh pr create の実装")
