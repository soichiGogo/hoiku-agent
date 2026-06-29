// 日誌/月案で共通の作成フロー（前月集計→収集→下書き→HITL→レビュー→確定→承認）。
// 生成は ADK /run_sse を直接駆動（自前 Runner は組まない＝§9）。harness/agents は不変。
// 「働いている実質」は計画ステッパー＋ステータスラインで示し、作成AI/レビューAI/ツールの細かな
// やりとりは既定で畳む（<details class="proc">）。保育士が前面で確認するのは「不足の確認（HITL）」と
// 「最終下書き＋不足内容」だけにする（過程は経過として開けば見られる）。

import * as adk from "./adk.js";
import { el, esc, clear, iconHTML, toolMeta, whoOf, toolBadgeEl, markToolDone, renderDocPanel, makeStepper, banner } from "./ui.js";

const DOC_META = {
  diary: { title: "保育日誌", icon: "diary" },
  monthly: { title: "個別月案", icon: "calendar" },
};

export function makeDocFlow({ area, button, stepper: stepperEl, steps, showDigest, kind, status }) {
  const iPrep = steps.indexOf("前月の集計");
  const iColl = steps.indexOf("情報を集める");
  const iDraft = steps.indexOf("下書き");
  const iReview = steps.indexOf("レビュー");

  let stepper = null;
  let maxStep = -1;
  let cur = null; // 直近の actor turn（連続イベントを同じ turn にまとめる）
  let toolBadges = {}; // functionCall id → バッジ要素（response で done へ）
  // 過程ログ（作成/レビュー/ツール/前月集計）は既定で畳む <details>。状態はステッパー＋ステータスライン。
  let proc = null,
    procBody = null,
    procLabel = null,
    procSpin = null;

  // ステップは前進のみ（遅れて来る収集イベント等で後退させない）。
  function toStep(idx, state) {
    if (idx < 0 || idx < maxStep) return;
    maxStep = idx;
    stepper.advanceTo(idx, state || "now");
  }

  // ステータスライン更新に合わせて、畳んだ過程ログの見出しも稼働中だけ追従させる。
  function phase(text, state) {
    status.setPhase(text, state);
    if (procLabel && procSpin) procLabel.textContent = text;
  }

  // 過程ログ（畳み）を用意する。actor turn・ツールバッジ・前月集計はこの中に積む。
  function buildProc() {
    proc = el("details", "proc");
    const sum = el("summary", "proc-sum");
    procSpin = el("span", "spinner");
    procLabel = el("span", "proc-label", "AI が作業しています…");
    sum.append(procSpin, procLabel, el("span", "proc-hint", "経過を見る"));
    proc.appendChild(sum);
    procBody = el("div", "proc-body");
    proc.appendChild(procBody);
    area.appendChild(proc);
  }
  // 過程が一段落したらスピナーを止める（偽の稼働を残さない＝降格/完了を正直に示す）。
  function procStop(text) {
    if (procSpin) {
      procSpin.remove();
      procSpin = null;
    }
    if (procLabel) procLabel.textContent = text || "AI のやりとり（経過）";
  }

  // 連続する同一 actor のイベントを1枚の turn に束ねる。
  function actorTurn(author) {
    const who = whoOf(author);
    if (cur && cur.author === author) return cur;
    const turn = el("div", "turn");
    turn.innerHTML =
      `<div class="turn-lane ${who.cls}"></div>` +
      `<div class="turn-body"><div class="turn-who ${who.cls}">${iconHTML(who.icon)}${esc(who.label)}</div></div>`;
    procBody.appendChild(turn);
    cur = { author, body: turn.querySelector(".turn-body"), toolsRow: null };
    return cur;
  }
  function addText(author, text) {
    const c = actorTurn(author);
    const p = el("div", "turn-text");
    p.textContent = text;
    c.body.appendChild(p);
  }
  function addTool(author, name) {
    const c = actorTurn(author);
    if (!c.toolsRow) {
      c.toolsRow = el("div", "tools-row");
      c.body.appendChild(c.toolsRow);
    }
    const b = toolBadgeEl(name);
    c.toolsRow.appendChild(b);
    return b;
  }

  async function run(seedState, messageText) {
    clear(area);
    cur = null;
    toolBadges = {};
    maxStep = -1;
    proc = procBody = procLabel = procSpin = null;
    buildProc();
    stepperEl.classList.remove("hidden");
    stepper = makeStepper(stepperEl, steps);
    if (kind === "monthly") {
      toStep(iPrep);
      phase("前月の積み重ねを集計しています", "working");
    } else {
      stepper.set(0, "done");
      maxStep = 0;
      toStep(iColl);
      phase("下書きを準備しています", "working");
    }
    button.disabled = true;
    try {
      const session = await adk.createSession(seedState);
      await drive(session.id, adk.textMessage(messageText), null);
    } catch (e) {
      if (e instanceof adk.PasscodeError) {
        window.__requireGate && window.__requireGate();
        banner(area, "info", "パスコードを入力してから、もう一度お試しください。");
      } else {
        banner(area, "err", "エラー: " + e.message);
      }
      procStop("中断しました");
      status.clearPhase();
    } finally {
      button.disabled = false;
    }
  }

  // 1 invocation を回し、ask_caregiver で止まったら質問カードを出して再開する。
  async function drive(sessionId, message, invocationId) {
    let pending = null;
    await adk.runSSE(
      sessionId,
      message,
      (ev) => {
        const invId = ev.invocationId || ev.invocation_id;
        for (const it of adk.adkParts(ev)) {
          if (it.kind === "text" && it.text.trim()) {
            // 下書きの JSON ブロック（```json … / 生の {…}）はタイムラインに出さない（確定書類で見せる）。
            let t = it.text;
            const cut = t.search(/```|\n\s*\{/);
            if (cut > 0) t = t.slice(0, cut).trim();
            if (t) {
              t = t.length > 360 ? t.slice(0, 360) + " …" : t;
              addText(it.author, t);
              const a = (it.author || "").toLowerCase();
              if (a.includes("prep")) {
                toStep(iPrep);
                phase("前月の積み重ねを集計しています", "working");
              } else if (a.includes("review")) {
                toStep(iReview);
                phase("別の視点で点検しています", "working");
              } else {
                toStep(iDraft);
                phase("下書きを作成しています", "working");
              }
            }
          } else if (it.kind === "call") {
            const badge = addTool(it.author, it.name);
            if (it.id) toolBadges[it.id] = badge;
            toStep(iColl);
            phase(toolMeta(it.name).label + "…", "working");
            if (it.name === "ask_caregiver" && it.longRunning) {
              pending = { id: it.id, question: it.args.question, choices: it.args.choices, invId };
            }
          } else if (it.kind === "response") {
            if (it.id && toolBadges[it.id]) markToolDone(toolBadges[it.id]);
          }
        }
      },
      { invocationId },
    );
    if (pending) {
      stepper.advanceTo(maxStep < 0 ? 0 : maxStep, "wait");
      phase("あなたの確認を待っています", "waiting");
      askCard(sessionId, pending);
      return;
    }
    await finalizeView(sessionId);
  }

  function askCard(sessionId, pending) {
    cur = null;
    const card = el("div", "ask");
    card.innerHTML = `<div class="q">${iconHTML("ask")}<span>${esc(pending.question || "確認したいことがあります")}</span></div>`;
    const actions = el("div", "ask-actions");
    const answerAndResume = async (answer) => {
      card.remove();
      cur = null;
      const turn = el("div", "turn");
      turn.innerHTML =
        `<div class="turn-lane caregiver"></div>` +
        `<div class="turn-body"><div class="turn-who caregiver">${iconHTML("caregiver")}保育士（あなた）</div><div class="turn-text">${esc(answer)}</div></div>`;
      area.appendChild(turn);
      cur = null;
      phase("回答を受けて再開しています", "working");
      await drive(
        sessionId,
        adk.functionResponseMessage(pending.id, "ask_caregiver", { answer, status: "answered" }),
        pending.invId,
      );
    };
    if (Array.isArray(pending.choices) && pending.choices.length) {
      for (const c of pending.choices) {
        const b = el("button", "btn btn-ghost btn-sm", esc(c));
        b.type = "button";
        b.onclick = () => answerAndResume(c);
        actions.appendChild(b);
      }
    } else {
      const ta = el("textarea", "memo");
      ta.rows = 2;
      ta.placeholder = "回答を入力してください";
      ta.setAttribute("aria-label", "保育士の回答");
      card.appendChild(ta);
      const b = el("button", "btn btn-primary btn-sm", `${iconHTML("check")}回答する`);
      b.type = "button";
      b.onclick = () => {
        if (ta.value.trim()) answerAndResume(ta.value.trim());
      };
      actions.appendChild(b);
    }
    card.appendChild(actions);
    area.appendChild(card);
    card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function finalizeView(sessionId) {
    const s = await adk.getSession(sessionId);
    const st = s.state || {};
    cur = null;

    // 前月集計は「AI が何を踏まえたか」の経過なので畳んだログ側に入れる（前面は最終下書きだけ）。
    if (showDigest && st.prev_month_digest != null) {
      const txt =
        typeof st.prev_month_digest === "string" ? st.prev_month_digest : JSON.stringify(st.prev_month_digest, null, 2);
      const dp = renderDocPanel({ titleIcon: "chart", title: "前月の積み重ね（自動集計・L2 還流）", formatted: txt });
      procBody.appendChild(dp);
    }

    const doc = st.final_document;
    if (!doc) {
      procStop("生成に失敗しました");
      banner(area, "err", "下書きを生成できませんでした（" + (st.finalize_parse_error || "原因不明") + "）。");
      phase("生成に失敗しました", "waiting");
      return;
    }

    const meta = DOC_META[kind] || DOC_META.diary;
    const panel = renderDocPanel({
      titleIcon: meta.icon,
      title: meta.title,
      labelHTML: `<span class="label-draft">${iconHTML("ask")}AI下書き（確認前）</span>`,
      formatted: doc,
    });

    const val = st.validation || [];
    const v = el("div", "validation " + (val.length ? "ng" : "ok"));
    v.innerHTML = val.length
      ? `${iconHTML("alert")}必須項目の不足: ${esc(val.join(" / "))}`
      : `${iconHTML("check")}必須項目を満たしています`;
    panel._body.appendChild(v);
    approveBar(sessionId, st, panel);
    area.appendChild(panel);

    procStop("AI のやりとり（経過）");
    stepper.allDone();
    phase("保育士の確定をお待ちしています", "waiting");
  }

  function approveBar(sessionId, st, panel) {
    const bar = el("div", "approve-bar");
    const mem = adk.config().memory_connected;
    const btn = el("button", "btn btn-approve", `${iconHTML("check")}この内容で確定・承認する`);
    btn.type = "button";
    btn.onclick = async () => {
      btn.disabled = true;
      await adk.patchState(sessionId, { caregiver_approved: true });
      const lbl = panel.querySelector(".label-draft");
      if (lbl) {
        lbl.className = "label-final";
        lbl.innerHTML = `${iconHTML("check")}公式記録`;
      }
      clear(bar);
      bar.appendChild(el("span", "approve-done", `${iconHTML("check")}保育士が確定・承認しました`));
      bar.appendChild(
        el(
          "span",
          "persist-note",
          mem
            ? "承認を記録（caregiver_approved）。来園の Memory Bank 書き戻しは確定パイプラインの承認ゲートで発火します。"
            : "承認を記録（caregiver_approved）。Memory Bank 未接続のため書き戻しは降格。",
        ),
      );
      phase("確定・承認しました", "done");
    };
    bar.appendChild(btn);
    if (st.awaiting_caregiver_approval) bar.appendChild(el("span", "persist-note", "保育士の確定をお待ちしています"));
    panel._body.appendChild(bar);
  }

  return { run };
}
