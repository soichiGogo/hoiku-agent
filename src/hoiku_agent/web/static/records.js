// 書類を見る＝アーカイブ閲覧タブ。ファイルシステム風のツリー（種別→子ども→書類）で確定書類を辿る。
// 生成ロジックは持たない＝harness/record_store の読取 API（/api/records・/api/records/{id}）を叩くだけ（§5/§11）。
//
// 表示に必要な分だけ取りに行く：
//  - タブを開いたら `/api/records` のメタ一覧（本文なし・軽い）を1回だけ取得しツリーをクライアント構築する。
//  - 折りたたみが既定で、展開したフォルダの DOM だけを都度組む（初期描画は種別フォルダのみ＝最速）。
//  - 書類の本文（重い・整形テキスト＋entry）は「ファイルを開いたとき」だけ /api/records/{id} を引き、
//    セッション内はキャッシュして再取得しない（更新反映は再読込＝タブ再オープン時にキャッシュを捨てる）。
import * as adk from "./adk.js";
import { el, esc, iconHTML } from "./ui.js";

const KIND_LABEL = { diary: "保育日誌", monthly: "個別月案", child_record: "児童票", nursery_record: "保育要録" };
const KIND_ICON = { diary: "diary", monthly: "calendar", child_record: "chart", nursery_record: "chart" };
// 第1階層（種別フォルダ）の並び順＝集積階層の順（日誌→月案→児童票→要録）。
const TYPE_ORDER = ["diary", "monthly", "child_record", "nursery_record"];
const NO_CHILD = ""; // child なしの書類は「クラス全体」フォルダへ。

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

  function renderTree(store) {
    ui.tree.innerHTML = "";
    if (store === "disabled" || store === "unavailable") {
      ui.tree.appendChild(
        el(
          "p",
          "rempty",
          store === "disabled"
            ? "書類アーカイブが未接続です（DATABASE_URL を設定すると、確定した書類がここに並びます）。"
            : "アーカイブに接続できませんでした。",
        ),
      );
      renderPlaceholder();
      return;
    }
    if (!docs.length) {
      ui.tree.appendChild(
        el("p", "rempty", "保存された書類がありません。「書類を作る」で確定すると、ここに並びます。"),
      );
      renderPlaceholder();
      return;
    }
    const byType = groupDocs(docs);
    for (const type of TYPE_ORDER) {
      if (byType.has(type)) ui.tree.appendChild(typeFolder(type, byType.get(type)));
    }
    // 未知の doc_type も末尾に出す（種別が増えても取りこぼさない）。
    for (const [type, byChild] of byType) {
      if (!TYPE_ORDER.includes(type)) ui.tree.appendChild(typeFolder(type, byChild));
    }
    // 選択中の書類がまだ存在すれば詳細を保つ（キャッシュ）。消えていれば案内に戻す。
    if (selectedId && docs.some((d) => d.id === selectedId) && bodyCache.has(selectedId)) {
      renderDetail(bodyCache.get(selectedId));
    } else {
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
      `<p>左のフォルダから書類を選ぶと、ここに内容と帳票PDFを表示します。</p></div>`;
  }

  function renderDetail(doc) {
    ui.detail.innerHTML = "";
    if (!doc) {
      ui.detail.appendChild(el("p", "rempty", "書類を取得できませんでした。"));
      return;
    }
    const kindLabel = KIND_LABEL[doc.doc_type] || doc.doc_type;
    const author = doc.author_kind === "caregiver" ? "保育士が編集" : "AI が作成";

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

    // 帳票PDF（現場の様式）で確認・保存する。整形テキストが空でも entry から描ける。
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
        const url = URL.createObjectURL(blob);
        const a = el("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      } catch (e) {
        msg.textContent = "帳票PDFの作成に失敗しました: " + e.message;
        msg.classList.remove("hidden");
      } finally {
        btn.disabled = false;
        btn.innerHTML = orig;
      }
    };
    act.append(btn, msg);
    ui.detail.appendChild(act);
  }

  async function init() {
    renderPlaceholder();
    await loadTree();
  }

  // タブを開くたびに最新化する（他タブで確定した書類がすぐ反映される）。
  return { init, refresh: loadTree };
}
