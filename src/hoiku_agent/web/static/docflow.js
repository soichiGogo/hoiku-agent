// 日誌/月案で共通の作成フロー（作成中→HITL→レビュー→確定→承認）。
// 生成は ADK /run_sse を直接駆動（自前 Runner は組まない＝§9）。harness/agents は不変。

import * as adk from "./adk.js";
import { el, esc, clear, toolLabel, whoOf, pushStep, renderDocument, banner } from "./ui.js";

export function makeDocFlow({ area, button, showDigest }) {
  async function run(seedState, messageText) {
    clear(area);
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
            const who = whoOf(it.author);
            // 下書きの JSON ブロック（```json … / 生の {…}）はタイムラインに出さない（確定書類で見せる）。
            let t = it.text;
            const cut = t.search(/```|\n\s*\{/);
            if (cut > 0) t = t.slice(0, cut).trim();
            if (t) {
              t = t.length > 360 ? t.slice(0, 360) + " …" : t;
              pushStep(area, { ico: who.ico, who: who.label, whoCls: who.cls, text: t });
            }
          } else if (it.kind === "call") {
            pushStep(area, { text: toolLabel(it.name), tool: true });
            if (it.name === "ask_caregiver" && it.longRunning) {
              pending = { id: it.id, question: it.args.question, choices: it.args.choices, invId };
            }
          }
        }
      },
      { invocationId },
    );
    if (pending) {
      askCard(sessionId, pending);
      return;
    }
    await finalizeView(sessionId);
  }

  function askCard(sessionId, pending) {
    const card = el("div", "ask");
    card.appendChild(el("div", "q", esc(pending.question || "確認したいことがあります")));
    const actions = el("div", "ask-actions");
    const answerAndResume = async (answer) => {
      card.remove();
      pushStep(area, { ico: "🗣️", who: "保育士", text: answer });
      await drive(
        sessionId,
        adk.functionResponseMessage(pending.id, "ask_caregiver", { answer, status: "answered" }),
        pending.invId,
      );
    };
    if (Array.isArray(pending.choices) && pending.choices.length) {
      for (const c of pending.choices) {
        const b = el("button", "btn btn-ghost", esc(c));
        b.onclick = () => answerAndResume(c);
        actions.appendChild(b);
      }
    } else {
      const ta = el("textarea", "memo");
      ta.rows = 2;
      ta.placeholder = "回答を入力してください";
      card.appendChild(ta);
      const b = el("button", "btn btn-primary", "回答する");
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

    if (showDigest && st.prev_month_digest != null) {
      const box = el("div", "card");
      box.appendChild(el("div", "field-label", "前月の積み重ね（自動集計・L2 還流）"));
      const txt =
        typeof st.prev_month_digest === "string"
          ? st.prev_month_digest
          : JSON.stringify(st.prev_month_digest, null, 2);
      box.appendChild(renderDocument(txt));
      area.appendChild(box);
    }

    const doc = st.final_document;
    if (!doc) {
      banner(area, "err", "下書きを生成できませんでした（" + (st.finalize_parse_error || "原因不明") + "）。");
      return;
    }
    const val = st.validation || [];
    const v = el("div", "validation " + (val.length ? "ng" : "ok"));
    v.textContent = val.length ? "⚠ 必須項目の不足: " + val.join(" / ") : "✓ 必須項目を満たしています";
    area.appendChild(v);
    area.appendChild(renderDocument(doc));
    approveBar(sessionId, st);
  }

  function approveBar(sessionId, st) {
    const bar = el("div", "approve-bar");
    const mem = adk.config().memory_connected;
    const btn = el("button", "btn btn-approve", "この内容で確定・承認する");
    btn.onclick = async () => {
      btn.disabled = true;
      await adk.patchState(sessionId, { caregiver_approved: true });
      clear(bar);
      bar.appendChild(el("span", "approve-done", "✓ 保育士が確定・承認しました"));
      bar.appendChild(
        el(
          "span",
          "persist-note",
          mem
            ? "承認を記録（caregiver_approved）。来園の Memory Bank 書き戻しは確定パイプラインの承認ゲートで発火します。"
            : "承認を記録（caregiver_approved）。Memory Bank 未接続のため書き戻しは降格。",
        ),
      );
    };
    bar.appendChild(btn);
    bar.appendChild(
      el("span", "persist-note", st.awaiting_caregiver_approval ? "保育士の確定待ちです" : ""),
    );
    area.appendChild(bar);
  }

  return { run };
}
