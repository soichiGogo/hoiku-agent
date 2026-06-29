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
    for asset in (
        "app.js",
        "adk.js",
        "docflow.js",
        "docedit.js",
        "improver.js",
        "ui.js",
        "styles.css",
    ):
        assert c.get(f"/app/{asset}").status_code == 200, asset


def test_root_lands_on_app() -> None:
    # 配布リンクの素の URL（/）は保育士 UI（/app/）へ着地する（dev UI は /dev-ui/ に温存）。
    r = _client().get("/")
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/app/"


def test_policy_and_baseline_routes() -> None:
    c = _client()
    assert c.get("/api/policy").status_code == 200
    assert "markdown" in c.get("/api/policy").json()
    base = c.get("/api/eval-baseline")
    assert base.status_code == 200
    data = base.json()
    # repo には committed baseline があるので mean を持つ（コンテナで不在なら None 降格も許容）。
    assert data is None or "mean" in data


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
    # 正しいパスコードはゲートを開ける（中身のバリデーション 422 になり、401 にはならない）。
    opened = c.post("/run_sse", json={}, headers={"X-Demo-Passcode": "secret"})
    assert opened.status_code != 401


def test_no_passcode_means_open(monkeypatch) -> None:
    monkeypatch.setattr(settings, "demo_passcode", "")
    c = _client()
    assert c.get("/api/config").json()["passcode_required"] is False
    # ゲート無効時は /run_sse がミドルウェアで 401 にはならない（バリデーション 422）。
    assert c.post("/run_sse", json={}).status_code != 401


# ──────────────────── 編集UI backend（form-meta / finalize-edit・harness 中継） ────────────────────


def _edit_diary_entry() -> dict:
    """編集フォームが送る DiaryEntry 相当の dict（型を通す good 例）。"""
    return {
        "date": "2026-06-25",
        "age_band": "0-2",
        "weather": "晴れ",
        "daily_aim": "安心して好きな遊びに関わる",
        "attendance": [{"child_id": "架空児A", "present": True, "reason": None}],
        "health_notes": None,
        "practice_record": "園庭で砂遊びを行った。",
        "individual_notes": [
            {
                "child_id": "架空児A",
                "observed_state": "砂の感触を確かめた",
                "tags": ["身近なものと関わり感性が育つ"],
                "life_record": {"meal": "完食", "sleep": "午睡2時間"},
            }
        ],
        "evaluation": {"child_focus": "感触に集中", "self_review": "道具が適切"},
        "parent_contact": None,
    }


def test_form_meta_exposes_enum_vocab() -> None:
    """タグ選択肢は schemas の Enum が SSOT（告示準拠の正しい文言を含む）。"""
    body = _client().get("/api/form-meta").json()
    assert "健やかに伸び伸びと育つ" in body["three_viewpoint"]  # 告示準拠（「と」入り）
    assert body["five_domains"] == ["健康", "人間関係", "環境", "言葉", "表現"]
    assert "数量や図形、標識や文字などへの関心・感覚" in body["ten_no_sugata"]


def test_finalize_edit_diary_revalidates_and_formats() -> None:
    """編集後の dict を harness で再検査・再整形して返す（標準様式の見出し・型成立）。"""
    r = _client().post("/api/finalize-edit", json={"kind": "diary", "entry": _edit_diary_entry()})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["problems"] == []
    assert "主な活動" in body["formatted"] and "個別の記録" in body["formatted"]


def test_finalize_edit_surfaces_validation_after_edit() -> None:
    """編集で生活記録を空にしたら不足を返す（編集後も型成立ゲートが効く）。"""
    entry = _edit_diary_entry()
    entry["individual_notes"][0]["life_record"] = {
        "meal": "",
        "sleep": "",
        "toilet": "",
        "mood_health": "",
    }
    body = _client().post("/api/finalize-edit", json={"kind": "diary", "entry": entry}).json()
    assert body["ok"] is False
    assert any("生活記録" in p for p in body["problems"])


def test_finalize_edit_not_passcode_gated(monkeypatch) -> None:
    """編集の再確定は LLM 非課金なのでパスコードでゲートしない（読み取り同様素通し）。"""
    monkeypatch.setattr(settings, "demo_passcode", "secret")
    c = _client()
    assert c.get("/api/form-meta").status_code == 200
    r = c.post("/api/finalize-edit", json={"kind": "diary", "entry": _edit_diary_entry()})
    assert r.status_code == 200 and r.json()["ok"] is True
