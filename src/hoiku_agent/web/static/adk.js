// ADK ネイティブ REST クライアント（保育士 UI から日誌/月案を直接駆動）。
// get_fast_api_app が出す /apps/.../sessions・/run_sse をそのまま叩く（自前 Runner は組まない＝§9）。

let _cfg = null;

export class PasscodeError extends Error {}

export async function loadConfig() {
  _cfg = await (await fetch("/api/config")).json();
  return _cfg;
}
export function config() {
  return _cfg;
}
const app = () => _cfg.app_name;
const uid = () => _cfg.default_user_id;

export async function gate(passcode) {
  const r = await fetch("/api/gate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ passcode }),
  });
  return r.ok;
}

// 育つ指針＝構造化カード＋変更履歴を読む（「指針を育てる」タブの閲覧）。
// 旧 backend（{markdown} だけ）や未配線でも壊れないよう空＋unavailable に降格する（偽の緑を出さない）。
export async function getPolicy() {
  try {
    const r = await fetch("/api/policy");
    if (!r.ok) return { cards: [], history: [], store: "unavailable" };
    const j = await r.json();
    return { cards: j.cards || [], history: j.history || [], store: j.store || "unavailable" };
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
    if (r.status === 401) return { status: "error", detail: "パスコードが必要です" };
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

// 書類の承認を記録する（承認証跡＝誰が承認したか。ADK state の caregiver_approved と並走）。
export async function approveRecord(kind, entry, actor) {
  try {
    const r = await fetch("/api/records/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, entry, actor: actor || "" }),
    });
    if (!r.ok) return { status: "error", detail: "承認記録に失敗 (" + r.status + ")" };
    return await r.json();
  } catch (e) {
    return { status: "error", detail: e.message };
  }
}

// 期間内の日誌 entry（アーカイブの最新版）＝月案 L2／児童票 L3 の seed。空＝呼び出し側がサンプルへ降格。
export async function getDiaryEntries(dateFrom, dateTo) {
  try {
    const r = await fetch(`/api/records/diary-entries?date_from=${dateFrom}&date_to=${dateTo}`);
    if (!r.ok) return [];
    return (await r.json()).entries || [];
  } catch {
    return [];
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

// 汎用 SSE POST：data: 行ごとに onItem(parsedJson) を呼ぶ。401 は PasscodeError。
export async function ssePost(url, body, onItem) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (r.status === 401) throw new PasscodeError();
  if (!r.ok && !r.body) throw new Error(url + " 失敗 (" + r.status + ")");
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
