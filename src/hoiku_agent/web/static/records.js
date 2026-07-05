// 書類を見る＝アーカイブ閲覧タブ（作成済みの日誌/月案/児童票/保育要録を種別で絞り込み・確定内容を確認）。
// 生成ロジックは持たない＝harness/record_store の読取 API（/api/records・/api/records/{id}）を
// 叩いて描くだけ（§5/§11）。参照データが適切かの点検にも使える（保存された確定内容そのものを見る）。
import * as adk from "./adk.js";
import { el, esc, iconHTML } from "./ui.js";

const KIND_LABEL = { diary: "保育日誌", monthly: "個別月案", child_record: "児童票", nursery_record: "保育要録" };
const KIND_ICON = { diary: "diary", monthly: "calendar", child_record: "chart", nursery_record: "chart" };

// record_store.store_status は disabled/ok/unavailable を返す（policy/notation の persistent 系とは別語彙）。
const STORE_LABEL = {
  ok: "保存先: 接続済み",
  disabled: "保存先: 未接続",
  unavailable: "保存先: 接続エラー",
};
const STORE_CLASS = { ok: "ok", disabled: "muted", unavailable: "warn" };

// 種別フィルタ（空＝すべて）。DocTypeRouter の doc_type と同じ語彙で絞り込む。
const FILTERS = [
  { key: "", label: "すべて" },
  { key: "diary", label: "保育日誌" },
  { key: "monthly", label: "個別月案" },
  { key: "child_record", label: "児童票" },
  { key: "nursery_record", label: "保育要録" },
];

export function makeRecords(ui) {
  // ui = { list, store, filter, detail }
  let currentFilter = "";
  let selectedId = null;

  function setStore(s) {
    ui.store.textContent = STORE_LABEL[s] || "";
    ui.store.className = "badge " + (STORE_CLASS[s] || "muted");
  }

  function statusBadge(status) {
    const approved = status === "approved";
    return `<span class="rbadge ${approved ? "ok" : "muted"}">${approved ? "承認済み" : "確定"}</span>`;
  }

  // 種別フィルタのセグメント（選択で一覧を絞り込む）。
  function renderFilter() {
    ui.filter.innerHTML = "";
    FILTERS.forEach((f, i) => {
      const chip = el("button", "chip" + (f.key === currentFilter ? " is-active" : ""), esc(f.label));
      chip.type = "button";
      chip.onclick = () => {
        currentFilter = f.key;
        [...ui.filter.children].forEach((c) => c.classList.remove("is-active"));
        chip.classList.add("is-active");
        loadList();
      };
      ui.filter.appendChild(chip);
    });
  }

  async function loadList() {
    ui.list.innerHTML = "";
    ui.list.appendChild(el("p", "rempty", "読み込み中…"));
    const { documents, store } = await adk.listRecords(currentFilter);
    setStore(store);
    renderList(documents, store);
  }

  function renderList(documents, store) {
    ui.list.innerHTML = "";
    ui.detail.hidden = true;
    selectedId = null;
    if (store === "disabled" || store === "unavailable") {
      ui.list.appendChild(
        el(
          "p",
          "rempty",
          store === "disabled"
            ? "書類アーカイブが未接続です（DATABASE_URL を設定すると、確定した書類がここに一覧されます）。"
            : "アーカイブに接続できませんでした。",
        ),
      );
      return;
    }
    if (!documents.length) {
      ui.list.appendChild(
        el("p", "rempty", "保存された書類がありません。「書類を作る」で確定すると、ここに並びます。"),
      );
      return;
    }
    documents.forEach((d) => ui.list.appendChild(rowView(d)));
  }

  function rowView(d) {
    const kindLabel = KIND_LABEL[d.doc_type] || d.doc_type;
    const row = el("button", "rrow");
    row.type = "button";
    row.dataset.id = d.id;
    row.innerHTML =
      `<span class="rrow-ic">${iconHTML(KIND_ICON[d.doc_type] || "book")}</span>` +
      `<span class="rrow-main">` +
      `<span class="rrow-title">${esc(kindLabel)}<span class="rrow-target">${esc(d.target || "")}</span></span>` +
      `<span class="rrow-sub">${d.child ? esc(d.child) : "クラス全体"}・更新 ${esc((d.updated_at || "").slice(0, 10))}</span>` +
      `</span>` +
      statusBadge(d.status);
    row.onclick = () => select(d.id);
    return row;
  }

  async function select(id) {
    selectedId = id;
    [...ui.list.children].forEach((c) => {
      if (c.dataset) c.classList.toggle("is-active", c.dataset.id === id);
    });
    ui.detail.hidden = false;
    ui.detail.innerHTML = "";
    ui.detail.appendChild(el("p", "rempty", "読み込み中…"));
    const doc = await adk.getRecord(id);
    renderDetail(doc);
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
    renderFilter();
    await loadList();
  }

  // タブを開くたびに最新化する（他タブで確定した書類がすぐ反映される）。
  return { init, refresh: loadList };
}
