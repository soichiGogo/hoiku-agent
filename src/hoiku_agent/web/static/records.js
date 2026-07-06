// 書類を見る＝アーカイブ閲覧タブ。ファイルシステム風のツリー（種別→子ども→書類）で確定書類を辿る。
// 生成ロジックは持たない＝harness/record_store の読取 API（/api/records・/api/records/{id}）を叩くだけ（§5/§11）。
//
// 表示に必要な分だけ取りに行く：
//  - タブを開いたら `/api/records` のメタ一覧（本文なし・軽い）を1回だけ取得しツリーをクライアント構築する。
//  - 折りたたみが既定で、展開したフォルダの DOM だけを都度組む（初期描画は種別フォルダのみ＝最速）。
//  - 書類の本文（重い・整形テキスト＋entry）は「ファイルを開いたとき」だけ /api/records/{id} を引き、
//    セッション内はキャッシュして再取得しない（更新反映は再読込＝タブ再オープン時にキャッシュを捨てる）。
//
// アップロード取込（§11）：ファイルシステムの階層＝種別で「取り込む」。各種別フォルダ（＋その下の子ども
// フォルダ）を開くと先頭に「取り込む」アクションが出て、そこから kind（と personal 種別なら child）が
// 場所から決まる。解析（LLM＝/api/parse-upload）→ 既存の標準様式編集フォーム（docedit.js）で確認・修正 →
// finalize-edit で再検査 → /api/records（author_kind=imported）で保存。検査・整形・保存の決定的実体は
// harness に1つ（ここは中継・描画のみ＝§5）。保存先が未接続のときは取り込めない（正直に降格）。
import * as adk from "./adk.js";
import { renderEditableDoc } from "./docedit.js";
import { actorName, banner, el, esc, iconHTML } from "./ui.js";

const KIND_LABEL = { diary: "保育日誌", monthly: "個別月案", class_monthly: "クラス月案", child_record: "保育経過記録", nursery_record: "保育要録" };
const KIND_ICON = { diary: "diary", monthly: "calendar", class_monthly: "calendar", child_record: "chart", nursery_record: "chart" };
// 第1階層（種別フォルダ）の並び順＝集積階層の順（日誌→クラス月案→保育経過記録→要録）。月案は
// 書類作成がクラス月案に一本化されたため、常時フォルダはクラス月案に統合する。旧・個別月案（monthly）は
// 常時表示から外す＝過去に取り込んだ個別月案が残っていれば末尾に閲覧のみで出る（KIND_LABEL は温存）。
const TYPE_ORDER = ["diary", "class_monthly", "child_record", "nursery_record"];
const NO_CHILD = ""; // child なしの書類は「クラス全体」フォルダへ。

// アップロード取込の種別別メタ：対象キーの入力（ラベル・input type・placeholder）と、child/年齢帯の要否。
// diary・class_monthly はクラス単位（child を取らない）・nursery_record は年長固定（年齢帯を取らない・常に 3-5）。
// 旧・個別月案（monthly）は取込対象から外す（書類作成がクラス月案に一本化＝統合）。
const UPLOAD_META = {
  diary: { targetLabel: "対象日", inputType: "date", placeholder: "", wantsChild: false, wantsAge: true },
  class_monthly: { targetLabel: "対象月", inputType: "month", placeholder: "", wantsChild: false, wantsAge: true },
  child_record: { targetLabel: "対象期間", inputType: "text", placeholder: "例: 2026-04〜2026-06", wantsChild: true, wantsAge: true },
  nursery_record: { targetLabel: "対象年度", inputType: "text", placeholder: "例: 2026", wantsChild: true, wantsAge: false },
};
const ACCEPT = ".pdf,.docx,.xlsx";

// record_store.store_status は disabled/ok/unavailable を返す（policy/notation の persistent 系とは別語彙）。
const STORE_LABEL = {
  ok: "保存先: 接続済み",
  disabled: "保存先: 未接続",
  unavailable: "保存先: 接続エラー",
};
const STORE_CLASS = { ok: "ok", disabled: "muted", unavailable: "warn" };

export function makeRecords(ui) {
  // ui = { tree, store, detail }
  const bodyCache = new Map(); // id -> 本文（現行版・整形テキスト＋entry）。タブ再オープンで捨てる。
  const expanded = new Set(); // 展開中フォルダの key（再読込を跨いで保持＝辿り位置を失わない）。
  let selectedId = null;
  let docs = []; // メタ一覧（本文なし）。
  let formMeta = null; // 編集フォームのタグ語彙（/api/form-meta・遅延取得）。
  let docTemplates = null; // 様式テンプレート（/api/doc-template・遅延取得）。

  function setStore(s) {
    ui.store.textContent = STORE_LABEL[s] || "";
    ui.store.className = "badge " + (STORE_CLASS[s] || "muted");
  }

  function statusBadge(status) {
    const approved = status === "approved";
    return `<span class="rbadge ${approved ? "ok" : "muted"}">${approved ? "承認済み" : "確定"}</span>`;
  }

  // ── メタ一覧の取得（本文は取らない）→ ツリー再構築 ──
  async function loadTree() {
    bodyCache.clear(); // 再読込は最新を正とする（他タブの確定/編集/承認を取り込む）。
    ui.tree.innerHTML = "";
    ui.tree.appendChild(el("p", "rempty", "読み込み中…"));
    const { documents, store } = await adk.listRecords(""); // 種別で分けずに1回で引き、階層はこちらで組む。
    setStore(store);
    docs = documents;
    renderTree(store);
  }

  // フラットなメタ配列を 種別→子ども→書類 の入れ子へ畳む（描画は展開時に遅延）。
  function groupDocs(documents) {
    const byType = new Map();
    for (const d of documents) {
      if (!byType.has(d.doc_type)) byType.set(d.doc_type, new Map());
      const byChild = byType.get(d.doc_type);
      const ck = d.child || NO_CHILD;
      if (!byChild.has(ck)) byChild.set(ck, []);
      byChild.get(ck).push(d);
    }
    return byType;
  }

  // すでにアーカイブに登場した子ども名（取込フォームの候補＝datalist に使う。新規の子は手入力）。
  function knownChildren() {
    const names = new Set();
    for (const d of docs) if (d.child) names.add(d.child);
    return [...names].sort((a, b) => a.localeCompare(b, "ja"));
  }

  function renderTree(store) {
    ui.tree.innerHTML = "";
    if (store === "disabled" || store === "unavailable") {
      ui.tree.appendChild(
        el(
          "p",
          "rempty",
          store === "disabled"
            ? "書類アーカイブが未接続です（DATABASE_URL を設定すると、確定した書類がここに並び、ファイルの取り込みもできます）。"
            : "アーカイブに接続できませんでした。",
        ),
      );
      renderPlaceholder();
      return;
    }
    const byType = groupDocs(docs);
    if (!docs.length) {
      // 空でも 4 種別フォルダを取込先として常時表示する（各フォルダを開くと「取り込む」が出る）。
      ui.tree.appendChild(
        el(
          "p",
          "rempty",
          "まだ書類がありません。フォルダを開いて「取り込む」からファイルを取り込むか、「書類作成」で確定すると、ここに並びます。",
        ),
      );
    }
    // 4 種別フォルダは常に出す（空でも取込先＝ファイルシステム的に場所から種別を選ぶ）。
    for (const type of TYPE_ORDER) {
      ui.tree.appendChild(typeFolder(type, byType.get(type) || new Map()));
    }
    // 未知の doc_type も末尾に出す（種別が増えても取りこぼさない）。
    for (const [type, byChild] of byType) {
      if (!TYPE_ORDER.includes(type)) ui.tree.appendChild(typeFolder(type, byChild));
    }
    // 選択中の書類がまだ存在すれば詳細を保つ（キャッシュ）。取込フォーム表示中は保持し、消えていれば案内へ。
    if (selectedId && docs.some((d) => d.id === selectedId) && bodyCache.has(selectedId)) {
      renderDetail(bodyCache.get(selectedId));
    } else if (!ui.detail.querySelector(".rup")) {
      selectedId = null;
      renderPlaceholder();
    }
  }

  // 折りたたみ可能なフォルダ行＋遅延生成される子コンテナ。childrenBuilder は初回展開時のみ呼ぶ。
  function folderRow({ key, depth, icon, label, count, childrenBuilder }) {
    const wrap = el("div", "fsnode");
    const row = el("button", "fsrow is-folder");
    row.type = "button";
    row.style.setProperty("--depth", depth);
    const open = expanded.has(key);
    row.setAttribute("aria-expanded", String(open));
    row.innerHTML =
      `<span class="fsrow-tw">${iconHTML("chevron", "fs-chev")}</span>` +
      `<span class="fsrow-ic">${iconHTML(icon)}</span>` +
      `<span class="fsrow-label">${esc(label)}</span>` +
      `<span class="fsrow-count">${count}</span>`;
    const kids = el("div", "fsnode-kids");
    kids.hidden = !open;
    if (open) {
      childrenBuilder(kids);
      kids.dataset.built = "1";
    }
    row.onclick = () => {
      if (kids.hidden) {
        if (!kids.dataset.built) {
          childrenBuilder(kids);
          kids.dataset.built = "1";
        }
        kids.hidden = false;
        expanded.add(key);
        row.setAttribute("aria-expanded", "true");
      } else {
        kids.hidden = true;
        expanded.delete(key);
        row.setAttribute("aria-expanded", "false");
      }
    };
    wrap.append(row, kids);
    return wrap;
  }

  // 「取り込む」アクション行（フォルダの先頭に置く＝場所から kind/child が決まる）。
  function importRow(kind, child, depth, label) {
    const row = el("button", "fsrow is-import");
    row.type = "button";
    row.style.setProperty("--depth", depth);
    row.innerHTML =
      `<span class="fsrow-tw">${iconHTML("download", "fs-imp")}</span>` +
      `<span class="fsrow-label">${esc(label)}</span>`;
    row.onclick = () => openUploadForm(kind, child);
    return row;
  }

  function typeFolder(type, byChild) {
    let total = 0;
    for (const list of byChild.values()) total += list.length;
    return folderRow({
      key: `t:${type}`,
      depth: 0,
      icon: KIND_ICON[type] || "book",
      label: KIND_LABEL[type] || type,
      count: total,
      childrenBuilder: (kids) => {
        // 先頭に「この種別に取り込む」（既知種別のみ・未知 doc_type は取込対象外）。
        if (UPLOAD_META[type]) {
          kids.appendChild(importRow(type, "", 1, `${KIND_LABEL[type]}を取り込む`));
        }
        // 仮名の子を五十音、クラス全体（child なし）は末尾に。
        const keys = [...byChild.keys()].sort((a, b) =>
          a === NO_CHILD ? 1 : b === NO_CHILD ? -1 : a.localeCompare(b, "ja"),
        );
        for (const ck of keys) kids.appendChild(childFolder(type, ck, byChild.get(ck)));
      },
    });
  }

  function childFolder(type, childKey, list) {
    // 新しい対象（日付/期/月）が上。target が無ければ更新日で代替。
    const sorted = [...list].sort((a, b) =>
      (b.target || b.updated_at || "").localeCompare(a.target || a.updated_at || ""),
    );
    return folderRow({
      key: `t:${type}|c:${childKey}`,
      depth: 1,
      icon: childKey ? "caregiver" : "folder",
      label: childKey || "クラス全体",
      count: list.length,
      childrenBuilder: (kids) => {
        // 個人単位の種別（月案/保育経過記録/要録）は「この子に取り込む」を先頭に（child を場所から確定）。
        if (childKey && UPLOAD_META[type] && UPLOAD_META[type].wantsChild) {
          kids.appendChild(importRow(type, childKey, 2, `${childKey}に取り込む`));
        }
        for (const d of sorted) kids.appendChild(fileRow(d, 2));
      },
    });
  }

  function fileRow(d, depth) {
    const row = el("button", "fsrow is-file" + (d.id === selectedId ? " is-active" : ""));
    row.type = "button";
    row.dataset.id = d.id;
    row.style.setProperty("--depth", depth);
    row.innerHTML =
      `<span class="fsrow-tw"></span>` +
      `<span class="fsrow-ic">${iconHTML("file")}</span>` +
      `<span class="fsrow-label">${esc(d.target || "（対象未設定）")}` +
      `<span class="fsrow-meta">更新 ${esc((d.updated_at || "").slice(0, 10))}</span></span>` +
      statusBadge(d.status);
    row.onclick = () => select(d.id, row);
    return row;
  }

  // ── ファイル選択＝本文を開く（重い取得はここだけ・キャッシュ） ──
  async function select(id, row) {
    selectedId = id;
    ui.tree.querySelectorAll(".fsrow.is-file.is-active").forEach((n) => n.classList.remove("is-active"));
    if (row) row.classList.add("is-active");
    if (bodyCache.has(id)) {
      renderDetail(bodyCache.get(id));
      return;
    }
    ui.detail.innerHTML = "";
    ui.detail.appendChild(el("p", "rempty", "読み込み中…"));
    const doc = await adk.getRecord(id);
    if (doc) bodyCache.set(id, doc);
    if (selectedId !== id) return; // 待機中に別ファイルを開いたら描かない（取り違え防止）。
    renderDetail(doc);
  }

  function renderPlaceholder() {
    ui.detail.innerHTML =
      `<div class="fs-placeholder">${iconHTML("folder")}` +
      `<p>左のフォルダから書類を選ぶと、ここに内容と帳票PDFを表示します。フォルダを開いて「取り込む」を押すと、既存のファイル（PDF / Word / Excel）を取り込めます。</p></div>`;
  }

  function renderDetail(doc) {
    ui.detail.innerHTML = "";
    if (!doc) {
      ui.detail.appendChild(el("p", "rempty", "書類を取得できませんでした。"));
      return;
    }
    const kindLabel = KIND_LABEL[doc.doc_type] || doc.doc_type;
    const author =
      doc.author_kind === "caregiver"
        ? "保育士が編集"
        : doc.author_kind === "imported"
          ? "取り込み"
          : "AI が作成";

    const head = el("div", "rdetail-head");
    head.innerHTML =
      `<div class="card-title">${iconHTML(KIND_ICON[doc.doc_type] || "book")}` +
      `${esc(kindLabel)}　${esc(doc.target || "")}${doc.child ? "　" + esc(doc.child) : ""}</div>` +
      `<div class="rmeta">` +
      statusBadge(doc.status) +
      `<span class="rbadge muted">${esc(author)}</span>` +
      (doc.created_by ? `<span class="rmeta-actor">${iconHTML("caregiver")}${esc(doc.created_by)}</span>` : "") +
      `</div>`;
    ui.detail.appendChild(head);

    const text = (doc.rendered_text || "").trim();
    if (text) {
      const pre = el("pre", "rtext");
      pre.textContent = doc.rendered_text;
      ui.detail.appendChild(pre);
    } else {
      ui.detail.appendChild(
        el("p", "rempty", "整形テキストが保存されていません（帳票PDF では内容を確認できます）。"),
      );
    }

    // 操作：帳票PDF／編集／（未承認なら）承認。整形テキストが空でも entry から描ける。
    const act = el("div", "rdetail-act");
    const msg = el("p", "rmsg hidden");
    const btn = el("button", "btn btn-ghost btn-sm", `${iconHTML("download")}帳票PDFをダウンロード`);
    btn.type = "button";
    btn.onclick = async () => {
      btn.disabled = true;
      const orig = btn.innerHTML;
      btn.innerHTML = `<span class="spinner"></span>PDFを作成中…`;
      msg.classList.add("hidden");
      try {
        const { blob, filename } = await adk.exportPdf(doc.doc_type, doc.entry || {});
        downloadBlob(blob, filename);
      } catch (e) {
        msg.textContent = "帳票PDFの作成に失敗しました: " + e.message;
        msg.classList.remove("hidden");
      } finally {
        btn.disabled = false;
        btn.innerHTML = orig;
      }
    };
    act.append(btn);

    // 編集（保育士の編集＝新しい版を積む・harness が再検査/再整形）。docedit が対応する種別のみ。
    if (KIND_LABEL[doc.doc_type]) {
      const editBtn = el("button", "btn btn-ghost btn-sm", `${iconHTML("edit")}編集する`);
      editBtn.type = "button";
      editBtn.onclick = () => renderEditDoc(doc);
      act.append(editBtn);
    }

    // 未承認（finalized）なら承認できる（編集で失効した承認の再承認もここから＝decision A）。
    if (doc.status !== "approved") {
      const apBtn = el("button", "btn btn-ghost btn-sm", `${iconHTML("check")}承認する`);
      apBtn.type = "button";
      apBtn.onclick = async () => {
        apBtn.disabled = true;
        const o = apBtn.innerHTML;
        apBtn.innerHTML = `<span class="spinner"></span>承認中…`;
        msg.classList.add("hidden");
        try {
          const r = await adk.approveRecord(doc.doc_type, doc.entry || {}, actorName());
          if (r.status === "approved") {
            await loadTree();
            await select(doc.id, ui.tree.querySelector(`.fsrow.is-file[data-id="${doc.id}"]`) || null);
          } else {
            msg.textContent = "承認できませんでした: " + (r.detail || r.reason || "未接続/エラー");
            msg.classList.remove("hidden");
            apBtn.disabled = false;
            apBtn.innerHTML = o;
          }
        } catch (e) {
          msg.textContent = "承認に失敗: " + e.message;
          msg.classList.remove("hidden");
          apBtn.disabled = false;
          apBtn.innerHTML = o;
        }
      };
      act.append(apBtn);
    }
    act.append(msg);
    ui.detail.appendChild(act);
  }

  // ── アップロード取込（右ペインにフォームを描く） ──
  // 種別（kind）は場所（フォルダ）から確定済み。対象キー・年齢帯・（個人種別なら）対象児と、ファイルを受ける。
  function openUploadForm(kind, child) {
    selectedId = null;
    ui.tree.querySelectorAll(".fsrow.is-file.is-active").forEach((n) => n.classList.remove("is-active"));
    const meta = UPLOAD_META[kind];
    if (!meta) return;
    ui.detail.innerHTML = "";
    const wrap = el("div", "rup");
    wrap.innerHTML =
      `<div class="rup-head"><span class="card-title">${iconHTML("download")}${esc(KIND_LABEL[kind])}を取り込む</span>` +
      `<p class="rup-sub">PDF / Word(.docx) / Excel(.xlsx) を選ぶと、AI が内容を読み取って下書きにします。` +
      `内容を確認・修正してから保存すると、ほかの書類と同じように次の書類作成で参照されます。</p></div>`;

    // 対象キー入力（種別で label / input type / placeholder を切替）。
    const targetWrap = el("label", "rup-field");
    targetWrap.innerHTML = `<span class="rup-label">${esc(meta.targetLabel)}</span>`;
    const targetInput = el("input", "rup-input");
    targetInput.type = meta.inputType;
    if (meta.placeholder) targetInput.placeholder = meta.placeholder;
    targetWrap.appendChild(targetInput);
    wrap.appendChild(targetWrap);

    // 対象児（個人種別のみ・場所から prefill・編集可＝新規の子も入力できる）。
    let childInput = null;
    if (meta.wantsChild) {
      const cw = el("label", "rup-field");
      cw.innerHTML = `<span class="rup-label">対象児</span>`;
      childInput = el("input", "rup-input");
      childInput.type = "text";
      childInput.placeholder = "子どもの呼び名";
      childInput.value = child || "";
      const listId = "rup-children";
      childInput.setAttribute("list", listId);
      const dl = el("datalist");
      dl.id = listId;
      for (const n of knownChildren()) {
        const o = el("option");
        o.value = n;
        dl.appendChild(o);
      }
      cw.append(childInput, dl);
      wrap.appendChild(cw);
    }

    // 年齢帯（要録以外・タグ語彙の枠組み＝0-2:3視点 / 3-5:5領域）。
    let ageSelect = null;
    if (meta.wantsAge) {
      const aw = el("label", "rup-field");
      aw.innerHTML = `<span class="rup-label">年齢帯</span>`;
      ageSelect = el("select", "rup-input");
      ageSelect.innerHTML =
        `<option value="0-2">0〜2歳児クラス（3つの視点）</option>` +
        `<option value="3-5">3〜5歳児クラス（5領域）</option>`;
      aw.appendChild(ageSelect);
      wrap.appendChild(aw);
    }

    // ファイル選択＋ドロップゾーン（ドラッグ&ドロップでも受け取る）。
    const drop = el("div", "rup-drop");
    const fileInput = el("input");
    fileInput.type = "file";
    fileInput.accept = ACCEPT;
    fileInput.className = "rup-file";
    const dropLabel = el("p", "rup-drop-label", "ここにファイルをドラッグするか、クリックして選択");
    const chosen = el("p", "rup-chosen hidden");
    drop.append(fileInput, dropLabel, chosen);
    fileInput.onchange = () => showChosen();
    function showChosen() {
      const f = fileInput.files && fileInput.files[0];
      if (f) {
        chosen.textContent = `選択: ${f.name}`;
        chosen.classList.remove("hidden");
      } else {
        chosen.classList.add("hidden");
      }
    }
    drop.addEventListener("dragover", (e) => {
      e.preventDefault();
      drop.classList.add("over");
    });
    drop.addEventListener("dragleave", () => drop.classList.remove("over"));
    drop.addEventListener("drop", (e) => {
      e.preventDefault();
      drop.classList.remove("over");
      if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        showChosen();
      }
    });
    wrap.appendChild(drop);

    // 操作バー（解析する / キャンセル）＋メッセージ。
    const bar = el("div", "rup-actions");
    const msg = el("p", "rup-msg hidden");
    const parseBtn = el("button", "btn btn-primary btn-sm", `${iconHTML("spark")}AIで解析する`);
    parseBtn.type = "button";
    const cancelBtn = el("button", "btn btn-ghost btn-sm", "キャンセル");
    cancelBtn.type = "button";
    cancelBtn.onclick = () => renderPlaceholder();
    parseBtn.onclick = async () => {
      const file = fileInput.files && fileInput.files[0];
      if (!file) {
        showMsg(msg, "ファイルを選んでください。", true);
        return;
      }
      const target = targetInput.value.trim();
      if (!target) {
        showMsg(msg, `${meta.targetLabel}を入力してください。`, true);
        return;
      }
      const childVal = childInput ? childInput.value.trim() : "";
      if (meta.wantsChild && !childVal) {
        showMsg(msg, "対象児を入力してください。", true);
        return;
      }
      const ageBand = ageSelect ? ageSelect.value : "3-5"; // 要録は年長固定。
      parseBtn.disabled = true;
      cancelBtn.disabled = true;
      const orig = parseBtn.innerHTML;
      parseBtn.innerHTML = `<span class="spinner"></span>AIが読み取り中…`;
      showMsg(msg, "", false);
      const res = await adk.parseUpload(kind, { target, child: childVal, ageBand }, file);
      parseBtn.disabled = false;
      cancelBtn.disabled = false;
      parseBtn.innerHTML = orig;
      if (res.error) {
        showMsg(msg, res.error, true);
        return;
      }
      await renderConfirm(kind, res);
    };
    bar.append(parseBtn, cancelBtn, msg);
    wrap.appendChild(bar);

    ui.detail.appendChild(wrap);
    targetInput.focus();
  }

  // 標準様式の編集フォーム（docedit.js）＋検査＋保存バーを ui.detail に描く共通処理。
  // 取込確認（author_kind=imported）とアーカイブ書類の編集（author_kind=caregiver）で共用する。
  // opts: { title, sub, saveLabel, authorKind, note, initialProblems, initialParseError, focusKey }
  async function mountEditor(kind, entry, opts) {
    if (formMeta === null || docTemplates === null) {
      try {
        [formMeta, docTemplates] = await Promise.all([adk.getFormMeta(), adk.getDocTemplate()]);
      } catch {
        formMeta = formMeta || {};
        docTemplates = docTemplates || { templates: {} };
      }
    }
    const template = (docTemplates.templates || {})[kind] || null;
    const editor = renderEditableDoc({ kind, entry: entry || {}, formMeta, template });

    ui.detail.innerHTML = "";
    const head = el("div", "rup-head");
    head.innerHTML =
      `<span class="card-title">${iconHTML("edit")}${esc(opts.title)}</span>` +
      `<p class="rup-sub">${esc(opts.sub)}</p>`;
    ui.detail.appendChild(head);
    if (opts.initialParseError) banner(ui.detail, "err", "AI 解析: " + opts.initialParseError);
    ui.detail.appendChild(editor.panel);

    const vNode = el("div", "validation");
    setValidation(vNode, opts.initialProblems || [], opts.initialParseError);
    editor.panel._body.appendChild(vNode);

    const bar = el("div", "approve-bar");
    const note = el("span", "persist-note", opts.note || "内容を確認・修正して保存してください。");
    const recheck = el("button", "btn btn-ghost btn-sm", `${iconHTML("shield")}再チェック`);
    recheck.type = "button";
    const saveBtn = el("button", "btn btn-approve", `${iconHTML("check")}${opts.saveLabel}`);
    saveBtn.type = "button";

    async function revalidate() {
      const e = editor.collect();
      const r = await adk.finalizeEdit(kind, e, null);
      setValidation(vNode, r.problems || [], r.parse_error);
      return { entry: e, ...r };
    }

    recheck.onclick = async () => {
      recheck.disabled = true;
      try {
        const r = await revalidate();
        note.textContent = r.ok
          ? "必須項目OK。よければ保存へ。"
          : "必須項目に不足があります（保存はできますが、確認をおすすめします）。";
      } catch (e) {
        note.textContent = "再チェックに失敗: " + e.message;
      } finally {
        recheck.disabled = false;
      }
    };

    saveBtn.onclick = async () => {
      saveBtn.disabled = true;
      recheck.disabled = true;
      try {
        const r = await revalidate();
        if (r.parse_error) {
          banner(ui.detail, "err", "保存できませんでした: " + r.parse_error);
          saveBtn.disabled = false;
          recheck.disabled = false;
          return;
        }
        const saved = await adk.saveRecord(kind, r.entry, r.formatted, opts.authorKind, actorName());
        if (saved.status === "saved") {
          await loadTree(); // ツリーを最新化（保存した版が反映＝以後 seed 参照可能）。
          const id = saved.document_id;
          const row = id ? ui.tree.querySelector(`.fsrow.is-file[data-id="${id}"]`) : null;
          if (id) await select(id, row || null); // 保存後は読取ビューへ（現行版を表示）。
        } else if (saved.status === "skipped") {
          banner(ui.detail, "err", "保存先が未接続のため保存できませんでした（DATABASE_URL を設定してください）。");
          saveBtn.disabled = false;
          recheck.disabled = false;
        } else {
          banner(ui.detail, "err", "保存に失敗: " + (saved.detail || "不明なエラー"));
          saveBtn.disabled = false;
          recheck.disabled = false;
        }
      } catch (e) {
        banner(ui.detail, "err", "保存に失敗: " + e.message);
        saveBtn.disabled = false;
        recheck.disabled = false;
      }
    };

    bar.append(recheck, saveBtn, note);
    editor.panel._body.appendChild(bar);

    // 指定欄へスクロール＋フォーカス（例: 評価・反省の記入導線＝クラス月案から飛んできた場合）。
    if (opts.focusKey) {
      const sec = editor.panel.querySelector(`[data-section-key="${opts.focusKey}"]`);
      if (sec) {
        sec.scrollIntoView({ behavior: "smooth", block: "center" });
        const first = sec.querySelector("textarea, input");
        if (first) first.focus();
      }
    }
  }

  // 取込：解析結果を確認・修正 → 保存（author_kind=imported＝AI 生成でも保育士編集でもない第三の来歴）。
  async function renderConfirm(kind, res) {
    await mountEditor(kind, res.entry || {}, {
      title: `${KIND_LABEL[kind]}を確認・修正`,
      sub: "AI が読み取った内容です。日付・子ども・タグや本文を直してから保存してください（保存時の検査・整形は harness が行います）。",
      saveLabel: "取り込んで保存する",
      authorKind: "imported",
      note: "内容を確認・修正して「取り込んで保存」を押してください。",
      initialProblems: res.problems || [],
      initialParseError: res.parse_error,
    });
  }

  // アーカイブ済み書類の編集（author_kind=caregiver＝保育士の編集）。承認済みは編集で失効し再承認が要る。
  function renderEditDoc(doc, { focusKey } = {}) {
    return mountEditor(doc.doc_type, doc.entry || {}, {
      title: `${KIND_LABEL[doc.doc_type] || doc.doc_type}を編集`,
      sub: "内容を直して保存すると、新しい版として記録されます（承認済みの場合は、編集後にもう一度承認が必要です）。",
      saveLabel: "保存する",
      authorKind: "caregiver",
      note: "内容を直して「保存する」を押してください。",
      focusKey,
    });
  }

  // 必須項目の不足（problems）／構造化失敗（parse_error）を正直に描く（偽の緑を出さない）。
  function setValidation(node, problems, parseError) {
    if (parseError) {
      node.className = "validation ng";
      node.innerHTML = `${iconHTML("alert")}構造化に失敗: ${esc(parseError)}`;
      return;
    }
    if (!problems || !problems.length) {
      node.className = "validation ok";
      node.innerHTML = `${iconHTML("check")}必須項目は満たしています`;
      return;
    }
    node.className = "validation ng";
    node.innerHTML =
      `${iconHTML("alert")}確認してください（${problems.length}件）` +
      `<ul>${problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ul>`;
  }

  function showMsg(node, text, isErr) {
    node.textContent = text;
    node.className = "rup-msg" + (isErr ? " err" : "") + (text ? "" : " hidden");
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = el("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function init() {
    renderPlaceholder();
    await loadTree();
  }

  // 特定の書類（id）を外（別タブ）から開く導線。edit=true なら編集フォームで開き、focus 指定の欄へ寄せる
  // （クラス月案作成時の「評価未記入の日誌へ飛んで記入」＝Slice4 が使う）。ツリー未取得なら先に読み込む。
  async function openDoc(id, { edit = false, focus = null } = {}) {
    if (!docs.length) await loadTree();
    selectedId = id;
    ui.tree.querySelectorAll(".fsrow.is-file.is-active").forEach((n) => n.classList.remove("is-active"));
    let doc = bodyCache.get(id);
    if (!doc) {
      ui.detail.innerHTML = "";
      ui.detail.appendChild(el("p", "rempty", "読み込み中…"));
      doc = await adk.getRecord(id);
      if (doc) bodyCache.set(id, doc);
    }
    if (!doc) {
      renderDetail(null);
      return false;
    }
    const row = ui.tree.querySelector(`.fsrow.is-file[data-id="${id}"]`);
    if (row) row.classList.add("is-active"); // 展開済みフォルダにあればハイライト。
    if (edit) renderEditDoc(doc, { focusKey: focus });
    else renderDetail(doc);
    return true;
  }

  // タブを開くたびに最新化する（他タブで確定した書類がすぐ反映される）。
  return { init, refresh: loadTree, openDoc };
}
