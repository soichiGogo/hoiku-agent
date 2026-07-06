"""アップロードされたファイル → 既存スキーマの entry dict へ変換する取込サービス（§11 presentation）。

「書類を見る」タブのアップロード取込（`/api/parse-upload`）の実体。3責務の線に沿って中継するだけ:
  1. **抽出（決定的・web）** `upload_extract` で bytes → LLM 入力コンテンツ（docx/xlsx=テキスト・pdf=生bytes）。
  2. **書き起こし（agentic・agents）** `build_upload_parser_agent` を InMemoryRunner で1パス駆動し、
     既存書類を JSON（```json フェンス）へ忠実に写す（improver_stream と同型・ただし HITL 無しの一発）。
  3. **確定検査・整形（決定的・harness）** 対象キー/child/age_band を保育士入力（与件）で権威的に上書きし、
     `finalize.extract_json_block` で復元 → `finalize_entry` で正規化→validate→整形（決定的実体は harness に1つ）。

自前の validation/整形は持たない（§5）。creds 未設定/LLM 失敗は正直に error を返す（偽の緑を出さない・§11）。
確認・修正は保育士が編集フォーム（docedit.js）で行い、保存は既存の `/api/records`（record_store）へ。
"""

from __future__ import annotations

import json

from google.genai import types

from ..agents.upload_parser_agent import UPLOAD_OUTPUT_KEY, build_upload_parser_agent
from ..harness.finalize import extract_json_block, finalize_entry
from . import upload_extract

_APP_NAME = "hoiku_upload"
_USER_ID = "caregiver"

# finalize_entry が受け付ける種別（record_store.DOC_KINDS と 1:1）。クラス月案（class_monthly）は
# クラス単位＝主対象児を持たない（日誌と同型）で、UI からは「書類を見る」タブのクラス月案フォルダから取り込む。
_KINDS = ("diary", "monthly", "class_monthly", "child_record", "nursery_record")


def _empty_entry(kind: str, *, target: str, child: str, age_band: str) -> dict:
    """抽出に失敗しても編集フォームが描けるよう、与件だけ入った最小 entry を作る。"""
    base: dict = {"age_band": age_band}
    if kind == "diary":
        base.update({"date": target, "attendance": [], "individual_notes": [], "evaluation": {}})
    elif kind == "monthly":
        base.update({"month": target, "child_id": child, "education": []})
    elif kind == "class_monthly":
        # クラス単位＝主対象児なし。必須欄（月・保育目標・先月の姿）は空で置き、grid は空＝正準化が7行へそろえる。
        base.update(
            {
                "month": target,
                "monthly_goal": "",
                "prev_month_state": "",
                "grid": [],
                "individual_goals": [],
            }
        )
    elif kind == "child_record":
        base.update({"period": target, "child_id": child, "development_notes": []})
    elif kind == "nursery_record":
        base.update({"fiscal_year": target, "child_id": child, "development_notes": []})
    return base


def _apply_authoritative_keys(
    entry: dict, kind: str, *, target: str, child: str, age_band: str
) -> dict:
    """保育士がアップロード時に指定した対象キー・child・age_band を entry へ権威的に上書きする。

    seed/検査に効く欄（対象キー・child_id・age_band）は LLM の取り違えを許さず保育士入力を正とする
    （日誌・クラス月案は child_id を持たない＝クラス単位なので個別 notes/個人目標側の子どもは原本のまま）。
    """
    e = dict(entry)
    if age_band:
        e["age_band"] = age_band
    if kind == "diary":
        e["date"] = target
    elif kind == "monthly":
        e["month"] = target
        if child:
            e["child_id"] = child
    elif kind == "class_monthly":
        e["month"] = target  # クラス単位＝主対象児なし（top-level child_id は付けない）
    elif kind == "child_record":
        e["period"] = target
        if child:
            e["child_id"] = child
    elif kind == "nursery_record":
        e["fiscal_year"] = target
        if child:
            e["child_id"] = child
    return e


async def _run_parser(agent, parts: list) -> str:
    """抽出AI を InMemoryRunner で1パス回し、最終応答テキスト（```json を含む）を返す。"""
    from google.adk.runners import InMemoryRunner

    runner = InMemoryRunner(agent=agent, app_name=_APP_NAME)
    session = await runner.session_service.create_session(app_name=_APP_NAME, user_id=_USER_ID)
    lead = types.Part(
        text="以下はアップロードされた保育書類の内容です。指示に従い、忠実に抽出してください。"
    )
    message = types.Content(role="user", parts=[lead, *parts])
    collected: list[str] = []
    async for event in runner.run_async(
        user_id=_USER_ID, session_id=session.id, new_message=message
    ):
        for part in getattr(getattr(event, "content", None), "parts", None) or []:
            if getattr(part, "text", None):
                collected.append(part.text)
    # output_key に格納された最終応答を優先し、無ければ収集テキストで代替する。
    final = await runner.session_service.get_session(
        app_name=_APP_NAME, user_id=_USER_ID, session_id=session.id
    )
    return str((final.state or {}).get(UPLOAD_OUTPUT_KEY) or "\n".join(collected))


async def parse_uploaded_file(
    kind: str,
    filename: str,
    mime_type: str | None,
    data: bytes,
    *,
    target: str,
    child: str = "",
    age_band: str = "",
) -> dict:
    """アップロード1件を entry dict へ取り込む（抽出→書き起こし→確定検査・整形）。

    Returns:
        {"kind", "entry"（編集フォーム用の dict）, "formatted", "problems", "parse_error", "ok"}。
        抽出/LLM 失敗でも entry（与件入りの最小 dict）を返し、parse_error に理由を載せる（フォームは描ける）。
    Raises:
        ValueError: 未対応 kind／未対応ファイル形式（ルートが 400 に変換）。
    """
    if kind not in _KINDS:
        raise ValueError(f"未対応の取込種別: {kind!r}")
    extracted = upload_extract.extract_upload(filename, mime_type, data)  # ValueError=未対応/壊れ
    parts = upload_extract.to_parts(extracted)
    agent = build_upload_parser_agent(kind, age_band=age_band, target=target, child=child)

    skeleton = _empty_entry(kind, target=target, child=child, age_band=age_band)
    try:
        raw_text = await _run_parser(agent, parts)
    except Exception as e:  # noqa: BLE001  creds 未設定・LLM 失敗は正直に降格（偽の緑を出さない）
        return {
            "kind": kind,
            "entry": skeleton,
            "formatted": "",
            "problems": [],
            "parse_error": f"AI 解析に失敗しました（{type(e).__name__}: {e}）。手入力で補えます。",
            "ok": False,
        }

    raw_json = extract_json_block(raw_text)
    parsed: dict | None = None
    if raw_json:
        try:
            loaded = json.loads(raw_json)
            if isinstance(loaded, dict):
                parsed = loaded
        except json.JSONDecodeError:
            parsed = None

    entry = _apply_authoritative_keys(
        parsed if parsed is not None else skeleton,
        kind,
        target=target,
        child=child,
        age_band=age_band,
    )
    result = finalize_entry(entry, kind=kind)
    # 型が成立すれば正規化後の entry を、失敗（validation エラー）でも抽出 entry をフォームに返す。
    entry_for_form = result.entry.model_dump(mode="json") if result.entry is not None else entry
    return {
        "kind": kind,
        "entry": entry_for_form,
        "formatted": result.formatted or "",
        "problems": result.problems,
        "parse_error": result.parse_error,
        "ok": result.ok,
    }
