// 保育士 UI のブートストラップ：アイコン展開・テーマ・ステータスライン・パスコードゲート・タブ・各フローの配線。
import * as adk from "./adk.js";
import { el, esc, iconHTML, hydrateIcons } from "./ui.js";
import { makeDocFlow } from "./docflow.js";
import { makeImprover } from "./improver.js";

const CHILDREN = ["架空児A", "架空児B", "架空児C"];

const DIARY_SAMPLES = [
  "戸外で砂遊び。スコップで砂をすくって繰り返し感触を確かめていた。友だちが来ると場所を空けていた。",
  "室内で積み木。高く積もうと何度も挑戦。崩れても笑って積み直していた。保育者に「みて」と指さしで知らせた。",
  "午前のおやつで自分でコップを持って飲もうとした。少しこぼれたが満足そう。午睡はぐっすり。",
];

const IMPROVE_SAMPLES = [
  "感触遊びは『感触語＋そのときの表情』を併記したい。ただし断定的な評価表現は避けたい。",
  "保護者向けの一文は、できた事実だけでなく『次への意欲』が伝わる表現にしたい。",
];

function samplePrevEntries(childId) {
  return [24, 25, 26].map((day) => ({
    date: `2026-06-${day}`,
    age_band: "0-2",
    weather: "晴れ",
    attendance: [{ child_id: childId, present: true, reason: null }],
    practice_record: "園庭で感触遊びを行った。",
    individual_notes: [
      {
        child_id: childId,
        observed_state: `6月${day}日：砂をすくって感触を確かめ、笑顔が見られた`,
        tags: ["身近なものと関わり感性が育つ"],
      },
    ],
    evaluation: { child_focus: "感触に繰り返し関わっていた", self_review: "素材を十分用意できた" },
  }));
}

const $ = (id) => document.getElementById(id);

/* ============================================================
   テーマ（auto / light / dark・localStorage 保存）
   ============================================================ */
function effectiveTheme() {
  const t = document.documentElement.getAttribute("data-theme");
  if (t) return t;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function applyTheme(t) {
  const html = document.documentElement;
  if (t) html.setAttribute("data-theme", t);
  else html.removeAttribute("data-theme");
  const btn = $("theme-toggle");
  if (btn) btn.querySelector("span").innerHTML = iconHTML(effectiveTheme() === "dark" ? "sun" : "moon");
}
function setupTheme() {
  let saved = null;
  try {
    saved = localStorage.getItem("hoiku-theme");
  } catch {
    /* localStorage 不可でも動く */
  }
  applyTheme(saved);
  $("theme-toggle").onclick = () => {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    try {
      localStorage.setItem("hoiku-theme", next);
    } catch {
      /* noop */
    }
    applyTheme(next);
  };
}

/* ============================================================
   ステータスライン（ambient：モデル・対象児・進行・降格）
   ============================================================ */
let slEls = {};
function buildStatusline(cfg) {
  const sl = $("statusline");
  sl.innerHTML = "";
  const model = el("span", "sl-item", `<span class="dotc" style="background:var(--state-done)"></span><b>${esc(cfg.model || "Gemini")}</b>`);
  const subject = el("span", "sl-item hidden");
  const phase = el("span", "sl-item hidden");
  sl.append(model, subject, phase, el("span", "sl-sep"));
  connPart(sl, "指針RAG", cfg.rag_connected, "未接続");
  connPart(sl, "メモリ", cfg.memory_connected, "未接続・確認を厚めに");
  slEls = { dot: model.querySelector(".dotc"), subject, phase };
}
function connPart(sl, label, ok, deg) {
  if (ok) sl.append(el("span", "sl-item", `<span class="dotc" style="background:var(--state-done)"></span>${esc(label)}`));
  else sl.append(el("span", "chip-deg", `${iconHTML("alert")}${esc(label + " " + deg)}`));
}
const status = {
  setSubject(name) {
    if (!slEls.subject) return;
    if (!name) {
      slEls.subject.classList.add("hidden");
      return;
    }
    slEls.subject.classList.remove("hidden");
    slEls.subject.innerHTML = `${iconHTML("caregiver")}対象児 <b>${esc(name)}</b>`;
  },
  setPhase(text, state) {
    if (!slEls.phase) return;
    slEls.phase.classList.remove("hidden");
    const color = { working: "var(--state-working)", waiting: "var(--state-waiting)", done: "var(--state-done)" }[state] || "var(--muted)";
    const live = state === "working" ? " live" : "";
    slEls.phase.innerHTML = `<span class="dotc${live}" style="background:${color}"></span><span class="sl-phase">${esc(text)}</span>`;
    if (slEls.dot) slEls.dot.classList.toggle("live", state === "working");
  },
  clearPhase() {
    if (slEls.phase) slEls.phase.classList.add("hidden");
    if (slEls.dot) slEls.dot.classList.remove("live");
  },
};

/* ============================================================
   タブ・チップ・ゲート
   ============================================================ */
function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll(".tab").forEach((t) => {
        t.classList.remove("is-active");
        t.setAttribute("aria-selected", "false");
      });
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("is-active"));
      tab.classList.add("is-active");
      tab.setAttribute("aria-selected", "true");
      $("tab-" + tab.dataset.tab).classList.add("is-active");
      status.clearPhase();
    };
  });
}

// 選択式チップ群を作り、選択中の値を返すゲッターを提供。
function chipGroup(container, values, onPick, iconName) {
  let selected = values[0];
  container.innerHTML = "";
  values.forEach((v, i) => {
    const chip = el("button", "chip" + (i === 0 ? " is-active" : ""), (iconName ? iconHTML(iconName) : "") + esc(v));
    chip.type = "button";
    chip.onclick = () => {
      container.querySelectorAll(".chip").forEach((c) => c.classList.remove("is-active"));
      chip.classList.add("is-active");
      selected = v;
      onPick && onPick(v);
    };
    container.appendChild(chip);
  });
  return () => selected;
}

function sampleChips(container, samples, onPick) {
  container.innerHTML = "";
  samples.forEach((s, i) => {
    const chip = el("button", "chip", iconHTML("memo") + "例" + (i + 1));
    chip.type = "button";
    chip.title = s;
    chip.onclick = () => onPick(s);
    container.appendChild(chip);
  });
}

function setupGate(cfg) {
  const gate = $("gate");
  const bg = () => document.querySelectorAll("header.app-header, main.container, footer.app-footer");
  // モーダル表示中は背後を inert で不活性化（フォーカストラップ相当）＋入力欄へフォーカス。
  const show = () => {
    gate.classList.remove("hidden");
    bg().forEach((n) => n.setAttribute("inert", ""));
    requestAnimationFrame(() => $("gate-input").focus());
  };
  const dismiss = () => {
    gate.classList.add("hidden");
    bg().forEach((n) => n.removeAttribute("inert"));
  };
  window.__requireGate = show;
  if (cfg.passcode_required) show();
  $("gate-submit").onclick = async () => {
    const ok = await adk.gate($("gate-input").value);
    if (ok) {
      dismiss();
      $("gate-error").classList.add("hidden");
    } else {
      $("gate-error").classList.remove("hidden");
    }
  };
  $("gate-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("gate-submit").click();
  });
}

/* ============================================================
   起動
   ============================================================ */
async function main() {
  hydrateIcons();
  setupTheme();
  setupTabs();

  let cfg;
  try {
    cfg = await adk.loadConfig();
  } catch {
    $("statusline").textContent = "設定の読込に失敗";
    return;
  }
  buildStatusline(cfg);
  setupGate(cfg);

  // ── 日誌 ──
  const diaryChild = chipGroup($("diary-children"), CHILDREN, null, "caregiver");
  sampleChips($("diary-samples"), DIARY_SAMPLES, (s) => ($("diary-memo").value = s));
  const diaryFlow = makeDocFlow({
    area: $("diary-flow"),
    button: $("diary-run"),
    stepper: $("diary-stepper"),
    steps: ["観察メモ", "情報を集める", "下書き", "レビュー", "確定"],
    showDigest: false,
    kind: "diary",
    status,
  });
  $("diary-run").onclick = () => {
    const memo = $("diary-memo").value.trim();
    if (!memo) {
      $("diary-memo").focus();
      return;
    }
    const child = diaryChild();
    status.setSubject(child);
    const text = `対象児: ${child}\n本日の観察メモ:\n${memo}`;
    diaryFlow.run(null, text);
  };

  // ── 月案 ──
  const monthlyChild = chipGroup($("monthly-children"), CHILDREN, () => updateSeedCount(), "caregiver");
  const updateSeedCount = () => ($("monthly-seed-count").textContent = samplePrevEntries(monthlyChild()).length + " 件");
  updateSeedCount();
  const monthlyFlow = makeDocFlow({
    area: $("monthly-flow"),
    button: $("monthly-run"),
    stepper: $("monthly-stepper"),
    steps: ["前月の集計", "情報を集める", "下書き", "レビュー", "確定"],
    showDigest: true,
    kind: "monthly",
    status,
  });
  $("monthly-run").onclick = () => {
    const child = monthlyChild();
    const month = $("monthly-month").value || "2026-07";
    status.setSubject(child);
    const seed = { doc_type: "月案", prev_month_entries: samplePrevEntries(child) };
    monthlyFlow.run(seed, `${month} の ${child} の個別月案を作成してください。`);
  };

  // ── 回す ──
  sampleChips($("improve-samples"), IMPROVE_SAMPLES, (s) => ($("improve-diff").value = s));
  const improver = makeImprover({ button: $("improve-run"), log: $("improve-log"), status });
  await improver.init();
  $("improve-run").onclick = () => {
    const diff = $("improve-diff").value.trim();
    if (!diff) {
      $("improve-diff").focus();
      return;
    }
    improver.run(diff, null);
  };
}

main();
