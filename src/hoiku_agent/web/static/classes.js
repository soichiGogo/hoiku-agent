// クラス（組）・園児の名簿管理 UI。園がクラスを定義し、園児を登録/割当する（日誌 roster の素）。
// 生成ロジックは持たない＝harness/record_store の中継 API（/api/classes・/api/children）を叩くだけ（§5/§11）。
// クラスは日誌の手入力フォーム（在籍児の一括流し込み）・年齢帯の自動決定・クラス月案の素になる。
import * as adk from "./adk.js";
import { el, esc, iconHTML } from "./ui.js";

const AGE_LABEL = { "0-2": "0〜2歳", "3-5": "3〜5歳" };
const GENDERS = [
  { value: "male", label: "男の子", honorific: "くん" },
  { value: "female", label: "女の子", honorific: "ちゃん" },
];
const HONORIFIC = Object.fromEntries(GENDERS.map((g) => [g.value, g.honorific]));

export function makeClasses(ui) {
  // ui = { list, store, msg, nameInput, fiscalInput, addBtn }
  let classes = [];
  let children = [];
  let storeState = "disabled";

  function flash(text, kind = "info") {
    ui.msg.className = "nmsg " + kind;
    ui.msg.textContent = text;
    ui.msg.classList.remove("hidden");
    if (kind === "info") setTimeout(() => ui.msg.classList.add("hidden"), 2500);
  }

  function setStore(s) {
    storeState = s;
    ui.store.textContent = s === "ok" ? "" : "現在利用できません";
    ui.store.className = "badge " + (s === "ok" ? "ok" : "muted");
    ui.store.hidden = s === "ok";
  }

  const childrenOf = (classId) => children.filter((c) => c.class_id === classId);
  const unassigned = () => children.filter((c) => !c.class_id);

  function classAgeLabel(c) {
    const bands = c.age_bands || [];
    if (!bands.length) return "年齢帯未確定";
    const label = bands.map((band) => AGE_LABEL[band] || band).join("・");
    return bands.length === 1 ? `${label}児` : `異年齢（${label}）`;
  }

  // 未所属児の並び替えに使う満年齢。生年月日が無い児は推測せず「年齢不明」へ送る。
  function ageInYears(birthdate) {
    if (!birthdate) return null;
    const birth = new Date(`${birthdate}T00:00:00`);
    if (Number.isNaN(birth.getTime())) return null;
    const today = new Date();
    let age = today.getFullYear() - birth.getFullYear();
    const birthdayPassed =
      today.getMonth() > birth.getMonth() ||
      (today.getMonth() === birth.getMonth() && today.getDate() >= birth.getDate());
    if (!birthdayPassed) age -= 1;
    return age >= 0 ? age : null;
  }

  function ageLabel(k) {
    const age = ageInYears(k.birthdate);
    return age == null ? "年齢不明" : `${age}歳`;
  }

  function enableDropTarget(target, classId) {
    target.classList.add("cdrop-target");
    target.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      target.classList.add("is-drag-over");
    });
    target.addEventListener("dragleave", (event) => {
      if (!event.relatedTarget || !target.contains(event.relatedTarget)) {
        target.classList.remove("is-drag-over");
      }
    });
    target.addEventListener("drop", async (event) => {
      event.preventDefault();
      target.classList.remove("is-drag-over");
      const child = event.dataTransfer.getData("text/plain");
      if (!child) return;
      const source = children.find((k) => k.display_name === child);
      if (source && (source.class_id || null) === (classId || null)) return;
      const res = await adk.assignChild(child, classId || "");
      if (applyWrite(res, classId ? "クラスを移動しました" : "未所属に戻しました")) await reload();
    });
  }

  // 書込結果を反映（失敗は正直に出す＝偽の緑を出さない）。成功なら true。
  function applyWrite(res, okMsg) {
    const ok = res && ["created", "exists", "ok"].includes(res.status);
    if (!ok) {
      console.error("クラス・園児情報の更新に失敗", (res && res.detail) || res);
      flash("更新できませんでした。時間をおいてもう一度お試しください。", "err");
      return false;
    }
    if (okMsg) flash(okMsg);
    return true;
  }

  async function reload() {
    const [cl, kids] = await Promise.all([adk.getClasses(), adk.getChildren()]);
    classes = cl.classes || [];
    children = kids || [];
    setStore(cl.store);
    render();
  }

  function render() {
    ui.list.innerHTML = "";
    if (storeState !== "ok") {
      ui.list.appendChild(
        el(
          "p",
          "cempty",
          "現在、クラス・園児の情報を表示できません。時間をおいてからもう一度お試しください。",
        ),
      );
      return;
    }
    if (!classes.length) {
      ui.list.appendChild(
        el("p", "cempty", "まだクラスがありません。上の「クラスを作る」から追加してください。"),
      );
    }
    classes.forEach((c) => ui.list.appendChild(classCard(c)));
    const un = unassigned();
    if (un.length) ui.list.appendChild(unassignedCard(un));
  }

  function classCard(c) {
    const card = el("section", "ccard");
    const head = el("div", "ccard-head");
    head.innerHTML =
      `<div class="ctitle">${esc(c.name)}` +
      `<span class="cmeta">${esc(classAgeLabel(c))}` +
      `${c.fiscal_year ? " ・ " + esc(c.fiscal_year) + "年度" : ""}</span></div>`;
    const count = el("span", "badge", `${childrenOf(c.id).length} 名`);
    head.appendChild(count);
    card.appendChild(head);

    // 在籍児（所属の移動はドラッグ＆ドロップ）
    const roster = el("div", "croster");
    enableDropTarget(roster, c.id);
    const kids = childrenOf(c.id);
    if (!kids.length) {
      roster.appendChild(el("p", "cempty-sm", "在籍児はまだいません。下から追加できます。"));
    } else {
      kids.forEach((k) => roster.appendChild(childRow(k)));
    }
    card.appendChild(roster);

    card.appendChild(addControls(c));
    return card;
  }

  function childRow(k) {
    const row = el("div", "crow");
    row.draggable = true;
    row.dataset.child = k.display_name;
    row.title = "ドラッグして所属を移動";
    row.addEventListener("dragstart", (event) => {
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", k.display_name);
      row.classList.add("is-dragging");
    });
    row.addEventListener("dragend", () => row.classList.remove("is-dragging"));
    const name = el("span", "cname", esc(k.display_name));
    if (k.official_name) name.title = k.official_name; // 本名（氏名欄用）はホバーで確認できる
    row.append(name);
    return row;
  }

  // クラスへの園児追加：① 未所属の既存児を割り当て ② 新規に登録して割り当て。
  function addControls(c) {
    const wrap = el("details", "cadd-child");
    const sum = el("summary", "", "園児を追加");
    wrap.appendChild(sum);
    const body = el("div", "cadd-body");

    // ① 既存の未所属児を割り当て
    const un = unassigned();
    if (un.length) {
      const rowA = el("div", "cadd-row");
      const sel = el("select", "input");
      sel.setAttribute("aria-label", "未所属の園児");
      sel.appendChild(el("option", "", "未所属の園児から選ぶ…"));
      un.forEach((k) => {
        const o = el("option", "", esc(k.display_name));
        o.value = k.display_name;
        sel.appendChild(o);
      });
      const btn = el("button", "btn btn-ghost btn-sm", "割り当て");
      btn.type = "button";
      btn.onclick = async () => {
        if (!sel.value) return;
        const res = await adk.assignChild(sel.value, c.id);
        if (applyWrite(res, "割り当てました")) await reload();
      };
      rowA.append(sel, btn);
      body.appendChild(rowA);
      body.appendChild(el("div", "cadd-or", "または新しい園児を登録"));
    }

    // ② 新規登録＋割り当て（本名 姓/名 ＋ 性別）。呼び名＋敬称＝display_name はサーバが合成する。
    const rowB = el("div", "cadd-row cadd-new");
    const family = el("input", "input");
    family.placeholder = "姓（任意）";
    family.setAttribute("aria-label", "姓");
    const given = el("input", "input");
    given.placeholder = "名（呼び名）";
    given.setAttribute("aria-label", "名（呼び名）");
    const gender = el("select", "input");
    gender.setAttribute("aria-label", "性別");
    GENDERS.forEach((g) => {
      const o = el("option", "", g.label);
      o.value = g.value;
      gender.appendChild(o);
    });
    // 生年月日（任意）。書類の「歳児」欄を満年齢（○歳○か月）で自動表示するための素。
    const birth = el("input", "input");
    birth.type = "date";
    birth.setAttribute("aria-label", "生年月日（任意）");
    birth.title = "生年月日（任意）";
    const preview = el("span", "cprev", "");
    const updatePreview = () => {
      const nm = given.value.trim();
      preview.textContent = nm ? nm + HONORIFIC[gender.value] : "";
    };
    given.addEventListener("input", updatePreview);
    gender.addEventListener("change", updatePreview);
    const reg = el("button", "btn btn-primary btn-sm", "登録して追加");
    reg.type = "button";
    reg.onclick = async () => {
      const nm = given.value.trim();
      if (!nm) {
        given.focus();
        return;
      }
      const res = await adk.addChild({
        given_name: nm,
        family_name: family.value.trim(),
        gender: gender.value,
        birthdate: birth.value || "",
        class_id: c.id,
      });
      if (applyWrite(res, "登録して追加しました")) {
        given.value = "";
        family.value = "";
        birth.value = "";
        updatePreview();
        await reload();
      }
    };
    rowB.append(family, given, gender, birth, preview, reg);
    body.appendChild(rowB);

    wrap.appendChild(body);
    return wrap;
  }

  // 未所属の園児（どのクラスにも属さない子）＝割当漏れが一目で分かる。
  function unassignedCard(un) {
    const card = el("section", "ccard ccard-un");
    card.appendChild(
      el("div", "ccard-head", `<div class="ctitle">未所属の園児<span class="cmeta">クラス未割当</span></div>`),
    );
    const roster = el("div", "croster cunassigned-roster");
    enableDropTarget(roster, "");
    const groups = new Map();
    un.forEach((k) => {
      const label = ageLabel(k);
      if (!groups.has(label)) groups.set(label, []);
      groups.get(label).push(k);
    });
    [...groups.entries()]
      .sort(([a], [b]) => {
        if (a === "年齢不明") return 1;
        if (b === "年齢不明") return -1;
        return Number.parseInt(a, 10) - Number.parseInt(b, 10);
      })
      .forEach(([label, kids]) => {
        const group = el("div", "cage-group");
        group.appendChild(el("div", "cage-label", label));
        kids.forEach((k) => group.appendChild(childRow(k)));
        roster.appendChild(group);
      });
    card.appendChild(roster);
    return card;
  }

  async function createClass() {
    const name = ui.nameInput.value.trim();
    if (!name) {
      ui.nameInput.focus();
      return;
    }
    const res = await adk.addClass({
      name,
      fiscal_year: ui.fiscalInput.value.trim(),
    });
    if (applyWrite(res, res.status === "exists" ? "既にあるクラスです" : "作成しました")) {
      ui.nameInput.value = "";
      ui.nameInput.focus();
      await reload();
    }
  }

  async function init() {
    ui.addBtn.onclick = createClass;
    await reload();
  }

  return { init, refresh: reload };
}
