// DOM ヘルパ＋インラインSVGアイコン（外部アイコンフォント禁止＝ここに集約）＋
// エージェントの生イベントを保育士に分かる言葉/役割/状態へ翻訳する辞書。

/* ============================================================
   DOM ヘルパ
   ============================================================ */
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
// 担当者名（ヘッダの自己申告入力・localStorage 永続）。アーカイブ証跡（audit_events）の actor に使う。
// 認証（Phase 3=IAP）導入までのつなぎ＝入力が無ければ空文字（record_store 側は空でも受ける）。
export function actorName() {
  const inp = document.getElementById("actor-name");
  return ((inp && inp.value) || localStorage.getItem("hoiku_actor") || "").trim();
}

/* ============================================================
   アイコン（24pxグリッド・stroke・currentColor で色追従。装飾は aria-hidden）
   ============================================================ */
const ICONS = {
  brand: '<path d="M12 21v-9"/><path d="M12 12C12 8.7 9.3 6 6 6c0 3.3 2.7 6 6 6z"/><path d="M12 12c0-2.8 2.2-5 5-5 0 2.8-2.2 5-5 5z"/>',
  diary: '<path d="M4 19.5l4-1L19 7.5a2 2 0 0 0-2.8-2.8L5 15.7z"/><path d="M13.5 6l4 4"/>',
  calendar: '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M4 9.5h16M8.5 3v4M15.5 3v4"/>',
  refresh: '<path d="M20.5 11A8.5 8.5 0 0 0 6 5.5L3.5 8"/><path d="M3.5 4v4h4"/><path d="M3.5 13A8.5 8.5 0 0 0 18 18.5L20.5 16"/><path d="M20.5 20v-4h-4"/>',
  author: '<path d="M4 19.5l4-1L19 7.5a2 2 0 0 0-2.8-2.8L5 15.7z"/><path d="M13.5 6l4 4"/>',
  review: '<circle cx="11" cy="11" r="7"/><path d="M20.5 20.5L16.5 16.5"/>',
  chart: '<path d="M4 4v16h16"/><path d="M8 17v-4M12.5 17V8.5M17 17v-7"/>',
  caregiver: '<circle cx="12" cy="8.2" r="3.2"/><path d="M5.5 20a6.5 6.5 0 0 1 13 0"/>',
  robot: '<rect x="5" y="8" width="14" height="11" rx="2.5"/><path d="M12 8V4.5M8.5 5h7"/><path d="M9.5 13h.01M14.5 13h.01"/><path d="M5 13H3M21 13h-2"/>',
  memory: '<path d="M3.5 12a8.5 8.5 0 1 0 2.8-6.3M3.5 4.5V8H7"/><path d="M12 8v4l3 2"/>',
  book: '<path d="M5 5.5A2.5 2.5 0 0 1 7.5 3H18a1 1 0 0 1 1 1v15.5H7.5A2.5 2.5 0 0 0 5 22z"/><path d="M9 8h6M9 11.5h5"/>',
  clipboard: '<rect x="6" y="4.5" width="12" height="16.5" rx="2"/><path d="M9 3.5h6V7H9z"/><path d="M9 12h6M9 15.5h4"/>',
  shield: '<path d="M12 3l7 3v5c0 4.5-3 7.6-7 9-4-1.4-7-4.5-7-9V6z"/><path d="M9 12l2 2 4-4.5"/>',
  ask: '<circle cx="12" cy="12" r="9"/><path d="M9.4 9.6a2.6 2.6 0 1 1 3.6 2.4c-.8.4-1 .8-1 1.7"/><path d="M12 17h.01"/>',
  tool: '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
  edit: '<path d="M4 19.5l4-1L19 7.5a2 2 0 0 0-2.8-2.8L5 15.7z"/><path d="M13.5 6l4 4"/>',
  gauge: '<path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4.5-5.5"/><circle cx="12" cy="18" r="1.1" fill="currentColor" stroke="none"/>',
  git: '<circle cx="6.5" cy="6" r="2.5"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="8" r="2.5"/><path d="M6.5 8.5v7"/><path d="M17.5 10.5c0 3.2-3.6 3.5-6.5 3.5"/>',
  hash: '<path d="M5 9h14M5 15h14M9.5 4l-2 16M16.5 4l-2 16"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/>',
  check: '<path d="M5 13l4 4L19 7"/>',
  alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17.5h.01"/>',
  xcircle: '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>',
  minus: '<path d="M6 12h12"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  lock: '<rect x="5" y="11" width="14" height="9.5" rx="2.5"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M19.1 4.9l-1.8 1.8M6.7 17.3l-1.8 1.8"/>',
  moon: '<path d="M20 13.5A8 8 0 1 1 10.5 4a6.3 6.3 0 0 0 9.5 9.5z"/>',
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
  memo: '<rect x="4" y="4" width="16" height="16" rx="2.5"/><path d="M8 9h8M8 13h6M8 17h4"/>',
  sprout: '<path d="M12 20v-7"/><path d="M12 13c-3.3 0-5.5-2-5.5-5 3.3 0 5.5 2 5.5 5z"/><path d="M12 11c0-2.8 2.2-5 5.5-5 0 2.8-2.2 5-5.5 5z"/>',
  download: '<path d="M12 4v10"/><path d="M8 10.5l4 4 4-4"/><path d="M5 19.5h14"/>',
  // ファイルツリー（書類を見る）用：フォルダ・展開シェブロン・ファイル。
  folder: '<path d="M4 7.5a2 2 0 0 1 2-2h3.3a2 2 0 0 1 1.4.6l1.1 1.1a2 2 0 0 0 1.4.6H18a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/>',
  chevron: '<path d="M9 6l6 6-6 6"/>',
  file: '<path d="M6.5 3.5H13l5 5V19a1.5 1.5 0 0 1-1.5 1.5h-10A1.5 1.5 0 0 1 5 19V5A1.5 1.5 0 0 1 6.5 3.5z"/><path d="M13 3.5V9h5"/>',
};
export function iconHTML(name, cls = "") {
  const path = ICONS[name] || ICONS.tool;
  return `<svg class="ic ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`;
}
// data-ic 属性付きプレースホルダを一括でアイコンに置換（静的HTML用・単一アイコン源を保つ）。
export function hydrateIcons(root = document) {
  root.querySelectorAll("[data-ic]").forEach((node) => {
    if (!node.dataset.icDone) {
      node.innerHTML = iconHTML(node.dataset.ic);
      node.dataset.icDone = "1";
    }
  });
}

/* ============================================================
   ツール → 保育士向けの「裏で何をしているか」＋アイコン
   ============================================================ */
const TOOL_META = {
  recall_child_history: { icon: "memory", label: "この子のこれまでの姿を確認" },
  search_guideline: { icon: "book", label: "保育所保育指針を参照" },
  // 文書作成指針は author/reviewer の InstructionProvider が prompt 冒頭へ前置注入する（read_policy ツールは撤去＝§5）。
  validate_fields: { icon: "shield", label: "必須項目を自己点検" },
  ask_caregiver: { icon: "ask", label: "保育士に確認" },
  // improver（指針を育てる）
  read_policy_cards: { icon: "clipboard", label: "いまの指針カードを確認" },
  propose_policy_card: { icon: "edit", label: "指針に足す案を作成" },
  commit_policy_card: { icon: "check", label: "指針に反映" },
};
export function toolMeta(name) {
  return TOOL_META[name] || { icon: "tool", label: name };
}

/* ============================================================
   エージェント名 → 役割（actor 色・アイコン）
   ============================================================ */
export function whoOf(author) {
  const a = (author || "").toLowerCase();
  if (a.includes("review")) return { label: "レビューAI", cls: "review", icon: "review" };
  // prep を author/monthly より先に判定する（monthly_prep が "monthly" に先取りされ
  // 作成AI に誤分類されるのを防ぐ。docflow drive() のステッパー routing と順序を一致させる）。
  // 保育経過記録の period_prep は「期間の集計」、要録の record_prep は「最終年度の集計」、月案の monthly_prep は「前月の集計」。
  if (a.includes("prep")) {
    if (a.includes("period")) return { label: "期間の集計", cls: "prep", icon: "chart" };
    if (a.includes("record")) return { label: "最終年度の集計", cls: "prep", icon: "chart" };
    return { label: "前月の集計", cls: "prep", icon: "chart" };
  }
  if (a.includes("author") || a.includes("monthly")) return { label: "作成AI", cls: "author", icon: "author" };
  if (a.includes("improv")) return { label: "改善エージェント", cls: "improver", icon: "refresh" };
  return { label: author || "AI", cls: "", icon: "robot" };
}

/* ============================================================
   状態チップ（idle/working/waiting/done/degraded/fail を語＋色＋アイコンで）
   ============================================================ */
const STATE = {
  working: { label: "処理中", icon: "spinner" },
  waiting: { label: "確認待ち", icon: "ask" },
  done: { label: "完了", icon: "check" },
  degraded: { label: "降格", icon: "alert" },
  fail: { label: "失敗", icon: "xcircle" },
};
export function stateChipHTML(state, label) {
  const s = STATE[state] || STATE.working;
  const lead = s.icon === "spinner" ? `<span class="spinner"></span>` : iconHTML(s.icon);
  return `<span class="schip ${state}">${lead}${esc(label || s.label)}</span>`;
}

/* ============================================================
   タイムライン部品
   ============================================================ */
// ツールバッジ（busy=スピナー付き。後で markToolDone で結果に差し替え）。
export function toolBadgeEl(name, { busy = true } = {}) {
  const m = toolMeta(name);
  const b = el("span", "tbadge" + (busy ? " busy" : ""));
  b.innerHTML = `${iconHTML(m.icon)}<span class="lbl">${esc(m.label)}</span>` + (busy ? `<span class="spinner"></span>` : "");
  return b;
}
export function markToolDone(badge, resultLabel) {
  if (!badge) return;
  badge.classList.remove("busy");
  const sp = badge.querySelector(".spinner");
  const res = `<span class="res">${iconHTML("check")}${esc(resultLabel || "完了")}</span>`;
  if (sp) sp.outerHTML = res;
  else badge.insertAdjacentHTML("beforeend", res);
}

/* ============================================================
   確定書類（書類パネル）
   ============================================================ */
function formatDocBody(formatted) {
  const lines = String(formatted || "")
    .split("\n")
    .map((ln) => (/対応する姿|対応する領域|└|10の姿|つの視点|5領域/.test(ln) ? `<span class="tagline">${esc(ln)}</span>` : esc(ln)))
    .join("\n");
  return `<pre>${lines}</pre>`;
}
// 書類パネルを作る。返り値の el._body に validation/承認バーを追記できる。
export function renderDocPanel({ titleIcon = "diary", title, stamp, labelHTML = "", formatted }) {
  const panel = el("div", "docp");
  panel.innerHTML =
    `<div class="docp-head"><span class="docp-title">${iconHTML(titleIcon)}${esc(title || "")}${labelHTML}</span>` +
    (stamp ? `<span class="docp-stamp">${esc(stamp)}</span>` : "") +
    `</div>`;
  const body = el("div", "docp-body", formatDocBody(formatted));
  panel.appendChild(body);
  panel._body = body;
  return panel;
}

export function banner(area, kind, text) {
  area.appendChild(el("div", "banner " + kind, `${iconHTML(kind === "err" ? "alert" : "info")}<span>${esc(text)}</span>`));
}

/* ============================================================
   計画ステッパー（観察メモ→情報収集→下書き→レビュー→確定 等）
   ============================================================ */
export function makeStepper(container, steps) {
  container.innerHTML = steps
    .map((s, i) => `<span class="stp" data-i="${i}"><span class="n">${i + 1}</span>${esc(s)}</span>`)
    .join("");
  function set(i, state) {
    const node = container.querySelector(`.stp[data-i="${i}"]`);
    if (!node) return;
    node.classList.remove("now", "done", "wait");
    if (state) node.classList.add(state);
    const n = node.querySelector(".n");
    n.innerHTML = state === "done" ? iconHTML("check") : String(i + 1);
  }
  return {
    set,
    // i 未満を done・i を now（state 指定可）にする。後退はしない。
    advanceTo(i, state = "now") {
      steps.forEach((_, k) => {
        if (k < i) set(k, "done");
        else if (k === i) set(k, state);
      });
    },
    allDone() {
      steps.forEach((_, k) => set(k, "done"));
    },
  };
}
