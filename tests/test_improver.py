"""improver（二階）の決定的ロジックの単体テスト（LLM 非依存）。

設計コンテキスト §8/§16：カード提案・意味的競合の申告/完全重複ガード・保育士決定の即反映（add/supersede）を
検証する。意味的競合の判定そのものは LLM の責務なのでここでは扱わない（申告の passthrough のみ）。
ストアは tmp に向けて（policy_store._POLICY_PATH を monkeypatch）creds 不要・決定的に回す。
"""

from __future__ import annotations

import pytest

from hoiku_agent.harness import policy_store as ps
from hoiku_agent.improver.tools import (
    build_policy_tools,
    commit_policy_card,
    commit_reference_update,
    propose_policy_card,
    propose_reference_update,
    read_policy_cards,
    read_reference_policy,
)
from hoiku_agent.schemas.policy import (
    PolicyBook,
    PolicyCard,
    PolicyCardKind,
    PolicyScope,
    ReferenceRule,
    ReferenceSource,
)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """共通カード1枚を入れた tmp ストアに向ける。"""
    p = tmp_path / "文書作成指針.json"
    monkeypatch.setattr(ps, "_POLICY_PATH", p)
    monkeypatch.delenv("K_SERVICE", raising=False)
    when = __import__("datetime").datetime(2026, 6, 21, 0, 0, 0)
    book = ps.add_card(
        PolicyBook(),
        PolicyCard(
            id="card-0001",
            scope=PolicyScope.共通,
            body="子ども・保護者の個人名は書類に書かない。",
            source="seed:初版",
            created_at=when,
            updated_at=when,
        ),
    )
    ps.save_book(book)
    return p


@pytest.fixture()
def reference_store(store):
    """保育経過記録の参照ポリシーを加えた tmp ストア。"""
    when = __import__("datetime").datetime(2026, 7, 11, 0, 0, 0)
    book = ps.load_book()
    book = book.model_copy(
        update={
            "cards": [
                *book.cards,
                PolicyCard(
                    id="card-0002",
                    scope=PolicyScope.保育経過記録,
                    kind=PolicyCardKind.reference_policy,
                    body="保育経過記録作成時の既定参照",
                    references=[
                        ReferenceRule(source=ReferenceSource.period_diary, enabled=True),
                        ReferenceRule(source=ReferenceSource.prev_child_records, enabled=True),
                    ],
                    source="seed:初版",
                    created_at=when,
                    updated_at=when,
                ),
            ]
        }
    )
    ps.save_book(book)
    return store


def test_read_policy_cards(store):
    out = read_policy_cards("共通")
    assert out["count"] == 1
    assert out["cards"][0]["id"] == "card-0001"


def test_propose_no_conflict(store):
    r = propose_policy_card(
        "保育日誌", "感触遊びは感触語と表情を併記する", rationale="現場の気づき"
    )
    assert r["status"] == "ok"
    assert r["has_conflict"] is False
    assert r["proposal"]["op"] == "add"
    assert r["exact_duplicate"] is None


def test_propose_exact_duplicate_detected(store):
    r = propose_policy_card("共通", "子ども・保護者の個人名は書類に書かない。")
    assert r["exact_duplicate"]["id"] == "card-0001"
    assert r["has_conflict"] is True


def test_propose_declared_conflict_passthrough(store):
    """LLM が申告した意味的競合 id を受け取り supersede に寄せる。"""
    r = propose_policy_card("共通", "個人名は仮名・属性で表す", conflicts_with="card-0001")
    assert r["has_conflict"] is True
    assert r["proposal"]["op"] == "supersede"
    assert r["proposal"]["supersede_id"] == "card-0001"
    assert r["declared_conflicts"][0]["id"] == "card-0001"


def test_propose_unknown_conflict_id_is_surfaced_not_dropped(store):
    """存在しない競合 id を申告したら黙って捨てず has_conflict=True＋unknown_conflict_ids で素通りさせない。"""
    r = propose_policy_card("共通", "個人名は仮名で表す", conflicts_with="card-9999")
    assert r["unknown_conflict_ids"] == ["card-9999"]
    assert r["has_conflict"] is True  # 「競合なし」で ask をスキップさせない
    assert r["declared_conflicts"] == []
    assert "見つかりません" in r["guidance"]


def test_propose_inactive_conflict_card_is_not_loaded_as_current_policy(store):
    """置換済みカードを申告されても、現行指針として提案へ取り込まない。"""
    committed = commit_policy_card(
        "共通", "個人名は仮名・属性で表す", op="supersede", supersede_id="card-0001"
    )
    assert committed["status"] == "committed"

    r = propose_policy_card("共通", "個人名は書かない", conflicts_with="card-0001")

    assert r["status"] == "ok"
    assert r["proposal"]["op"] == "add"
    assert r["proposal"]["supersede_id"] == ""
    assert r["declared_conflicts"] == []
    assert r["inactive_conflict_ids"] == ["card-0001"]
    assert r["has_conflict"] is True
    assert "現行指針ではありません" in r["guidance"]


def test_propose_invalid_scope_lists_all_scopes(store):
    """不正 scope のエラー文言は PolicyScope 全値（保育要録 含む）を enum から導出する（文言ドリフト防止）。"""
    r = propose_policy_card("不明", "x")
    assert r["status"] == "error"
    assert "保育要録" in r["detail"]  # scope 追加に文言が追随している


def test_commit_add_reflects_immediately(store):
    r = commit_policy_card("保育日誌", "感触遊びは感触語と表情を併記する", source="保育士A")
    assert r["status"] == "committed"
    assert r["card"]["doc_type"] == "diary"
    assert r["store"] == "persistent"
    # 即反映：ストアに増えている
    assert any(c.body.startswith("感触遊び") for c in ps.active_cards(ps.load_book()))


def test_commit_child_record_scope(store):
    """保育経過記録 scope も既存機構に相乗りして propose→commit できる（§19・二重実装しない）。"""
    assert (
        propose_policy_card("保育経過記録", "身体測定値は創作しない（原簿系＝保育士が記入）")[
            "status"
        ]
        == "ok"
    )
    r = commit_policy_card(
        "保育経過記録", "身体測定値は創作しない（原簿系＝保育士が記入）", source="保育士C"
    )
    assert r["status"] == "committed"
    assert r["card"]["doc_type"] == "child_record" and r["card"]["doc_label"] == "保育経過記録"
    assert any(
        c.body.startswith("身体測定値")
        for c in ps.active_cards(ps.load_book(), PolicyScope.保育経過記録)
    )


def test_commit_records_decided_by_in_history(store):
    """「回した証拠」＝カード内蔵履歴に即反映の決定者（decided_by）が残る。"""
    r = commit_policy_card("保育日誌", "感触遊びは感触語と表情を併記する", decided_by="保育士B")
    assert r["status"] == "committed"
    assert ps.load_book().history[-1].decided_by == "保育士B"


def test_commit_supersede(store):
    r = commit_policy_card(
        "共通", "個人名は仮名・属性で表す", op="supersede", supersede_id="card-0001"
    )
    assert r["status"] == "committed"
    book = ps.load_book()
    assert ps.find_card(book, "card-0001").status.value == "superseded"
    assert [c.id for c in ps.active_cards(book, PolicyScope.共通)] == ["card-0002"]


def test_commit_exact_duplicate_rejected(store):
    r = commit_policy_card("共通", "子ども・保護者の個人名は書類に書かない。")
    assert r["status"] == "rejected"


def test_commit_invalid_scope(store):
    assert commit_policy_card("不明", "x")["status"] == "error"


def test_commit_version_conflict_rejected(policy_db, monkeypatch):
    """DB ストアで読み込み後に他所が先に更新 → 黙って上書きせず rejected（version 楽観ロック・§8）。"""
    ps.save_book(PolicyBook())  # シード（version 1）

    orig = ps.load_book_meta

    def racy_load(path=None):
        book, version = orig(path)
        return (
            book,
            version - 1,
        )  # 読み込み直後に他所の更新が入った＝手元の version が古い状態を再現

    monkeypatch.setattr(ps, "load_book_meta", racy_load)
    r = commit_policy_card("保育日誌", "感触遊びは感触語と表情を併記する")
    assert r["status"] == "rejected"
    assert "競合" in r["detail"]


def test_read_reference_policy_returns_labels_with_plain_str(reference_store):
    """FunctionTool と同じ素の str scope で、日本語ラベル付きの現在設定を読める。"""
    result = read_reference_policy("保育経過記録")
    assert result["scope"] == "保育経過記録"
    assert result["references"][0] == {
        "source": "period_diary",
        "enabled": True,
        "note": None,
        "label": "期間内の保育日誌",
        "description": "作成対象の期間に書かれた日誌です。",
    }


def test_read_reference_policy_missing_scope_degrades(store):
    result = read_reference_policy("共通")
    assert result["references"] == []
    assert "ありません" in result["detail"]


def test_propose_reference_update_with_plain_str_is_stateless(reference_store):
    """素の str 引数から変更案を作るだけで、保存済み book は変えない。"""
    result = propose_reference_update(
        "保育経過記録",
        "prev_month_diaries",
        "period_diary",
        reason="前月の流れを確認するため",
    )
    assert result["status"] == "ok"
    proposal = result["proposal"]
    assert proposal["reason"] == "前月の流れを確認するため"
    before = {rule["source"]: rule for rule in proposal["before"]}
    after = {rule["source"]: rule for rule in proposal["after"]}
    assert before["period_diary"]["enabled"] is True
    assert after["period_diary"]["enabled"] is False
    assert after["prev_month_diaries"]["enabled"] is True
    assert "前月の保育日誌" == after["prev_month_diaries"]["label"]
    assert ps.reference_policy_card(ps.load_book(), PolicyScope.保育経過記録).references == [
        ReferenceRule(source=ReferenceSource.period_diary, enabled=True),
        ReferenceRule(source=ReferenceSource.prev_child_records, enabled=True),
    ]


def test_propose_reference_update_rejects_unknown_source(reference_store):
    result = propose_reference_update("保育経過記録", "unknown_source", "")
    assert result["status"] == "rejected"
    assert "unknown_source" in result["detail"]
    assert {item["source"] for item in result["valid_sources"]} == {
        source.value for source in ReferenceSource
    }


def test_commit_reference_update_with_plain_str_records_history(reference_store):
    result = commit_reference_update(
        "保育経過記録",
        "prev_month_diaries",
        "period_diary",
        decided_by="主任保育士",
    )
    assert result["status"] == "committed"
    assert result["card"]["kind"] == "reference_policy"
    book = ps.load_book()
    card = ps.reference_policy_card(book, PolicyScope.保育経過記録)
    states = {rule.source: rule.enabled for rule in card.references}
    assert states[ReferenceSource.period_diary] is False
    assert states[ReferenceSource.prev_month_diaries] is True
    assert book.history[-1].decided_by == "主任保育士"
    assert book.history[-1].source == "改善エージェント"
    assert result["history_entry"]["by"] == "主任保育士"


def test_commit_reference_update_version_conflict_rejected(policy_db, monkeypatch):
    """参照設定も read-modify-write の競合を黙って上書きしない。"""
    when = __import__("datetime").datetime(2026, 7, 11, 0, 0, 0)
    ps.save_book(
        PolicyBook(
            cards=[
                PolicyCard(
                    id="card-0001",
                    scope=PolicyScope.保育経過記録,
                    kind=PolicyCardKind.reference_policy,
                    body="保育経過記録作成時の既定参照",
                    references=[ReferenceRule(source=ReferenceSource.period_diary)],
                    created_at=when,
                    updated_at=when,
                )
            ]
        )
    )
    original = ps.load_book_meta

    def stale_load(*args, **kwargs):
        book, version = original(*args, **kwargs)
        return book, version - 1

    monkeypatch.setattr(ps, "load_book_meta", stale_load)
    result = commit_reference_update("保育経過記録", "", "period_diary")
    assert result["status"] == "rejected"
    assert "競合" in result["detail"]


def test_bound_policy_tools_write_only_to_workspace_book(policy_db):
    """guideline と reference の commit は束縛された book だけを書き、default へ漏らさない。"""
    import inspect

    when = __import__("datetime").datetime(2026, 7, 11, 0, 0, 0)
    book_id = "workspace:test-workspace"
    ps.save_book(
        PolicyBook(
            cards=[
                PolicyCard(
                    id="card-0001",
                    scope=PolicyScope.保育経過記録,
                    kind=PolicyCardKind.reference_policy,
                    body="保育経過記録作成時の既定参照",
                    references=[ReferenceRule(source=ReferenceSource.period_diary)],
                    created_at=when,
                    updated_at=when,
                )
            ]
        ),
        book_id=book_id,
    )
    tools = {tool.__name__: tool for tool in build_policy_tools(book_id)}
    assert all("book_id" not in inspect.signature(tool).parameters for tool in tools.values())
    implementations = {
        "read_policy_cards": read_policy_cards,
        "propose_policy_card": propose_policy_card,
        "commit_policy_card": commit_policy_card,
        "read_reference_policy": read_reference_policy,
        "propose_reference_update": propose_reference_update,
        "commit_reference_update": commit_reference_update,
    }
    assert all(tool.__doc__ == implementations[name].__doc__ for name, tool in tools.items())

    guideline = tools["commit_policy_card"]("共通", "観察した事実を先に書く")
    reference = tools["commit_reference_update"](
        "保育経過記録", "prev_child_records", "period_diary"
    )

    assert guideline["status"] == "committed"
    assert reference["status"] == "committed"
    workspace_book = ps.load_book(book_id=book_id)
    assert any(card.body == "観察した事実を先に書く" for card in workspace_book.cards)
    rules = {
        rule.source: rule.enabled
        for rule in ps.reference_policy_card(workspace_book, PolicyScope.保育経過記録).references
    }
    assert rules == {
        ReferenceSource.period_diary: False,
        ReferenceSource.prev_child_records: True,
    }
    assert ps.load_book().cards == []


def test_reference_update_preserves_existing_order_and_appends_new_source(reference_store):
    """変更後はカードの規則順を維持し、新規有効化した資料だけを末尾へ足す。"""
    book = ps.load_book()
    card = ps.reference_policy_card(book, PolicyScope.保育経過記録)
    reordered = card.model_copy(
        update={
            "references": [
                ReferenceRule(source=ReferenceSource.prev_child_records, enabled=False),
                ReferenceRule(source=ReferenceSource.period_diary, enabled=True),
                ReferenceRule(source=ReferenceSource.class_child_records, enabled=True),
            ]
        }
    )
    ps.save_book(
        book.model_copy(
            update={
                "cards": [
                    reordered if existing.id == card.id else existing for existing in book.cards
                ]
            }
        )
    )

    result = propose_reference_update(
        "保育経過記録",
        "prev_child_records,past_class_plans",
        "period_diary",
    )

    assert [rule["source"] for rule in result["proposal"]["after"]] == [
        "prev_child_records",
        "period_diary",
        "class_child_records",
        "past_class_plans",
    ]
    assert [rule["enabled"] for rule in result["proposal"]["after"]] == [
        True,
        False,
        True,
        True,
    ]
