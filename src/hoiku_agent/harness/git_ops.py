"""harness：育つ指針（カードストア JSON）の git 証拠 commit（決定的・降格付き）。

設計コンテキスト §5/§8。育つ指針の正(SSOT)は構造化カード `knowledge/文書作成指針.json`（編集の決定的
実体は `harness/policy_store.py`）。本モジュールは **保育士の決定で即反映された JSON を git に commit して
「回した証拠」を残す** 役割だけを持つ（カードの中身は触らない）。

重要な区別:
- ここで行う git は「プロダクト自身」が育つ指針を回すための操作（§8）。
- 開発者（人）のブランチ/コミット/PR 運用はグローバル CLAUDE.md のブランチ戦略に従う別物。混同しない。

安全側の既定（外向き・dev checkout を触るので）:
- `commit_policy_book(..., dry_run=True)` が既定。計画の返却のみで実 commit はしない。
- `dry_run=False` で git を実行する。失敗時は raise せず status を返して降格する（improver を落とさない）。
  暫定として repo_root（既定は dev checkout）の working tree を直接操作するため、本番は専用 worktree/clone を
  repo_root に渡して分離するのが望ましい（中期 TODO）。commit は branch に残し、処理後は元ブランチへ
  switch し戻して dev checkout を改善ブランチに残さない。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_POLICY_PATH = _REPO_ROOT / "knowledge" / "文書作成指針.json"


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)


def commit_policy_book(
    *,
    title: str,
    body: str = "",
    branch: str = "improver/policy-update",
    repo_root: Path = _REPO_ROOT,
    dry_run: bool = True,
) -> dict:
    """即反映済みのカードストア JSON を branch commit して「回した証拠」を残す（決定的・§8）。

    既定 dry_run=True は安全側：計画の返却のみ（実 commit なし）。dry_run=False で git を実行する。
    JSON 自体の更新は `policy_store.save_book`（即反映）が済ませている前提＝ここは add/commit のみ。
    git が無い・失敗した場合は raise せず status を返して降格する。
    """
    policy = repo_root / "knowledge" / "文書作成指針.json"
    plan = {"branch": branch, "title": title, "path": str(policy.relative_to(repo_root))}

    if not policy.exists():
        return {"status": "error", "stage": "check", "detail": "指針 JSON が存在しません", **plan}

    if dry_run:
        return {
            "status": "dry_run",
            **plan,
            "note": "実 commit は未実行。証拠を git に残すときに dry_run=False にする（git 必要）。",
        }

    if shutil.which("git") is None:
        return {"status": "skipped", "reason": "git 不在", **plan}

    base = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_root)
    base_branch = base.stdout.strip() or "main"

    r = _run(["git", "switch", "-c", branch], repo_root)
    if r.returncode != 0:
        return {"status": "error", "stage": "switch", "detail": r.stderr.strip(), **plan}

    for cmd in (
        ["git", "add", str(policy.relative_to(repo_root))],
        ["git", "commit", "-m", title] + (["-m", body] if body else []),
    ):
        r = _run(cmd, repo_root)
        if r.returncode != 0:
            _run(["git", "switch", base_branch], repo_root)
            return {
                "status": "error",
                "stage": " ".join(cmd[:2]),
                "detail": r.stderr.strip(),
                **plan,
            }

    head = _run(["git", "rev-parse", "--short", "HEAD"], repo_root)
    # commit は branch に残しつつ、作業ツリーは元ブランチへ戻す（dev checkout を改善ブランチに残さない）。
    _run(["git", "switch", base_branch], repo_root)
    return {"status": "committed", "commit": head.stdout.strip(), **plan}
