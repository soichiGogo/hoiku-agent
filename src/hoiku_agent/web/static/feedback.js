// feedback.js — 確定/承認画面・アーカイブ詳細に置く「👍👎＋ひとこと」の軽量フィードバック導線。
// 送信で record_store へ保存（文書＋その版に紐付け＝§8「回す」の一次入力）。ひとことがあれば
// 「この気づきを指針に活かす」を出し、押すとその場（インライン）に改善エージェント（policy.js の
// makePolicy）を展開＝育てるタブと同じ 提案→比較相談→保育士決定で即反映 を回す。
// web は中継/描画のみ（保存は harness・指針化の判断は improver＝§5）。降格は偽の緑を出さない。

import * as adk from "./adk.js";
import { el, esc, clear, iconHTML, actorName } from "./ui.js";
import { makePolicy } from "./policy.js";
import { POLICY_SCOPE_OF } from "./scopes.js";

// 確定/承認画面・アーカイブ詳細に差し込む 👍👎＋ひとこと バーを作る。
// opts.docKind＝書類種別（scope 解決用）／opts.getDocId()＝現在の document_id（未保存/未接続は "" を返しうる）。
export function makeFeedbackBar({ docKind, getDocId }) {
  let verdict = null; // "up" / "down"
  let policy = null; // makePolicy インスタンス（「活かす」初回で生成）

  const root = el("div", "fbbar");
  root.appendChild(
    el(
      "div",
      "fbbar-lead",
      `${iconHTML("sprout")}<span>この書類はどうでしたか？（改善のヒントになります）</span>`,
    ),
  );

  // 👍👎 トグル＋ひとこと＋送信の行。
  const row = el("div", "fbbar-row");
  const thumbs = el("div", "fb-thumbs");
  const upBtn = thumbBtn("up", "thumbs-up", "良かった");
  const downBtn = thumbBtn("down", "thumbs-down", "直したい");
  thumbs.append(upBtn, downBtn);
  const comment = el("textarea", "fb-comment");
  comment.rows = 1;
  comment.placeholder = "ひとこと（任意）。気づきがあれば指針づくりに活かせます。";
  comment.setAttribute("aria-label", "フィードバックのひとこと");
  const sendBtn = el("button", "btn btn-primary btn-sm fb-send", `${iconHTML("check")}送信`);
  sendBtn.type = "button";
  sendBtn.disabled = true; // 👍👎 未選択では押せない
  row.append(thumbs, comment, sendBtn);
  root.appendChild(row);

  const note = el("div", "fb-note");
  root.appendChild(note);

  // 「この気づきを指針に活かす」ボタン（送信後・ひとことがあるときだけ出す）＋インライン改善パネル。
  const improveWrap = el("div", "fb-improve-wrap");
  root.appendChild(improveWrap);

  function thumbBtn(v, icon, label) {
    const b = el("button", "fb-thumb fb-" + v, `${iconHTML(icon)}<span>${esc(label)}</span>`);
    b.type = "button";
    b.setAttribute("aria-pressed", "false");
    b.onclick = () => {
      verdict = v;
      upBtn.classList.toggle("on", v === "up");
      downBtn.classList.toggle("on", v === "down");
      upBtn.setAttribute("aria-pressed", String(v === "up"));
      downBtn.setAttribute("aria-pressed", String(v === "down"));
      sendBtn.disabled = false;
    };
    return b;
  }

  // 送信＝👍👎（＋ひとこと）を保存（文書＋版に紐付け）。未接続でも本流は壊さず正直に降格表示する。
  sendBtn.onclick = async () => {
    if (!verdict) return;
    sendBtn.disabled = true;
    const docId = (getDocId && getDocId()) || "";
    const text = comment.value.trim();
    clear(note);
    let res;
    if (docId) {
      res = await adk.saveFeedback(docId, verdict, text, actorName());
    } else {
      res = { status: "skipped", reason: "no_doc" }; // 未保存の書類＝紐付け先が無い（改善は別途動く）
    }
    setSaveNote(res, !!docId);
    // ひとことがあれば「指針に活かす」を出す（保存の成否に関わらず改善フローは動く）。
    if (text) showImproveAffordance();
    sendBtn.disabled = false;
  };

  function setSaveNote(res, hadDoc) {
    if (res.status === "saved") {
      note.innerHTML = `${iconHTML("check")}フィードバックを保存しました（この書類に紐付け）。ありがとうございます。`;
    } else if (res.status === "skipped") {
      note.innerHTML = hadDoc
        ? `${iconHTML("info")}アーカイブ未接続のため保存はされませんが、ひとことは指針づくりに活かせます。`
        : `${iconHTML("info")}この書類はまだ保存されていないため記録は紐付きませんが、ひとことは指針づくりに活かせます。`;
    } else {
      note.innerHTML = `${iconHTML("alert")}保存に失敗しました：${esc(res.detail || "原因不明")}`;
    }
  }

  // ひとことがあるときだけ出す「この気づきを指針に活かす」。押すとインライン改善エージェントを起こす。
  function showImproveAffordance() {
    policy = null; // 再送信で作り直すため（古いパネルの参照を残さない）
    clear(improveWrap);
    const btn = el(
      "button",
      "btn btn-ghost btn-sm fb-improve-btn",
      `${iconHTML("sprout")}この気づきを指針に活かす`,
    );
    btn.type = "button";
    const panel = el("div", "fb-improve");
    improveWrap.append(btn, panel);
    btn.onclick = () => runImprove(comment.value.trim(), btn, panel);
  }

  // インライン改善エージェント：育てるタブと同じ makePolicy を専用コンテナで動かす（別エントリの原則は
  // improver_stream が担保・ここは描画の再利用のみ）。全デッキは出さず、この気づき由来の流れだけを見せる。
  function runImprove(text, btn, panel) {
    if (!text) return;
    if (!policy) {
      clear(panel);
      const stepper = el("div", "stepper hidden");
      const statusLine = el("div", "fb-improve-status");
      const flow = el("div", "fb-improve-flow");
      // grid/history は makePolicy が要求するデッキ枠（CSS で非表示）。反映結果は flow の提案カードの
      // ラベルが「確認前→反映済み」に変わって示す（全カードデッキは育てるタブに任せる）。
      const grid = el("div", "fb-improve-grid");
      const history = el("div", "fb-improve-history");
      panel.append(stepper, statusLine, flow, grid, history);
      const status = {
        setPhase(t, state) {
          statusLine.textContent = t || "";
          statusLine.dataset.state = state || "";
        },
        clearPhase() {
          statusLine.textContent = "";
        },
      };
      policy = makePolicy({ grid, history, flow, button: btn, stepper, status });
    }
    const scope = POLICY_SCOPE_OF[docKind] || null;
    // 👍👎 の valence を improver へ渡す（肯定/否定でカード化の観点が変わる。prompt 本文なので絵文字可）。
    const valence = verdict === "up" ? "👍（良かった点として）" : "👎（直したい点として）";
    policy.run(text, scope, valence);
  }

  return root;
}
