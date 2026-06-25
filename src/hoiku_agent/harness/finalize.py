"""harness：ドラフトの確定処理（決定的）。

設計コンテキスト §6：最終の確定 validation と整形済みドラフトの確定出力は、tool ではなく
harness のパイプライン末尾の "ステップ" として決定的に実行する。本モジュールはその純ロジック
（LLM 非依存）を持ち、pipeline.py の FinalizeAgent（薄い BaseAgent ラッパ）から呼ばれる。

作成AI（author）は instruction に従い、最終応答の末尾に DiaryEntry を表す JSON を ```json
フェンスで埋め込む（prompts.py）。ここでは:
1. その JSON を堅牢に抽出して DiaryEntry へ復元（parse_draft_to_entry）。
2. validate_fields で必須欄・年齢分岐を確定検査。
3. write_draft で様式へ確定整形。
を1関数 finalize_document にまとめ、結果を FinalizedDocument で返す。

決定的ロジックの実体は harness に1つ（§5）。tools/agents 側で再実装しない。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from ..schemas import DiaryEntry
from .draft import write_draft
from .schema_check import validate_fields


@dataclass
class FinalizedDocument:
    """確定処理の結果（決定的）。"""

    entry: DiaryEntry | None = None
    problems: list[str] = field(default_factory=list)  # validate_fields 違反（空＝充足）
    formatted: str | None = None  # write_draft の整形済み出力
    parse_error: str | None = None  # JSON 抽出/検証失敗の理由（None＝成功）

    @property
    def ok(self) -> bool:
        """型として成立（パース成功かつ違反0）か。最終OK（確定）は別途 保育士＝HITL。"""
        return self.parse_error is None and not self.problems


def extract_json_block(text: str) -> str | None:
    """テキストから DiaryEntry を表す JSON 文字列を抽出する。

    優先順位: ①```json フェンス（最後のもの） ②素の ``` フェンス ③最初の波括弧バランス。
    LLM 出力の揺れ（前後の散文・複数フェンス）に耐えるための堅牢抽出。
    """
    fences = _find_fenced_blocks(text)
    for block in reversed(fences):  # 最後の JSON フェンスを正とする
        stripped = block.strip()
        if stripped.startswith("{"):
            return stripped
    # フェンスが無ければ波括弧バランスで最初の JSON オブジェクトを拾う
    return _first_balanced_object(text)


def _find_fenced_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    i = 0
    while True:
        start = text.find("```", i)
        if start == -1:
            break
        # 言語指定（```json 等）の行末まで飛ばす
        nl = text.find("\n", start)
        if nl == -1:
            break
        end = text.find("```", nl + 1)
        if end == -1:
            break
        blocks.append(text[nl + 1 : end])
        i = end + 3
    return blocks


def _first_balanced_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def parse_draft_to_entry(text: str) -> DiaryEntry:
    """author のドラフト文字列から DiaryEntry を復元する。失敗時は ValueError。"""
    raw = extract_json_block(text)
    if raw is None:
        raise ValueError("ドラフトから DiaryEntry の JSON を抽出できなかった")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"DiaryEntry の JSON 解析に失敗: {e}") from e
    try:
        return DiaryEntry.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"DiaryEntry のスキーマ検証に失敗: {e}") from e


def finalize_document(text: str, template_ref: str | None = None) -> FinalizedDocument:
    """ドラフト文字列を確定処理（復元→検査→整形）する。

    Args:
        text: author が生成したドラフト（DiaryEntry の JSON を含む）。
        template_ref: 様式参照（あれば write_draft に渡す）。

    Returns:
        FinalizedDocument（entry / problems / formatted / parse_error）。
    """
    try:
        entry = parse_draft_to_entry(text)
    except ValueError as e:
        return FinalizedDocument(parse_error=str(e))
    problems = validate_fields(entry)
    formatted = write_draft(entry, template_ref=template_ref)
    return FinalizedDocument(entry=entry, problems=problems, formatted=formatted)
