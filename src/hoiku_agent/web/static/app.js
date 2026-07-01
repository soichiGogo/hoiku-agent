// 保育士 UI のブートストラップ：アイコン展開・テーマ・ステータスライン・パスコードゲート・タブ・各フローの配線。
import * as adk from "./adk.js";
import { el, esc, iconHTML, hydrateIcons } from "./ui.js";
import { makeDocFlow } from "./docflow.js";
import { makePolicy } from "./policy.js";

// 対象児は実在しない仮名（下の名前＋ちゃん/くん）＝現場の日誌の書き方に寄せる（§14・実名は扱わない）。
const CHILDREN = ["はるとくん", "ゆいちゃん", "そうたくん"];

// サンプルメモは当日の生活情報（食事量・午睡時刻・排泄回数・体温・月齢）を含める＝生成される日誌の
// 生活記録（食事/睡眠/排泄/機嫌・体調）が現場同様に埋まる（手がかりが無い欄は空のまま＝§14・作成AIは創作しない）。
const DIARY_SAMPLES = [
  "戸外で砂遊び。スコップで砂をすくって繰り返し感触を確かめていた。友だちが来ると場所を空けていた。離乳食完了期を8割、麦茶80ml。午睡12:15〜14:20。排尿4回・排便1回。視診で体温36.5℃、機嫌よし。1歳3か月。",
  "室内で積み木。高く積もうと何度も挑戦。崩れても笑って積み直していた。保育者に「みて」と指さしで知らせた。給食を9割、汁物も完食。午睡12:30〜14:10。排尿5回・排便なし。体温36.7℃、鼻水が少しあるが機嫌はよい。1歳6か月。",
  "午前のおやつで自分でコップを持って飲もうとした。少しこぼれたが満足そう。給食は完了期を全量摂取。午睡12:00〜14:00でぐっすり。排尿4回・排便1回。体温36.6℃、変化なし。0歳11か月。",
];

const POLICY_SAMPLES = [
  "感触遊びは『感触語＋そのときの表情』を併記したい。ただし断定的な評価表現は避けたい。",
  "保護者向けの一文は、できた事実だけでなく『次への意欲』が伝わる表現にしたい。",
];

// 前月日誌の仮名サンプル（L2 還流のデモ seed）。現場に即した複数日（感触遊び/歩行/絵本）＝月齢・
// 数量化した生活記録・具体的な姿。scripts/run_monthly.py の _sample_prev_entries と同趣旨（§14）。
function samplePrevEntries(childId) {
  const days = [
    {
      date: "2026-06-24",
      weather: "晴れ",
      practice_record: "園庭の砂場で感触遊びを行った。",
      observed_state: "砂場でスコップに砂をすくっては空ける動作を繰り返し、こぼれる様子をじっと見つめた",
      tags: ["身近なものと関わり感性が育つ"],
      meal: "完了期の給食を8割摂取、麦茶80ml",
      sleep: "12:15〜14:20 午睡",
      toilet: "排尿4回・排便1回",
      mood_health: "視診で体温36.5℃、機嫌よく変化なし",
      child_focus: "素材の感触に繰り返し関わっていた",
      self_review: "スコップやカップを人数分用意できた",
    },
    {
      date: "2026-06-26",
      weather: "くもり",
      practice_record: "室内で歩行や移動を促す環境を整えた。",
      observed_state: "両手を広げてバランスを取りながら数歩歩き、保育者のもとへ進もうとした",
      tags: ["健やかに伸び伸びと育つ"],
      meal: "完了期の給食を9割摂取",
      sleep: "12:20〜14:30 ぐっすり午睡",
      toilet: "排尿5回・排便1回",
      mood_health: "視診で体温36.6℃、活発で気になる点なし",
      child_focus: "自分から体を動かそうとする意欲が高まっていた",
      self_review: "転倒に備えマットと広い動線を用意できた",
    },
    {
      date: "2026-06-30",
      weather: "晴れ",
      practice_record: "少人数で絵本を読み、指さしや発声に応じた。",
      observed_state: "絵本の動物を指さして声を出し、保育者に見せようとした",
      tags: ["身近な人と気持ちが通じ合う"],
      meal: "完了期の給食を全量摂取、麦茶90ml",
      sleep: "12:15〜14:10 午睡",
      toilet: "排尿4回・排便1回",
      mood_health: "視診で体温36.6℃、機嫌よく変化なし",
      child_focus: "好きなものを見つけ、伝えたい気持ちが育っていた",
      self_review: "発見に共感的に応答し、繰り返しを楽しめるようにした",
    },
  ];
  return days.map((d) => ({
    date: d.date,
    age_band: "0-2",
    weather: d.weather,
    attendance: [{ child_id: childId, present: true, reason: null }],
    practice_record: d.practice_record,
    individual_notes: [
      {
        child_id: childId,
        age_months: "1歳3か月",
        observed_state: d.observed_state,
        tags: d.tags,
        life_record: { meal: d.meal, sleep: d.sleep, toilet: d.toilet, mood_health: d.mood_health },
      },
    ],
    evaluation: { child_focus: d.child_focus, self_review: d.self_review },
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
function buildStatusline() {
  const sl = $("statusline");
  sl.innerHTML = "";
  const subject = el("span", "sl-item hidden");
  const phase = el("span", "sl-item hidden");
  sl.append(subject, phase);
  slEls = { dot: null, subject, phase };
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
  buildStatusline();
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

  // ── 指針を育てる ──
  sampleChips($("policy-samples"), POLICY_SAMPLES, (s) => ($("policy-memo").value = s));
  const policy = makePolicy({
    grid: $("policy-grid"),
    history: $("policy-history"),
    flow: $("policy-flow"),
    button: $("policy-run"),
    stepper: $("policy-stepper"),
    status,
  });
  await policy.init();
  $("policy-run").onclick = () => {
    const memo = $("policy-memo").value.trim();
    if (!memo) {
      $("policy-memo").focus();
      return;
    }
    status.setSubject(null);
    policy.run(memo);
  };
}

main();
