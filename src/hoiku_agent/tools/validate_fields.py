"""ツール：必須欄の充足・年齢分岐チェック（harness への薄いラッパ）。

設計コンテキスト §5/§6。**実体は harness/schema_check.py に1つだけ**。ここはそれを FunctionTool
として author に渡すための薄いラッパで、ロジックを再実装しない（二重実装禁止＝§5）。author には
「生成途中の自己点検」に使わせる。最終の確定 validation は harness がパイプライン末尾で実行する。

引数は **ドラフトを表す JSON 文字列**（author が最終出力に出すのと同じ DiaryEntry JSON）にする。
DiaryEntry をネストした pydantic 引数として LLM に組ませると、ADK の実験的 JSON schema 機能や
深い anyOf 宣言に依存し関数呼び出しが脆くなるため、単純な string 引数で受け、内部で harness の
parse_draft_to_entry（復元）→ validate_fields（検査）を呼ぶ（復元ロジックも harness に1つ）。
"""

from __future__ import annotations

# 実体モジュールを直接参照する（harness パッケージ __init__ 経由だと
# harness.pipeline → agents → tools → ここ の循環 import に巻き込まれるため）。
# finalize/schema_check は harness/__init__ で pipeline より前に import 済みのため安全。
from ..harness.finalize import parse_draft_to_entry
from ..harness.schema_check import validate_fields as _validate_fields


def validate_fields(draft_json: str) -> list[str]:
    """下書き（DiaryEntry を表す JSON 文字列）の必須欄・年齢分岐を自己点検し、違反一覧を返す。

    Args:
        draft_json: DiaryEntry を表す JSON 文字列（```json フェンス付きでも素の JSON でも可）。

    Returns:
        違反メッセージのリスト（空＝型として成立）。JSON を解釈できない場合はその旨を1件返す。
    """
    try:
        entry = parse_draft_to_entry(draft_json)
    except ValueError as e:
        return [f"ドラフトJSONを解釈できませんでした（自己点検不可）: {e}"]
    return _validate_fields(entry)
