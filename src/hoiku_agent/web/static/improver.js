// 「回す」コンソール：improver（二階）を /api/improve で SSE 駆動し、回す全体をパイプラインで可視化する。
// 提案 → 競合二択(HITL) → 評価ゲート3軸（main 比） → PR を、左から点灯する横帯＋コンソール面に描く（審査点②）。

import * as adk from "./adk.js";
import { el, esc, clear, iconHTML, toolBadgeEl, banner } from "./ui.js";

const AXIS_LABEL = {
  axis_guideline_alignment: "指針整合",
  axis_ten_no_sugata: "10の姿",
  axis_expression: "保護者向け表現",
};

const PIPE = [
  { id: "propose", title: "① 提案", icon: "edit" },
  { id: "conflict", title: "② 競合チェック", icon: "shield" },
  { id: "eval", title: "③ 評価ゲート", icon: "gauge" },
  { id: "pr", title: "④ PR", icon: "git" },
];

export function makeImprover({ button, log, status }) {
  let baseline = null;
  const pipe = document.getElementById("improve-pipe");

  /* ---- パイプライン ---- */
  function renderPipe() {
    pipe.innerHTML = PIPE.map(
      (s) =>
        `<div class="pstep" id="step-${s.id}"><div class="pt">${iconHTML(s.icon)}${esc(s.title)}</div>` +
        `<div class="pv">待機</div><span class="cschip idle">${iconHTML("minus")}—</span></div>`,
    ).join("");
  }
  function setStep(id, { state, value, chipLabel } = {}) {
    const node = document.getElementById("step-" + id);
    if (!node) return;
    node.classList.remove("on", "pass", "fail");
    if (state === "working") node.classList.add("on");
    else if (state === "pass") node.classList.add("pass");
    else if (state === "fail") node.classList.add("fail");
    if (value != null) node.querySelector(".pv").textContent = value;
    const map = {
      working: ["working", "spinner", "処理中"],
      pass: ["pass", "check", "OK"],
      fail: ["fail", "xcircle", "NG"],
      pending: ["pending", "clock", "保留"],
      idle: ["idle", "minus", "—"],
    };
    const [cls, ic, lbl] = map[state] || map.idle;
    const chip = node.querySelector(".cschip");
    chip.className = "cschip " + cls;
    chip.innerHTML = (ic === "spinner" ? `<span class="spinner"></span>` : iconHTML(ic)) + esc(chipLabel || lbl);
  }

  /* ---- コンソール面 ---- */
  function setPane(id, html) {
    const n = document.getElementById(id);
    n.classList.remove("console-empty");
    n.innerHTML = html;
    return n;
  }
  function paneEmpty(id, text) {
    const n = document.getElementById(id);
    n.className = "console-empty";
    n.textContent = text;
  }

  /* ---- ログ（actor lane＝改善エージェント） ---- */
  function logTurn(text) {
    const turn = el("div", "turn");
    turn.innerHTML =
      `<div class="turn-lane improver"></div>` +
      `<div class="turn-body"><div class="turn-who improver">${iconHTML("refresh")}改善エージェント</div><div class="turn-text">${esc(text)}</div></div>`;
    log.appendChild(turn);
    turn.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  function logDone(text) {
    const turn = el("div", "turn");
    turn.innerHTML =
      `<div class="turn-lane improver"></div>` +
      `<div class="turn-body"><div class="turn-who improver">${iconHTML("check")}取り込み判断</div><div class="turn-text">${esc(text)}</div></div>`;
    log.appendChild(turn);
    turn.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  function logTool(name) {
    const turn = el("div", "turn");
    turn.innerHTML = `<div class="turn-lane improver"></div><div class="turn-body"><div class="tools-row"></div></div>`;
    turn.querySelector(".tools-row").appendChild(toolBadgeEl(name, { busy: false }));
    log.appendChild(turn);
    turn.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  /* ---- baseline ---- */
  function showBaseline() {
    if (baseline && typeof baseline.mean === "number") {
      setPane(
        "pane-eval",
        `<div class="gate-meta">main 基準（committed baseline）</div>` +
          barsHtml(baseline.axis_means) +
          `<div class="gate-meta">mean ${fmt(baseline.mean)}・must_fix ${baseline.must_fix_violations ?? 0}</div>`,
      );
    } else {
      paneEmpty("pane-eval", "指針整合・10の姿・保護者向け表現の3軸で採点。main 比で非劣化かつ must_fix 0 なら緑。");
    }
  }

  async function init() {
    baseline = await adk.getBaseline();
    renderPipe();
    showBaseline();
  }

  function resetPanels() {
    renderPipe();
    paneEmpty("pane-flow", "修正差分から、どの見出しに何を足すかを提案します。競合があれば保育士が正を選びます。");
    paneEmpty("pane-pr", "緑なら PR を起票（既定 dry_run）。採否は CI 評価ゲートが決めます。");
    showBaseline();
  }

  /* ---- SSE イベント ---- */
  function handleItem(item) {
    if (item.type === "text" && (item.text || "").trim()) {
      logTurn(item.text);
    } else if (item.type === "tool_call") {
      logTool(item.name);
      if (item.name === "propose_policy_change") {
        setStep("propose", { state: "working", value: "提案を作成中…" });
        status.setPhase("指針の更新を提案しています", "working");
      } else if (item.name === "run_eval") {
        setStep("eval", { state: "working", value: "採点中…" });
        status.setPhase("評価ゲートで採点しています", "working");
      } else if (item.name === "open_pr") {
        setStep("pr", { state: "working", value: "起票中…" });
        status.setPhase("PR を起票しています", "working");
      }
    } else if (item.type === "tool_result") {
      routeResult(item.name, item.result);
    } else if (item.type === "needs_input") {
      renderConflictChoice(item);
    } else if (item.type === "error") {
      // 進行中のステップのスピナーを止める（採点中のまま見えて「降格の正直さ」を損なわないように）。
      for (const s of PIPE) {
        const n = document.getElementById("step-" + s.id);
        if (n && n.classList.contains("on")) setStep(s.id, { state: "pending", value: "降格" });
      }
      banner(log, "err", "降格: " + item.detail + "（LLM 資格情報やネット未設定の可能性）");
      status.setPhase("降格しました", "waiting");
      button.disabled = false;
    } else if (item.type === "done") {
      if (item.policy_change) logDone(item.policy_change);
      status.setPhase("回し終えました", "done");
      button.disabled = false;
    }
  }

  function routeResult(name, result) {
    if (!result || typeof result !== "object") return;
    if (name === "propose_policy_change") renderPropose(result);
    else if (name === "run_eval") renderEval(result);
    else if (name === "open_pr") renderPr(result);
  }

  function renderDiff(e) {
    const anchor = `<div class="diff-anchor">${iconHTML("hash")}文書作成指針.md ／ <code>${esc(e.target_heading || "—")}</code>（${esc(e.op || "add")}）</div>`;
    const rmLines = e.before ? String(e.before).split("\n").filter((x) => x.trim().length) : [];
    const addLines = String(e.after || "").split("\n");
    const rows =
      rmLines.map((l) => `<div class="dl rm"><span class="gut">−</span><span class="txt">${esc(l)}</span></div>`).join("") +
      addLines.map((l) => `<div class="dl add"><span class="gut">+</span><span>${esc(l)}</span></div>`).join("");
    const rat = e.rationale ? `<div class="gate-meta">理由: ${esc(e.rationale)}</div>` : "";
    return anchor + `<div class="diff">${rows}</div>` + rat;
  }

  function renderPropose(r) {
    const e = r.edit || {};
    setStep("propose", { state: "pass", value: esc(e.target_heading || e.op || "提案") });
    let html = renderDiff(e);
    if (r.has_conflict && (r.conflicts || []).length) {
      setStep("conflict", { state: "pending", value: `競合 ${r.conflicts.length}件`, chipLabel: "要判断" });
      html +=
        `<div class="gate-meta">既存と競合（${r.conflicts.length}件）。保育士が正を選ぶまで取り込みません。</div>` +
        `<div class="diff" style="margin-top:6px">` +
        r.conflicts.map((c) => `<div class="dl rm"><span class="gut">既存</span><span class="txt">${esc(c)}</span></div>`).join("") +
        `</div>`;
    } else {
      setStep("conflict", { state: "pass", value: "競合なし" });
    }
    setPane("pane-flow", html);
  }

  function renderEval(r) {
    const hasScore = typeof r.mean === "number";
    const axis = hasScore ? r.axis_means || {} : baseline && baseline.axis_means;
    const verdictCls = r.passed === true ? "pass" : r.passed === false ? "fail" : "none";
    const verdictIcon = r.passed === true ? "check" : r.passed === false ? "xcircle" : "info";
    const verdictLabel =
      r.passed === true ? "緑（取り込み可）" : r.passed === false ? "赤（取り込み不可）" : "main 基準を表示（実採点は CI）";
    const cmp = hasScore
      ? `<div class="gate-meta">今回 mean ${fmt(r.mean)}${
          typeof r.baseline_mean === "number" ? ` ／ main 基準 ${fmt(r.baseline_mean)}` : ""
        }・must_fix ${r.must_fix_violations ?? 0}</div>`
      : `<div class="gate-meta">配信器では採点を回さず main 基準（committed baseline）を表示。実採点は CI 評価ゲート（nightly/PR）が3軸で実施し、main 比 非劣化＆must_fix 0 のみ取り込み${
          baseline && typeof baseline.mean === "number" ? ` ／ main mean ${fmt(baseline.mean)}` : ""
        }。</div>`;
    setPane("pane-eval", barsHtml(axis) + cmp + `<span class="gate-verdict ${verdictCls}">${iconHTML(verdictIcon)}${verdictLabel}</span>`);
    setStep("eval", {
      state: r.passed === true ? "pass" : r.passed === false ? "fail" : "pending",
      value: r.passed === true ? "非劣化OK" : r.passed === false ? "must_fix違反" : "main 基準",
      chipLabel: r.passed == null ? "CIで採点" : undefined,
    });
  }

  function renderPr(r) {
    const status_ = r.status || "—";
    // 成否を色に正直に反映（非成功 status で偽の緑を出さない）。
    const st = String(status_).toLowerCase();
    const ok = st === "dry_run" || st.includes("open") || st.includes("creat") || st.includes("success");
    const bad = st.includes("error") || st.includes("fail");
    setStep("pr", { state: ok ? "pass" : bad ? "fail" : "pending", value: esc(status_) });
    const rows = [];
    rows.push(
      `<div class="pr-row"><span class="k">状態</span> <b>${esc(status_)}</b>${status_ === "dry_run" ? "（実 PR なし・安全側）" : ""}</div>`,
    );
    if (r.branch) rows.push(`<div class="pr-row"><span class="k">branch</span> <code>${esc(r.branch)}</code></div>`);
    if (r.title) rows.push(`<div class="pr-row"><span class="k">title</span> ${esc(r.title)}</div>`);
    // http(s) のみリンク化（javascript: 等のスキーム混入に対する深層防御）。
    if (r.pr_url && /^https?:\/\//i.test(r.pr_url))
      rows.push(`<div class="pr-row"><span class="k">PR</span> <a href="${esc(r.pr_url)}" target="_blank" rel="noopener">${esc(r.pr_url)}</a></div>`);
    else if (r.pr_url) rows.push(`<div class="pr-row"><span class="k">PR</span> ${esc(r.pr_url)}</div>`);
    if (r.preview)
      rows.push(`<div class="diff" style="margin-top:6px"><div class="dl ctx">${esc(typeof r.preview === "string" ? r.preview : JSON.stringify(r.preview))}</div></div>`);
    if (r.detail) rows.push(`<div class="gate-meta">${esc(r.detail)}</div>`);
    setPane("pane-pr", rows.join(""));
  }

  function renderConflictChoice(item) {
    setStep("conflict", { state: "pending", value: "保育士の判断待ち", chipLabel: "要判断" });
    status.setPhase("競合の判断をお待ちしています", "waiting");
    const wrap = el("div", "cask");
    wrap.innerHTML = `<div class="cq">${iconHTML("ask")}<span>${esc(item.question || "どちらを正としますか？")}</span></div>`;
    const actions = el("div", "cask-actions");
    const choices = item.choices && item.choices.length ? item.choices : ["既存を残す", "新しい案にする"];
    for (const c of choices) {
      const b = el("button", "cbtn", esc(c));
      b.type = "button";
      b.onclick = async () => {
        wrap.innerHTML = `<div class="gate-meta">保育士の判断: <b>${esc(c)}</b> → 再開中…</div>`;
        setStep("conflict", { state: "working", value: "再開中…" });
        status.setPhase("判断を受けて再開しています", "working");
        await adk.ssePost(
          "/api/improve/resume",
          { session_id: item.session_id, function_call_id: item.function_call_id, answer: c },
          handleItem,
        );
      };
      actions.appendChild(b);
    }
    wrap.appendChild(actions);
    const pane = document.getElementById("pane-flow");
    pane.classList.remove("console-empty");
    pane.appendChild(wrap);
    wrap.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function run(diff, feedback) {
    clear(log);
    resetPanels();
    button.disabled = true;
    status.setSubject(null);
    status.setPhase("回しはじめています", "working");
    const sid = (crypto.randomUUID && crypto.randomUUID()) || "imp-" + Date.now();
    try {
      await adk.ssePost("/api/improve", { diff, feedback: feedback || null, session_id: sid }, handleItem);
    } catch (e) {
      if (e instanceof adk.PasscodeError) {
        window.__requireGate && window.__requireGate();
        banner(log, "info", "パスコードを入力してから、もう一度お試しください。");
      } else {
        banner(log, "err", "エラー: " + e.message);
      }
      status.clearPhase();
      button.disabled = false;
    }
  }

  return { init, run };
}

function fmt(x) {
  return typeof x === "number" ? x.toFixed(3) : "—";
}
function barsHtml(axisMeans) {
  if (!axisMeans) return "";
  return (
    `<div class="bars">` +
    Object.keys(AXIS_LABEL)
      .map((k) => {
        const v = axisMeans[k];
        const pct = typeof v === "number" ? Math.round(v * 100) : 0;
        const cls = typeof v === "number" ? (v >= 0.8 ? "pass" : v >= 0.6 ? "warn" : "fail") : "warn";
        return (
          `<div class="bar-row"><span>${AXIS_LABEL[k]}</span>` +
          `<span class="bar-track"><span class="bar-fill ${cls}" style="width:${pct}%"></span></span>` +
          `<span class="bar-val">${typeof v === "number" ? v.toFixed(2) : "—"}</span></div>`
        );
      })
      .join("") +
    `</div>`
  );
}
