// 確定した書類（state["final_entry"]）を「標準様式の見た目の編集フォーム」に描く。
// 保育士は欄ごとに自由に編集でき、collect() で編集後の entry(dict) を返す。再検査・再整形は
// harness（/api/finalize-edit）に投げる＝決定的ロジックはここに持たない（描画と収集だけ＝§5/§11）。
//
// 機械メタ（記録日・月齢の date 系）は read-only 扱い、タグは form-meta の Enum 語彙から多選択。

import { el, esc, iconHTML } from "./ui.js";

const AGE_LABEL = { "0-2": "0〜2歳児", "3-5": "3〜5歳児" };

/* ---- 部品 ---- */
function ta(value, rows = 2, placeholder = "") {
  const t = el("textarea", "de-input");
  t.rows = rows;
  t.value = value == null ? "" : String(value);
  if (placeholder) t.placeholder = placeholder;
  return t;
}
function inp(value, placeholder = "") {
  const i = el("input", "de-input");
  i.type = "text";
  i.value = value == null ? "" : String(value);
  if (placeholder) i.placeholder = placeholder;
  return i;
}
// ラベル＋入力欄を縦に積む（1フィールド）。
function field(label, control, hint) {
  const f = el("div", "de-field");
  const lab = el("label", "de-lab", esc(label));
  if (hint) lab.appendChild(el("span", "de-hint", esc(hint)));
  f.append(lab, control);
  return f;
}
// read-only の機械メタ（記録日等）。
function roField(label, value) {
  const f = el("div", "de-field");
  f.append(
    el("label", "de-lab", esc(label) + " "),
    el("div", "de-ro", `${iconHTML("lock")}${esc(value || "（未設定）")}`),
  );
  return f;
}
function section(label, hint) {
  const s = el("div", "de-sec");
  const h = el("div", "de-sec-h", esc(label));
  if (hint) h.appendChild(el("span", "de-hint", esc(hint)));
  s.appendChild(h);
  s._b = el("div", "de-sec-b");
  s.appendChild(s._b);
  return s;
}

// 年齢で必須語彙が変わるタグ多選択（必須＝3つの視点/5領域、任意＝10の姿）。
function tagEditor(currentTags, formMeta, ageBand) {
  const wrap = el("div", "de-tags");
  // form-meta 取得失敗時も落とさない（語彙は空＝既存タグは selected として保持される）。
  const required = (ageBand === "3-5" ? formMeta.five_domains : formMeta.three_viewpoint) || [];
  const reqLabel = ageBand === "3-5" ? "5領域（必須）" : "3つの視点（必須）";
  const selected = new Set(currentTags || []);
  // 語彙に無い既存タグ（form-meta 欠落時など）も選択中チップとして見せる。
  const extra = [...selected].filter((t) => !required.includes(t) && !(formMeta.ten_no_sugata || []).includes(t));
  const groups = [
    [reqLabel, required],
    ["10の姿（任意）", formMeta.ten_no_sugata || []],
  ];
  if (extra.length) groups.push(["現在のタグ", extra]);
  for (const [gl, vocab] of groups) {
    const g = el("div", "de-taggroup");
    g.appendChild(el("span", "de-taglabel", esc(gl)));
    for (const v of vocab) {
      const chip = el("button", "de-tag" + (selected.has(v) ? " on" : ""), esc(v));
      chip.type = "button";
      chip.setAttribute("aria-pressed", selected.has(v) ? "true" : "false");
      chip.onclick = () => {
        if (selected.has(v)) selected.delete(v);
        else selected.add(v);
        const on = selected.has(v);
        chip.classList.toggle("on", on);
        chip.setAttribute("aria-pressed", on ? "true" : "false");
      };
      g.appendChild(chip);
    }
    wrap.appendChild(g);
  }
  wrap._get = () => [...selected];
  return wrap;
}

// 可変リスト（出欠・個別記録・教育ねらい）。各項目は renderItem→{node, collect}。追加/削除可。
function listSection(label, hint, items, renderItem, makeEmpty, addLabel) {
  const sec = section(label, hint);
  const list = el("div", "de-list");
  const refs = [];
  function addItem(item) {
    const { node, collect } = renderItem(item);
    const wrap = el("div", "de-item");
    const ref = { collect };
    const rm = el("button", "de-rm", iconHTML("xcircle"));
    rm.type = "button";
    rm.title = "この項目を削除";
    rm.setAttribute("aria-label", "この項目を削除");
    rm.onclick = () => {
      wrap.remove();
      const i = refs.indexOf(ref);
      if (i >= 0) refs.splice(i, 1);
    };
    wrap.append(rm, node);
    list.appendChild(wrap);
    refs.push(ref);
  }
  (items || []).forEach(addItem);
  const add = el("button", "de-add", `${iconHTML("spark")}${esc(addLabel || "追加")}`);
  add.type = "button";
  add.onclick = () => addItem(makeEmpty());
  sec._b.append(list, add);
  sec._collect = () => refs.map((r) => r.collect());
  return sec;
}

/* ---- 出欠 1件 ---- */
function attendanceItem(a) {
  a = a || {};
  const cid = inp(a.child_id, "はるとくん");
  const present = el("select", "de-input de-sel");
  for (const [val, lab] of [
    ["true", "出席"],
    ["false", "欠席"],
  ]) {
    const o = el("option", null, lab);
    o.value = val;
    if (String(!!a.present) === val) o.selected = true;
    present.appendChild(o);
  }
  const reason = inp(a.reason, "欠席理由（任意）");
  const node = el("div", "de-grid");
  node.append(field("対象児", cid), field("出欠", present), field("欠席理由", reason));
  return {
    node,
    collect: () => ({
      child_id: cid.value.trim(),
      present: present.value === "true",
      reason: reason.value.trim() || null,
    }),
  };
}

/* ---- 個別の記録 1件（0–2 の本体：姿＋タグ＋生活記録＋個人のねらい） ---- */
function noteItem(formMeta, ageBand) {
  return (n) => {
    n = n || {};
    const lr = n.life_record || {};
    const cid = inp(n.child_id, "はるとくん");
    const months = inp(n.age_months, "1歳3か月（任意）");
    const obs = ta(n.observed_state, 2, "今日の子どもの姿");
    const tags = tagEditor(n.tags, formMeta, ageBand);
    const meal = inp(lr.meal, "食事・授乳");
    const sleep = inp(lr.sleep, "睡眠・午睡");
    const toilet = inp(lr.toilet, "排泄");
    const mood = inp(lr.mood_health, "機嫌・体調・視診");
    const aim = ta(n.individual_aim, 1, "個人のねらい（任意）");

    const node = el("div", "de-note");
    const head = el("div", "de-grid");
    head.append(field("対象児", cid), field("月齢", months));
    node.append(head, field("子どもの姿", obs), field("対応する姿・領域（タグ）", tags));
    const life = el("div", "de-grid de-grid-4");
    life.append(
      field("食事", meal),
      field("睡眠", sleep),
      field("排泄", toilet),
      field("機嫌・体調", mood),
    );
    node.append(
      el("div", "de-sub", `${iconHTML("memo")}生活記録（養護の中核）`),
      life,
      field("個人のねらい", aim),
    );
    return {
      node,
      collect: () => ({
        child_id: cid.value.trim(),
        age_months: months.value.trim(),
        observed_state: obs.value,
        tags: tags._get(),
        life_record: {
          meal: meal.value,
          sleep: sleep.value,
          toilet: toilet.value,
          mood_health: mood.value,
        },
        individual_aim: aim.value,
      }),
    };
  };
}

/* ---- 教育ねらい 1件（月案） ---- */
function educationItem(formMeta, ageBand) {
  return (e) => {
    e = e || {};
    const aim = ta(e.aim, 2, "今月の教育のねらい・内容");
    const tags = tagEditor(e.tags, formMeta, ageBand);
    const node = el("div", "de-note");
    node.append(field("ねらい・内容", aim), field("対応する姿・領域（タグ）", tags));
    return { node, collect: () => ({ aim: aim.value, tags: tags._get() }) };
  };
}

/* ---- 日誌フォーム ---- */
function buildDiary(body, entry, formMeta) {
  const ageBand = entry.age_band || "0-2";

  const basic = section("基本情報");
  const brow = el("div", "de-grid");
  const weather = inp(entry.weather, "天候（例：晴れ）");
  const temperature = inp(entry.temperature, "気温（例：26℃）");
  const className = inp(entry.class_name, "組名（例：ひよこ組）");
  brow.append(
    roField("記録日", entry.date),
    field("天候", weather),
    field("気温", temperature),
    roField("クラス", AGE_LABEL[ageBand] || ageBand),
    field("組", className),
  );
  basic._b.appendChild(brow);
  body.appendChild(basic);

  const aim = ta(entry.daily_aim, 2, "本日のねらい（養護・教育）");
  const aimSec = section("本日のねらい");
  aimSec._b.appendChild(aim);
  body.appendChild(aimSec);

  const att = listSection(
    "出欠",
    null,
    entry.attendance,
    attendanceItem,
    () => ({ child_id: "", present: true, reason: null }),
    "対象児を追加",
  );
  body.appendChild(att);

  const practice = ta(entry.practice_record, 3, "主な活動・保育者の援助");
  const pSec = section("主な活動・保育者の援助");
  pSec._b.appendChild(practice);
  body.appendChild(pSec);

  const notes = listSection(
    "個別の記録（子ども一人ひとり）",
    "0–2 の本体。姿・タグ・生活記録（養護）を記録します",
    entry.individual_notes,
    noteItem(formMeta, ageBand),
    () => ({}),
    "子どもを追加",
  );
  body.appendChild(notes);

  const health = ta(entry.health_notes, 2, "体温・視診・午睡など（特記なければ空）");
  const hSec = section("健康・視診");
  hSec._b.appendChild(health);
  body.appendChild(hSec);

  const parent = ta(entry.parent_contact, 2, "保護者への連絡・申し送り（任意）");
  const fSec = section("家庭への連絡");
  fSec._b.appendChild(parent);
  body.appendChild(fSec);

  const ev = entry.evaluation || {};
  const cf = ta(ev.child_focus, 2, "(a) 子どもに焦点を当てた振り返り");
  const sr = ta(ev.self_review, 2, "(b) 自分の保育（ねらい・環境構成・関わり）の適否");
  const eSec = section("評価・反省", "2視点（子ども焦点／自己評価）");
  eSec._b.append(field("(a) 子どもに焦点", cf), field("(b) 自分の保育の適否", sr));
  body.appendChild(eSec);

  return () => ({
    date: entry.date,
    age_band: ageBand,
    weather: weather.value,
    temperature: temperature.value,
    class_name: className.value,
    daily_aim: aim.value,
    attendance: att._collect(),
    health_notes: health.value.trim() || null,
    practice_record: practice.value,
    individual_notes: notes._collect(),
    evaluation: { child_focus: cf.value, self_review: sr.value },
    parent_contact: parent.value.trim() || null,
  });
}

/* ---- 月案フォーム（養護→教育の順） ---- */
function buildMonthly(body, entry, formMeta) {
  const ageBand = entry.age_band || "0-2";

  const basic = section("基本情報");
  const child = inp(entry.child_id, "はるとくん");
  const months = inp(entry.age_months, "1歳3か月（任意）");
  const brow = el("div", "de-grid");
  brow.append(roField("対象月", entry.month), field("対象児", child), field("月齢", months));
  basic._b.appendChild(brow);
  body.appendChild(basic);

  const prev = ta(entry.prev_child_state, 3, "前月の子どもの姿（前月集積から）");
  const goals = ta(entry.monthly_goals, 2, "今月のねらい・内容");
  const nLife = ta(entry.nurturing_life, 2, "生命の保持（安全・健康・生理的欲求）");
  const nEmo = ta(entry.nurturing_emotion, 2, "情緒の安定（応答的関わり・愛着）");
  const env = ta(entry.environment_support, 2, "環境構成・援助（配慮）");
  const family = ta(entry.events_family_food, 2, "家庭との連携／食育・健康・行事（任意）");
  const evalr = ta(entry.evaluation_reflection, 2, "評価・反省（翌月へ）");

  const simple = (label, control, hint) => {
    const s = section(label, hint);
    s._b.appendChild(control);
    body.appendChild(s);
  };
  simple("前月の子どもの姿", prev);
  simple("今月のねらい・内容", goals);
  simple("養護：生命の保持", nLife, "0–2 は養護2本柱を分けます");
  simple("養護：情緒の安定", nEmo);

  const edu = listSection(
    "教育（ねらい・内容）",
    ageBand === "3-5" ? "5領域でタグ付け" : "3つの視点でタグ付け",
    entry.education,
    educationItem(formMeta, ageBand),
    () => ({}),
    "ねらいを追加",
  );
  body.appendChild(edu);

  simple("環境構成・援助（配慮）", env);
  simple("家庭との連携／食育・健康・行事", family);
  simple("評価・反省", evalr);

  return () => ({
    month: entry.month,
    age_band: ageBand,
    child_id: child.value.trim(),
    age_months: months.value.trim(),
    prev_child_state: prev.value,
    nurturing_life: nLife.value,
    nurturing_emotion: nEmo.value,
    education: edu._collect(),
    monthly_goals: goals.value,
    environment_support: env.value,
    events_family_food: family.value.trim() || null,
    evaluation_reflection: evalr.value,
  });
}

const META = {
  diary: { title: "保育日誌", icon: "diary", build: buildDiary },
  monthly: { title: "個別月案", icon: "calendar", build: buildMonthly },
};

// 編集フォーム panel と collect()（編集後 entry dict）を返す。
export function renderEditableDoc({ kind, entry, formMeta }) {
  const meta = META[kind] || META.diary;
  const panel = el("div", "docp docedit");
  panel.innerHTML =
    `<div class="docp-head"><span class="docp-title">${iconHTML(meta.icon)}${esc(meta.title)}` +
    `<span class="label-draft">${iconHTML("edit")}編集できます</span></span>` +
    `<span class="docp-stamp">あなたが自由に直せます</span></div>`;
  const body = el("div", "docp-body de-body");
  panel.appendChild(body);
  panel._body = body; // docflow が validation/承認バーを追記する

  const collect = meta.build(body, entry || {}, formMeta || {});
  return { panel, collect };
}
