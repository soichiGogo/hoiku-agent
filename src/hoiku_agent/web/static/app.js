// 保育士 UI のブートストラップ：設定・接続表示・パスコードゲート・タブ・各フローの配線。
import * as adk from "./adk.js";
import { el } from "./ui.js";
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

function renderConn(cfg) {
  const c = $("conn");
  c.innerHTML = "";
  c.appendChild(el("span", "dot on", "🤖 " + (cfg.model || "Gemini")));
  c.appendChild(el("span", "dot " + (cfg.memory_connected ? "on" : "off"), (cfg.memory_connected ? "🧠 メモリ接続" : "🧠 メモリ未接続")));
  c.appendChild(el("span", "dot " + (cfg.rag_connected ? "on" : "off"), (cfg.rag_connected ? "📚 指針RAG接続" : "📚 指針RAG未接続")));
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("is-active"));
      document.querySelectorAll(".panel").forEach((p) => p.classList.remove("is-active"));
      tab.classList.add("is-active");
      $("tab-" + tab.dataset.tab).classList.add("is-active");
    };
  });
}

// 選択式チップ群を作り、選択中の値を返すゲッターを提供。
function chipGroup(container, values, onPick) {
  let selected = values[0];
  container.innerHTML = "";
  values.forEach((v, i) => {
    const chip = el("button", "chip" + (i === 0 ? " is-active" : ""), v);
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
    const chip = el("button", "chip", "例" + (i + 1));
    chip.title = s;
    chip.onclick = () => onPick(s);
    container.appendChild(chip);
  });
}

function setupGate(cfg) {
  const gate = $("gate");
  const show = () => gate.classList.remove("hidden");
  window.__requireGate = show;
  if (cfg.passcode_required) show();
  $("gate-submit").onclick = async () => {
    const ok = await adk.gate($("gate-input").value);
    if (ok) {
      gate.classList.add("hidden");
      $("gate-error").classList.add("hidden");
    } else {
      $("gate-error").classList.remove("hidden");
    }
  };
  $("gate-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") $("gate-submit").click();
  });
}

async function main() {
  setupTabs();
  let cfg;
  try {
    cfg = await adk.loadConfig();
  } catch (e) {
    $("conn").textContent = "設定の読込に失敗";
    return;
  }
  renderConn(cfg);
  setupGate(cfg);

  // ── 日誌 ──
  const diaryChild = chipGroup($("diary-children"), CHILDREN);
  sampleChips($("diary-samples"), DIARY_SAMPLES, (s) => ($("diary-memo").value = s));
  const diaryFlow = makeDocFlow({ area: $("diary-flow"), button: $("diary-run"), showDigest: false });
  $("diary-run").onclick = () => {
    const memo = $("diary-memo").value.trim();
    if (!memo) {
      $("diary-memo").focus();
      return;
    }
    const text = `対象児: ${diaryChild()}\n本日の観察メモ:\n${memo}`;
    diaryFlow.run(null, text);
  };

  // ── 月案 ──
  const monthlyChild = chipGroup($("monthly-children"), CHILDREN, () => updateSeedCount());
  const updateSeedCount = () => ($("monthly-seed-count").textContent = samplePrevEntries(monthlyChild()).length + " 件");
  updateSeedCount();
  const monthlyFlow = makeDocFlow({ area: $("monthly-flow"), button: $("monthly-run"), showDigest: true });
  $("monthly-run").onclick = () => {
    const child = monthlyChild();
    const month = $("monthly-month").value || "2026-07";
    const seed = { doc_type: "月案", prev_month_entries: samplePrevEntries(child) };
    monthlyFlow.run(seed, `${month} の ${child} の個別月案を作成してください。`);
  };

  // ── 回す ──
  sampleChips($("improve-samples"), IMPROVE_SAMPLES, (s) => ($("improve-diff").value = s));
  const improver = makeImprover({
    button: $("improve-run"),
    log: $("improve-log"),
    panels: { propose: $("dash-propose"), conflict: $("dash-conflict"), eval: $("dash-eval"), pr: $("dash-pr") },
  });
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
