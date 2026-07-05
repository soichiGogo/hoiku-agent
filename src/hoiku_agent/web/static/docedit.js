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

/* ---- テンプレ駆動の本文レンダラ ----
   本文セクションの順序・見出しラベルは様式テンプレート（/api/doc-template）から取る（テキスト整形・帳票PDF と
   共通の SSOT＝レイアウトの二重管理を解消・§18）。ヘッダ（基本情報）と各欄の widget・collect はコードが持つ
   （form 固有の hint・任意欄の null 化・タグ多選択は widget の関心事）。テンプレ未取得は各ビルダ既定順にフォールバック。 */

// テキスト欄1つのセクション。collect は key→値の部分オブジェクト（nullable=空文字は null へ寄せる）。
function textSection(label, value, rows, ph, key, opts = {}) {
  const c = ta(value, rows, ph);
  const s = section(label, opts.hint);
  s._b.appendChild(c);
  return { node: s, collect: () => ({ [key]: opts.nullable ? c.value.trim() || null : c.value }) };
}

// テンプレの本文セクション列（無ければ defaultOrder）を歩き、各ビルダで {node, collect} を作って body へ。
// ビルダは (label) を受け取り（テンプレ由来／null なら自前の既定ラベル）、collect のリストを返す。
function buildBody(body, templateSections, builders, defaultOrder) {
  const sections =
    templateSections && templateSections.length
      ? templateSections
      : defaultOrder.map((key) => ({ key, label: null }));
  const collects = [];
  for (const sec of sections) {
    const make = builders[sec.key];
    if (!make) continue; // テンプレに未知 key があってもフォームは壊さない
    const { node, collect } = make(sec.label);
    body.appendChild(node);
    collects.push(collect);
  }
  return collects;
}

// ヘッダ（基本情報）＋テンプレ駆動の本文をまとめ、最終 collect（ヘッダ＋各節をマージ）を返す共通処理。
function assembleForm(body, headerNode, headerCollect, templateSections, builders, defaultOrder) {
  body.appendChild(headerNode);
  const collects = buildBody(body, templateSections, builders, defaultOrder);
  return () => Object.assign({}, headerCollect(), ...collects.map((c) => c()));
}

/* ---- 日誌フォーム ---- */
function buildDiary(body, entry, formMeta, template) {
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
  const headerCollect = () => ({
    date: entry.date,
    age_band: ageBand,
    weather: weather.value,
    temperature: temperature.value,
    class_name: className.value,
  });

  const builders = {
    daily_aim: (label) =>
      textSection(label || "本日のねらい", entry.daily_aim, 2, "本日のねらい（養護・教育）", "daily_aim"),
    attendance: (label) => {
      const att = listSection(
        label || "出欠",
        null,
        entry.attendance,
        attendanceItem,
        () => ({ child_id: "", present: true, reason: null }),
        "対象児を追加",
      );
      return { node: att, collect: () => ({ attendance: att._collect() }) };
    },
    practice_record: (label) =>
      textSection(
        label || "主な活動・保育者の援助",
        entry.practice_record,
        3,
        "主な活動・保育者の援助",
        "practice_record",
      ),
    individual_notes: (label) => {
      const notes = listSection(
        label || "個別の記録（子ども一人ひとり）",
        ageBand === "3-5"
          ? "姿・タグ（5領域）を記録します。生活記録は任意"
          : "0–2 の本体。姿・タグ・生活記録（養護）を記録します",
        entry.individual_notes,
        noteItem(formMeta, ageBand),
        () => ({}),
        "子どもを追加",
      );
      return { node: notes, collect: () => ({ individual_notes: notes._collect() }) };
    },
    health_notes: (label) =>
      textSection(label || "健康・視診", entry.health_notes, 2, "体温・視診・午睡など（特記なければ空）", "health_notes", {
        nullable: true,
      }),
    parent_contact: (label) =>
      textSection(label || "家庭への連絡", entry.parent_contact, 2, "保護者への連絡・申し送り（任意）", "parent_contact", {
        nullable: true,
      }),
    evaluation: (label) => {
      const ev = entry.evaluation || {};
      const cf = ta(ev.child_focus, 2, "(a) 子どもに焦点を当てた振り返り");
      const sr = ta(ev.self_review, 2, "(b) 自分の保育（ねらい・環境構成・関わり）の適否");
      const s = section(label || "評価・反省", "2視点（子ども焦点／自己評価）");
      s._b.append(field("(a) 子どもに焦点", cf), field("(b) 自分の保育の適否", sr));
      return {
        node: s,
        collect: () => ({ evaluation: { child_focus: cf.value, self_review: sr.value } }),
      };
    },
  };
  return assembleForm(body, basic, headerCollect, template, builders, [
    "daily_aim",
    "attendance",
    "practice_record",
    "individual_notes",
    "health_notes",
    "parent_contact",
    "evaluation",
  ]);
}

/* ---- 月案フォーム（養護→教育の順） ---- */
function buildMonthly(body, entry, formMeta, template) {
  const ageBand = entry.age_band || "0-2";

  const basic = section("基本情報");
  const child = inp(entry.child_id, "はるとくん");
  const months = inp(entry.age_months, "1歳3か月（任意）");
  const brow = el("div", "de-grid");
  brow.append(roField("対象月", entry.month), field("対象児", child), field("月齢", months));
  basic._b.appendChild(brow);
  const headerCollect = () => ({
    month: entry.month,
    age_band: ageBand,
    child_id: child.value.trim(),
    age_months: months.value.trim(),
  });

  const builders = {
    prev_child_state: (label) =>
      textSection(label || "前月の子どもの姿", entry.prev_child_state, 3, "前月の子どもの姿（前月集積から）", "prev_child_state"),
    monthly_goals: (label) =>
      textSection(label || "今月のねらい・内容", entry.monthly_goals, 2, "今月のねらい・内容", "monthly_goals"),
    nurturing_life: (label) =>
      textSection(label || "養護：生命の保持", entry.nurturing_life, 2, "生命の保持（安全・健康・生理的欲求）", "nurturing_life", {
        hint: "0–2 は養護2本柱を分けます",
      }),
    nurturing_emotion: (label) =>
      textSection(label || "養護：情緒の安定", entry.nurturing_emotion, 2, "情緒の安定（応答的関わり・愛着）", "nurturing_emotion"),
    education: (label) => {
      const edu = listSection(
        label || "教育（ねらい・内容）",
        ageBand === "3-5" ? "5領域でタグ付け" : "3つの視点でタグ付け",
        entry.education,
        educationItem(formMeta, ageBand),
        () => ({}),
        "ねらいを追加",
      );
      return { node: edu, collect: () => ({ education: edu._collect() }) };
    },
    environment_support: (label) =>
      textSection(label || "環境構成・援助（配慮）", entry.environment_support, 2, "環境構成・援助（配慮）", "environment_support"),
    events_family_food: (label) =>
      textSection(label || "家庭との連携／食育・健康・行事", entry.events_family_food, 2, "家庭との連携／食育・健康・行事（任意）", "events_family_food", {
        nullable: true,
      }),
    evaluation_reflection: (label) =>
      textSection(label || "評価・反省", entry.evaluation_reflection, 2, "評価・反省（翌月へ）", "evaluation_reflection"),
  };
  return assembleForm(body, basic, headerCollect, template, builders, [
    "prev_child_state",
    "monthly_goals",
    "nurturing_life",
    "nurturing_emotion",
    "education",
    "environment_support",
    "events_family_food",
    "evaluation_reflection",
  ]);
}

/* ---- 発達の経過 1件（児童票） ---- */
function developmentItem(formMeta, ageBand) {
  return (n) => {
    n = n || {};
    const desc = ta(n.description, 2, "その期の発達・生活の経過（叙述）");
    const tags = tagEditor(n.tags, formMeta, ageBand);
    const node = el("div", "de-note");
    node.append(field("経過（叙述）", desc), field("対応する姿・領域（タグ）", tags));
    return { node, collect: () => ({ description: desc.value, tags: tags._get() }) };
  };
}

// 発達の経過リスト節（児童票・要録で共用。key/追加ラベルだけ切替）。
function developmentSection(label, addLabel, entry, formMeta, ageBand) {
  const dev = listSection(
    label,
    ageBand === "3-5" ? "5領域でタグ付け" : "3つの視点でタグ付け",
    entry.development_notes,
    developmentItem(formMeta, ageBand),
    () => ({}),
    addLabel,
  );
  return { node: dev, collect: () => ({ development_notes: dev._collect() }) };
}

/* ---- 児童票フォーム（期ごとの保育経過記録） ---- */
function buildChildRecord(body, entry, formMeta, template) {
  const ageBand = entry.age_band || "0-2";

  const basic = section("基本情報");
  const child = inp(entry.child_id, "はるとくん");
  const months = inp(entry.age_months, "1歳6か月（任意）");
  // 身長・体重は原簿系＝AI は生成しない（保育士が記入）。帳票PDF（年間マトリクス）の該当期の列に載る。
  const height = inp(entry.height_cm, "身長 cm（任意・例: 78.5）");
  const weight = inp(entry.weight_kg, "体重 kg（任意・例: 10.2）");
  const brow = el("div", "de-grid");
  brow.append(
    roField("対象期間", entry.period),
    field("対象児", child),
    field("月齢・年齢", months),
    roField("クラス", AGE_LABEL[ageBand] || ageBand),
    field("身長（cm）", height),
    field("体重（kg）", weight),
  );
  basic._b.appendChild(brow);
  const headerCollect = () => ({
    period: entry.period,
    age_band: ageBand,
    child_id: child.value.trim(),
    age_months: months.value.trim(),
    height_cm: height.value.trim(),
    weight_kg: weight.value.trim(),
  });

  const builders = {
    development_notes: (label) =>
      developmentSection(label || "発達の経過（領域別の叙述）", "経過を追加", entry, formMeta, ageBand),
    care_notes: (label) =>
      textSection(label || "配慮事項・特記", entry.care_notes, 2, "個別配慮・医療的ケアの経過など（任意）", "care_notes"),
    family_liaison: (label) =>
      textSection(label || "家庭との連携", entry.family_liaison, 2, "保護者とのやりとり・家庭との共有（任意）", "family_liaison"),
    overall_note: (label) =>
      textSection(label || "総合所見", entry.overall_note, 3, "その期の育ちの総括（開示前提＝肯定的・断定しない表現で）", "overall_note", {
        hint: "保護者に開示され得ます（肯定的・非断定で）",
      }),
    next_aims: (label) =>
      textSection(label || "次期に向けて", entry.next_aims, 2, "次期に向けての課題・ねらい（任意）", "next_aims"),
  };
  return assembleForm(body, basic, headerCollect, template, builders, [
    "development_notes",
    "care_notes",
    "family_liaison",
    "overall_note",
    "next_aims",
  ]);
}

/* ---- 保育要録フォーム（保育所児童保育要録・年長・L4） ---- */
function buildNurseryRecord(body, entry, formMeta, template) {
  const ageBand = entry.age_band || "3-5";

  const basic = section("基本情報");
  const child = inp(entry.child_id, "はるとくん");
  const months = inp(entry.age_months, "5歳8か月（任意）");
  // 就学先・保育期間は「入所に関する記録」の原簿系＝AI は生成しない（保育士が記入）。
  const school = inp(entry.school_name, "就学先の小学校名（任意）");
  const enroll = inp(entry.enrollment_period, "保育期間 入所〜卒所（任意）");
  const brow = el("div", "de-grid");
  brow.append(
    roField("対象年度", entry.fiscal_year),
    field("対象児", child),
    field("月齢・年齢", months),
    roField("クラス", AGE_LABEL[ageBand] || ageBand),
    field("就学先の小学校", school),
    field("保育期間", enroll),
  );
  basic._b.appendChild(brow);
  const headerCollect = () => ({
    fiscal_year: entry.fiscal_year,
    age_band: ageBand,
    child_id: child.value.trim(),
    age_months: months.value.trim(),
    school_name: school.value.trim(),
    enrollment_period: enroll.value.trim(),
  });

  const builders = {
    final_year_focus: (label) =>
      textSection(label || "最終年度の重点", entry.final_year_focus, 2, "年長クラス全体の年間目標・ねらい", "final_year_focus", {
        hint: "クラス全体のねらい",
      }),
    individual_focus: (label) =>
      textSection(label || "個人の重点", entry.individual_focus, 2, "1年を振り返り特に重視した点", "individual_focus"),
    development_notes: (label) =>
      developmentSection(label || "保育の展開と子どもの育ち", "育ちの姿を追加", entry, formMeta, ageBand),
    special_notes: (label) =>
      textSection(label || "特に配慮すべき事項", entry.special_notes, 2, "特に配慮すべき事項（就学支援等。無ければ空＝「なし」）", "special_notes"),
    growth_until_final: (label) =>
      textSection(label || "最終年度に至るまでの育ち", entry.growth_until_final, 3, "入所時〜前年度の育ちの経過（開示前提＝肯定的・断定しない表現で）", "growth_until_final", {
        hint: "小学校の先生に伝わるよう具体的に",
      }),
  };
  return assembleForm(body, basic, headerCollect, template, builders, [
    "final_year_focus",
    "individual_focus",
    "development_notes",
    "special_notes",
    "growth_until_final",
  ]);
}

const META = {
  diary: { title: "保育日誌", icon: "diary", build: buildDiary },
  monthly: { title: "個別月案", icon: "calendar", build: buildMonthly },
  child_record: { title: "児童票", icon: "chart", build: buildChildRecord },
  nursery_record: { title: "保育要録", icon: "chart", build: buildNurseryRecord },
};

// 編集フォーム panel と collect()（編集後 entry dict）を返す。
// template＝様式テンプレートの当該 doc_type セクション列（本文の順序/ラベル・§18）。未指定は各ビルダ既定順。
export function renderEditableDoc({ kind, entry, formMeta, template }) {
  const meta = META[kind] || META.diary;
  const panel = el("div", "docp docedit");
  panel.innerHTML =
    `<div class="docp-head"><span class="docp-title">${iconHTML(meta.icon)}${esc(meta.title)}` +
    `<span class="label-draft">${iconHTML("edit")}編集できます</span></span></div>`;
  const body = el("div", "docp-body de-body");
  panel.appendChild(body);
  panel._body = body; // docflow が validation/承認バーを追記する

  const collect = meta.build(body, entry || {}, formMeta || {}, template || null);
  return { panel, collect };
}
