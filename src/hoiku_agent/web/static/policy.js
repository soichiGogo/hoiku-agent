// 「指針を育てる」タブ：上=現在の指針カード＋変更履歴（閲覧）／下=改善提案フロー（温かい）。
// 改善エージェント（二階）を /api/improve で SSE 駆動し、提案→意味的競合の比較相談（HITL）→
// 保育士の決定で即反映 をライブに描く（日誌/月案と同じ世界観・docflow の proc/turn 部品を踏襲）。
// 決定的ロジック・採点は持たない（実体は harness/eval＝§5）。降格は偽の緑を出さずスピナーを止める。

import * as adk from "./adk.js";
import { el, esc, clear, iconHTML, toolMeta, whoOf, toolBadgeEl, markToolDone, makeStepper, banner } from "./ui.js";

const STEPS = ["修正メモ", "競合を精査", "整合", "反映"];
// scope（共通/保育日誌/月案）→ 対象書類タグ（左ライン色分け・ラベル）。提案カードの描画に使う
// （反映済みカードは backend の card_view が doc_type/doc_label を持つ）。
const SCOPE_DT = {
  共通: ["common", "共通"],
  保育日誌: ["diary", "保育日誌"],
  月案: ["monthly", "クラス月案"],
  保育経過記録: ["child_record", "保育経過記録"],
  保育要録: ["nursery_record", "保育要録"],
};

export function makePolicy({ grid, history, flow, button, stepper: stepperEl, status }) {
  let stepper = null;
  let maxStep = -1;
  let cur = null; // 直近 actor turn
  let toolBadges = {};
  let proc = null,
    procBody = null,
    procSpin = null;
  let lastProposal = null; // 直近 propose の result（needs_input で既存↔新を並べるため保持）
  let proposedPanel = null; // 前面の提案カード（反映で label を「反映済み」へ）
  // デッキ（いまの指針カード）の全カード＋対象書類フィルタ。フィルタは doc_type の allowlist
  // （null＝全表示）。対象書類セレクタ（app.js）から setFilter で切替＝反映先の可視化（Thread A）。
  let allCards = [];
  let allHistory = [];
  let curStore = null;
  let bookVersion = 0;
  let filterDocTypes = null;

  /* ---------- 閲覧デッキ（上） ---------- */
  function cardEl(card, { isNew = false } = {}) {
    const dt = card.doc_type || "common";
    const label = card.doc_label || card.scope || "共通";
    const node = el("div", `pcard dt-${dt}` + (isNew ? " is-new" : ""));
    const meta =
      `<span class="pcard-tag">${esc(label)}</span>` +
      (card.source ? `<span class="pcard-src">${iconHTML("caregiver")}${esc(card.source)}</span>` : "") +
      (card.date ? `<span class="pcard-date">${esc(card.date)}</span>` : "");
    node.innerHTML = `<div class="pcard-body">${esc(card.body)}</div><div class="pcard-meta">${meta}</div>`;
    return node;
  }
  function historyEl(h) {
    const item = el("div", "phist-item");
    item.innerHTML =
      `<span class="phist-when">${esc(h.at || "")}</span>` +
      `<span class="phist-what"><span class="phist-by">${esc(h.by || "保育士")}</span> ${esc(h.summary || "")}</span>`;
    return item;
  }
  function renderDeck({ cards, history: hist, store, version }) {
    allCards = cards || [];
    allHistory = hist || [];
    curStore = store;
    bookVersion = version ?? bookVersion;
    paintDeck();
  }
  // 現在のフィルタ（対象書類）でデッキを描く。フィルタは card_view の doc_type（共通＝common）で絞る＝
  // 「共通＋その書類」の範囲だけ見せて反映先を明示する（render_for_doc の前置注入範囲と一致）。
  function paintDeck() {
    clear(grid);
    clear(history);
    const shown = filterDocTypes
      ? allCards.filter((c) => filterDocTypes.includes(c.doc_type || "common"))
      : allCards;
    if (!shown.length) {
      grid.appendChild(
        el(
          "p",
          "policy-empty",
          filterDocTypes
            ? "この書類に効く指針カードはまだありません。下のメモから追加できます。"
            : "指針カードはまだありません。下のメモから育てられます。",
        ),
      );
    } else {
      shown.forEach((c) => grid.appendChild(cardEl(c)));
    }
    allHistory.forEach((h) => history.appendChild(historyEl(h)));
    if (curStore && curStore !== "persistent") {
      const msg =
        curStore === "ephemeral"
          ? "この環境では反映はこのセッション内の参照用です（再起動で消えます）。永続化はストア接続後に有効になります。"
          : "指針ストアは未接続です（閲覧降格）。";
      banner(grid, "info", msg);
    }
  }
  // 対象書類フィルタを切り替える（docTypes＝doc_type の allowlist・null/空で全表示＝従来動作）。
  function setFilter(docTypes) {
    filterDocTypes = docTypes && docTypes.length ? docTypes : null;
    paintDeck();
  }
  async function init() {
    renderDeck(await adk.getPolicy());
  }

  /* ---------- 過程ログ（proc）＝docflow と同じ畳み ---------- */
  function toStep(idx, state) {
    if (idx < 0 || idx < maxStep) return;
    maxStep = idx;
    stepper.advanceTo(idx, state || "now");
  }
  function phase(text, state) {
    status.setPhase(text, state);
  }
  function buildProc() {
    proc = el("details", "proc");
    const sum = el("summary", "proc-sum");
    procSpin = el("span", "spinner");
    sum.append(el("span", "proc-hint", "経過を見る"), procSpin);
    proc.appendChild(sum);
    procBody = el("div", "proc-body");
    proc.appendChild(procBody);
    flow.appendChild(proc);
  }
  function procStop() {
    if (procSpin) {
      procSpin.remove();
      procSpin = null;
    }
  }
  function actorTurn(author) {
    const who = whoOf(author || "improver");
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

  /* ---------- 提案カード（前面） ---------- */
  function cardFromProposal(p) {
    const [dt, label] = SCOPE_DT[p.scope] || ["common", p.scope];
    return { body: p.body, scope: p.scope, doc_type: dt, doc_label: label, source: p.source || "提案", date: "" };
  }
  function renderProposed(result) {
    lastProposal = result;
    cur = null;
    const p = result.proposal || {};
    const panel = el("div", "ppropose");
    const verb = p.op === "supersede" ? "置き換え提案" : "追加提案";
    panel.innerHTML = `<div class="ppropose-head">${iconHTML("edit")}指針への${esc(verb)}<span class="label-draft">${iconHTML("ask")}確認前</span></div>`;
    panel.appendChild(cardEl(cardFromProposal(p)));
    if (result.has_conflict) {
      panel.appendChild(el("div", "ppropose-note", `${iconHTML("info")}既にある指針と重なる可能性があります。下で見比べて決めてください。`));
    }
    flow.appendChild(panel);
    proposedPanel = panel;
  }

  /* ---------- 競合の比較相談（HITL・既存↔新を並べる） ---------- */
  function renderConflictCompare(item) {
    cur = null;
    toStep(2, "wait");
    phase("あなたの判断を待っています", "waiting");
    const r = lastProposal || {};
    const existing = (r.declared_conflicts || []).slice();
    if (r.exact_duplicate) existing.push(r.exact_duplicate);

    const ask = el("div", "ask");
    ask.innerHTML = `<div class="q">${iconHTML("ask")}<span>${esc(item.question || "この気づきをどう反映しますか？")}</span></div>`;

    if (existing.length && r.proposal) {
      const cmp = el("div", "compare");
      const left = el("div", "compare-col");
      left.appendChild(el("div", "compare-head existing", `${iconHTML("clipboard")}いまの指針`));
      existing.forEach((c) => left.appendChild(cardEl({ body: c.body, scope: c.scope, doc_type: (SCOPE_DT[c.scope] || ["common"])[0], doc_label: (SCOPE_DT[c.scope] || [, c.scope])[1] })));
      const right = el("div", "compare-col");
      right.appendChild(el("div", "compare-head proposed", `${iconHTML("edit")}新しい案`));
      right.appendChild(cardEl(cardFromProposal(r.proposal)));
      cmp.append(left, right);
      ask.appendChild(cmp);
    }

    const actions = el("div", "ask-actions");
    const choices = Array.isArray(item.choices) && item.choices.length ? item.choices : ["この内容で反映する", "やめる"];
    for (const c of choices) {
      const b = el("button", "btn btn-ghost btn-sm", esc(c));
      b.type = "button";
      b.onclick = () => resume(item, c);
      actions.appendChild(b);
    }
    ask.appendChild(actions);
    flow.appendChild(ask);
    ask.scrollIntoView({ behavior: "smooth", block: "nearest" });
    // 第1選択へフォーカス（a11y）。
    const first = actions.querySelector("button");
    if (first) requestAnimationFrame(() => first.focus());
  }

  async function resume(item, answer) {
    // 保育士のターンを残す
    const turn = el("div", "turn");
    turn.innerHTML =
      `<div class="turn-lane caregiver"></div>` +
      `<div class="turn-body"><div class="turn-who caregiver">${iconHTML("caregiver")}保育士（あなた）</div><div class="turn-text">${esc(answer)}</div></div>`;
    flow.appendChild(turn);
    cur = null;
    // ask カードを消す（直近の .ask）
    const asks = flow.querySelectorAll(".ask");
    if (asks.length) asks[asks.length - 1].remove();
    toStep(2, "working");
    phase("判断を受けて整えています", "working");
    try {
      await adk.ssePost(
        "/api/improve/resume",
        { session_id: item.session_id, function_call_id: item.function_call_id, answer },
        handleItem,
      );
    } catch (e) {
      onError(e.message || String(e));
    }
  }

  /* ---------- 反映の確定（即反映） ---------- */
  function onCommitted(result) {
    if (result.status !== "committed") {
      // banner() が内部で esc() するので呼び出し側では素の文字列を渡す（二重エスケープ回避）。
      banner(flow, "info", "反映されませんでした：" + (result.detail || result.status || "不明"));
      return;
    }
    if (proposedPanel) {
      const lbl = proposedPanel.querySelector(".label-draft");
      if (lbl) {
        lbl.className = "label-final";
        lbl.innerHTML = `${iconHTML("check")}反映済み`;
      }
    }
    // デッキへライブ反映（先頭に差し込み）。
    if (result.card) grid.prepend(cardEl(result.card, { isNew: true }));
    if (result.history_entry) history.prepend(historyEl(result.history_entry));
    if (result.store && result.store !== "persistent") {
      const note = result.store === "ephemeral" ? "この環境では揮発します（再起動で消えます）" : "ストア未接続";
      flow.appendChild(el("div", "store-note", `${iconHTML("info")}${esc(note)}`));
    }
    toStep(3, "done");
  }

  function onError(detail) {
    procStop();
    banner(flow, "err", "エラー: " + detail);
    phase("降格しました", "waiting");
    button.disabled = false;
  }

  /* ---------- SSE イベント（improver_stream の正規化済み {type,...}） ---------- */
  function handleItem(item) {
    switch (item.type) {
      case "text":
        if (item.text && item.text.trim()) {
          let t = item.text.trim();
          t = t.length > 360 ? t.slice(0, 360) + " …" : t;
          addText(item.author, t);
        }
        break;
      case "tool_call": {
        const b = addTool(item.author, item.name);
        if (item.id) toolBadges[item.id] = b;
        if (item.name === "propose_policy_card") {
          toStep(1, "working");
          phase("既存の指針と重ならないか精査しています", "working");
        } else if (item.name === "commit_policy_card") {
          toStep(3, "working");
          phase("指針に反映しています", "working");
        } else {
          phase(toolMeta(item.name).label + "…", "working");
        }
        break;
      }
      case "tool_result": {
        if (item.id && toolBadges[item.id]) markToolDone(toolBadges[item.id]);
        const r = item.result || {};
        if (item.name === "propose_policy_card" && r.proposal) renderProposed(r);
        else if (item.name === "commit_policy_card") onCommitted(r);
        break;
      }
      case "needs_input":
        renderConflictCompare(item);
        break;
      case "error":
        onError(item.detail || "原因不明");
        break;
      case "done":
        toStep(3, "done");
        procStop();
        stepper.allDone();
        phase("反映しました", "done");
        button.disabled = false;
        // 権威ある最終状態へ整合（ライブ差し込みと二重表示しないよう全再描画）。
        adk.getPolicy().then(renderDeck);
        break;
      default:
        break;
    }
  }

  /* ---------- 実行 ---------- */
  // targetScope＝保育士が選んだ対象書類（PolicyScope 値・null＝すべて＝AI 判断）。改善エージェントの
  // scope の既定にする（backend は既定として尊重しつつ、内容的に共通と判断したら提案する＝勝手に変えない）。
  // feedback＝👍👎 の valence（確定画面のフィードバック導線から起こすとき・育てるタブからは null）。
  async function run(memo, targetScope = null, feedback = null) {
    clear(flow);
    cur = null;
    toolBadges = {};
    maxStep = -1;
    lastProposal = null;
    proposedPanel = null;
    proc = procBody = procSpin = null;
    buildProc();
    stepperEl.classList.remove("hidden");
    stepper = makeStepper(stepperEl, STEPS);
    stepper.set(0, "done");
    maxStep = 0;
    toStep(1, "now");
    phase("既存の指針と重ならないか精査しています", "working");
    button.disabled = true;
    try {
      await adk.ssePost(
        "/api/improve",
        { diff: memo, feedback, target_scope: targetScope, session_id: crypto.randomUUID() },
        handleItem,
      );
    } catch (e) {
      onError(e.message || String(e));
    } finally {
      button.disabled = false;
    }
  }

  return { init, run, setFilter };
}
