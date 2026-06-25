"""harness.pipeline の書き戻し判定（決定的）の単体テスト（LLM 非依存）。

設計コンテキスト §9/§13：来園セッションを子の長期メモリへ書き戻すか否かの "判定" は harness の
決定的な純関数（_should_persist_visit）。型成立の確定下書きのときだけ True で、像を汚さない。
書き戻しの "実行"（add_session_to_memory）の結合は tests/test_e2e/ で実ランタイム検証する。
"""

from __future__ import annotations

from hoiku_agent.harness.pipeline import _should_persist_visit


def test_persist_when_type_valid():
    # finalize 成功（parse 成功・違反0・整形出力あり）＝書き戻してよい
    state = {"final_document": "■ 保育日誌…", "validation": [], "finalize_parse_error": None}
    assert _should_persist_visit(state) is True


def test_skip_when_validation_problems():
    # 年齢分岐/必須欄違反が残る確定下書きは像を汚さないため書き戻さない
    state = {
        "final_document": "■ 保育日誌…",
        "validation": ["天候が未記入"],
        "finalize_parse_error": None,
    }
    assert _should_persist_visit(state) is False


def test_skip_when_parse_error():
    # DiaryEntry JSON を復元できなかった（型不成立）→ 書き戻さない
    state = {"final_document": None, "validation": [], "finalize_parse_error": "JSON抽出に失敗"}
    assert _should_persist_visit(state) is False


def test_skip_when_finalize_not_run():
    # finalize 未実行（final_document 無し）→ 書き戻さない（空 state でも安全）
    assert _should_persist_visit({}) is False
    assert _should_persist_visit({"final_document": None}) is False
