"""harness：git/PR 操作と構造化編集の適用（決定的）。

設計コンテキスト §5/§8。改善エージェント（improver/）が提案した指針更新を、ここで決定的に
適用する：構造化編集を knowledge/文書作成指針.md の該当見出しへ適用 → branch commit →
`gh pr create`（→ 緑なら CI 側で `gh pr merge --auto`）。subprocess で git/gh を叩く。

重要な区別:
- ここで行う git/PR は「プロダクト自身」が育つ指針を回すための操作（§8）。
- 開発者（人）のブランチ/コミット/PR 運用はグローバル CLAUDE.md のブランチ戦略に従う別物。
  両者を混同しない。

構造化編集フォーマット（§8）:
    {target_heading, op: add|modify|remove, before, after, rationale}
v0 スコープ（§8）: 手動起動・1見出しへの追記（add）中心・競合検出は文字列一致レベル（improver 側）。

安全側の既定（外向き・不可逆の操作なので）:
- `open_pr(..., dry_run=True)` が既定。適用後テキストの算出と計画の返却のみで、実 commit/PR はしない。
  実行は `dry_run=False`（gh/git が使える環境）でのみ行い、失敗時は raise せず status を返して降格する
  （稼働中の improver を落とさない）。「閉じる1事例」を回すときに明示的に dry_run=False にする。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TypedDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
_GUIDELINE_PATH = _REPO_ROOT / "knowledge" / "文書作成指針.md"


class StructuredEdit(TypedDict):
    """propose_policy_change が返す構造化編集（§8）。"""

    target_heading: str  # 例: "### 書類別の勘所 > 保育日誌" または "### 保育日誌"
    op: str  # add | modify | remove（v0 は add 中心）
    before: str
    after: str
    rationale: str


# ──────────────────────────── 見出し解決（純関数） ────────────────────────────


def _heading_text(line: str) -> str | None:
    """markdown 見出し行なら見出しテキスト（#除去）を、そうでなければ None を返す。"""
    s = line.lstrip()
    if not s.startswith("#"):
        return None
    return s.lstrip("#").strip()


def _heading_level(line: str) -> int:
    s = line.lstrip()
    level = 0
    for ch in s:
        if ch == "#":
            level += 1
        else:
            break
    return level


def _find_heading_index(lines: list[str], target_heading: str) -> int:
    """target_heading を見出し行の index に解決する。

    "親 > 子" のパス表記（§8）は親→子で範囲を絞り一意に解決する（別セクションの同名見出しを
    誤って選ばない）。最終セグメントが複数一致して一意に定まらない場合は、黙って先頭を選ばず
    ValueError（harness の fail-loud 方針）。見つからなければ -1。
    """
    segments = [s.strip().lstrip("#").strip() for s in target_heading.split(">")]
    segments = [s for s in segments if s]
    if not segments:
        return -1
    start, end = 0, len(lines)
    idx = -1
    for n, seg in enumerate(segments):
        matches = [i for i in range(start, end) if _heading_text(lines[i]) == seg]
        if not matches:
            return -1
        if n == len(segments) - 1 and len(matches) > 1:
            raise ValueError(
                f"見出しが一意に定まらない: {target_heading!r}（候補 {len(matches)} 件）"
            )
        idx = matches[0]
        start, end = idx + 1, _section_end(lines, idx)
    return idx


def _section_end(lines: list[str], heading_idx: int) -> int:
    """見出し直下セクションの終端（同レベル以上の次見出し、無ければ末尾）を返す。"""
    level = _heading_level(lines[heading_idx])
    for j in range(heading_idx + 1, len(lines)):
        if _heading_text(lines[j]) is not None and _heading_level(lines[j]) <= level:
            return j
    return len(lines)


def _direct_content_end(lines: list[str], heading_idx: int) -> int:
    """見出し直下の "直接内容" の終端＝最初の下位/同位の次見出し（無ければ末尾）。

    add 挿入・箇条書き列挙を見出し直下のフラットな箇条書きに限定し、下位見出し配下の小節へ項目が
    紛れ込むのを防ぐ（§8 の編集単位「見出し直下の箇条書き1項目」）。
    """
    for j in range(heading_idx + 1, len(lines)):
        if _heading_text(lines[j]) is not None:
            return j
    return len(lines)


def _is_bullet(line: str) -> bool:
    """箇条書き行か（"- " 始まり）。水平線 '---' 等は箇条書きとして扱わない。"""
    return line.lstrip().startswith("- ")


def _as_bullet(text: str) -> str:
    text = text.strip()
    return text if _is_bullet(text) else f"- {text}"


def _bullet_body(line: str) -> str:
    return line.strip().lstrip("-").strip()


def list_section_bullets(target_heading: str, path: Path = _GUIDELINE_PATH) -> list[str]:
    """指定見出し直下の箇条書き項目（本文のみ）の一覧を返す（競合検出の入力・§8）。

    見出しが無ければ空リスト（競合検出を止めないため、見出しが一意に定まらない場合も空）。決定的・純関数。
    """
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").split("\n")
    try:
        idx = _find_heading_index(lines, target_heading)
    except ValueError:
        return []
    if idx == -1:
        return []
    end = _direct_content_end(lines, idx)
    return [_bullet_body(lines[j]) for j in range(idx + 1, end) if _is_bullet(lines[j])]


# ──────────────────────────── 構造化編集の適用（純関数） ────────────────────────────


def apply_structured_edit(edit: StructuredEdit, path: Path = _GUIDELINE_PATH) -> str:
    """構造化編集を文書作成指針へ適用し、変更後テキスト（文字列）を返す（書き込みはしない）。

    - add    … 該当見出しセクションの末尾（次見出しの直前）へ箇条書きを1項目追加。
    - modify … before に一致する箇条書きを after で置換。
    - remove … before に一致する箇条書きを削除。

    ファイルは書き換えず "変更後テキスト" を返す純関数（テスト可・§16）。実際の書き込み・commit は
    open_pr が行う。見出し/項目が見つからなければ ValueError。
    """
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")

    idx = _find_heading_index(lines, edit["target_heading"])
    if idx == -1:
        raise ValueError(f"見出しが見つからない: {edit['target_heading']!r}")
    # 見出し直下のフラットな箇条書きに限定（下位見出し配下の小節を侵さない）。
    end = _direct_content_end(lines, idx)

    op = edit.get("op", "add")
    after = (edit.get("after") or "").strip()
    before = (edit.get("before") or "").strip()

    if op == "add":
        if not after:
            raise ValueError("add には after（追加する項目本文）が必要")
        insert_at = idx + 1
        for j in range(end - 1, idx, -1):  # セクション内の最後の非空行の直後へ
            if lines[j].strip():
                insert_at = j + 1
                break
        lines.insert(insert_at, _as_bullet(after))
    elif op in ("modify", "remove"):
        if not before:
            raise ValueError(f"{op} には before（対象項目の本文）が必要")
        match = -1
        target_body = _bullet_body(before)
        for j in range(idx + 1, end):
            if _is_bullet(lines[j]) and _bullet_body(lines[j]) == target_body:
                match = j
                break
        if match == -1:
            raise ValueError(f"before に一致する項目が見つからない: {before!r}")
        if op == "modify":
            if not after:
                raise ValueError("modify には after が必要")
            lines[match] = _as_bullet(after)
        else:  # remove
            del lines[match]
    else:
        raise ValueError(f"未知の op: {op!r}（add|modify|remove）")

    return "\n".join(lines)


# ──────────────────────────── git/PR（subprocess・降格付き） ────────────────────────────


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


def open_pr(
    edit: StructuredEdit,
    *,
    title: str,
    body: str,
    branch: str = "improver/policy-update",
    repo_root: Path = _REPO_ROOT,
    dry_run: bool = True,
) -> dict:
    """構造化編集を適用 → branch commit → `gh pr create` で起票する（決定的・§8）。

    既定 dry_run=True は安全側：適用後テキストの算出と計画の返却のみ（実 commit/PR なし）。
    dry_run=False で git/gh を実行する。採否は CI 評価ゲートが決める（保育士OK≠マージOK＝§8/§12）。
    git/gh が無い・失敗した場合は raise せず status を返して降格する。

    注意（暫定）：dry_run=False は repo_root（既定は dev checkout）の working tree を直接操作する。
    これは「プロダクトの git 操作」だが物理的には開発者の checkout を触るため、本番は専用 worktree/clone を
    repo_root に渡して分離するのが望ましい（中期 TODO）。commit は branch に残し、処理後は元ブランチへ
    switch し戻して dev checkout を改善ブランチに残さない。
    """
    guideline = repo_root / "knowledge" / "文書作成指針.md"
    try:
        new_text = apply_structured_edit(edit, path=guideline)
    except (ValueError, OSError) as e:
        return {"status": "error", "stage": "apply", "detail": str(e)}

    plan = {
        "branch": branch,
        "title": title,
        "target_heading": edit.get("target_heading"),
        "op": edit.get("op"),
    }

    if dry_run:
        return {
            "status": "dry_run",
            **plan,
            "preview": new_text[-400:],
            "note": "実 commit/PR は未実行。閉じる1事例を回すときに dry_run=False にする（gh/git 必要）。",
        }

    if shutil.which("git") is None:
        return {"status": "skipped", "reason": "git 不在", **plan}

    base = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_root)
    base_branch = base.stdout.strip() or "main"
    steps = [
        ["git", "switch", "-c", branch],
    ]
    for cmd in steps:
        r = _run(cmd, repo_root)
        if r.returncode != 0:
            return {"status": "error", "stage": " ".join(cmd), "detail": r.stderr.strip(), **plan}

    try:
        guideline.write_text(new_text, encoding="utf-8")
    except OSError as e:
        _run(["git", "switch", base_branch], repo_root)
        return {"status": "error", "stage": "write", "detail": str(e), **plan}

    for cmd in (
        ["git", "add", str(guideline.relative_to(repo_root))],
        ["git", "commit", "-m", title],
    ):
        r = _run(cmd, repo_root)
        if r.returncode != 0:
            _run(["git", "switch", base_branch], repo_root)
            return {"status": "error", "stage": " ".join(cmd), "detail": r.stderr.strip(), **plan}

    if shutil.which("gh") is None:
        result = {"status": "committed_no_pr", "reason": "gh 不在", **plan}
    else:
        r = _run(
            ["gh", "pr", "create", "--title", title, "--body", body, "--base", base_branch],
            repo_root,
        )
        result = (
            {"status": "pr_opened", "pr_url": r.stdout.strip(), **plan}
            if r.returncode == 0
            else {"status": "committed_no_pr", "reason": r.stderr.strip(), **plan}
        )

    # commit は branch に残しつつ、作業ツリーは元ブランチへ戻す（dev checkout を改善ブランチに残さない）。
    _run(["git", "switch", base_branch], repo_root)
    return result
