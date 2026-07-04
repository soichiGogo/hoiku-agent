"""improver（二階）の決定的ロジックの単体テスト（LLM 非依存）。

設計コンテキスト §8/§16：カード提案・意味的競合の申告/完全重複ガード・保育士決定の即反映（add/supersede）を
検証する。意味的競合の判定そのものは LLM の責務なのでここでは扱わない（申告の passthrough のみ）。
ストアは tmp に向けて（policy_store._POLICY_PATH を monkeypatch）creds 不要・決定的に回す。
"""

from __future__ import annotations

import pytest

from hoiku_agent.harness import policy_store as ps
from hoiku_agent.improver.tools import commit_policy_card, propose_policy_card, read_policy_cards
from hoiku_agent.schemas.policy import PolicyBook, PolicyCard, PolicyScope


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


def test_propose_invalid_scope(store):
    assert propose_policy_card("不明", "x")["status"] == "error"


def test_commit_add_reflects_immediately(store):
    r = commit_policy_card("保育日誌", "感触遊びは感触語と表情を併記する", source="保育士A")
    assert r["status"] == "committed"
    assert r["card"]["doc_type"] == "diary"
    assert r["store"] == "persistent"
    assert r["committed"] is None  # commit=False 既定＝git 不発火
    # 即反映：ストアに増えている
    assert any(c.body.startswith("感触遊び") for c in ps.active_cards(ps.load_book()))


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


def test_commit_generation_conflict_rejected(gcs_store, monkeypatch):
    """GCS 外部ストアで読み込み後に他所が先に更新 → 黙って上書きせず rejected（楽観ロック・§8）。"""
    ps.save_book(PolicyBook())  # シード（generation 1）

    orig = ps.load_book_meta

    def racy_load(path=None):
        book, generation = orig(path)
        gcs_store["generation"] += 1  # 読み込み直後に他所の更新が入ったことをシミュレート
        return book, generation

    monkeypatch.setattr(ps, "load_book_meta", racy_load)
    r = commit_policy_card("保育日誌", "感触遊びは感触語と表情を併記する")
    assert r["status"] == "rejected"
    assert "競合" in r["detail"]


def test_commit_git_evidence_skipped_on_external_store(gcs_store):
    """GCS 運用中はローカル JSON が正でない＝commit=True でも git 証拠 commit を行わない。"""
    r = commit_policy_card("保育日誌", "感触遊びは感触語と表情を併記する", commit=True)
    assert r["status"] == "committed"
    assert r["store"] == "persistent"
    assert r["committed"]["status"] == "skipped"
