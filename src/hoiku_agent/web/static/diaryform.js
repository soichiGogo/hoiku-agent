// 保育日誌＝保育士の手入力フォーム（AI 生成はしない＝ヒアリング 2026-07：日誌は自分の言葉で打つ一次情報の
// 蓄積口）。クラスを選ぶと在籍児が児童ごとの欄に並び、共通欄はまとめて記録する。検査・整形・保存・帳票は
// 既存の決定的経路（docedit の編集フォーム＋/api/finalize-edit＋/api/records＋帳票PDF/Word）をそのまま再利用する
// ＝AI を一切通さない（§5/§11）。表記の統一（子供→子ども）は finalize が決定的に当てる。ADK セッションは使わない
// （生成パイプラインを迂回するため）＝承認はアーカイブの承認証跡で残す（Memory Bank 書き戻しは手入力では発火しない）。
import * as adk from "./adk.js";
import { el, esc, iconHTML, banner, actorName, makeDocumentCompletion } from "./ui.js";
import { renderEditableDoc } from "./docedit.js";

const KIND = "diary";

// 児童ごとの空欄（姿・タグ・生活記録）。保育士がここに手入力する。
function blankNote(name) {
  return {
    child_id: name,
    age_months: "",
    observed_state: "",
    tags: [],
    life_record: { meal: "", sleep: "", toilet: "", mood_health: "" },
    individual_aim: "",
  };
}

// 校正提案をパス（例 "individual_notes[0].observed_state"）で entry の該当フィールドへ反映する。
function setByPath(obj, path, value) {
  const tokens = path.replace(/\[(\d+)\]/g, ".$1").split(".");
  let node = obj;
  for (let i = 0; i < tokens.length - 1; i++) {
    if (node == null) return;
    node = node[tokens[i]];
  }
  if (node != null) node[tokens[tokens.length - 1]] = value;
}

// クラスの在籍児（roster）から空の日誌 entry を組む。共通欄は空・出欠と個別記録は在籍児ぶん並べる。
function blankEntry({ className, ageBand, date, roster }) {
  const names = roster || [];
  return {
    date,
    age_band: ageBand || "0-2",
    weather: "",
    temperature: "",
    class_name: className || "",
    daily_aim: "",
    practice_record: "",
    health_notes: null,
    parent_contact: null,
    attendance: names.map((n) => ({ child_id: n, present: true, reason: null })),
    individual_notes: names.map(blankNote),
    evaluation: { child_focus: "", self_review: "" },
  };
}

export function makeDiaryForm({ area, status, onNewDocument }) {
  // 承認済み＝公式記録にロック済みか。校正AIの「提案を反映」は render() でフォームを作り直すため、
  // 承認後に押されると全欄が編集可能へ戻ってしまう。承認時にこのフラグを立て、再マウント時に再ロックする。
  let approved = false;

  // 必須項目の充足チェックの見た目（保存＝再チェックのたびに更新）。
  function setValidation(node, problems, checked) {
    if (!checked) {
      node.className = "validation";
      node.innerHTML = `${iconHTML("info")}記入後「保存して再チェック」で必須項目を確認します`;
      return;
    }
    node.className = "validation " + (problems.length ? "ng" : "ok");
    node.innerHTML = problems.length
      ? `${iconHTML("alert")}必須項目の不足: ${esc(problems.join(" / "))}`
      : `${iconHTML("check")}必須項目を満たしています`;
  }

  // アーカイブ（保存/承認）の結果を正直に表示（saved/approved＝済・skipped＝未接続・error＝失敗）。
  function setArchiveNote(node, res, label) {
    if (!node || !res) return;
    node.hidden = false;
    if (res.status === "saved") {
      node.innerHTML = `${iconHTML("check")}アーカイブに保存しました（版 ${res.version_seq}${res.doc_status === "approved" ? "・承認済み書類" : ""}）`;
    } else if (res.status === "approved") {
      node.innerHTML = "";
      node.hidden = true;
    } else if (res.status === "skipped") {
      node.innerHTML = `${iconHTML("info")}アーカイブ未接続（DATABASE_URL 未設定）＝この日誌は DB に永続保存されません`;
    } else {
      node.innerHTML = `${iconHTML("alert")}${esc(label)}に失敗: ${esc(res.detail || "原因不明")}`;
    }
  }

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = el("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function downloadButton(label, busyLabel, errLabel, fetcher) {
    const btn = el("button", "btn btn-ghost btn-sm", `${iconHTML("download")}${label}`);
    btn.type = "button";
    btn.onclick = async () => {
      btn.disabled = true;
      const orig = btn.innerHTML;
      btn.innerHTML = `<span class="spinner"></span>${busyLabel}`;
      try {
        const { blob, filename } = await fetcher();
        saveBlob(blob, filename);
      } catch (e) {
        banner(area, "err", errLabel + ": " + e.message);
      } finally {
        btn.disabled = false;
        btn.innerHTML = orig;
      }
    };
    return btn;
  }

  async function open(seed) {
    area.innerHTML = "";
    approved = false; // 新しい日誌を開くたびにロック状態をリセットする
    if (status) status.setSubject(seed.className || "クラス");

    // タグ語彙・様式テンプレ（本文セクションの順序/ラベル）を取得（失敗しても編集自体は可能）。
    let formMeta = {};
    let docTemplate = { templates: {} };
    try {
      [formMeta, docTemplate] = await Promise.all([adk.getFormMeta(), adk.getDocTemplate()]);
    } catch {
      /* 取得失敗でも既定順で編集できる */
    }
    const template = (docTemplate.templates || {})[KIND] || null;
    render(blankEntry(seed), formMeta, template, !(seed.roster || []).length);
  }

  // フォームを（再）マウントする。校正提案の反映時は patch した entry で呼び直す（1回の再描画）。
  function render(entry, formMeta, template, rosterEmpty) {
    area.innerHTML = "";
    const editor = renderEditableDoc({ kind: KIND, entry, formMeta, template });

    // 手入力であることを明示する見出し（AI 生成でない＝自分の言葉で書く一次情報）。
    const head = el("div", "diaryform-head");
    head.innerHTML =
      `${iconHTML("edit")}<b>保育日誌（手入力）</b>` +
      `<span class="df-sub">共通欄はまとめて、児童ごとは在籍児の欄に記録します。フォームで子どもの追加・削除もできます。</span>`;
    editor.panel._body.prepend(head);

    const vNode = el("div", "validation");
    setValidation(vNode, [], false);
    editor.panel._body.appendChild(vNode);

    // 承認済み＝公式記録へロック（入力欄＋校正AIボタン＋提案一覧を無効化）。校正の「提案を反映」が
    // フォームを作り直しても、承認中はこの関数で再ロックし編集可能へ戻さない（docflow のロックと同じ一貫性）。
    function lockForm() {
      editor.panel
        .querySelectorAll("input, textarea, select, .de-tag, .de-add, .de-rm")
        .forEach((n) => {
          n.setAttribute("disabled", "");
          n.classList.add("locked");
        });
      proofBtn.disabled = true;
      proofList.innerHTML = "";
    }

    // 校正AI（日本語チェック・言い換え提案）＝提案のみ・採否は保育士（自動書換はしない・自分の言葉を尊重）。
    const proof = el("div", "proofread");
    const proofBtn = el("button", "btn btn-ghost btn-sm", `${iconHTML("spark")}日本語をチェック（AI）`);
    proofBtn.type = "button";
    proofBtn.title = "手入力した文章の誤り・不自然さ・言い換えをAIが提案します（採否はあなたが決めます）";
    const proofList = el("div", "proof-list");
    proofBtn.onclick = async () => {
      proofBtn.disabled = true;
      const orig = proofBtn.innerHTML;
      proofBtn.innerHTML = `<span class="spinner"></span>チェック中…`;
      try {
        const res = await adk.proofread(KIND, editor.collect());
        renderSuggestions(res);
      } finally {
        proofBtn.disabled = false;
        proofBtn.innerHTML = orig;
      }
    };
    proof.append(proofBtn, proofList);
    editor.panel._body.appendChild(proof);

    // 提案を欄ごとに描く（元→提案＋理由・反映チェック）。反映は選んだ分だけ entry に当てて1回で再描画。
    function renderSuggestions(res) {
      proofList.innerHTML = "";
      if (res.error) {
        proofList.appendChild(el("p", "proof-note err", esc(res.error)));
        return;
      }
      const sugs = res.suggestions || [];
      if (!sugs.length) {
        proofList.appendChild(
          el(
            "p",
            "proof-note ok",
            `${iconHTML("check")}気になる日本語は見つかりませんでした（${res.checked || 0}文をチェック）`,
          ),
        );
        return;
      }
      const checks = [];
      sugs.forEach((s) => {
        const card = el("div", "proof-card");
        card.innerHTML =
          `<div class="proof-label">${esc(s.label)}</div>` +
          `<div class="proof-diff"><span class="proof-orig">${esc(s.original)}</span>` +
          `<span class="narr" aria-hidden="true">→</span><span class="proof-new">${esc(s.suggestion)}</span></div>` +
          (s.reason ? `<div class="proof-reason">${esc(s.reason)}</div>` : "");
        const cb = el("input");
        cb.type = "checkbox";
        cb.checked = true;
        const lab = el("label", "proof-check", "");
        lab.append(cb, el("span", "", "この提案を反映する"));
        card.appendChild(lab);
        checks.push({ s, cb });
        proofList.appendChild(card);
      });
      const applyBtn = el("button", "btn btn-primary btn-sm", `${iconHTML("check")}選んだ提案を反映`);
      applyBtn.type = "button";
      applyBtn.onclick = () => {
        const patched = editor.collect(); // 現在のフォーム値を丸ごと拾ってから提案を当てる（他欄を壊さない）
        checks.forEach(({ s, cb }) => {
          if (cb.checked) setByPath(patched, s.path, s.suggestion);
        });
        render(patched, formMeta, template, false); // patch した entry で1回だけ再描画
      };
      const closeBtn = el("button", "btn btn-ghost btn-sm", "閉じる");
      closeBtn.type = "button";
      closeBtn.onclick = () => (proofList.innerHTML = "");
      const actionsRow = el("div", "proof-actions");
      actionsRow.append(applyBtn, closeBtn);
      proofList.appendChild(actionsRow);
    }

    // 帳票PDF・Word（園の様式で綴じる/編集する最終形）。承認後も押せるよう独立行に置く。
    const actions = el("div", "doc-actions");
    actions.appendChild(
      downloadButton("帳票PDFをダウンロード", "PDFを作成中…", "帳票PDFの作成に失敗", () =>
        adk.exportPdf(KIND, editor.collect()),
      ),
    );
    const docxKinds = (adk.config() && adk.config().docx_kinds) || [];
    if (docxKinds.includes(KIND)) {
      actions.appendChild(
        downloadButton("Word様式でダウンロード", "Wordを作成中…", "Word様式の作成に失敗", () =>
          adk.exportDocx(KIND, editor.collect()),
        ),
      );
    }
    editor.panel._body.appendChild(actions);

    const archNote = el("div", "persist-note archive-note");
    editor.panel._body.appendChild(archNote);

    // 保存＝harness で再検査・再整形（表記正規化含む）→ アーカイブに版を積む（author_kind=caregiver＝
    // 手入力／編集の来歴）。ADK セッションは使わない（生成パイプラインを迂回する手入力経路）。
    async function save() {
      const entryNow = editor.collect();
      const res = await adk.finalizeEdit(KIND, entryNow, entryNow.date || null);
      if (res.parse_error) {
        vNode.className = "validation ng";
        vNode.innerHTML = `${iconHTML("alert")}保存できませんでした: ${esc(res.parse_error)}`;
        throw new Error(res.parse_error);
      }
      const problems = res.problems || [];
      setValidation(vNode, problems, true);
      const archive = await adk.saveRecord(
        KIND,
        entryNow,
        res.formatted,
        "caregiver",
        actorName(),
      );
      setArchiveNote(
        archNote,
        archive,
        "日誌のアーカイブ保存",
      );
      return { ...res, archive };
    }

    const bar = el("div", "approve-bar");
    const note = el("span", "persist-note", "");
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
        const saved = await save(); // 直前の編集を必ず保存・再検査してから承認する
        const approval = await adk.approveRecord(
          KIND,
          editor.collect(),
          actorName(),
          saved.archive && saved.archive.version_seq,
        );
        if (approval.status !== "approved") {
          throw new Error(approval.detail || "承認できませんでした");
        }
        approved = true;
        lockForm(); // 入力欄＋校正AIボタン＋提案一覧を無効化（校正経由の巻き戻しを防ぐ）
        bar.innerHTML = "";
        // 内部の保存・Memory Bank・監査ログは従来どおり実行するが、完了画面では説明しない。
        archNote.hidden = true;
        bar.appendChild(makeDocumentCompletion(onNewDocument));
        status.setPhase("確定しました", "done");
      } catch (e) {
        approveBtn.disabled = false;
        saveBtn.disabled = false;
        banner(area, "err", "確定に失敗: " + e.message);
      }
    };
    bar.append(saveBtn, approveBtn, note);
    editor.panel._body.appendChild(bar);

    area.appendChild(editor.panel);
    if (approved) lockForm(); // 承認済みのまま再マウントされたら（校正反映等）即ロックへ戻す
    if (rosterEmpty) {
      banner(
        area,
        "info",
        "在籍児がまだいません。フォームの「子どもを追加」で記録する子を足すか、「クラス・園児」タブでクラスに園児を登録してください。",
      );
    }
  }

  return { open };
}
