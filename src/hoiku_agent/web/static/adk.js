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

export async function getPolicy() {
  return (await (await fetch("/api/policy")).json()).markdown || "";
}
export async function getBaseline() {
  try {
    const r = await fetch("/api/eval-baseline");
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
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
