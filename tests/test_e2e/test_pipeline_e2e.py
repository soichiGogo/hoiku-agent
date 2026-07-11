"""決定論E2E（結合テスト）：作成パイプラインの**共用機構**を LLM/GCP 非依存に通す。

設計コンテキスト §4/§5/§16。harness（型の保証）と agents（中身）の "結合" ＝パイプラインの
順序制御を、実 Gemini を呼ばずに検証する層。author/reviewer の build_xxx(model=...) に
FakeLlm（BaseLlm の決定的スタブ）を注入し、authoring_loop（作成→レビュー→ゲートの巡回）→finalize を
実 ADK ランタイムで end-to-end に回す。creds 不要・無料・決定的なので毎PR/毎編集で回せる（品質採点は別層＝eval/）。

**保育日誌の AI 生成パイプラインは退役した**（ヒアリング 2026-07：日誌は手入力＝AI を通さない）ので、
共用機構（`build_authoring_loop`・`FinalizeAgent`）は月案/保育経過記録/要録が
使い続ける。ここでは**保育経過記録パイプライン**（`build_child_record_pipeline`）を代表の乗り物にして、
共用機構の結合経路（harness/pipeline.py・finalize.py が分岐を持つ点）を固定する:
  1. 連結          author→state["draft"]→reviewer→state["review"]→finalize→state["final_document"]
  2. 早期終了      reviewer 1行目 APPROVED で ApprovalGate が escalate（is_approved）
  3. 再作成        NEEDS_REVISION で author が次巡で再作成し、2枚目の下書きが確定される（巡回に author を含む）
  4. 巡回上限      APPROVED が出ない場合 MAX_REVIEW_ITERATIONS で頭打ち→finalize へ抜ける
  5. 確定3経路     ① 成功（problems 空・formatted 生成）② parse 失敗（finalize_parse_error）
                   ③ 検証不足（validation 非空でも確定下書きは生成される）
  6. HITL 関門     ask_caregiver を発火させずに通る／確定段で awaiting_caregiver_approval=True

中身の良し悪し（指針整合/10の姿/表現）は採点しない（それは層B eval＝要 LLM・/adk-eval）。
ここは "型と順序" だけを決定的に検証する。
"""

from __future__ import annotations

import asyncio
import json

import pytest

# google-adk 未インストール環境（CI 初期等）では結合テストは回せないので skip に降格する
# （tests/test_smoke.py / test_eval.py と同じ方針）。以降の import は ADK 前提。
pytest.importorskip("google.adk", reason="google-adk 未インストール（uv sync 後に有効化）")

from typing import AsyncGenerator  # noqa: E402

from google.adk.models import BaseLlm, LlmResponse  # noqa: E402
from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402
from pydantic import PrivateAttr  # noqa: E402

from hoiku_agent.harness.child_record import build_child_record_pipeline  # noqa: E402
from hoiku_agent.harness.pipeline import MAX_REVIEW_ITERATIONS  # noqa: E402

_APP = "hoiku_e2e"
_USER = "tester"
_MEMO = "2026-04〜2026-06 の保育経過記録の下書きを作成してください。"


class FakeLlm(BaseLlm):
    """決定論E2E 用の LLM スタブ（テスト専用・ネットワーク/creds 不要）。

    responses[i] を i 回目の generate_content_async 呼び出しで返す（末尾を超えたら最後を反復）。
    関数呼び出し（tool-use）は一切返さないため、注入先 LlmAgent はテキストを最終応答とみなし
    output_key（state["draft"] / state["review"]）へ格納する。結果として ask_caregiver（HITL）も
    発火しない＝決定論E2Eで意図的に「HITL 不発火」の経路を通す。
    """

    model: str = "fake-llm"
    responses: list[str]
    _calls: int = PrivateAttr(default=0)

    @property
    def call_count(self) -> int:
        """generate_content_async が呼ばれた回数（巡回回数の検証に使う）。"""
        return self._calls

    async def generate_content_async(
        self, llm_request, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        idx = min(self._calls, len(self.responses) - 1)
        self._calls += 1
        yield LlmResponse(
            content=types.Content(role="model", parts=[types.Part(text=self.responses[idx])])
        )


# ───────────────────────────── fixtures（架空児のみ・§14） ─────────────────────────────


def _valid_entry() -> dict:
    """validate_child_record_fields を通過する 0–2 の ChildRecord（タグ＝3つの視点）。"""
    return {
        "period": "2026-04〜2026-06",
        "age_band": "0-2",
        "child_id": "架空児A",
        "development_notes": [
            {
                "description": "感触遊びに繰り返し関わり、素材への探索が広がった。",
                "tags": ["身近なものと関わり感性が育つ"],  # ThreeViewpoint（0–2 必須）
            }
        ],
        "care_notes": "",
        "family_liaison": "",
        "overall_note": "身近なものへの興味を土台に、自分から関わる姿が育った。",
        "next_aims": "",
    }


def _author_text(entry: dict) -> str:
    """author の最終応答を模す（散文＋```json フェンスの ChildRecord）。"""
    return (
        "期間集積から保育経過記録の下書きを作成しました。\n```json\n"
        + json.dumps(entry, ensure_ascii=False, indent=2)
        + "\n```"
    )


def _base_state(extra: dict | None = None) -> dict:
    """共用機構を回すための最小 state（保育経過記録パイプラインの入力）。

    period_entries は空でよい（fetch_reference 未呼出しでも pipeline は落ちない）。
    """
    state = {"doc_type": "保育経過記録", "period_entries": []}
    if extra:
        state.update(extra)
    return state


def _function_call_names(events) -> list[str]:
    """イベント列に現れた function_call（ツール呼び出し）名を集める（HITL 不発火の検証用）。"""
    names: list[str] = []
    for ev in events:
        content = getattr(ev, "content", None)
        for part in getattr(content, "parts", None) or []:
            fc = getattr(part, "function_call", None)
            if fc is not None:
                names.append(fc.name)
    return names


def _run(author_model, reviewer_model, session_id: str = "s1", initial_state: dict | None = None):
    """pipeline をオフライン実行し (最終 state, events) を返す（決定論・creds 不要）。"""

    async def _go():
        pipeline = build_child_record_pipeline(
            author_model=author_model, reviewer_model=reviewer_model
        )
        session_service = InMemorySessionService()
        await session_service.create_session(
            app_name=_APP, user_id=_USER, session_id=session_id, state=_base_state(initial_state)
        )
        runner = Runner(app_name=_APP, agent=pipeline, session_service=session_service)
        events = [
            ev
            async for ev in runner.run_async(
                user_id=_USER,
                session_id=session_id,
                new_message=types.Content(role="user", parts=[types.Part(text=_MEMO)]),
            )
        ]
        sess = await session_service.get_session(
            app_name=_APP, user_id=_USER, session_id=session_id
        )
        return dict(sess.state), events

    return asyncio.run(_go())


# ───────────────────────────────── 結合経路テスト ─────────────────────────────────


def test_happy_path_approved_finalizes_and_skips_hitl():
    """① 連結 ＋ ② 早期終了 ＋ ④-① 確定成功 ＋ ⑤ HITL不発火/承認待ち。"""
    author = FakeLlm(responses=[_author_text(_valid_entry())])
    reviewer = FakeLlm(responses=["APPROVED\n指摘なし。"])

    state, events = _run(author, reviewer)

    # ① 連結：各段の output_key が state に乗っている
    assert "```json" in (state.get("draft") or "")
    assert (state.get("review") or "").startswith("APPROVED")
    # ④-① 確定成功：違反なし・整形済みドラフト生成・parse エラーなし
    assert state.get("validation") == []
    assert state.get("finalize_parse_error") is None
    assert state.get("final_document")
    assert state.get("final_doc_kind") == "child_record"
    # ⑤ HITL：最終OKは保育士＝承認待ちフラグが立つ／ask_caregiver は呼ばれていない
    assert state.get("awaiting_caregiver_approval") is True
    assert "ask_caregiver" not in _function_call_names(events)
    # ② 早期終了：APPROVED が1巡目で出たので reviewer は1回だけ呼ばれる
    assert reviewer.call_count == 1
    assert author.call_count == 1


def test_first_content_event_authored_by_llm_author():
    """eval 互換の回帰防止（§12）：invocation の先頭 content 付きイベントは LLM 段（author）が著者。

    ADK の rubric judge は invocation_events（＝content を持つイベント）の先頭著者の developer
    instructions を引き、非LLM段（prep）が登録されないため採点不能になる。集積を prep の content
    イベントでなく state-only 集計で運ぶことで、先頭 content 段＝author に保つ。ここでは保育経過記録
    パイプラインの先頭 content イベントが author（child_record_author）であることを固定する。
    """
    author = FakeLlm(responses=[_author_text(_valid_entry())])
    reviewer = FakeLlm(responses=["APPROVED\n指摘なし。"])

    _, events = _run(author, reviewer)

    def _has_content(ev) -> bool:
        parts = getattr(ev.content, "parts", None) if ev.content else None
        return bool(parts) and any(
            (p.text or p.function_call or p.function_response) for p in parts
        )

    first = next((e for e in events if e.author != "user" and _has_content(e)), None)
    assert first is not None
    assert first.author == "child_record_author"


def test_needs_revision_then_approved_loops_then_early_exits():
    """② 巡回が複数回回り、APPROVED が出た巡で早期終了することを検証。

    author を巡回に含めたので、1巡＝作成→レビューが author/reviewer をそれぞれ1回呼ぶ。
    """
    author = FakeLlm(responses=[_author_text(_valid_entry())])
    reviewer = FakeLlm(
        responses=["NEEDS_REVISION\n発達の経過を補ってください。", "APPROVED\n改善を確認。"]
    )

    state, _ = _run(author, reviewer)

    # 1巡目 NEEDS_REVISION（escalate せず）→ 2巡目 APPROVED（escalate）＝各2回呼ばれる
    assert reviewer.call_count == 2
    assert author.call_count == 2  # 作成AIも巡回に含まれ、2巡目で再作成している
    assert (state.get("review") or "").startswith("APPROVED")
    assert state.get("awaiting_caregiver_approval") is True


def test_needs_revision_triggers_reauthor_and_second_draft_finalizes():
    """★共用機構の核：NEEDS_REVISION で作成AIが再作成し、2枚目の下書きが確定される。

    旧構成（author をループ外）では再作成が起きず1枚目が確定していた。author を巡回に含めたことで、
    1巡目 NEEDS_REVISION → 2巡目に author が再提出 → その2枚目が finalize されることを固定する。
    """
    entry_v1 = _valid_entry()
    entry_v1["overall_note"] = "初回の総合所見（指摘前）。"
    entry_v2 = _valid_entry()
    entry_v2["overall_note"] = "修正後の総合所見（指摘を反映）。"
    author = FakeLlm(responses=[_author_text(entry_v1), _author_text(entry_v2)])
    reviewer = FakeLlm(
        responses=["NEEDS_REVISION\n総合所見を具体化してください。", "APPROVED\n改善を確認。"]
    )

    state, _ = _run(author, reviewer)

    # 1巡目（author=1/reviewer=1・NEEDS_REVISION）→ 2巡目（author=2/reviewer=2・APPROVED）で早期終了
    assert author.call_count == 2, (
        "NEEDS_REVISION で作成AIが再作成するはず（旧構成は再作成しなかった）"
    )
    assert reviewer.call_count == 2
    # 確定されるのは2枚目（再作成後）の下書き
    final_doc = state.get("final_document") or ""
    assert "修正後の総合所見（指摘を反映）。" in final_doc
    assert "初回の総合所見（指摘前）。" not in final_doc
    assert state.get("validation") == []
    assert state.get("awaiting_caregiver_approval") is True


def test_never_approved_hits_max_iterations_then_finalizes():
    """③ APPROVED が出なくても MAX_REVIEW_ITERATIONS で頭打ち→finalize へ抜ける。"""
    author = FakeLlm(responses=[_author_text(_valid_entry())])
    reviewer = FakeLlm(responses=["NEEDS_REVISION\nまだ不十分です。"])  # 常に未承認

    state, _ = _run(author, reviewer)

    assert reviewer.call_count == MAX_REVIEW_ITERATIONS  # 上限まで回って止まる
    assert author.call_count == MAX_REVIEW_ITERATIONS  # 作成AIも各巡で再作成を試みる
    assert not (state.get("review") or "").startswith("APPROVED")
    # 早期終了しなくても finalize は必ず実行される（確定下書き＋承認待ち）
    assert state.get("final_document")
    assert state.get("awaiting_caregiver_approval") is True


def test_parse_error_when_draft_has_no_json():
    """④-② author 出力に ChildRecord JSON が無ければ finalize は parse_error を立てる。"""
    author = FakeLlm(responses=["集積が不足しており下書きを作成できませんでした。"])  # 波括弧なし
    reviewer = FakeLlm(responses=["APPROVED\n（内容なし）"])

    state, _ = _run(author, reviewer)

    assert state.get("finalize_parse_error")  # 抽出失敗の理由が入る
    assert state.get("final_document") is None  # 整形は行われない
    assert state.get("awaiting_caregiver_approval") is True  # それでも人の確認に回す


def test_validation_problems_surface_but_draft_still_produced():
    """④-③ パースは成功するが年齢分岐タグ不足→validation 非空・確定下書きは生成。"""
    entry = _valid_entry()
    entry["development_notes"][0]["tags"] = ["表現"]  # FiveDomains＝0–2 では不適合
    author = FakeLlm(responses=[_author_text(entry)])
    reviewer = FakeLlm(responses=["APPROVED\n（型は別途）"])

    state, _ = _run(author, reviewer)

    problems = state.get("validation") or []
    assert problems, "0–2 に 5領域タグ→年齢分岐違反が検出されるはず"
    assert any("3つの視点" in p for p in problems)
    assert state.get("finalize_parse_error") is None  # parse は成功している
    assert state.get("final_document")  # 違反があっても確定下書きは作る（人が直す）
    assert state.get("awaiting_caregiver_approval") is True


def test_all_events_share_one_invocation_id_for_eval_compat():
    """eval 互換：1ユーザターンの全イベントが同一の非空 invocation_id を持つこと。

    ADK の eval は「invocation 数＝conversation 数」を要求する（local_eval_service・採点段）。
    custom BaseAgent（ApprovalGate/FinalizeAgent）が Event に invocation_id を
    伝播しないと、それらが空 id の別 invocation 扱いになり、1ターンが複数 invocation に割れて
    本採点が ValueError で落ちる。harness 側で ctx.invocation_id を載せる回帰防止。
    """
    author = FakeLlm(responses=[_author_text(_valid_entry())])
    reviewer = FakeLlm(responses=["APPROVED\n指摘なし。"])

    _, events = _run(author, reviewer)

    inv_ids = {ev.invocation_id for ev in events}
    assert "" not in inv_ids and None not in inv_ids, (
        f"全イベントが非空 invocation_id を持つべき（custom agent 由来の欠落を検出）: {inv_ids}"
    )
    assert len(inv_ids) == 1, (
        f"1ターンの invocation_id は1つに揃うべき（prep/finalize/gate の欠落）: {inv_ids}"
    )
