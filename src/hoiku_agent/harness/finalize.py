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

from pydantic import BaseModel, ValidationError

from ..schemas import DiaryEntry, MonthlyPlan
from .draft import write_draft, write_monthly_draft
from .schema_check import validate_fields, validate_monthly_fields


@dataclass
class FinalizedDocument:
    """確定処理の結果（決定的）。日誌（DiaryEntry）と月案（MonthlyPlan）で共用する。"""

    entry: DiaryEntry | MonthlyPlan | None = None  # 復元した書類モデル（日誌 or 月案）
    problems: list[str] = field(default_factory=list)  # validate_* 違反（空＝充足）
    formatted: str | None = None  # write_* の整形済み出力
    parse_error: str | None = None  # JSON 抽出/検証失敗の理由（None＝成功）

    @property
    def ok(self) -> bool:
        """型として成立（パース成功かつ違反0）か。最終OK（確定）は別途 保育士＝HITL。"""
        return self.parse_error is None and not self.problems


def extract_json_block(text: str) -> str | None:
    """テキストから書類（DiaryEntry / MonthlyPlan）を表す JSON 文字列を抽出する。

    優先順位（docstring と実装を一致させる）:
      ① 言語タグが json のフェンス（複数あれば最後のもの）
      ② 言語タグ無し（素）フェンスで中身が { 始まり（複数あれば最後のもの）
      ③ 波括弧バランスで最初の JSON オブジェクト
    LLM 出力の揺れ（前後の散文・説明用の別フェンス）に耐えるための堅牢抽出。説明用に後置された
    素フェンスが正規の ```json ドラフトを上書きしないよう、言語タグを区別する。
    """
    fences = _find_fenced_blocks(text)
    json_tagged = [
        body for lang, body in fences if lang.lower() == "json" and body.strip().startswith("{")
    ]
    if json_tagged:
        return json_tagged[-1].strip()
    bare = [body for lang, body in fences if not lang and body.strip().startswith("{")]
    if bare:
        return bare[-1].strip()
    return _first_balanced_object(text)


def _find_fenced_blocks(text: str) -> list[tuple[str, str]]:
    """``` フェンスを (言語タグ, 本文) のリストで返す。"""
    blocks: list[tuple[str, str]] = []
    i = 0
    while True:
        start = text.find("```", i)
        if start == -1:
            break
        nl = text.find("\n", start)
        if nl == -1:
            break
        lang = text[start + 3 : nl].strip()
        end = text.find("```", nl + 1)
        if end == -1:
            break
        blocks.append((lang, text[nl + 1 : end]))
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


def _parse_json_to_model(text: str, model_cls: type[BaseModel], label: str) -> BaseModel:
    """ドラフト文字列から JSON を抽出し pydantic モデルへ復元する（汎用）。失敗時は ValueError。"""
    raw = extract_json_block(text)
    if raw is None:
        raise ValueError(f"ドラフトから {label} の JSON を抽出できなかった")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"{label} の JSON 解析に失敗: {e}") from e
    try:
        return model_cls.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"{label} のスキーマ検証に失敗: {e}") from e


def parse_draft_to_entry(text: str) -> DiaryEntry:
    """author のドラフト文字列から DiaryEntry を復元する。失敗時は ValueError。"""
    return _parse_json_to_model(text, DiaryEntry, "DiaryEntry")  # type: ignore[return-value]


def parse_draft_to_plan(text: str) -> MonthlyPlan:
    """月案 author のドラフト文字列から MonthlyPlan を復元する。失敗時は ValueError。"""
    return _parse_json_to_model(text, MonthlyPlan, "MonthlyPlan")  # type: ignore[return-value]


def _finalize(text, *, parse, validate, write, template_ref) -> FinalizedDocument:
    """確定処理の汎用本体（復元→検査→整形）。日誌/月案で parse/validate/write を差し替える。"""
    try:
        entry = parse(text)
    except ValueError as e:
        return FinalizedDocument(parse_error=str(e))
    problems = validate(entry)
    formatted = write(entry, template_ref=template_ref)
    return FinalizedDocument(entry=entry, problems=problems, formatted=formatted)


def finalize_document(text: str, template_ref: str | None = None) -> FinalizedDocument:
    """日誌ドラフトを確定処理（復元→検査→整形）する。

    Args:
        text: author が生成したドラフト（DiaryEntry の JSON を含む）。
        template_ref: 様式参照（あれば write_draft に渡す）。

    Returns:
        FinalizedDocument（entry / problems / formatted / parse_error）。
    """
    return _finalize(
        text,
        parse=parse_draft_to_entry,
        validate=validate_fields,
        write=write_draft,
        template_ref=template_ref,
    )


def finalize_monthly_document(text: str, template_ref: str | None = None) -> FinalizedDocument:
    """月案ドラフトを確定処理（復元→検査→整形）する（§10）。日誌の finalize_document と対称。

    Args:
        text: 月案 author が生成したドラフト（MonthlyPlan の JSON を含む）。
        template_ref: 様式参照（あれば write_monthly_draft に渡す）。

    Returns:
        FinalizedDocument（entry=MonthlyPlan / problems / formatted / parse_error）。
    """
    return _finalize(
        text,
        parse=parse_draft_to_plan,
        validate=validate_monthly_fields,
        write=write_monthly_draft,
        template_ref=template_ref,
    )
