"""校正AI（日本語チェック・言い換え提案）の中継サービス（§11 presentation）。

「書類を作る」の手入力フォーム（`diaryform.js`）の「日本語をチェック」から呼ぶ（`/api/proofread`）。
保育士が手入力した叙述文を集め、校正AI（`agents/proofreader_agent`）を InMemoryRunner で1パス駆動して
**提案**（誤り・不自然さ・言い換え・開示前提の表現）を返す。upload_parse と同型の別エントリ・1パス。

3責務の線:
- **抽出（決定的・web）**：entry から叙述文（プロース系フィールド）を id/パス/ラベル付きで集める。数量的な
  生活記録（食事/睡眠/排泄）や仮名/タグ/日付は校正対象にしない（AI が事実を触らないようそもそも渡さない）。
- **提案（agentic・agents）**：校正AI が ```json フェンスで {"suggestions":[...]} を返す（作文しない・採否は保育士）。
- **反映（保育士・front）**：提案の採否は `docedit`/`diaryform` の UI で保育士が決め、accept したものだけ entry へ
  反映してから確定する（自動書換はしない）。表記の機械的統一（子供→子ども）は finalize の notation が別途担う。

creds 未設定/LLM 失敗は正直に error（提案なし）を返す（偽の緑を出さない・§11）。
"""

from __future__ import annotations

import json

from google.genai import types

from ..agents.proofreader_agent import PROOFREAD_OUTPUT_KEY, build_proofreader_agent
from ..harness.finalize import extract_json_block
from ..schemas.proofread import ProofreadResult

_APP_NAME = "hoiku_proofread"
_USER_ID = "caregiver"

# 校正対象の書類種別（開示前提の書類は instruction 側で観点を足す＝proofreader_agent）。
_KINDS = ("diary", "monthly", "class_monthly", "child_record", "nursery_record")

# 校正するプロース系フィールド（数量的な生活記録・仮名・タグ・日付は含めない＝AI に事実を触らせない）。
# パスは `key` / `key.sub` / `list[].key`（list 要素は dict）。notation の NARRATIVE_FIELDS より狭い（散文限定）。
_PROOFREAD_FIELDS: dict[str, list[str]] = {
    "diary": [
        "daily_aim",
        "practice_record",
        "health_notes",
        "parent_contact",
        "individual_notes[].observed_state",
        "individual_notes[].individual_aim",
        "evaluation.child_focus",
        "evaluation.self_review",
    ],
    "monthly": [
        "prev_child_state",
        "nurturing_life",
        "nurturing_emotion",
        "monthly_goals",
        "environment_support",
        "evaluation_reflection",
    ],
    "child_record": [
        "development_notes[].description",
        "care_notes",
        "family_liaison",
        "overall_note",
        "next_aims",
    ],
    "nursery_record": [
        "final_year_focus",
        "individual_focus",
        "development_notes[].description",
        "special_notes",
        "growth_until_final",
    ],
}

# フィールド名（末尾セグメント）→ 保育士向けの短いラベル（UI 表示・AI への文脈）。
_LABELS: dict[str, str] = {
    "daily_aim": "本日のねらい",
    "practice_record": "主な活動・保育者の援助",
    "health_notes": "健康・視診",
    "parent_contact": "家庭への連絡",
    "observed_state": "子どもの姿",
    "individual_aim": "個人のねらい",
    "child_focus": "評価（子どもに焦点）",
    "self_review": "評価（自己評価）",
    "prev_child_state": "前月の子どもの姿",
    "nurturing_life": "養護：生命の保持",
    "nurturing_emotion": "養護：情緒の安定",
    "monthly_goals": "今月のねらい",
    "environment_support": "環境構成・援助",
    "evaluation_reflection": "評価・反省",
    "description": "発達の経過",
    "care_notes": "配慮・特記",
    "family_liaison": "家庭との連携",
    "overall_note": "総合所見",
    "next_aims": "次期に向けて",
    "final_year_focus": "最終年度の重点",
    "individual_focus": "個人の重点",
    "special_notes": "特に配慮すべき事項",
    "growth_until_final": "最終年度に至るまでの育ち",
}


def _split_segments(template: str) -> list[tuple[str, bool]]:
    """ "individual_notes[].observed_state" → [("individual_notes", True), ("observed_state", False)]。"""
    segs: list[tuple[str, bool]] = []
    for raw in template.split("."):
        is_list = raw.endswith("[]")
        segs.append((raw[:-2] if is_list else raw, is_list))
    return segs


def _walk(node: object, segs: list[tuple[str, bool]], prefix: str):
    """テンプレートを entry に当て、非空の文字列リーフを (具体パス, 値) で yield する。"""
    if not segs or not isinstance(node, dict):
        return
    (name, is_list), rest = segs[0], segs[1:]
    if name not in node:
        return
    val = node[name]
    path = f"{prefix}.{name}" if prefix else name
    if is_list:
        if not isinstance(val, list):
            return
        for i, item in enumerate(val):
            yield from _walk(item, rest, f"{path}[{i}]")
    elif rest:
        yield from _walk(val, rest, path)
    elif isinstance(val, str) and val.strip():
        yield path, val


def _child_of_path(entry: dict, path: str) -> str:
    """パスが individual_notes[i] を含むなら、その子の呼び名を返す（ラベルの文脈用）。空なら ""。"""
    if "individual_notes[" not in path:
        return ""
    try:
        idx = int(path.split("individual_notes[", 1)[1].split("]", 1)[0])
        notes = entry.get("individual_notes") or []
        return str((notes[idx] or {}).get("child_id") or "")
    except (ValueError, IndexError, KeyError):
        return ""


def collect_items(kind: str, entry: dict) -> list[dict]:
    """entry から校正対象の叙述文を id/パス/ラベル/本文つきで集める（純関数・非破壊）。"""
    items: list[dict] = []
    for template in _PROOFREAD_FIELDS.get(kind, []):
        leaf = template.split(".")[-1].replace("[]", "")
        base_label = _LABELS.get(leaf, leaf)
        for path, text in _walk(entry, _split_segments(template), ""):
            child = _child_of_path(entry, path)
            label = f"{child}・{base_label}" if child else base_label
            items.append({"id": len(items) + 1, "path": path, "label": label, "text": text})
    return items


def _build_message(items: list[dict]) -> str:
    """校正AI へ渡す「番号付きの叙述文リスト」を組む。"""
    lines = [
        "以下は保育士が手入力した保育書類の叙述文です。各文を校正し、改善できる点だけ提案してください。",
        "",
    ]
    for it in items:
        lines.append(f"[{it['id']}] {it['label']}:")
        lines.append(it["text"])
        lines.append("")
    return "\n".join(lines)


async def _run_proofreader(agent, message_text: str) -> str:
    """校正AI を InMemoryRunner で1パス回し、最終応答テキスト（```json を含む）を返す。"""
    from google.adk.runners import InMemoryRunner

    runner = InMemoryRunner(agent=agent, app_name=_APP_NAME)
    session = await runner.session_service.create_session(app_name=_APP_NAME, user_id=_USER_ID)
    message = types.Content(role="user", parts=[types.Part(text=message_text)])
    collected: list[str] = []
    async for event in runner.run_async(
        user_id=_USER_ID, session_id=session.id, new_message=message
    ):
        for part in getattr(getattr(event, "content", None), "parts", None) or []:
            if getattr(part, "text", None):
                collected.append(part.text)
    final = await runner.session_service.get_session(
        app_name=_APP_NAME, user_id=_USER_ID, session_id=session.id
    )
    return str((final.state or {}).get(PROOFREAD_OUTPUT_KEY) or "\n".join(collected))


async def proofread_entry(kind: str, entry: dict, *, model=None) -> dict:
    """手入力 entry の叙述文を校正AI に通し、採否用の提案（パス付き）を返す。

    Args:
        model: 校正AI のモデル（既定 None＝実 Gemini）。決定論テストで FakeLlm 等を注入する差込口。
    Returns:
        {"suggestions": [{"path","label","original","suggestion","reason","kind"}], "checked": <対象文数>,
         "error": <降格理由 or None>}。creds 無/LLM 失敗/未対応 kind は suggestions 空＋error（正直に降格）。
    """
    if kind not in _KINDS:
        return {"suggestions": [], "checked": 0, "error": f"未対応の校正種別: {kind!r}"}
    items = collect_items(kind, entry)
    if not items:
        return {
            "suggestions": [],
            "checked": 0,
            "error": None,
        }  # 叙述文が空＝何も提案しない（正常）

    by_id = {it["id"]: it for it in items}
    agent = build_proofreader_agent(kind, model=model)
    try:
        raw_text = await _run_proofreader(agent, _build_message(items))
    except Exception as e:  # noqa: BLE001  creds 未設定・LLM 失敗は正直に降格（偽の緑を出さない）
        return {
            "suggestions": [],
            "checked": len(items),
            "error": f"AI 校正に失敗しました（{type(e).__name__}: {e}）。そのまま保存もできます。",
        }

    raw_json = extract_json_block(raw_text)
    if not raw_json:
        return {"suggestions": [], "checked": len(items), "error": None}  # 提案なし（改善点なし）
    try:
        result = ProofreadResult.model_validate_json(raw_json)
    except (json.JSONDecodeError, ValueError):
        return {
            "suggestions": [],
            "checked": len(items),
            "error": None,
        }  # 壊れた出力は握って提案なし

    out: list[dict] = []
    for s in result.suggestions:
        item = by_id.get(s.id)
        # 対象外 id・空提案・元と同一・原文と一致しない提案（別文への誤爆）は落とす（安全網）。
        if item is None or not s.suggestion.strip() or s.suggestion.strip() == item["text"].strip():
            continue
        out.append(
            {
                "path": item["path"],
                "label": item["label"],
                "original": item["text"],
                "suggestion": s.suggestion.strip(),
                "reason": s.reason.strip(),
                "kind": s.kind,
            }
        )
    return {"suggestions": out, "checked": len(items), "error": None}
