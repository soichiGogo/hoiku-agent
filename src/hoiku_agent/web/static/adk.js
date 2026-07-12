// ADK ネイティブ REST クライアント（保育士 UI から日誌/月案を直接駆動）。
// get_fast_api_app が出す /apps/.../sessions・/run_sse をそのまま叩く（自前 Runner は組まない＝§9）。

let _cfg = null;

export async function loadConfig() {
  _cfg = await (await fetch("/api/config")).json();
  return _cfg;
}
async function refreshBudget() {
  try {
    const next = await (await fetch("/api/config")).json();
    if (!next.llm_budget) return;
    _cfg = { ..._cfg, ...next };
    window.dispatchEvent(new CustomEvent("llm-budget", { detail: next.llm_budget }));
  } catch {
    // 利用枠表示の再読込に失敗しても、作成済みの書類フローを失敗扱いにしない。
  }
}
export function config() {
  return _cfg;
}
const app = () => _cfg.app_name;
const uid = () => _cfg.default_user_id;

// 自分の表示名（display_name）を登録/編集する（Google サインイン前提）。email はサーバが検証済み値で
// 解決する（body に載せない＝偽装不可）。未サインインは 403（auth_required）で正直に降格。
// 成功は {status:"ok", email, display_name}／DB 未接続は {status:"skipped"}。
export async function setUserProfile(displayName) {
  try {
    const r = await fetch("/api/user", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: displayName }),
    });
    if (r.status === 403) return { status: "error", detail: "サインインが必要です" };
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return { status: j.status || "error", detail: j.detail || `失敗 (${r.status})` };
    return j;
  } catch (e) {
    return { status: "error", detail: e.message || String(e) };
  }
}

// 育つ指針＝構造化カード＋変更履歴を読む（「指針を育てる」タブの閲覧）。
// 旧 backend（{markdown} だけ）や未配線でも壊れないよう空＋unavailable に降格する（偽の緑を出さない）。
export async function getPolicy() {
  try {
    const r = await fetch("/api/policy");
    if (!r.ok) return { cards: [], history: [], store: "unavailable" };
    const j = await r.json();
    return {
      cards: j.cards || [],
      history: j.history || [],
      store: j.store || "unavailable",
      version: j.version ?? 0,
    };
  } catch {
    return { cards: [], history: [], store: "unavailable" };
  }
}

// 表記ルール辞書（ひらがな表記DX）を読む（未配線/壊れは空＋unavailable に降格＝偽の中身を出さない）。
export async function getNotation() {
  try {
    const r = await fetch("/api/notation");
    if (!r.ok) return { rules: [], store: "unavailable" };
    const j = await r.json();
    return { rules: j.rules || [], store: j.store || "unavailable" };
  } catch {
    return { rules: [], store: "unavailable" };
  }
}
// 表記ルールの追加/編集/削除（成功で更新後の {rules, store} を返す。失敗は status:error/rejected＋detail）。
export async function addNotationRule(body) {
  return _notationWrite("/api/notation", "POST", body);
}
export async function updateNotationRule(ruleId, body) {
  return _notationWrite(`/api/notation/${encodeURIComponent(ruleId)}`, "PATCH", body);
}
export async function deleteNotationRule(ruleId) {
  return _notationWrite(`/api/notation/${encodeURIComponent(ruleId)}`, "DELETE", null);
}
async function _notationWrite(url, method, body) {
  try {
    const r = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) return { status: j.status || "error", detail: j.detail || `失敗 (${r.status})` };
    return j; // { status:"ok", rules, store }
  } catch (e) {
    return { status: "error", detail: e.message };
  }
}

// 編集フォームのタグ選択肢（schemas Enum が SSOT）。一度読んだらキャッシュする。
let _formMeta = null;
export async function getFormMeta() {
  if (_formMeta) return _formMeta;
  _formMeta = await (await fetch("/api/form-meta")).json();
  return _formMeta;
}

let _docTemplate = null;
// 様式テンプレート（本文セクションの順序・ラベル・種別）。編集フォームが本文の並び/見出しに使う。
// 取得失敗は空 templates（フロントは既定順にフォールバック）。
export async function getDocTemplate() {
  if (_docTemplate) return _docTemplate;
  try {
    _docTemplate = await (await fetch("/api/doc-template")).json();
  } catch {
    _docTemplate = { templates: {} };
  }
  return _docTemplate;
}
// 保育士の編集後 entry を harness で再検査・再整形する（決定的ロジックは harness 側）。
export async function finalizeEdit(kind, entry, docDate) {
  const r = await fetch("/api/finalize-edit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, entry, doc_date: docDate || null }),
  });
  if (!r.ok) throw new Error("再チェックに失敗 (" + r.status + ")");
  return await r.json(); // { formatted, problems, parse_error, ok }
}

// ── 書類アーカイブ（harness/record_store の中継・Phase 1）────────────────────────────
// アーカイブの失敗で本流（state 保存・承認）を壊さない＝通信例外も status:"error" に畳んで返し、
// 呼び出し側が正直に表示する（skipped＝未接続降格 / error＝失敗。偽の緑を出さない）。

// 確定書類をアーカイブへ保存（AI 確定＝"ai" / 保育士の編集保存＝"caregiver"）。
export async function saveRecord(kind, entry, renderedText, authorKind, actor) {
  try {
    const r = await fetch("/api/records", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind,
        entry,
        rendered_text: renderedText || "",
        author_kind: authorKind,
        actor: actor || "",
      }),
    });
    if (!r.ok) return { status: "error", detail: "アーカイブ保存に失敗 (" + r.status + ")" };
    return await r.json();
  } catch (e) {
    return { status: "error", detail: e.message };
  }
}

// 保存済みの現行版をMemory Bankへ同期してから承認する。expectedVersionSeqで並行編集を検知する。
export async function approveRecord(kind, entry, actor, expectedVersionSeq = null) {
  try {
    const r = await fetch("/api/records/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        kind,
        entry,
        actor: actor || "",
        expected_version_seq: expectedVersionSeq,
      }),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) {
      return {
        status: "error",
        code: body.code || "approval_failed",
        detail: body.detail || "承認に失敗 (" + r.status + ")",
      };
    }
    return body;
  } catch (e) {
    return { status: "error", detail: e.message };
  }
}

// 書類への 👍👎（＋ひとこと）を保存する（確定/承認画面の軽量フィードバック＝§8「回す」の一次入力）。
// verdict は "up"/"down"。未接続は status:"skipped"（本流を壊さない補助シグナル）・失敗は status:"error"。
export async function saveFeedback(documentId, verdict, comment, actor) {
  try {
    const r = await fetch("/api/records/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: documentId || "",
        verdict,
        comment: comment || "",
        actor: actor || "",
      }),
    });
    if (!r.ok) return { status: "error", detail: "フィードバックの保存に失敗 (" + r.status + ")" };
    return await r.json();
  } catch (e) {
    return { status: "error", detail: e.message };
  }
}

// 書類フィードバックの一覧（新しい順）。未接続/障害は空＝呼び出し側が正直に降格する。
export async function listFeedback(documentId) {
  try {
    const q = documentId ? "?document_id=" + encodeURIComponent(documentId) : "";
    const r = await fetch("/api/records/feedback" + q);
    if (!r.ok) return { feedback: [], store: "unavailable" };
    const j = await r.json();
    return { feedback: j.feedback || [], store: j.store || "unavailable" };
  } catch {
    return { feedback: [], store: "unavailable" };
  }
}

// 期間内の日誌 entry（アーカイブの最新版）。空なら呼び出し側は作成を止めて記録を促す。
export async function getDiaryEntries(dateFrom, dateTo) {
  try {
    const r = await fetch(`/api/records/diary-entries?date_from=${dateFrom}&date_to=${dateTo}`);
    if (!r.ok) return [];
    return (await r.json()).entries || [];
  } catch {
    return [];
  }
}

// 期間内の日誌メタ（id・対象日・状態・評価充足）＝クラス月案作成時の「評価未記入」検出用。
// entries の要素は {id, date, status, evaluation_complete}。未接続/障害は空＝検出をスキップ（黙って進む）。
export async function getDiaryMeta(dateFrom, dateTo) {
  try {
    const r = await fetch(`/api/records/diary-meta?date_from=${dateFrom}&date_to=${dateTo}`);
    if (!r.ok) return [];
    return (await r.json()).entries || [];
  } catch {
    return [];
  }
}

// 指定児の保育経過記録（最新版・全期）＝要録 L4／保育経過記録「前回まで」の seed 取得口。
// excludePeriod を渡すと当該期間の記録を除く（作成対象の期を自己履歴に混ぜない＝依存モデル 2026-07）。
// 未接続/障害/該当なしは空＝呼び出し側が作成を止める（黙って誤解釈しない）。
export async function getChildRecordEntries(child, excludePeriod) {
  try {
    const q = excludePeriod ? `&exclude_period=${encodeURIComponent(excludePeriod)}` : "";
    const r = await fetch(
      `/api/records/child-record-entries?child=${encodeURIComponent(child)}${q}`,
    );
    if (!r.ok) return [];
    return (await r.json()).entries || [];
  } catch {
    return [];
  }
}

// クラス月案の seed 3系統（依存モデル 2026-07）＝①クラス児童の保育経過記録すべて ②それまでの
// クラス月案 ③経過記録に未反映の期間の日誌（境界計算はサーバ側 harness に1つ＝JS で再実装しない）。
// 未接続/障害は全部空＝呼び出し側が作成を止める。
export async function getClassMonthlySeed(ageBand, month) {
  const empty = { class_diary_entries: [], class_record_entries: [], past_class_plans: [] };
  try {
    const r = await fetch(
      `/api/records/class-monthly-seed?age_band=${encodeURIComponent(ageBand)}&month=${encodeURIComponent(month)}`,
    );
    if (!r.ok) return empty;
    const j = await r.json();
    return {
      class_diary_entries: j.class_diary_entries || [],
      class_record_entries: j.class_record_entries || [],
      past_class_plans: j.past_class_plans || [],
    };
  } catch {
    return empty;
  }
}

// 書類アーカイブの一覧（メタ）＝「書類を見る」タブ。docType 指定で種別フィルタ。未接続/障害は
// 空＋store で正直に降格（偽の中身を出さない）。
export async function listRecords(docType) {
  try {
    const q = docType ? `?doc_type=${encodeURIComponent(docType)}` : "";
    const r = await fetch(`/api/records${q}`);
    if (!r.ok) return { documents: [], store: "unavailable" };
    const j = await r.json();
    return { documents: j.documents || [], store: j.store || "unavailable" };
  } catch {
    return { documents: [], store: "unavailable" };
  }
}

// アップロードしたファイル（pdf/docx/xlsx）を解析し、確認・編集用の entry を受け取る（「書類を見る」取込）。
// 種別・対象・年齢帯・対象児は保育士が場所/フォームで指定した与件（サーバが権威的に上書きしてから解析）。
// 401（認証切れ）・400（未対応形式）は {error} に畳んで返す（呼び出し側が正直に表示）。
export async function parseUpload(kind, { target, child, ageBand }, file) {
  const fd = new FormData();
  fd.append("kind", kind);
  fd.append("target", target || "");
  fd.append("child", child || "");
  fd.append("age_band", ageBand || "");
  fd.append("file", file);
  try {
    const r = await fetch("/api/parse-upload", { method: "POST", body: fd });
    if (!r.ok) {
      let detail = "解析に失敗しました (" + r.status + ")";
      try {
        detail = (await r.json()).error || detail;
      } catch {
        /* 本文が JSON でなければ既定メッセージ */
      }
      await refreshBudget();
      return { error: detail };
    }
    const result = await r.json();
    await refreshBudget();
    return result; // { kind, entry, formatted, problems, parse_error, ok }
  } catch (e) {
    return { error: e.message };
  }
}

// 単一書類の全文（現行版の整形テキスト＋本文 entry）。不在/未接続/障害は null（呼び出し側が正直に表示）。
export async function getRecord(id) {
  try {
    const r = await fetch(`/api/records/${encodeURIComponent(id)}`);
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

// 児童マスタ（アーカイブに登場した子）。未設定/障害は空＝呼び出し側が従来チップへ降格する。
export async function getChildren() {
  try {
    const r = await fetch("/api/children");
    if (!r.ok) return [];
    return (await r.json()).children || [];
  } catch {
    return [];
  }
}

// 新規児を児童マスタへ登録する（本名＝姓/名＋性別）。呼び名＋敬称＝display_name はサーバが合成する。
// 成功は {status, display_name, store, ...}／失敗は {status:"error", detail}／未認証は 401（gate 要求）。
export async function addChild(payload) {
  try {
    const r = await fetch("/api/children", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return await r.json();
  } catch {
    return { status: "error", detail: "登録に失敗しました" };
  }
}

// クラス（組）一覧＋在籍児数（園の名簿管理・日誌のクラス選択）。未設定/障害は空＝降格。
export async function getClasses(fiscalYear) {
  try {
    const q = fiscalYear ? "?fiscal_year=" + encodeURIComponent(fiscalYear) : "";
    const r = await fetch("/api/classes" + q);
    if (!r.ok) return { classes: [], store: "unavailable" };
    return await r.json();
  } catch {
    return { classes: [], store: "unavailable" };
  }
}

// 指定クラスの在籍児（日誌フォームの roster／名簿UIのクラス内一覧）。未接続/不在は空。
export async function getClassRoster(classId) {
  try {
    const r = await fetch("/api/classes/roster?class_id=" + encodeURIComponent(classId));
    if (!r.ok) return [];
    return (await r.json()).children || [];
  } catch {
    return [];
  }
}

// クラス（組）を定義する。成功 {status:"created"/"exists", ...}。
export async function addClass(payload) {
  try {
    const r = await fetch("/api/classes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return await r.json();
  } catch {
    return { status: "error", detail: "クラスの作成に失敗しました" };
  }
}

// 児童をクラスへ割当/移動/解除する（class_id 空＝未所属へ・書込ゲート）。
export async function assignChild(child, classId) {
  try {
    const r = await fetch("/api/classes/assign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ child, class_id: classId || "" }),
    });
    return await r.json();
  } catch {
    return { status: "error", detail: "割り当てに失敗しました" };
  }
}

// 校正AI（日本語チェック・言い換え提案）。手入力 entry の叙述文への提案（パス付き）を返す。
// LLM 口はログインと利用枠が必要。creds 無/失敗は 200＋error（suggestions 空）で正直に降格。
export async function proofread(kind, entry) {
  try {
    const r = await fetch("/api/proofread", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, entry }),
    });
    const result = await r.json();
    await refreshBudget();
    return result;
  } catch {
    return { suggestions: [], error: "校正の呼び出しに失敗しました" };
  }
}

// 確定 entry を園の帳票PDFに描いて受け取る（現場でそのまま綴じる最終形）。{ blob, filename } を返す。
export async function exportPdf(kind, entry) {
  const r = await fetch("/api/export-pdf", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, entry }),
  });
  if (!r.ok) throw new Error("帳票PDFの生成に失敗 (" + r.status + ")");
  const blob = await r.blob();
  // Content-Disposition の filename*（RFC5987・UTF-8）からダウンロード名を取り出す。
  let filename = kind === "monthly" ? "月案.pdf" : "保育日誌.pdf";
  const cd = r.headers.get("content-disposition") || "";
  const m = cd.match(/filename\*=UTF-8''([^;]+)/i);
  if (m) {
    try {
      filename = decodeURIComponent(m[1]);
    } catch {
      /* 壊れていれば既定名で保存する */
    }
  }
  return { blob, filename };
}

// 確定 entry を園の実 Word 様式（.docx）へ流し込んで受け取る（Word 編集用の最終形）。{ blob, filename } を返す。
export async function exportDocx(kind, entry) {
  const r = await fetch("/api/export-docx", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, entry }),
  });
  if (!r.ok) throw new Error("Word様式の生成に失敗 (" + r.status + ")");
  const blob = await r.blob();
  let filename = "書類.docx";
  const cd = r.headers.get("content-disposition") || "";
  const m = cd.match(/filename\*=UTF-8''([^;]+)/i);
  if (m) {
    try {
      filename = decodeURIComponent(m[1]);
    } catch {
      /* 壊れていれば既定名で保存する */
    }
  }
  return { blob, filename };
}

export async function createSession(state) {
  const r = await fetch(`/apps/${app()}/users/${uid()}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state ? { state } : {}),
  });
  if (!r.ok) throw new Error("セッション作成に失敗 (" + r.status + ")");
  return await r.json(); // { id, ... }
}
export async function getSession(sessionId) {
  const r = await fetch(`/apps/${app()}/users/${uid()}/sessions/${sessionId}`);
  if (!r.ok) throw new Error("セッション取得に失敗 (" + r.status + ")");
  return await r.json();
}
export async function patchState(sessionId, stateDelta) {
  const r = await fetch(`/apps/${app()}/users/${uid()}/sessions/${sessionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ state_delta: stateDelta }),
  });
  // 他のセッション系ヘルパと同様、失敗は throw する（握りつぶして偽の成功＝偽の緑を出さない）。
  if (!r.ok) throw new Error("状態の保存に失敗 (" + r.status + ")");
  return true;
}

// 汎用 SSE POST：data: 行ごとに onItem(parsedJson) を呼ぶ。
export async function ssePost(url, body, onItem) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  // 非 OK 応答（4xx/5xx）は body を SSE として読まず即 throw する。fetch の Response.body は
  // エラー応答でも ReadableStream として存在する（null になるのは 204/304 等のみ）ため、`!r.body`
  // に頼ると 422/500 が握りつぶされ、呼び出し側がストリーム完了＝成功と誤認しスピナーが回り続ける。
  if (!r.ok) {
    let detail = "";
    try {
      detail = (await r.json()).error || "";
    } catch {
      detail = await r.text().catch(() => "");
    }
    await refreshBudget();
    throw new Error(detail || url + " 失敗 (" + r.status + ")");
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const json = line.slice(5).trim();
      if (!json) continue;
      try {
        onItem(JSON.parse(json));
      } catch (e) {
        console.warn("SSE parse", e, json);
      }
    }
  }
  await refreshBudget();
}

// 日誌/月案の実行（ADK /run_sse）。new_message を渡してイベントを onEvent(adkEvent) で受ける。
// 保留中の長時間ツールを再開するときは opts.invocationId に元 invocation を渡す（確実に同じ invocation を継ぐ）。
export async function runSSE(sessionId, newMessage, onEvent, opts = {}) {
  const body = {
    app_name: app(),
    user_id: uid(),
    session_id: sessionId,
    new_message: newMessage,
    streaming: false,
  };
  if (opts.invocationId) body.invocation_id = opts.invocationId;
  await ssePost("/run_sse", body, onEvent);
}

// テキスト1通の user メッセージ。
export function textMessage(text) {
  return { role: "user", parts: [{ text }] };
}
// 保留中の長時間ツール（ask_caregiver）への function_response で invocation を再開する。
export function functionResponseMessage(callId, name, response) {
  return { role: "user", parts: [{ function_response: { id: callId, name, response } }] };
}

// ADK Event(JSON) → フラットな部品列に正規化（by_alias の camelCase / snake_case 両対応）。
export function adkParts(ev) {
  const author = ev.author;
  const lr = new Set(ev.longRunningToolIds || ev.long_running_tool_ids || []);
  const parts = (ev.content && ev.content.parts) || [];
  const out = [];
  for (const p of parts) {
    if (p.text) out.push({ kind: "text", author, text: p.text });
    const fc = p.functionCall || p.function_call;
    if (fc) out.push({ kind: "call", author, name: fc.name, args: fc.args || {}, id: fc.id, longRunning: lr.has(fc.id) });
    const fr = p.functionResponse || p.function_response;
    if (fr) out.push({ kind: "response", author, name: fr.name, id: fr.id, response: fr.response });
  }
  return out;
}
