"""harness.pipeline の書き戻し判定（真の承認ゲート・決定的）の単体テスト（LLM 非依存）。

設計コンテキスト §9/§13：来園セッションを子の長期メモリへ書き戻すか否かの "判定" は harness の
決定的な純関数（_should_persist_visit）。**保育士の明示承認（caregiver_approved=True）かつ型成立**の
ときだけ True で、像を汚さない（型成立だけでは書き戻さない＝保育士OK ≠ 自動確定）。
書き戻しの "実行"（add_session_to_memory）の結合は tests/test_e2e/ で実ランタイム検証する。
"""

from __future__ import annotations

from hoiku_agent.harness.pipeline import _should_persist_visit, mark_caregiver_approved

# 型成立（parse 成功・違反0・整形出力あり）の確定下書き state（承認だけ差し替えてテストする）。
_VALID = {"final_document": "■ 保育日誌…", "validation": [], "finalize_parse_error": None}


def test_persist_when_approved_and_type_valid():
    # 明示承認＋型成立＝書き戻してよい
    assert _should_persist_visit({**_VALID, **mark_caregiver_approved()}) is True


def test_skip_when_not_approved_even_if_type_valid():
    # 真の承認ゲート：型成立でも保育士の明示承認が無ければ書き戻さない（承認待ち）
    assert _should_persist_visit(_VALID) is False
    assert _should_persist_visit({**_VALID, "caregiver_approved": False}) is False


def test_mark_caregiver_approved_delta():
    # 承認プリミティブの戻り（state delta）が承認キーを True にする
    assert mark_caregiver_approved() == {"caregiver_approved": True}
    assert mark_caregiver_approved(False) == {"caregiver_approved": False}


def test_skip_when_validation_problems_even_if_approved():
    # 承認済みでも年齢分岐/必須欄違反が残る確定下書きは像を汚さないため書き戻さない
    state = {**_VALID, "validation": ["天候が未記入"], **mark_caregiver_approved()}
    assert _should_persist_visit(state) is False


def test_skip_when_parse_error_even_if_approved():
    # 承認済みでも DiaryEntry JSON を復元できなかった（型不成立）→ 書き戻さない
    state = {
        "final_document": None,
        "validation": [],
        "finalize_parse_error": "JSON抽出に失敗",
        **mark_caregiver_approved(),
    }
    assert _should_persist_visit(state) is False


def test_skip_when_finalize_not_run():
    # finalize 未実行（final_document 無し）→ 承認の有無に依らず書き戻さない（空 state でも安全）
    assert _should_persist_visit({}) is False
    assert _should_persist_visit(mark_caregiver_approved()) is False
    assert _should_persist_visit({"final_document": None, **mark_caregiver_approved()}) is False
