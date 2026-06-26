// DOM ヘルパと、エージェントの生イベントを保育士に分かる言葉へ翻訳する辞書。

export function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
}
export function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}
export function clear(node) {
  node.innerHTML = "";
}

// ツール呼び出し → 保育士向けの進行メッセージ（裏で何をしているかを優しく見せる）。
const TOOL_LABEL = {
  recall_child_history: "🧠 この子のこれまでの姿を思い出しています",
  search_guideline: "📖 保育所保育指針を参照しています",
  read_policy: "📋 園の文書作成指針を確認しています",
  validate_fields: "✅ 必須項目を自己点検しています",
  ask_caregiver: "🙋 保育士に確認したいことがあります",
};
export function toolLabel(name) {
  return TOOL_LABEL[name] || `🔧 ${name}`;
}

// エージェント名 → 役割表示。
export function whoOf(author) {
  const a = (author || "").toLowerCase();
  if (a.includes("review")) return { label: "レビューAI", cls: "review", ico: "🔎" };
  if (a.includes("author") || a.includes("monthly")) return { label: "作成AI", cls: "author", ico: "✍️" };
  if (a.includes("prep")) return { label: "前月の集計", cls: "author", ico: "📊" };
  return { label: author || "AI", cls: "", ico: "🤖" };
}

// 進行ステップを1枚追加。
export function pushStep(area, { ico, who, whoCls, text, tool }) {
  const step = el("div", "step" + (tool ? " tool" : ""));
  step.appendChild(el("div", "ico", ico || "•"));
  const body = el("div", "body");
  if (who) body.appendChild(el("div", "who " + (whoCls || ""), who));
  body.appendChild(el("div", "txt", esc(text)));
  step.appendChild(body);
  area.appendChild(step);
  step.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return step;
}

// 確定書類テキストの整形描画：タグ行（└対応する姿/領域:）を色付けして見やすく。
export function renderDocument(formatted) {
  const wrap = el("div", "doc");
  const pre = el("pre");
  const lines = String(formatted || "").split("\n");
  pre.innerHTML = lines
    .map((ln) => {
      if (/対応する姿|対応する領域|└/.test(ln)) return `<span class="tagline">${esc(ln)}</span>`;
      return esc(ln);
    })
    .join("\n");
  wrap.appendChild(pre);
  return wrap;
}

export function banner(area, kind, text) {
  area.appendChild(el("div", "banner " + kind, esc(text)));
}
