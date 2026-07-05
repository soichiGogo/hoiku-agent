"""配布 Web UI（src/hoiku_agent/web）の決定論スモーク（LLM 非依存・creds 不要）。

生成そのもの（/run_sse 経由の日誌/月案）は LLM が要るのでここでは検証しない（層B eval / 実機スモーク）。
ここで担保するのは「配線が崩れていないこと」＝静的配信・自前 API の形・コストゲートの開閉・/ の着地。
"""

from __future__ import annotations

from datetime import datetime

import pytest
import server
from fastapi.testclient import TestClient
from hoiku_agent.config import settings
from hoiku_agent.harness import record_store


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
        "policy.js",
        "notation.js",
        "records.js",
        "ui.js",
        "styles.css",
    ):
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


def _edit_child_record_entry() -> dict:
    """児童票の編集フォーム相当 dict（型を通す good 例・§19）。"""
    return {
        "period": "2026-04〜2026-06",
        "age_band": "0-2",
        "child_id": "架空児A",
        "age_months": "1歳3か月",
        "development_notes": [
            {
                "description": "伝い歩きから一人歩きへ移行し、探索範囲が広がった",
                "tags": ["健やかに伸び伸びと育つ"],
            }
        ],
        "care_notes": "",
        "family_liaison": "連絡帳で歩行の様子を共有した",
        "overall_note": "安心できる関係を土台に自分から環境へ関わる姿が増えた",
        "next_aims": "",
    }


def test_finalize_edit_child_record_revalidates_and_formats() -> None:
    """児童票の編集後 dict も harness で再検査・再整形できる（kind=child_record）。"""
    r = _client().post(
        "/api/finalize-edit", json={"kind": "child_record", "entry": _edit_child_record_entry()}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "児童票・保育経過記録" in body["formatted"] and "総合所見" in body["formatted"]


def test_finalize_edit_child_record_surfaces_validation() -> None:
    """総合所見を空にしたら不足を返す（児童票でも編集後の型成立ゲートが効く）。"""
    entry = _edit_child_record_entry()
    entry["overall_note"] = ""
    body = (
        _client().post("/api/finalize-edit", json={"kind": "child_record", "entry": entry}).json()
    )
    assert body["ok"] is False
    assert any("総合所見" in p for p in body["problems"])


def test_finalize_edit_not_passcode_gated(monkeypatch) -> None:
    """編集の再確定は LLM 非課金なのでパスコードでゲートしない（読み取り同様素通し）。"""
    monkeypatch.setattr(settings, "demo_passcode", "secret")
    c = _client()
    assert c.get("/api/form-meta").status_code == 200
    r = c.post("/api/finalize-edit", json={"kind": "diary", "entry": _edit_diary_entry()})
    assert r.status_code == 200 and r.json()["ok"] is True


# ──────────────────── 帳票PDF 出力（/api/export-pdf・現場でそのまま綴じる最終形） ────────────────────


def _edit_monthly_entry() -> dict:
    """月案の編集フォーム相当 dict（帳票PDF 描画の入力）。"""
    return {
        "month": "2026-07",
        "age_band": "0-2",
        "child_id": "架空児A",
        "age_months": "1歳3か月",
        "prev_child_state": "前月は感触遊びに集中していた",
        "nurturing_life": "安全と生理的欲求の充足",
        "nurturing_emotion": "応答的関わりで安心を支える",
        "education": [{"aim": "素材に親しむ", "tags": ["身近なものと関わり感性が育つ"]}],
        "monthly_goals": "夏の遊びを楽しむ",
        "environment_support": "水遊びの環境を整える",
        "events_family_food": None,
        "evaluation_reflection": "翌月へつなげる",
    }


def _assert_is_pdf(r) -> None:
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"
    # 日本語ファイル名を RFC5987 で載せる（ダウンロード名が化けない）。
    assert "filename*=UTF-8''" in r.headers.get("content-disposition", "")


def test_export_pdf_diary_returns_pdf() -> None:
    r = _client().post("/api/export-pdf", json={"kind": "diary", "entry": _edit_diary_entry()})
    _assert_is_pdf(r)


def test_export_pdf_monthly_returns_pdf() -> None:
    r = _client().post("/api/export-pdf", json={"kind": "monthly", "entry": _edit_monthly_entry()})
    _assert_is_pdf(r)


def test_export_pdf_child_record_returns_pdf() -> None:
    r = _client().post(
        "/api/export-pdf", json={"kind": "child_record", "entry": _edit_child_record_entry()}
    )
    _assert_is_pdf(r)


def test_export_pdf_sparse_entry_still_renders() -> None:
    """空欄多めの entry でも帳票は出る（型検査はしない＝描画のみ・型の保証は harness）。"""
    r = _client().post(
        "/api/export-pdf",
        json={"kind": "diary", "entry": {"age_band": "0-2", "individual_notes": [{}]}},
    )
    _assert_is_pdf(r)


def test_export_pdf_invalid_kind_400() -> None:
    r = _client().post("/api/export-pdf", json={"kind": "weekly", "entry": _edit_diary_entry()})
    assert r.status_code == 400
    assert r.json()["code"] == "invalid_request"


def test_export_pdf_not_passcode_gated(monkeypatch) -> None:
    """帳票PDF 出力は LLM 非課金なのでパスコードでゲートしない（読み取り同様素通し）。"""
    monkeypatch.setattr(settings, "demo_passcode", "secret")
    r = _client().post("/api/export-pdf", json={"kind": "diary", "entry": _edit_diary_entry()})
    _assert_is_pdf(r)


# ──────────────────── 書類アーカイブ（/api/records・/api/children＝record_store 中継・Phase 1） ────────────────────


@pytest.fixture()
def records_db(tmp_path, monkeypatch):
    """sqlite の一時 DB に向けてアーカイブのスキーマを作る（web 経由の決定論検証）。"""
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/archive.db")
    record_store.reset_engine_cache()
    record_store.Base.metadata.create_all(record_store._engine())
    yield
    record_store.reset_engine_cache()


def test_records_degrade_when_db_unset(monkeypatch) -> None:
    """DATABASE_URL 未設定＝降格（保存 skipped・一覧/児童は空・config は未接続を正直に返す）。"""
    monkeypatch.setattr(settings, "database_url", "")
    record_store.reset_engine_cache()
    c = _client()
    assert c.get("/api/config").json()["records_connected"] is False
    r = c.post(
        "/api/records", json={"kind": "diary", "entry": _edit_diary_entry(), "author_kind": "ai"}
    )
    assert r.json()["status"] == "skipped"
    assert c.get("/api/children").json() == {"children": [], "store": "disabled"}
    assert c.get("/api/records").json()["documents"] == []


def test_records_save_edit_approve_flow(records_db) -> None:
    """AI 確定→編集保存→承認 のアーカイブ一連（版が積まれ・児童が登録され・証跡が残る）。"""
    c = _client()
    entry = _edit_diary_entry()
    # AI 確定（author_kind=ai）
    r1 = c.post(
        "/api/records",
        json={"kind": "diary", "entry": entry, "rendered_text": "整形", "author_kind": "ai"},
    ).json()
    assert r1["status"] == "saved" and r1["version_seq"] == 1
    # 保育士の編集保存（同一書類に版が積まれる）
    r2 = c.post(
        "/api/records",
        json={
            "kind": "diary",
            "entry": entry,
            "author_kind": "caregiver",
            "actor": "保育士A",
        },
    ).json()
    assert r2["status"] == "saved" and r2["version_seq"] == 2
    assert r2["document_id"] == r1["document_id"]
    # 承認（証跡＝actor が残る）
    r3 = c.post(
        "/api/records/approve", json={"kind": "diary", "entry": entry, "actor": "園長"}
    ).json()
    assert r3["status"] == "approved"
    docs = c.get("/api/records").json()
    assert docs["store"] == "ok"
    assert docs["documents"][0]["status"] == "approved"
    # 児童マスタへ auto-create → /api/children で選択肢に出る
    children = c.get("/api/children").json()["children"]
    assert [x["display_name"] for x in children] == ["架空児A"]
    # 監査証跡（誰が・いつ・何を）
    actions = [(e["action"], e["actor"]) for e in record_store.list_audit_events()]
    assert ("approve", "園長") in actions and ("edit", "保育士A") in actions


def test_records_write_is_passcode_gated_reads_open(records_db, monkeypatch) -> None:
    """アーカイブの**書込**はパスコードでゲート（公開デモ URL からのゴミデータ・偽承認証跡の防止）。

    読み取り（一覧・児童・seed）は従来どおり素通し。正しいパスコードは書込を開ける。
    """
    monkeypatch.setattr(settings, "demo_passcode", "secret")
    c = _client()
    payload = {"kind": "diary", "entry": _edit_diary_entry(), "author_kind": "ai"}
    # 書込はパスコード無しだと 401
    assert c.post("/api/records", json=payload).status_code == 401
    assert c.post("/api/records/approve", json={"kind": "diary", "entry": {}}).status_code == 401
    # 読み取りは素通し
    assert c.get("/api/records").status_code == 200
    assert c.get("/api/children").status_code == 200
    # 正しいパスコードは書込を開ける
    ok = c.post("/api/records", json=payload, headers={"X-Demo-Passcode": "secret"})
    assert ok.status_code == 200 and ok.json()["status"] == "saved"


def test_records_diary_entries_returns_seed(records_db) -> None:
    """seed 取得口＝期間内の日誌 entry（最新版）を返す（月案 L2／児童票 L3 の還流を DB から）。"""
    c = _client()
    c.post(
        "/api/records", json={"kind": "diary", "entry": _edit_diary_entry(), "author_kind": "ai"}
    )
    body = c.get(
        "/api/records/diary-entries", params={"date_from": "2026-06-01", "date_to": "2026-06-30"}
    ).json()
    assert body["store"] == "ok"
    assert [e["date"] for e in body["entries"]] == ["2026-06-25"]
    # 範囲外は空
    empty = c.get(
        "/api/records/diary-entries", params={"date_from": "2026-07-01", "date_to": "2026-07-31"}
    ).json()
    assert empty["entries"] == []
    # 不正日付は 400（黙って全件を返さない）
    bad = c.get("/api/records/diary-entries", params={"date_from": "abc", "date_to": "2026-07-31"})
    assert bad.status_code == 400


def test_get_record_returns_full_document(records_db) -> None:
    """GET /api/records/{id}＝「書類を見る」タブの詳細（現行版の整形テキスト＋本文 entry）。"""
    c = _client()
    saved = c.post(
        "/api/records",
        json={
            "kind": "diary",
            "entry": _edit_diary_entry(),
            "rendered_text": "整形本文",
            "author_kind": "ai",
        },
    ).json()
    r = c.get(f"/api/records/{saved['document_id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["doc_type"] == "diary"
    assert body["rendered_text"] == "整形本文"
    assert body["author_kind"] == "ai"
    assert body["entry"]["date"] == "2026-06-25"


def test_get_record_missing_or_invalid_404(records_db) -> None:
    """不在・不正 id は 404（500 にしない・偽の中身を出さない）。リテラル路より後宣言でも衝突しない。"""
    import uuid

    c = _client()
    assert c.get(f"/api/records/{uuid.uuid4()}").status_code == 404
    assert c.get("/api/records/not-a-uuid").json()["code"] == "not_found"
    # 併存するリテラル路（diary-entries）は {document_id} に飲まれない（宣言順で優先）。
    assert (
        c.get(
            "/api/records/diary-entries",
            params={"date_from": "2026-07-01", "date_to": "2026-07-31"},
        ).status_code
        == 200
    )


def test_get_record_read_not_passcode_gated(records_db, monkeypatch) -> None:
    """単一書類の閲覧は読取＝非ゲート（保存はゲート・読み取りは素通し）。"""
    monkeypatch.setattr(settings, "demo_passcode", "secret")
    c = _client()
    saved = c.post(
        "/api/records",
        json={"kind": "diary", "entry": _edit_diary_entry(), "author_kind": "ai"},
        headers={"X-Demo-Passcode": "secret"},
    ).json()
    assert c.get(f"/api/records/{saved['document_id']}").status_code == 200


# ──────────────────── 児童票 年間マトリクスの過去期埋め込み（chohyo_pdf × record_store） ────────────────────


def test_assign_period_columns_fills_same_fiscal_year_only() -> None:
    """期→列割当の純関数＝同じ年度だけ他列へ・今回の期が常に優先・読めない期/別児は除外。"""
    from hoiku_agent.web.chohyo_pdf import assign_period_columns

    current = {"period": "2026-07〜2026-09", "child_id": "はるとくん", "overall_note": "今回"}
    past_q1 = {"period": "2026-04〜2026-06", "child_id": "はるとくん", "overall_note": "1期"}
    other_year = {"period": "2025-04〜2025-06", "child_id": "はるとくん"}  # 前年度＝別シート
    unparseable = {"period": "1学期", "child_id": "はるとくん"}  # 期が読めない＝誤配置しない
    other_child = {"period": "2026-10〜2026-12", "child_id": "めいちゃん"}  # 別児＝防御的に除外
    stale_same_q = {"period": "2026-07〜2026-09", "child_id": "はるとくん", "overall_note": "旧版"}
    cols = assign_period_columns(
        current, [past_q1, other_year, unparseable, other_child, stale_same_q]
    )
    assert set(cols) == {0, 1}
    assert cols[0] is past_q1
    assert cols[1] is current  # アーカイブの旧版より今回の entry が勝つ


def test_assign_period_columns_unparseable_current_stays_alone() -> None:
    """今回の期が読めなければ年度を同定できない＝過去期は埋めず先頭列に今回だけ（誤った列に描かない）。"""
    from hoiku_agent.web.chohyo_pdf import assign_period_columns

    current = {"period": "1学期", "child_id": "はるとくん"}
    past = {"period": "2026-04〜2026-06", "child_id": "はるとくん"}
    assert assign_period_columns(current, [past]) == {0: current}


def test_export_pdf_child_record_embeds_archived_periods(records_db) -> None:
    """児童票の帳票PDF はアーカイブの同児・同年度の過去期で他列を埋めて返す（未接続は従来どおり）。"""
    past = dict(_edit_child_record_entry(), overall_note="1期の所見")
    saved = record_store.save_document(
        "child_record", past, author_kind="ai", now=datetime(2026, 7, 5)
    )
    assert saved["status"] == "saved"
    current = dict(
        _edit_child_record_entry(),
        period="2026-07〜2026-09",
        overall_note="2期の所見",
    )
    r = _client().post("/api/export-pdf", json={"kind": "child_record", "entry": current})
    _assert_is_pdf(r)


# ──────────────────── IAP identity（Phase 3・検証済み actor と users） ────────────────────


def test_iap_headers_ignored_when_audience_unset() -> None:
    """IAP_AUDIENCE 未設定＝ヘッダを一切信用しない（IAP を経由しない面での偽装防止・fail-closed）。"""
    r = _client().get("/api/config", headers={"x-goog-iap-jwt-assertion": "spoofed"})
    assert r.json()["user_email"] is None


def test_iap_verified_email_becomes_actor_and_provisions_user(records_db, monkeypatch) -> None:
    """検証済み email が config に出て、証跡 actor は自己申告より優先され、users へ auto-provision される。"""
    from hoiku_agent.web import iap

    monkeypatch.setattr(settings, "iap_audience", "/projects/1/locations/l/services/s")
    monkeypatch.setattr(
        iap,
        "_verify_assertion",
        lambda assertion, audience: {"email": "accounts.google.com:sensei@example.com"},
    )
    c = _client()
    headers = {"x-goog-iap-jwt-assertion": "signed-jwt"}
    assert c.get("/api/config", headers=headers).json()["user_email"] == "sensei@example.com"
    payload = {
        "kind": "diary",
        "entry": _edit_diary_entry(),
        "author_kind": "ai",
        "actor": "なりすまし名義",
    }
    assert c.post("/api/records", json=payload, headers=headers).json()["status"] == "saved"
    approve = {"kind": "diary", "entry": _edit_diary_entry(), "actor": "なりすまし名義"}
    assert (
        c.post("/api/records/approve", json=approve, headers=headers).json()["status"] == "approved"
    )
    assert {e["actor"] for e in record_store.list_audit_events()} == {"sensei@example.com"}
    # users へ auto-provision（表示名は後から DB で設定できる）
    with record_store.Session(record_store._engine()) as session:
        users = list(session.scalars(record_store.sa.select(record_store.User)))
    assert [u.email for u in users] == ["sensei@example.com"]


def test_iap_verification_failure_falls_back_to_declared_actor(records_db, monkeypatch) -> None:
    """署名検証に失敗したら匿名扱い＝actor は従来の自己申告（偽の認証を通さない・本流は壊さない）。"""
    from hoiku_agent.web import iap

    monkeypatch.setattr(settings, "iap_audience", "/projects/1/locations/l/services/s")

    def _boom(assertion: str, audience: str) -> dict:
        raise ValueError("bad signature")

    monkeypatch.setattr(iap, "_verify_assertion", _boom)
    c = _client()
    headers = {"x-goog-iap-jwt-assertion": "tampered"}
    assert c.get("/api/config", headers=headers).json()["user_email"] is None
    payload = {
        "kind": "diary",
        "entry": _edit_diary_entry(),
        "author_kind": "ai",
        "actor": "保育士A",
    }
    assert c.post("/api/records", json=payload, headers=headers).json()["status"] == "saved"
    assert record_store.list_audit_events()[0]["actor"] == "保育士A"


# ──────────────────── 表記ルール辞書（ひらがな表記DX＝/api/notation の中継） ────────────────────


def test_notation_get_returns_rules_and_store() -> None:
    """GET /api/notation は表記ルール一覧＋store を返す（読み取りは素通し）。"""
    body = _client().get("/api/notation").json()
    assert "rules" in body and "store" in body
    assert all(
        {"id", "pattern", "replacement", "kind", "enabled"} <= r.keys() for r in body["rules"]
    )


def test_notation_crud_roundtrip(tmp_path, monkeypatch) -> None:
    """追加→編集→削除が harness 経由で回り、更新後の一覧を返す（repo シードは汚さない）。"""
    from hoiku_agent.harness import notation_store as ns

    monkeypatch.setattr(ns, "_NOTATION_PATH", tmp_path / "表記ルール.json")
    c = _client()
    # 追加
    r = c.post(
        "/api/notation", json={"pattern": "出来た", "replacement": "できた", "note": "補助動詞"}
    )
    assert r.status_code == 200 and r.json()["status"] == "ok"
    rules = r.json()["rules"]
    added = next(x for x in rules if x["pattern"] == "出来た")
    assert added["replacement"] == "できた" and added["enabled"] is True
    rid = added["id"]
    # 編集（無効化）
    r = c.patch(f"/api/notation/{rid}", json={"enabled": False, "replacement": "でけた"})
    assert r.json()["status"] == "ok"
    edited = next(x for x in r.json()["rules"] if x["id"] == rid)
    assert edited["enabled"] is False and edited["replacement"] == "でけた"
    # 削除
    r = c.delete(f"/api/notation/{rid}")
    assert r.json()["status"] == "ok"
    assert all(x["id"] != rid for x in r.json()["rules"])


def test_notation_add_duplicate_pattern_rejected(tmp_path, monkeypatch) -> None:
    from hoiku_agent.harness import notation_store as ns

    monkeypatch.setattr(ns, "_NOTATION_PATH", tmp_path / "表記ルール.json")
    c = _client()
    assert (
        c.post("/api/notation", json={"pattern": "子供", "replacement": "子ども"}).status_code
        == 200
    )
    dup = c.post("/api/notation", json={"pattern": "子供", "replacement": "こども"})
    assert dup.status_code == 409 and dup.json()["status"] == "rejected"


def test_notation_invalid_kind_400(tmp_path, monkeypatch) -> None:
    from hoiku_agent.harness import notation_store as ns

    monkeypatch.setattr(ns, "_NOTATION_PATH", tmp_path / "表記ルール.json")
    r = _client().post(
        "/api/notation", json={"pattern": "x", "replacement": "y", "kind": "怪しい種別"}
    )
    assert r.status_code == 400 and r.json()["status"] == "error"


def test_notation_writes_are_passcode_gated(monkeypatch) -> None:
    """書込（POST/PATCH/DELETE）は公開デモの辞書荒らし防止でゲート、読取（GET）は素通し。"""
    monkeypatch.setattr(settings, "demo_passcode", "secret")
    c = _client()
    assert c.get("/api/notation").status_code == 200
    assert c.post("/api/notation", json={"pattern": "x", "replacement": "y"}).status_code == 401
    assert c.patch("/api/notation/rule-0001", json={"enabled": False}).status_code == 401
    assert c.delete("/api/notation/rule-0001").status_code == 401
