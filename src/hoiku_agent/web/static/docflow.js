// 日誌/月案/児童票で共通の作成フロー（集計→収集→下書き→HITL→レビュー→確定→承認）。
// 生成は ADK /run_sse を直接駆動（自前 Runner は組まない＝§9）。harness/agents は不変。
// 「働いている実質」は計画ステッパー＋ステータスラインで示し、作成AI/レビューAI/ツールの細かな
// やりとりは既定で畳む（<details class="proc">）。保育士が前面で確認するのは「不足の確認（HITL）」と
// 「最終下書き＋不足内容」だけにする（過程は経過として開けば見られる）。

import * as adk from "./adk.js";
import { el, esc, clear, iconHTML, toolMeta, whoOf, toolBadgeEl, markToolDone, renderDocPanel, makeStepper, banner, actorName } from "./ui.js";
import { renderEditableDoc } from "./docedit.js";

const DOC_META = {
  diary: { title: "保育日誌", icon: "diary" },
  monthly: { title: "個別月案", icon: "calendar" },
  child_record: { title: "児童票", icon: "chart" },
};

// doc_type（フロントの kind）→ 指針カードの scope（harness の PolicyScope 値）。
// 「指針を取り込む」ステップで共通＋当該書類のカードだけを絞って見せる（render_for_doc と同じ絞り）。
const POLICY_SCOPE_OF = { diary: "保育日誌", monthly: "月案", child_record: "児童票" };

// 集計 prep を持つ doc_type の表示メタ（digest の state キー・見出し・稼働中フェーズ文言）。
const PREP_META = {
  monthly: {
    digestKey: "prev_month_digest",
    digestTitle: "前月の積み重ね（自動集計・L2 還流）",
    phaseText: "前月の積み重ねを集計しています",
  },
  child_record: {
    digestKey: "period_digest",
    digestTitle: "期間の積み重ね（自動集計・L3 還流）",
    phaseText: "期間の積み重ねを集計しています",
  },
};

export function makeDocFlow({ area, button, stepper: stepperEl, steps, showDigest, kind, status, onBusy }) {
  const prepMeta = PREP_META[kind] || null;
  const iPrep = steps.findIndex((s) => s.includes("集計"));
  const iPolicy = steps.indexOf("指針を取り込む");
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

  // 「指針を取り込む」ステップ：harness は author/reviewer の prompt 冒頭へ文書作成指針を前置注入する。
  // その"取り込み"をフロントでも先に見せる（指針を取り込む → ツール呼び出し → 考えてる、の流れ）。
  // 指針の実体は /api/policy（共通＋当該書類の scope に絞る＝render_for_doc と同じ絞り）。取得失敗/未整備は
  // パネルを出さず step だけ進める（偽の中身を出さない＝降格を正直に）。
  async function showPolicyStep() {
    if (iPolicy < 0) return;
    toStep(iPolicy);
    phase("園の文書作成指針を取り込んでいます", "working");
    let cards = [];
    try {
      const scope = POLICY_SCOPE_OF[kind];
      const p = await adk.getPolicy();
      cards = (p.cards || []).filter((c) => c.scope === "共通" || c.scope === scope);
    } catch {
      /* 取得失敗はパネルを出さず step だけ進める */
    }
    const label = (DOC_META[kind] || {}).title || "この書類";
    const body = cards.length
      ? cards.map((c) => "・" + c.body).join("\n")
      : "（現在この書類に適用する指針カードはありません。共通ルールに沿って作成します）";
    procBody.appendChild(
      renderDocPanel({
        titleIcon: "clipboard",
        title: `文書作成指針を取り込みました（${label}向け・${cards.length}件）`,
        formatted: body,
      }),
    );
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
    if (prepMeta) {
      toStep(iPrep);
      phase(prepMeta.phaseText, "working");
    } else {
      stepper.set(0, "done");
      maxStep = 0;
    }
    button.disabled = true;
    onBusy && onBusy(true); // 生成中は種別セグメントを固定（統合タブでの切替ロック）
    try {
      // 生成に入る前に「指針を取り込む」ステップを見せる（前置注入の可視化）。
      await showPolicyStep();
      phase("下書きを準備しています", "working");
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
      onBusy && onBusy(false);
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
                phase(prepMeta ? prepMeta.phaseText : "積み重ねを集計しています", "working");
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

    // 集計（前月/期間）は「AI が何を踏まえたか」の経過なので畳んだログ側に入れる（前面は最終下書きだけ）。
    const digest = prepMeta ? st[prepMeta.digestKey] : null;
    if (showDigest && prepMeta && digest != null) {
      const txt = typeof digest === "string" ? digest : JSON.stringify(digest, null, 2);
      const dp = renderDocPanel({ titleIcon: "chart", title: prepMeta.digestTitle, formatted: txt });
      procBody.appendChild(dp);
    }

    const doc = st.final_document;
    const entry = st.final_entry;
    if (!doc || !entry) {
      // parse 失敗等＝構造化エントリが無い。編集フォームは出せないので正直に失敗表示（偽の緑を出さない）。
      procStop("生成に失敗しました");
      banner(area, "err", "下書きを生成できませんでした（" + (st.finalize_parse_error || "原因不明") + "）。");
      phase("生成に失敗しました", "waiting");
      return;
    }

    // 標準様式の見た目の「編集フォーム」で前面に出す（保育士が自由に直せる＝要望の核）。
    let formMeta = {};
    try {
      formMeta = await adk.getFormMeta();
    } catch {
      /* タグ語彙の取得に失敗しても編集自体は可能（既存タグはそのまま保持） */
    }
    const docKind = st.final_doc_kind || kind;
    const editor = renderEditableDoc({ kind: docKind, entry, formMeta });

    const v = el("div", "validation");
    setValidation(v, st.validation || []);
    editor.panel._body.appendChild(v);

    const preview = renderPreview(doc); // 整形テキスト（コピー・印刷用）は畳んで添える
    editor.panel._body.appendChild(preview);

    pdfDownloadRow(editor, docKind); // 園の帳票PDF（現場でそのまま綴じる最終形）は承認後も残す
    editBar(sessionId, st, editor, v, preview, docKind);
    // アーカイブ状態の表示行（保存/承認のたびに更新。skipped/error も正直に出す＝偽の緑を出さない）。
    const archNote = el("div", "persist-note archive-note");
    editor.panel._archNote = archNote;
    editor.panel._body.appendChild(archNote);
    area.appendChild(editor.panel);

    procStop("AI のやりとり（経過）");
    stepper.allDone();
    phase("保育士の確認・編集をお待ちしています", "waiting");

    // AI 確定版を書類アーカイブへ保存（Phase 1・author_kind=ai。表示より後＝UI をブロックしない）。
    setArchiveNote(archNote, await adk.saveRecord(docKind, entry, doc, "ai", actorName()), "確定下書きの保存");
  }

  // アーカイブ（書類の永続保存）の結果表示。saved/approved＝済・skipped＝未接続降格・error＝失敗。
  function setArchiveNote(node, res, label) {
    if (!node || !res) return;
    if (res.status === "saved") {
      node.innerHTML = `${iconHTML("check")}アーカイブに保存しました（版 ${res.version_seq}${res.doc_status === "approved" ? "・承認済み書類" : ""}）`;
    } else if (res.status === "approved") {
      node.innerHTML = `${iconHTML("check")}承認をアーカイブに記録しました（承認証跡）`;
    } else if (res.status === "skipped") {
      node.innerHTML = `${iconHTML("info")}アーカイブ未接続（DATABASE_URL 未設定）＝この書類は DB に永続保存されません`;
    } else {
      node.innerHTML = `${iconHTML("alert")}${esc(label)}に失敗: ${esc(res.detail || "原因不明")}`;
    }
  }

  // validation チップの中身を（保存後も）更新する。
  function setValidation(node, problems) {
    node.className = "validation " + (problems.length ? "ng" : "ok");
    node.innerHTML = problems.length
      ? `${iconHTML("alert")}必須項目の不足: ${esc(problems.join(" / "))}`
      : `${iconHTML("check")}必須項目を満たしています`;
  }

  // 園の帳票PDF（現場でそのまま綴じる最終形）をダウンロードする永続アクション行。
  // editBar は承認時に clear されるため、ここは別行にして下書き段でも承認後でも押せるようにする。
  function pdfDownloadRow(editor, docKind) {
    const row = el("div", "doc-actions");
    const btn = el("button", "btn btn-ghost btn-sm", `${iconHTML("download")}帳票PDFをダウンロード`);
    btn.type = "button";
    btn.title = "園の様式（帳票）の PDF を保存します";
    btn.onclick = async () => {
      btn.disabled = true;
      const orig = btn.innerHTML;
      btn.innerHTML = `<span class="spinner"></span>PDFを作成中…`;
      try {
        const { blob, filename } = await adk.exportPdf(docKind, editor.collect());
        const url = URL.createObjectURL(blob);
        const a = el("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (e) {
        banner(area, "err", "帳票PDFの作成に失敗: " + e.message);
      } finally {
        btn.disabled = false;
        btn.innerHTML = orig;
      }
    };
    row.appendChild(btn);
    editor.panel._body.appendChild(row);
  }

  // 整形テキスト（write_draft の出力）をコピー・印刷用に畳んで添える。
  function renderPreview(formatted) {
    const d = el("details", "proc de-preview");
    const sum = el("summary", "proc-sum");
    sum.innerHTML = `<span class="proc-label">整形テキスト（コピー・印刷用）</span><span class="proc-hint">開く</span>`;
    const body = el("div", "proc-body");
    const pre = el("pre", "de-pre");
    pre.textContent = formatted;
    body.appendChild(pre);
    d.append(sum, body);
    d._pre = pre;
    return d;
  }

  // 確定・承認後に編集を凍結し「公式記録」表示にする。
  function lockEditor(panel) {
    panel.querySelectorAll("input, textarea, select, .de-tag, .de-add, .de-rm").forEach((n) => {
      n.setAttribute("disabled", "");
      n.classList.add("locked");
    });
    const lbl = panel.querySelector(".label-draft");
    if (lbl) {
      lbl.className = "label-final";
      lbl.innerHTML = `${iconHTML("check")}公式記録`;
    }
  }

  // 編集バー：保存して再チェック（harness で再 validate/整形）＋ 確定・承認（真の承認ゲート）。
  function editBar(sessionId, st, editor, vNode, preview, docKind) {
    const bar = el("div", "approve-bar");
    const mem = adk.config().memory_connected;
    const note = el("span", "persist-note", "編集して「保存して再チェック」または「確定・承認」を押せます");

    // 編集後 entry を harness で再検査・再整形し、結果を state へ反映する（型成立ゲートを編集後も効かせる）。
    async function save() {
      const entry = editor.collect();
      const res = await adk.finalizeEdit(docKind, entry, entry.date || null);
      if (res.parse_error) {
        // 構造化に失敗（通常の編集フォームでは到達しないが、偽の緑を出さず正直に失敗を出す）。
        vNode.className = "validation ng";
        vNode.innerHTML = `${iconHTML("alert")}保存できませんでした: ${esc(res.parse_error)}`;
        throw new Error(res.parse_error);
      }
      const problems = res.problems || [];
      // 先に state へ反映する（patchState は失敗時 throw＝UI を緑にしない）。型成立ゲートは編集後の値で評価される。
      await adk.patchState(sessionId, {
        final_entry: entry,
        final_document: res.formatted,
        validation: problems,
      });
      setValidation(vNode, problems);
      if (preview._pre && res.formatted) preview._pre.textContent = res.formatted;
      // 編集内容を書類アーカイブにも版として積む（author_kind=caregiver＝AIとの修正差分が残る）。
      // アーカイブ失敗は本流（state 保存）を壊さず、表示行で正直に知らせる。
      setArchiveNote(
        editor.panel._archNote,
        await adk.saveRecord(docKind, entry, res.formatted, "caregiver", actorName()),
        "編集内容のアーカイブ保存",
      );
      return res;
    }

    const saveBtn = el("button", "btn btn-ghost btn-sm", `${iconHTML("check")}保存して再チェック`);
    saveBtn.type = "button";
    saveBtn.onclick = async () => {
      saveBtn.disabled = true;
      try {
        const res = await save();
        note.textContent = res.ok
          ? "保存しました（必須項目OK）。よければ「確定・承認」へ。"
          : "保存しました。必須項目に不足があります（確定はできますが、確認をおすすめします）。";
      } catch (e) {
        banner(area, "err", "再チェックに失敗: " + e.message);
      } finally {
        saveBtn.disabled = false;
      }
    };

    const approveBtn = el("button", "btn btn-approve", `${iconHTML("check")}この内容で確定・承認する`);
    approveBtn.type = "button";
    approveBtn.onclick = async () => {
      approveBtn.disabled = true;
      saveBtn.disabled = true;
      try {
        await save(); // 直前の編集を必ず保存・再検査してから承認する
        await adk.patchState(sessionId, { caregiver_approved: true });
        // 承認証跡をアーカイブに記録（誰が承認したか＝担当者名。ADK state の承認と並走）。
        setArchiveNote(
          editor.panel._archNote,
          await adk.approveRecord(docKind, editor.collect(), actorName()),
          "承認記録",
        );
        lockEditor(editor.panel);
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
      } catch (e) {
        approveBtn.disabled = false;
        saveBtn.disabled = false;
        banner(area, "err", "確定に失敗: " + e.message);
      }
    };

    bar.append(saveBtn, approveBtn, note);
    editor.panel._body.appendChild(bar);
  }

  return { run };
}
