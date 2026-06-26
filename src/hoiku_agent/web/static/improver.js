// 「回す」ダッシュボード：improver（二階）を /api/improve で SSE 駆動し、回す全体を可視化する。
// 提案 diff → 競合二択(HITL) → 評価ゲート3軸 → PR の中間生成物をパネルに描く（審査点②）。

import * as adk from "./adk.js";
import { el, esc, clear, toolLabel, whoOf, pushStep, banner } from "./ui.js";

const AXIS_LABEL = {
  axis_guideline_alignment: "指針整合",
  axis_ten_no_sugata: "10の姿",
  axis_expression: "保護者向け表現",
};

export function makeImprover({ button, log, panels }) {
  let baseline = null;

  async function init() {
    baseline = await adk.getBaseline();
    if (baseline && typeof baseline.mean === "number") {
      panels.eval.classList.remove("placeholder");
      panels.eval.innerHTML =
        `<div class="muted" style="font-size:12px">main 基準（committed baseline）</div>` +
        barsHtml(baseline.axis_means) +
        `<div class="diff-meta">mean ${fmt(baseline.mean)}・must_fix ${baseline.must_fix_violations ?? 0}</div>`;
    }
  }

  function resetPanels() {
    for (const k of ["propose", "conflict", "pr"]) {
      panels[k].classList.add("placeholder");
    }
    panels.propose.textContent = "提案を待っています…";
    panels.conflict.textContent = "競合チェック中…";
    panels.pr.textContent = "起票を待っています…";
  }

  function handleItem(item) {
    if (item.type === "text" && (item.text || "").trim()) {
      const who = whoOf(item.author || "improver");
      pushStep(log, { ico: "🔄", who: "改善エージェント", text: item.text });
    } else if (item.type === "tool_call") {
      pushStep(log, { text: toolLabel(item.name), tool: true });
    } else if (item.type === "tool_result") {
      routeResult(item.name, item.result);
    } else if (item.type === "needs_input") {
      renderConflictChoice(item);
    } else if (item.type === "error") {
      banner(log, "err", "降格: " + item.detail + "（LLM 資格情報やネット未設定の可能性）");
      button.disabled = false;
    } else if (item.type === "done") {
      if (item.policy_change) pushStep(log, { ico: "✅", who: "改善エージェント", text: item.policy_change });
      button.disabled = false;
    }
  }

  function routeResult(name, result) {
    if (!result || typeof result !== "object") return;
    if (name === "propose_policy_change") renderPropose(result);
    else if (name === "run_eval") renderEval(result);
    else if (name === "open_pr") renderPr(result);
  }

  function renderPropose(r) {
    const edit = r.edit || {};
    panels.propose.classList.remove("placeholder");
    panels.propose.innerHTML =
      `<div class="diff-meta">見出し: <b>${esc(edit.target_heading || "—")}</b>（${esc(edit.op || "add")}）</div>` +
      `<div class="diff-after">${esc(edit.after || "")}</div>` +
      (edit.rationale ? `<div class="diff-meta">理由: ${esc(edit.rationale)}</div>` : "");

    panels.conflict.classList.remove("placeholder");
    if (r.has_conflict && (r.conflicts || []).length) {
      panels.conflict.innerHTML =
        `<div class="conflict-yes">⚠ 競合あり（${r.conflicts.length}件）</div>` +
        r.conflicts.map((c) => `<div class="diff-before">${esc(c)}</div>`).join("") +
        `<div class="diff-meta">保育士が正を選ぶまで取り込みません。</div>`;
    } else {
      panels.conflict.innerHTML = `<div class="conflict-none">✓ 競合なし</div><div class="diff-meta">そのまま評価ゲートへ。</div>`;
    }
  }

  function renderEval(r) {
    panels.eval.classList.remove("placeholder");
    const axis = r.axis_means || {};
    const verdict =
      r.passed === true
        ? `<span class="gate-verdict pass">緑（取り込み可）</span>`
        : r.passed === false
          ? `<span class="gate-verdict fail">赤（取り込み不可）</span>`
          : `<span class="gate-verdict none">main 基準を表示（実採点は CI）</span>`;
    const cmp =
      typeof r.mean === "number"
        ? `<div class="diff-meta">今回 mean ${fmt(r.mean)}${
            typeof r.baseline_mean === "number" ? `／ main 基準 ${fmt(r.baseline_mean)}` : ""
          }・must_fix ${r.must_fix_violations ?? 0}</div>`
        : `<div class="diff-meta">配信器では採点を回さず main 基準（committed baseline）を表示。実採点は CI 評価ゲート（nightly/PR）が 3軸で実施し、main 比 非劣化＆must_fix 0 のみ取り込み${
            baseline && typeof baseline.mean === "number" ? `／main mean ${fmt(baseline.mean)}` : ""
          }。</div>`;
    panels.eval.innerHTML = barsHtml(typeof r.mean === "number" ? axis : baseline && baseline.axis_means) + cmp + verdict;
  }

  function renderPr(r) {
    panels.pr.classList.remove("placeholder");
    const status = r.status || "—";
    const rows = [];
    rows.push(`<div class="pr-row">状態: <b>${esc(status)}</b>${status === "dry_run" ? "（実 PR なし・安全側）" : ""}</div>`);
    if (r.branch) rows.push(`<div class="pr-row">branch: <code>${esc(r.branch)}</code></div>`);
    if (r.title) rows.push(`<div class="pr-row">title: ${esc(r.title)}</div>`);
    if (r.pr_url) rows.push(`<div class="pr-row">PR: <a href="${esc(r.pr_url)}" target="_blank" rel="noopener">${esc(r.pr_url)}</a></div>`);
    if (r.preview) rows.push(`<div class="diff-before">${esc(typeof r.preview === "string" ? r.preview : JSON.stringify(r.preview))}</div>`);
    if (r.detail) rows.push(`<div class="diff-meta">${esc(r.detail)}</div>`);
    panels.pr.innerHTML = rows.join("");
  }

  function renderConflictChoice(item) {
    panels.conflict.classList.remove("placeholder");
    const wrap = el("div");
    wrap.appendChild(el("div", "conflict-yes", "🙋 " + (item.question || "どちらを正としますか？")));
    const actions = el("div", "ask-actions");
    const choices = item.choices && item.choices.length ? item.choices : ["既存を残す", "新しい案にする"];
    for (const c of choices) {
      const b = el("button", "btn btn-ghost", esc(c));
      b.onclick = async () => {
        wrap.remove();
        panels.conflict.innerHTML = `<div class="diff-meta">保育士の判断: <b>${esc(c)}</b> → 再開中…</div>`;
        await adk.ssePost(
          "/api/improve/resume",
          { session_id: item.session_id, function_call_id: item.function_call_id, answer: c },
          handleItem,
        );
      };
      actions.appendChild(b);
    }
    wrap.appendChild(actions);
    panels.conflict.innerHTML = "";
    panels.conflict.appendChild(wrap);
  }

  async function run(diff, feedback) {
    clear(log);
    resetPanels();
    button.disabled = true;
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
        return (
          `<div class="bar-row"><span>${AXIS_LABEL[k]}</span>` +
          `<span class="bar-track"><span class="bar-fill" style="width:${pct}%"></span></span>` +
          `<span>${typeof v === "number" ? v.toFixed(2) : "—"}</span></div>`
        );
      })
      .join("") +
    `</div>`
  );
}
