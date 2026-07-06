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
    # 園の実 Word 様式に対応済みの kind を UI の出し分け用に返す（保育経過記録・クラス月案は配線済み）。
    assert "child_record" in body["docx_kinds"]
    assert "class_monthly" in body["docx_kinds"]
    # レビュー巡回の上限＝harness の SSOT を露出（UI が差し戻し時「N巡目/最大M」の M に使う）。
    from hoiku_agent.harness.pipeline import MAX_REVIEW_ITERATIONS

    assert body["max_review_iterations"] == MAX_REVIEW_ITERATIONS


def test_doc_template_shape() -> None:
    """/api/doc-template＝編集フォームが本文の順序/ラベルに使う（4種別・key/label/kind）。"""
    body = _client().get("/api/doc-template").json()
    assert set(body["templates"]) == {"diary", "monthly", "child_record", "nursery_record"}
    diary = body["templates"]["diary"]
    assert diary and diary[0]["key"] == "daily_aim"
    for sec in diary:
        assert {"key", "label", "kind"} <= set(sec)


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


def test_finalize_edit_class_monthly_revalidates_and_formats() -> None:
    """クラス月案の編集後 dict も harness で再検査・再整形できる（kind=class_monthly・§18）。"""
    r = _client().post(
        "/api/finalize-edit",
        json={"kind": "class_monthly", "entry": _edit_class_monthly_entry()},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "月間指導計画" in body["formatted"] and "指導計画（区分×領域）" in body["formatted"]


def test_finalize_edit_class_monthly_surfaces_validation() -> None:
    """0–2 で個人目標を空にしたら不足を返す（編集後も型成立ゲートが効く）。"""
    entry = _edit_class_monthly_entry()
    entry["individual_goals"] = []
    body = (
        _client().post("/api/finalize-edit", json={"kind": "class_monthly", "entry": entry}).json()
    )
    assert body["ok"] is False
    assert any("個人目標" in p for p in body["problems"])


def _edit_child_record_entry() -> dict:
    """保育経過記録の編集フォーム相当 dict（型を通す good 例・§19）。"""
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
    """保育経過記録の編集後 dict も harness で再検査・再整形できる（kind=child_record）。"""
    r = _client().post(
        "/api/finalize-edit", json={"kind": "child_record", "entry": _edit_child_record_entry()}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "保育経過記録" in body["formatted"] and "総合所見" in body["formatted"]


def test_finalize_edit_child_record_surfaces_validation() -> None:
    """総合所見を空にしたら不足を返す（保育経過記録でも編集後の型成立ゲートが効く）。"""
    entry = _edit_child_record_entry()
    entry["overall_note"] = ""
    body = (
        _client().post("/api/finalize-edit", json={"kind": "child_record", "entry": entry}).json()
    )
    assert body["ok"] is False
    assert any("総合所見" in p for p in body["problems"])


def _edit_nursery_record_entry() -> dict:
    """保育要録の編集フォーム相当 dict（型を通す good 例・§19・L4）。"""
    return {
        "fiscal_year": "2026",
        "age_band": "3-5",
        "child_id": "架空児A",
        "age_months": "6歳0か月",
        "final_year_focus": "共通の目的に向かって思いや考えを出し合いながら活動を楽しむ",
        "individual_focus": "自分を発揮しながらさまざまな活動を楽しむ",
        "development_notes": [
            {"description": "友だちと考えを出し合い協力する姿が増えた", "tags": ["人間関係"]}
        ],
        "special_notes": "",
        "growth_until_final": "入園当初は不安が大きかったが、生き生きと表現を楽しむ姿へ育った",
    }


def test_finalize_edit_nursery_record_revalidates_and_formats() -> None:
    """保育要録の編集後 dict も harness で再検査・再整形できる（kind=nursery_record）。"""
    r = _client().post(
        "/api/finalize-edit",
        json={"kind": "nursery_record", "entry": _edit_nursery_record_entry()},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "保育所児童保育要録" in body["formatted"]
    assert "最終年度に至るまでの育ち" in body["formatted"]


def test_finalize_edit_nursery_record_surfaces_validation() -> None:
    """最終年度に至るまでの育ちを空にしたら不足を返す（要録でも編集後の型成立ゲートが効く）。"""
    entry = _edit_nursery_record_entry()
    entry["growth_until_final"] = ""
    body = (
        _client().post("/api/finalize-edit", json={"kind": "nursery_record", "entry": entry}).json()
    )
    assert body["ok"] is False
    assert any("最終年度に至るまでの育ち" in p for p in body["problems"])


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


def _edit_class_monthly_entry() -> dict:
    """クラス月案の編集フォーム相当 dict（園の実様式＝区分×領域グリッド＋0–2 の個人目標）。"""
    grid = [
        {
            "category": cat,
            "domain": dom,
            "aim": f"{dom}のねらい",
            "environment": "環境",
            "child_state": "姿",
            "support": "配慮",
        }
        for cat, dom in (
            ("養護", "生命の保持"),
            ("養護", "情緒の安定"),
            ("教育", "健康"),
            ("教育", "人間関係"),
            ("教育", "環境"),
            ("教育", "言葉"),
            ("教育", "表現"),
        )
    ]
    return {
        "month": "2026-07",
        "age_band": "0-2",
        "class_name": "ひよこ組",
        "monthly_goal": "梅雨期も健康に過ごす",
        "prev_month_state": "前月は感触遊びに集中していた",
        "events": "七夕",
        "parent_support": "連絡帳で連携",
        "grid": grid,
        "syokuiku": "手づかみ食べ",
        "health_safety": "ブレスチェック",
        "family_liaison": "連絡帳",
        "staff_liaison": "申し送り",
        "individual_goals": [
            {
                "child_id": "架空児A",
                "age_months": "1歳3か月",
                "child_state": "歩行安定",
                "aim_support": "探索保障",
            }
        ],
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


def test_export_pdf_class_monthly_returns_pdf() -> None:
    r = _client().post(
        "/api/export-pdf", json={"kind": "class_monthly", "entry": _edit_class_monthly_entry()}
    )
    _assert_is_pdf(r)


def test_export_pdf_child_record_returns_pdf() -> None:
    r = _client().post(
        "/api/export-pdf", json={"kind": "child_record", "entry": _edit_child_record_entry()}
    )
    _assert_is_pdf(r)


def test_export_pdf_nursery_record_returns_pdf() -> None:
    r = _client().post(
        "/api/export-pdf", json={"kind": "nursery_record", "entry": _edit_nursery_record_entry()}
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


# ──────────── 園の実 Word 様式（/api/export-docx・Word 編集用の最終形・python-docx） ────────────


def _assert_is_docx(r) -> None:
    assert r.status_code == 200
    assert "wordprocessingml.document" in r.headers["content-type"]
    assert r.content[:2] == b"PK"  # docx = zip
    assert "filename*=UTF-8''" in r.headers.get("content-disposition", "")


def test_export_docx_child_record_returns_docx() -> None:
    r = _client().post(
        "/api/export-docx", json={"kind": "child_record", "entry": _edit_child_record_entry()}
    )
    _assert_is_docx(r)


def test_export_docx_monthly_returns_docx() -> None:
    r = _client().post("/api/export-docx", json={"kind": "monthly", "entry": _edit_monthly_entry()})
    _assert_is_docx(r)


def test_export_docx_class_monthly_returns_docx() -> None:
    r = _client().post(
        "/api/export-docx", json={"kind": "class_monthly", "entry": _edit_class_monthly_entry()}
    )
    _assert_is_docx(r)


def test_export_docx_nursery_record_returns_docx() -> None:
    r = _client().post(
        "/api/export-docx", json={"kind": "nursery_record", "entry": _edit_nursery_record_entry()}
    )
    _assert_is_docx(r)


def test_export_docx_unsupported_kind_400() -> None:
    """docx 未対応の kind（現状 diary 等）は 400 で正直に返す（握りつぶさない）。"""
    r = _client().post("/api/export-docx", json={"kind": "diary", "entry": _edit_diary_entry()})
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


def test_add_child_registers_real_name_and_gender(records_db) -> None:
    """新規児登録＝本名（姓/名）＋性別。呼び名＋敬称（性別導出）＝display_name をサーバが合成する。"""
    c = _client()
    r = c.post(
        "/api/children",
        json={"family_name": "佐藤", "given_name": "はると", "gender": "male"},
    ).json()
    assert r["status"] == "created"
    assert r["display_name"] == "はるとくん"  # 名＋敬称（男→くん）
    assert r["official_name"] == "佐藤　はると"  # 氏名欄用の本名（姓＋名）
    # /api/children の選択肢に本名つきで出る
    row = next(
        x for x in c.get("/api/children").json()["children"] if x["display_name"] == "はるとくん"
    )
    assert row["given_name"] == "はると" and row["gender"] == "male"
    # 女の子は「ちゃん」
    r2 = c.post("/api/children", json={"given_name": "ゆい", "gender": "female"}).json()
    assert r2["display_name"] == "ゆいちゃん"


def test_add_child_validates_input(records_db) -> None:
    c = _client()
    assert c.post("/api/children", json={"given_name": "", "gender": "male"}).status_code == 400
    assert (
        c.post("/api/children", json={"given_name": "そら", "gender": "その他"}).status_code == 400
    )


def test_add_child_degrades_when_db_unset(monkeypatch) -> None:
    """DB 未設定は skipped（永続化なし）だが display_name は合成して返す（フロントはセッション追加）。"""
    monkeypatch.setattr(settings, "database_url", "")
    record_store.reset_engine_cache()
    r = _client().post("/api/children", json={"given_name": "はると", "gender": "male"}).json()
    assert r["status"] == "skipped" and r["display_name"] == "はるとくん"


def test_add_child_is_passcode_gated(records_db, monkeypatch) -> None:
    """児童マスタへの書込（POST）も辞書荒らしと同枠でゲート。読取（GET）は素通し。"""
    monkeypatch.setattr(settings, "demo_passcode", "secret")
    c = _client()
    assert (
        c.post("/api/children", json={"given_name": "はると", "gender": "male"}).status_code == 401
    )
    assert c.get("/api/children").status_code == 200
    ok = c.post(
        "/api/children",
        json={"given_name": "はると", "gender": "male"},
        headers={"X-Demo-Passcode": "secret"},
    )
    assert ok.status_code == 200 and ok.json()["display_name"] == "はるとくん"


# ──────────────────── クラス（組）マスタ（/api/classes＝record_store 中継・名簿管理） ────────────────────


def test_classes_crud_and_roster_flow(records_db) -> None:
    """クラス作成→児童をクラスへ割当→roster/一覧に反映（園の名簿管理・日誌 roster の素）。"""
    c = _client()
    # クラス作成
    r = c.post(
        "/api/classes", json={"name": "ひまわり組", "age_band": "3-5", "fiscal_year": "2026"}
    ).json()
    assert r["status"] == "created" and r["name"] == "ひまわり組" and r["age_band"] == "3-5"
    cid = r["id"]
    # 児童登録（クラス指定つき＝1操作で割当まで完結）
    reg = c.post(
        "/api/children",
        json={"given_name": "はると", "gender": "male", "class_id": cid},
    ).json()
    assert reg["status"] == "created" and reg.get("assign") == "ok"
    # 児童登録（後から assign）
    c.post("/api/children", json={"given_name": "ゆい", "gender": "female"})
    asg = c.post("/api/classes/assign", json={"child": "ゆいちゃん", "class_id": cid}).json()
    assert asg["status"] == "ok" and asg["class_name"] == "ひまわり組"
    # roster＝クラスの在籍児（日誌フォームの素）
    roster = c.get("/api/classes/roster", params={"class_id": cid}).json()["children"]
    assert [x["display_name"] for x in roster] == ["はるとくん", "ゆいちゃん"]
    assert roster[0]["class_age_band"] == "3-5"
    # 一覧＋在籍児数
    lst = c.get("/api/classes").json()
    assert lst["store"] == "ok"
    assert next(x for x in lst["classes"] if x["id"] == cid)["child_count"] == 2
    # 未所属へ戻す
    assert (
        c.post("/api/classes/assign", json={"child": "ゆいちゃん", "class_id": ""}).json()["status"]
        == "ok"
    )
    assert [
        x["display_name"]
        for x in c.get("/api/classes/roster", params={"class_id": cid}).json()["children"]
    ] == ["はるとくん"]


def test_classes_validate_input(records_db) -> None:
    c = _client()
    assert c.post("/api/classes", json={"name": "", "age_band": "3-5"}).status_code == 400
    assert c.post("/api/classes", json={"name": "ばら組", "age_band": "9-9"}).status_code == 400
    assert c.post("/api/classes/assign", json={"child": "", "class_id": "x"}).status_code == 400


def test_classes_degrade_when_db_unset(monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_url", "")
    record_store.reset_engine_cache()
    c = _client()
    assert c.get("/api/classes").json() == {"classes": [], "store": "disabled"}
    assert c.get("/api/classes/roster", params={"class_id": "x"}).json()["children"] == []
    assert (
        c.post("/api/classes", json={"name": "ひまわり組", "age_band": "0-2"}).json()["status"]
        == "skipped"
    )


def test_classes_write_is_passcode_gated_reads_open(records_db, monkeypatch) -> None:
    """クラスの書込（POST）は辞書荒らしと同枠でゲート。読取（GET）は素通し。"""
    monkeypatch.setattr(settings, "demo_passcode", "secret")
    c = _client()
    assert c.post("/api/classes", json={"name": "ひまわり組", "age_band": "3-5"}).status_code == 401
    assert (
        c.post("/api/classes/assign", json={"child": "はるとくん", "class_id": "x"}).status_code
        == 401
    )
    assert c.get("/api/classes").status_code == 200
    assert c.get("/api/classes/roster", params={"class_id": "x"}).status_code == 200
    ok = c.post(
        "/api/classes",
        json={"name": "ひまわり組", "age_band": "3-5"},
        headers={"X-Demo-Passcode": "secret"},
    )
    assert ok.status_code == 200 and ok.json()["status"] == "created"


def test_export_pdf_nursery_uses_registered_real_name(records_db) -> None:
    """要録の氏名欄は登録済みの本名で解決できる（get_child 経路が通り PDF を返す）。"""
    c = _client()
    c.post("/api/children", json={"family_name": "佐藤", "given_name": "はると", "gender": "male"})
    entry = {**_edit_nursery_record_entry(), "child_id": "はるとくん"}
    _assert_is_pdf(c.post("/api/export-pdf", json={"kind": "nursery_record", "entry": entry}))


def test_child_record_entries_endpoint_seeds_youroku(records_db) -> None:
    """保育要録 L4 の seed 取得口＝指定児の保育経過記録（最新版・期間順）を返す（読取なので非ゲート）。"""
    c = _client()
    for period, overall in [("2026-04〜2026-07", "1期"), ("2026-08〜2026-11", "2期")]:
        c.post(
            "/api/records",
            json={
                "kind": "child_record",
                "entry": {
                    "period": period,
                    "age_band": "3-5",
                    "child_id": "架空児A",
                    "development_notes": [{"description": overall, "tags": ["健康"]}],
                    "overall_note": overall,
                },
                "author_kind": "ai",
            },
        )
    body = c.get("/api/records/child-record-entries", params={"child": "架空児A"}).json()
    assert body["store"] == "ok"
    assert [e["period"] for e in body["entries"]] == ["2026-04〜2026-07", "2026-08〜2026-11"]
    # 未登録児は空＝フロントがサンプルへ降格
    assert (
        c.get("/api/records/child-record-entries", params={"child": "未登録"}).json()["entries"]
        == []
    )


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
    """seed 取得口＝期間内の日誌 entry（最新版）を返す（月案 L2／保育経過記録 L3 の還流を DB から）。"""
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


# ──────────────────── 保育経過記録 年間マトリクスの過去期埋め込み（chohyo_pdf × record_store） ────────────────────


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
    """保育経過記録の帳票PDF はアーカイブの同児・同年度の過去期で他列を埋めて返す（未接続は従来どおり）。"""
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


def test_set_user_display_name_updates_config_and_actor(records_db, monkeypatch) -> None:
    """POST /api/user＝IAP の検証済み email に表示名を紐づけ、config と証跡に反映される。"""
    from hoiku_agent.web import iap

    monkeypatch.setattr(settings, "iap_audience", "/projects/1/locations/l/services/s")
    monkeypatch.setattr(iap, "_verify_assertion", lambda a, aud: {"email": "sensei@example.com"})
    c = _client()
    headers = {"x-goog-iap-jwt-assertion": "signed-jwt"}
    r = c.post("/api/user", json={"display_name": "そうた先生"}, headers=headers)
    assert r.status_code == 200 and r.json()["display_name"] == "そうた先生"
    # config に user_display_name として乗る（フロントが名前を表示できる）。
    cfg = c.get("/api/config", headers=headers).json()
    assert cfg["user_email"] == "sensei@example.com"
    assert cfg["user_display_name"] == "そうた先生"
    # 以後の保存の証跡 actor は「表示名（email）」＝自己申告の名義は無視される。
    payload = {
        "kind": "diary",
        "entry": _edit_diary_entry(),
        "author_kind": "ai",
        "actor": "無視名義",
    }
    assert c.post("/api/records", json=payload, headers=headers).json()["status"] == "saved"
    assert {e["actor"] for e in record_store.list_audit_events()} == {
        "そうた先生（sensei@example.com）"
    }


def test_set_user_display_name_requires_signin(monkeypatch) -> None:
    """未サインイン（検証済み email なし）は 403＝偽装ヘッダで他人の表示名を書けない（fail-closed）。"""
    monkeypatch.setattr(settings, "iap_audience", "")  # IAP 未配線＝ヘッダを信用しない
    r = _client().post(
        "/api/user",
        json={"display_name": "なりすまし"},
        headers={"x-goog-iap-jwt-assertion": "spoofed"},
    )
    assert r.status_code == 403 and r.json()["code"] == "auth_required"


def test_set_user_display_name_not_passcode_gated(records_db, monkeypatch) -> None:
    """/api/user はパスコードゲート外＝サインイン済みならパスコード無しで自分の表示名を保存できる。"""
    from hoiku_agent.web import iap

    monkeypatch.setattr(settings, "demo_passcode", "secret")  # ゲート有効でも…
    monkeypatch.setattr(settings, "iap_audience", "/projects/1/locations/l/services/s")
    monkeypatch.setattr(iap, "_verify_assertion", lambda a, aud: {"email": "sensei@example.com"})
    r = _client().post(
        "/api/user",
        json={"display_name": "そうた先生"},
        headers={"x-goog-iap-jwt-assertion": "signed-jwt"},
    )
    assert r.status_code == 200 and r.json()["status"] == "ok"  # パスコードで 401 にならない


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


# ──────────────────── アップロード取込（upload_extract / /api/parse-upload） ────────────────────
# 実 LLM は回さない（creds 不要・決定論）：抽出（決定的）は実物で、書き起こし（agentic）は _run_parser を
# monkeypatch で差し替える。権威的上書き（対象キー/child/age_band）と harness.finalize 中継・降格を担保する。


def _docx_bytes(*lines: str) -> bytes:
    """テスト用の docx を1段落ずつ作ってバイト列で返す。"""
    import io

    from docx import Document

    d = Document()
    for line in lines:
        d.add_paragraph(line)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


def _xlsx_bytes(rows: list[list[str]]) -> bytes:
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_upload_extract_docx_xlsx_pdf() -> None:
    """decision論：docx/xlsx はテキスト抽出、pdf は inline_data、未対応/空は ValueError。"""
    from hoiku_agent.web import upload_extract as ux

    ex = ux.extract_upload("n.docx", None, _docx_bytes("保育日誌 5月15日", "はるとくん 完食"))
    assert ex.fmt == "docx" and "はるとくん" in ex.text and ux.to_parts(ex)[0].text

    ex2 = ux.extract_upload("m.xlsx", None, _xlsx_bytes([["対象月", "2026-06"], ["児童", "めい"]]))
    assert ex2.fmt == "xlsx" and "2026-06" in ex2.text

    ex3 = ux.extract_upload("s.pdf", "application/pdf", b"%PDF-1.4 x")
    assert ex3.fmt == "pdf" and ex3.text == "" and ux.to_parts(ex3)[0].inline_data is not None

    with pytest.raises(ValueError):
        ux.extract_upload("old.doc", None, b"bin")  # 旧バイナリ様式は非対応
    with pytest.raises(ValueError):
        ux.extract_upload("empty.pdf", None, b"")  # 空


def test_parse_upload_overrides_keys_and_relays_finalize(monkeypatch) -> None:
    """取込エンドポイント：LLM が種別/対象を取り違えても保育士入力（与件）で権威的に上書きし、
    harness.finalize で整形・検査した結果を返す（保存は後段 /api/records・ここは解析のみ）。"""
    monkeypatch.setattr(settings, "demo_passcode", "")  # ゲート無効で素通しにする
    from hoiku_agent.web import upload_parse

    fence = (
        "読み取りました。\n```json\n"
        '{"period":"WRONG","age_band":"0-2","child_id":"別の子",'
        '"development_notes":[{"description":"友だちと関わって遊ぶ姿が増えた","tags":["人間関係"]}],'
        '"overall_note":"関わりが広がった。"}\n```'
    )

    async def _fake(agent, parts):
        return fence

    monkeypatch.setattr(upload_parse, "_run_parser", _fake)
    c = _client()
    r = c.post(
        "/api/parse-upload",
        data={
            "kind": "child_record",
            "target": "2026-04〜2026-06",
            "child": "はるとくん",
            "age_band": "3-5",
        },
        files={
            "file": ("j.docx", _docx_bytes("保育経過記録 はると 1期"), "application/octet-stream")
        },
    )
    assert r.status_code == 200
    body = r.json()
    # 与件で権威的に上書きされている（LLM の取り違えを封じる）。
    assert body["entry"]["period"] == "2026-04〜2026-06"
    assert body["entry"]["child_id"] == "はるとくん"
    assert body["entry"]["age_band"] == "3-5"
    # harness の整形・検査結果が中継されている。
    assert body["ok"] is True and body["parse_error"] is None
    assert "発達の経過" in body["formatted"]


def test_parse_upload_class_monthly_overrides_and_relays(monkeypatch) -> None:
    """クラス月案の取込（§18）：クラス単位＝主対象児なしで、対象月＝与件を権威的に上書きし、
    grid が正準7行に整えられた harness 確定結果を中継する（kind=class_monthly・class_monthly も取込対応）。"""
    monkeypatch.setattr(settings, "demo_passcode", "")
    import json as _json

    from hoiku_agent.web import upload_parse

    parsed = {
        "month": "WRONG",  # LLM の取り違え → 与件で上書きされることを確かめる
        "age_band": "0-2",
        "class_name": "ひよこ組",
        "monthly_goal": "梅雨期も健康に過ごす",
        "prev_month_state": "感触遊びに集中していた",
        "grid": [
            {
                "category": c,
                "domain": d,
                "aim": f"{d}のねらい",
                "environment": "環境",
                "child_state": "姿",
                "support": "配慮",
            }
            for c, d in (
                ("養護", "生命の保持"),
                ("養護", "情緒の安定"),
                ("教育", "健康"),
                ("教育", "人間関係"),
                ("教育", "環境"),
                ("教育", "言葉"),
                ("教育", "表現"),
            )
        ],
        "individual_goals": [
            {
                "child_id": "はるとくん",
                "age_months": "1歳3か月",
                "child_state": "歩行が安定",
                "aim_support": "探索を見守る",
            }
        ],
    }
    fence = "読み取りました。\n```json\n" + _json.dumps(parsed, ensure_ascii=False) + "\n```"

    async def _fake(agent, parts):
        return fence

    monkeypatch.setattr(upload_parse, "_run_parser", _fake)
    r = _client().post(
        "/api/parse-upload",
        data={"kind": "class_monthly", "target": "2026-07", "child": "", "age_band": "0-2"},
        files={
            "file": (
                "m.docx",
                _docx_bytes("月間指導計画 7月 0歳児クラス"),
                "application/octet-stream",
            )
        },
    )
    assert r.status_code == 200
    body = r.json()
    # 対象月は与件で権威的に上書き。クラス単位なので top-level child_id は付かない。
    assert body["entry"]["month"] == "2026-07"
    assert body["entry"]["age_band"] == "0-2"
    assert "child_id" not in body["entry"]
    # grid は正準7行にそろい、0–2 の個人目標は原本のまま残る。
    assert len(body["entry"]["grid"]) == 7
    assert body["entry"]["individual_goals"][0]["child_id"] == "はるとくん"
    # harness の整形・検査結果が中継され、型が成立している。
    assert body["ok"] is True and body["parse_error"] is None
    assert body["formatted"]


def test_parse_upload_degrades_on_llm_failure(monkeypatch) -> None:
    """LLM 失敗（creds 未設定等）は 200＋parse_error で正直に降格し、与件入りの最小 entry を返す。"""
    monkeypatch.setattr(settings, "demo_passcode", "")
    from hoiku_agent.web import upload_parse

    async def _boom(agent, parts):
        raise RuntimeError("no creds")

    monkeypatch.setattr(upload_parse, "_run_parser", _boom)
    r = _client().post(
        "/api/parse-upload",
        data={"kind": "diary", "target": "2026-05-15", "age_band": "0-2"},
        files={"file": ("n.docx", _docx_bytes("保育日誌"), "application/octet-stream")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["parse_error"]  # 正直に降格
    assert body["entry"]["date"] == "2026-05-15"  # 与件は入っている＝手入力で補える


def test_parse_upload_unsupported_format_400(monkeypatch) -> None:
    monkeypatch.setattr(settings, "demo_passcode", "")
    r = _client().post(
        "/api/parse-upload",
        data={"kind": "diary", "target": "2026-05-15", "age_band": "0-2"},
        files={"file": ("old.doc", b"legacy-binary", "application/msword")},
    )
    assert r.status_code == 400 and r.json()["code"] == "invalid_request"


def test_parse_upload_is_passcode_gated(monkeypatch) -> None:
    """アップロード取込は LLM を回す口なのでパスコードゲート（/api/improve と同枠）。"""
    monkeypatch.setattr(settings, "demo_passcode", "secret")
    r = _client().post(
        "/api/parse-upload",
        data={"kind": "diary", "target": "2026-05-15", "age_band": "0-2"},
        files={"file": ("n.docx", _docx_bytes("x"), "application/octet-stream")},
    )
    assert r.status_code == 401
