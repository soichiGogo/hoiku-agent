// 表記ルール辞書（ひらがな表記DX）＝保育士が育てる編集辞書の CRUD UI。
// 生成ロジックは持たない＝harness/notation_store の中継 API（/api/notation）を叩いて描くだけ（§5/§11）。
// 正規化そのものは確定時に harness が決定的に適用する（このタブは「どの表記をそろえるか」の辞書管理）。
import * as adk from "./adk.js";
import { el, esc, iconHTML } from "./ui.js";

const KIND_OPTIONS = ["ひらがな化", "表記統一", "その他"];
const STORE_LABEL = {
  persistent: "保存先: 永続",
  ephemeral: "保存先: 一時（再起動で消えます）",
  unavailable: "保存先: 未接続",
};

export function makeNotation(ui) {
  // ui = { list, store, msg, patternInput, replacementInput, kindSelect, noteInput, addBtn }
  let rules = [];

  function flash(text, kind = "info") {
    ui.msg.className = "nmsg " + kind;
    ui.msg.textContent = text;
    ui.msg.classList.remove("hidden");
    if (kind === "info") setTimeout(() => ui.msg.classList.add("hidden"), 2500);
  }

  function setStore(s) {
    ui.store.textContent = STORE_LABEL[s] || "";
    ui.store.className = "badge " + (s === "persistent" ? "ok" : s === "ephemeral" ? "warn" : "muted");
  }

  // 書込 API の結果を反映（失敗は正直に出す＝偽の緑を出さない）。成功なら true。
  function apply(result) {
    if (!result || (result.status && result.status !== "ok")) {
      flash((result && result.detail) || "うまくいきませんでした", "err");
      return false;
    }
    rules = result.rules || [];
    setStore(result.store);
    render();
    return true;
  }

  function render() {
    ui.list.innerHTML = "";
    if (!rules.length) {
      ui.list.appendChild(el("p", "nempty", "まだルールがありません。上のフォームから追加できます。"));
      return;
    }
    rules.forEach((r) => ui.list.appendChild(rowView(r)));
  }

  function mapHTML(pattern, replacement) {
    const to = replacement ? esc(replacement) : '<span class="nto-empty">（削除）</span>';
    return `<span class="nfrom">${esc(pattern)}</span><span class="narr" aria-hidden="true">→</span><span class="nto">${to}</span>`;
  }

  function rowView(r) {
    const row = el("div", "nrow" + (r.enabled ? "" : " is-off"));
    const cb = el("input");
    cb.type = "checkbox";
    cb.checked = r.enabled;
    cb.setAttribute("aria-label", `「${r.pattern}」の変換を${r.enabled ? "無効" : "有効"}にする`);
    cb.onchange = () => toggle(r, cb.checked);
    const toggleWrap = el("label", "ntoggle", "");
    toggleWrap.title = "この表記の自動変換を有効/無効";
    toggleWrap.append(cb, el("span", "ntog-track"));

    const body = el("div", "nbody");
    body.innerHTML =
      `<div class="nmap">${mapHTML(r.pattern, r.replacement)}</div>` +
      `<div class="nmeta"><span class="nkind">${esc(r.kind)}</span>${r.note ? `<span class="nnote">${esc(r.note)}</span>` : ""}</div>`;

    const act = el("div", "nact");
    const edit = el("button", "icon-btn", iconHTML("edit"));
    edit.type = "button";
    edit.title = "編集";
    edit.setAttribute("aria-label", `「${r.pattern}」を編集`);
    edit.onclick = () => row.replaceWith(rowEdit(r));
    const del = el("button", "icon-btn", iconHTML("minus"));
    del.type = "button";
    del.title = "削除";
    del.setAttribute("aria-label", `「${r.pattern}」を削除`);
    del.onclick = () => remove(r);
    act.append(edit, del);

    row.append(toggleWrap, body, act);
    return row;
  }

  function rowEdit(r) {
    const row = el("div", "nrow is-editing");
    const p = el("input", "input");
    p.value = r.pattern;
    p.setAttribute("aria-label", "変換元");
    const rep = el("input", "input");
    rep.value = r.replacement;
    rep.setAttribute("aria-label", "変換先");
    const kind = el("select", "input");
    KIND_OPTIONS.forEach((k) => {
      const o = el("option", "", esc(k));
      o.value = k;
      if (k === r.kind) o.selected = true;
      kind.appendChild(o);
    });
    const note = el("input", "input");
    note.value = r.note || "";
    note.placeholder = "メモ（任意）";
    note.setAttribute("aria-label", "メモ");

    const map = el("div", "nedit-map");
    map.append(p, el("span", "narr", "→"), rep);

    const save = el("button", "btn btn-primary btn-sm", "保存");
    save.type = "button";
    save.onclick = async () => {
      const pattern = p.value.trim();
      if (!pattern) {
        p.focus();
        return;
      }
      const res = await adk.updateNotationRule(r.id, {
        pattern,
        replacement: rep.value,
        kind: kind.value,
        note: note.value.trim(),
      });
      if (apply(res)) flash("更新しました");
    };
    const cancel = el("button", "btn btn-ghost btn-sm", "取消");
    cancel.type = "button";
    cancel.onclick = () => row.replaceWith(rowView(r));
    const act = el("div", "nedit-act");
    act.append(save, cancel);

    row.append(map, kind, note, act);
    return row;
  }

  async function toggle(r, enabled) {
    const res = await adk.updateNotationRule(r.id, { enabled });
    apply(res);
  }

  async function remove(r) {
    const res = await adk.deleteNotationRule(r.id);
    if (apply(res)) flash("削除しました");
  }

  async function add() {
    const pattern = ui.patternInput.value.trim();
    if (!pattern) {
      ui.patternInput.focus();
      return;
    }
    const res = await adk.addNotationRule({
      pattern,
      replacement: ui.replacementInput.value,
      kind: ui.kindSelect.value,
      note: ui.noteInput.value.trim(),
    });
    if (apply(res)) {
      ui.patternInput.value = "";
      ui.replacementInput.value = "";
      ui.noteInput.value = "";
      ui.patternInput.focus();
      flash("追加しました");
    }
  }

  async function init() {
    const data = await adk.getNotation();
    rules = data.rules;
    setStore(data.store);
    render();
    ui.addBtn.onclick = add;
    // Enter で追加（メモ欄以外）。
    [ui.patternInput, ui.replacementInput].forEach((inp) =>
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") add();
      }),
    );
  }

  return { init };
}
