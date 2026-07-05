"""write_*_draft の golden パリティテスト（LLM 非依存）。

テンプレ駆動化（`harness/draft.py` の内部をテンプレ駆動レンダラへ置換）で**整形出力が変わらない**
ことを担保する回帰網。golden ファイル（`golden/<name>.txt`）は現行 write_* の出力を固定したもので、
`_doc_fixtures.FIXTURES` と 1:1 対応する。

golden の再生成（ラベル統一など**意図的**な変更を反映するとき）:
    uv run python tests/test_harness/test_draft_golden.py --write
差分は必ず PR に列挙する（silent な整形変更を作らない）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hoiku_agent.harness import (
    write_child_record_draft,
    write_draft,
    write_monthly_draft,
    write_nursery_record_draft,
)

# tests/ は __init__.py を持たない（各テスト独立の規約）。pytest の prepend import mode で
# このディレクトリが sys.path に載るため、隣の共有 fixture は絶対 import で取る（スクリプト直実行時も同様）。
from _doc_fixtures import FIXTURES

_GOLDEN_DIR = Path(__file__).parent / "golden"

# write 関数のキー → 実際の整形関数（テンプレ駆動化後もこの公開 API は不変）。
_WRITERS = {
    "diary": write_draft,
    "monthly": write_monthly_draft,
    "child_record": write_child_record_draft,
    "nursery_record": write_nursery_record_draft,
}


def _render(name: str) -> str:
    kind, builder = FIXTURES[name]
    return _WRITERS[kind](builder())


@pytest.mark.parametrize("name", list(FIXTURES))
def test_draft_matches_golden(name: str):
    golden = _GOLDEN_DIR / f"{name}.txt"
    assert golden.exists(), f"golden 未生成: {golden}（--write で生成）"
    expected = golden.read_text(encoding="utf-8")
    assert _render(name) == expected, (
        f"{name}: 整形出力が golden と不一致。意図的な変更なら --write で更新し PR に差分を列挙する"
    )


def _write_all() -> None:
    _GOLDEN_DIR.mkdir(exist_ok=True)
    for name in FIXTURES:
        (_GOLDEN_DIR / f"{name}.txt").write_text(_render(name), encoding="utf-8")
        print(f"wrote golden/{name}.txt")


if __name__ == "__main__":
    import sys

    if "--write" in sys.argv:
        _write_all()
    else:
        print("使い方: python -m tests.test_harness.test_draft_golden --write")
