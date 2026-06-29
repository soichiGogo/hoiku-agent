"""配布 Web UI（src/hoiku_agent/web）の決定論スモーク（LLM 非依存・creds 不要）。

生成そのもの（/run_sse 経由の日誌/月案）は LLM が要るのでここでは検証しない（層B eval / 実機スモーク）。
ここで担保するのは「配線が崩れていないこと」＝静的配信・自前 API の形・コストゲートの開閉・/ の着地。
"""

from __future__ import annotations

import server
from fastapi.testclient import TestClient
from hoiku_agent.config import settings


def _client() -> TestClient:
    # follow_redirects=False で / → /app/ のリダイレクトを検証できるようにする。
    return TestClient(server.app, follow_redirects=False)


def test_config_shape() -> None:
    r = _client().get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert body["app_name"] == "hoiku_agent"
    assert body["default_user_id"] == "caregiver"
    for key in ("memory_connected", "rag_connected", "passcode_required", "model"):
        assert key in body


def test_static_ui_served() -> None:
    c = _client()
    # SPA 本体と各 ES モジュールが配信される。
    assert c.get("/app/").status_code == 200
    for asset in ("app.js", "adk.js", "docflow.js", "policy.js", "ui.js", "styles.css"):
        assert c.get(f"/app/{asset}").status_code == 200, asset


def test_root_lands_on_app() -> None:
    # 配布リンクの素の URL（/）は保育士 UI（/app/）へ着地する（dev UI は /dev-ui/ に温存）。
    r = _client().get("/")
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/app/"


def test_policy_route_returns_cards_and_history() -> None:
    """/api/policy は育つ指針＝構造化カード＋変更履歴＋store を返す（閲覧・素通し）。"""
    c = _client()
    r = c.get("/api/policy")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body.get("cards"), list)
    assert isinstance(body.get("history"), list)
    assert body.get("store") in ("persistent", "ephemeral", "unavailable")
    # seed（共通/月案）が読める環境ではカードが入る。カード形（doc_type/body）も確認。
    if body["cards"]:
        assert {"id", "body", "doc_type", "doc_label"} <= body["cards"][0].keys()


def test_list_apps_has_root_agent() -> None:
    assert "hoiku_agent" in _client().get("/list-apps").json()


def test_passcode_gate_blocks_cost_endpoints(monkeypatch) -> None:
    # demo_passcode を設定すると LLM を回す口だけが要パスコードになる（読み取り・config は素通し）。
    monkeypatch.setattr(settings, "demo_passcode", "secret")
    c = _client()
    assert c.post("/run_sse", json={}).status_code == 401
    assert c.post("/api/improve", json={"diff": "x"}).status_code == 401
    assert c.get("/api/config").status_code == 200
    assert c.get("/api/config").json()["passcode_required"] is True
    # 閲覧（指針カードの読み取り）はパスコード無でも素通し（コストが発生しない）。
    assert c.get("/api/policy").status_code == 200
    # 正しいパスコードはゲートを開ける（中身のバリデーション 422 になり、401 にはならない）。
    opened = c.post("/run_sse", json={}, headers={"X-Demo-Passcode": "secret"})
    assert opened.status_code != 401


def test_no_passcode_means_open(monkeypatch) -> None:
    monkeypatch.setattr(settings, "demo_passcode", "")
    c = _client()
    assert c.get("/api/config").json()["passcode_required"] is False
    # ゲート無効時は /run_sse がミドルウェアで 401 にはならない（バリデーション 422）。
    assert c.post("/run_sse", json={}).status_code != 401
