// 保育士 UI のブートストラップ：アイコン展開・テーマ・ステータスライン・タブ・各フローの配線。
import * as adk from "./adk.js";
import { el, esc, iconHTML, hydrateIcons } from "./ui.js";
import { makeDocFlow } from "./docflow.js";
import { makePolicy } from "./policy.js";
import { makeNotation } from "./notation.js";
import { makeRecords } from "./records.js";
import { makeClasses } from "./classes.js";
import { makeDiaryForm } from "./diaryform.js";

// 対象児は実在しない仮名（下の名前＋ちゃん/くん）＝現場の日誌の書き方に寄せる（§14・実名は扱わない）。
// さくらちゃんは 3–5 歳児クラスの仮名児（全年齢対応＝§19。年齢帯で枠組み＝3視点/5領域が切り替わるデモ）。
const CHILDREN = ["はるとくん", "ゆいちゃん", "そうたくん"];
const RECORD_CHILDREN = [...CHILDREN, "さくらちゃん"];
const AGE_BAND_OF = { さくらちゃん: "3-5" }; // 既定は 0-2

// 性別→敬称（男→くん / 女→ちゃん 固定）。呼び名（名）＋敬称＝表示名＝child_id の同定キー。
// サーバ（record_store.compose_display_name）と一致させる（新規児登録のプレビュー・降格時のセッション追加用）。
const GENDER_OPTIONS = [
  { value: "male", label: "男の子", honorific: "くん" },
  { value: "female", label: "女の子", honorific: "ちゃん" },
];
const HONORIFIC_OF = Object.fromEntries(GENDER_OPTIONS.map((g) => [g.value, g.honorific]));
const composeDisplayName = (given, gender) => `${(given || "").trim()}${HONORIFIC_OF[gender] || ""}`;
const AGE_BANDS = ["0〜2歳児クラス", "3〜5歳児クラス"];
const AGE_BAND_VALUE = { "0〜2歳児クラス": "0-2", "3〜5歳児クラス": "3-5" };
const AGE_BAND_LABEL = { "0-2": "0〜2歳児クラス", "3-5": "3〜5歳児クラス" }; // ageBandOf(値)→チップ表示
function classAgeBandSummary(cls) {
  const bands = cls.age_bands || [];
  if (!bands.length) return "年齢帯未確定";
  const labels = bands.map((band) => AGE_BAND_LABEL[band] || band).join("・");
  return bands.length === 1 ? labels : `異年齢（${labels}）`;
}
// 日誌の記録日の既定（今日）。toISOString() は UTC 日付を返すため JST 早朝は前日になる
// （記録日は dedupe キー兼 L2/L3/L4 seed の期間クエリ対象なので、日付ずれは版混線・集計月ずれを招く）。
// ローカルタイムゾーンの暦日で組み立てる。
const todayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

// 作成できる書類の種別（統合タブの種別セグメント）。UI キー＝diary/monthly/record/youroku。
// monthly セグメントは**クラス月案**（園の実様式・§18）＝flow kind は "class_monthly"（DocTypeRouter の
// doc_type "クラス月案" に対応）。record は保育経過記録（kind="child_record"）。
// needsChild＝上部の対象児コンボを使うか（クラス月案はクラス単位なので不要）。
const DOC_TYPES = [
  {
    key: "diary",
    label: "保育日誌",
    icon: "diary",
    runLabel: "日誌フォームを開く",
    desc: "",
    needsChild: false, // 日誌は手入力＝クラス（在籍児 roster）単位。単一の対象児コンボは使わない
  },
  {
    key: "monthly",
    label: "クラス月案",
    icon: "calendar",
    runLabel: "クラス月案の下書きを作成する",
    desc: "",
    needsChild: false,
  },
  {
    key: "record",
    label: "保育経過記録",
    icon: "chart",
    runLabel: "保育経過記録の下書きを作成する",
    desc: "",
    needsChild: true,
  },
  {
    key: "youroku",
    label: "保育要録",
    icon: "chart",
    runLabel: "保育要録の下書きを作成する",
    desc: "",
    needsChild: true,
  },
];
const DOC_TYPE_OF = Object.fromEntries(DOC_TYPES.map((d) => [d.key, d]));

// 書類作成画面のカテゴリ別グループ表示（案A）。保育書類を4カテゴリ（指導計画/保育記録/保護者連携/
// 園運営）に分けて一望させる。items の status＝"ready"（作成できる＝DOC_TYPES にフロー実体あり）／
// "soon"（今後対応予定＝灰色の非選択 placeholder・クリックで一言案内）。soon は生成させない＝
// ロードマップの提示（対応済みと未対応を1画面で見せる）。ready item の label/icon は DOC_TYPES から引く
// （二重管理しない）ので key のみ、soon item は自前 label/icon を持つ。
const DOC_CATEGORIES = [
  {
    key: "plan",
    label: "指導計画",
    icon: "calendar",
    items: [
      { key: "annual", status: "soon", label: "年間指導計画", icon: "calendar" },
      { key: "monthly", status: "ready" },
      { key: "weekly", status: "soon", label: "週案", icon: "calendar" },
      { key: "daily", status: "soon", label: "日案", icon: "calendar" },
    ],
  },
  {
    key: "record",
    label: "保育記録",
    icon: "chart",
    items: [
      { key: "diary", status: "ready" },
      { key: "record", status: "ready" },
      { key: "youroku", status: "ready" },
    ],
  },
  {
    key: "parent",
    label: "保護者連携",
    icon: "caregiver",
    items: [
      { key: "renrakucho", status: "soon", label: "連絡帳", icon: "memo" },
      { key: "otayori", status: "soon", label: "おたより", icon: "memo" },
    ],
  },
  {
    key: "ops",
    label: "園運営",
    icon: "users",
    items: [{ key: "shift", status: "soon", label: "勤務シフト", icon: "clock" }],
  },
];

// 表示名→誕生日（DB 接続時のみ・/api/children の birthdate を main() で流し込む）。年齢帯の自動判定に使う。
const BIRTHDATE_OF = {};

// 対象児の年齢帯（0-2/3-5）を解く。DB に誕生日があれば満年齢で判定（3歳以上=3-5・未満=0-2）、
// 無ければ従来のハードコード表→既定 0-2 に降格。30人規模でも DB から正しく引ける。
// 学年（4月区切り）の厳密さは v0 簡略化（§19 と同枠＝園差はヒアリング残課題）。
function ageBandOf(name) {
  const bd = BIRTHDATE_OF[name];
  if (bd) {
    const d = new Date(bd);
    if (!isNaN(d.getTime())) {
      const now = new Date();
      let age = now.getFullYear() - d.getFullYear();
      const m = now.getMonth() - d.getMonth();
      if (m < 0 || (m === 0 && now.getDate() < d.getDate())) age--;
      return age >= 3 ? "3-5" : "0-2";
    }
  }
  return AGE_BAND_OF[name] || "0-2";
}

const POLICY_SAMPLES = [
  "感触遊びは『感触語＋そのときの表情』を併記したい。ただし断定的な評価表現は避けたい。",
  "保護者向けの一文は、できた事実だけでなく『次への意欲』が伝わる表現にしたい。",
];

// 指針を育てるの「対象書類」＝改善エージェントの scope と 1:1（backend の PolicyScope 値をそのまま送る）。
// この気づきがどの書類に効くかを保育士が先に選ぶ＝反映先を可視化する（依存の実体＝共通は全書類／各書類は
// その1書類。render_for_doc が「共通＋その書類」を前置注入するのと一致）。「すべて」だけ scope=null＝
// 対象は AI 判断（従来動作）で、デッキも全カード表示。docTypes は下のカードデッキの絞り込みキー（card_view の doc_type）。
const POLICY_TARGETS = [
  { key: "all", label: "すべて", scope: null, docTypes: null },
  { key: "common", label: "共通", scope: "共通", docTypes: ["common"] },
  { key: "diary", label: "保育日誌", scope: "保育日誌", docTypes: ["common", "diary"] },
  { key: "monthly", label: "クラス月案", scope: "月案", docTypes: ["common", "monthly"] },
  { key: "child_record", label: "保育経過記録", scope: "保育経過記録", docTypes: ["common", "child_record"] },
  { key: "nursery_record", label: "保育要録", scope: "保育要録", docTypes: ["common", "nursery_record"] },
];
const POLICY_TARGET_OF = Object.fromEntries(POLICY_TARGETS.map((t) => [t.key, t]));

// 前月日誌の仮名サンプル（L2 還流のデモ seed）。現場に即した複数日（感触遊び/歩行/絵本）＝月齢・
// 数量化した生活記録・具体的な姿。scripts/run_monthly.py の _sample_prev_entries と同趣旨（§14）。
function samplePrevEntries(childId) {
  const days = [
    {
      date: "2026-06-24",
      weather: "晴れ",
      practice_record: "園庭の砂場で感触遊びを行った。",
      observed_state: "砂場でスコップに砂をすくっては空ける動作を繰り返し、こぼれる様子をじっと見つめた",
      tags: ["身近なものと関わり感性が育つ"],
      meal: "完了期の給食を8割摂取、麦茶80ml",
      sleep: "12:15〜14:20 午睡",
      toilet: "排尿4回・排便1回",
      mood_health: "視診で体温36.5℃、機嫌よく変化なし",
      child_focus: "素材の感触に繰り返し関わっていた",
      self_review: "スコップやカップを人数分用意できた",
    },
    {
      date: "2026-06-26",
      weather: "くもり",
      practice_record: "室内で歩行や移動を促す環境を整えた。",
      observed_state: "両手を広げてバランスを取りながら数歩歩き、保育者のもとへ進もうとした",
      tags: ["健やかに伸び伸びと育つ"],
      meal: "完了期の給食を9割摂取",
      sleep: "12:20〜14:30 ぐっすり午睡",
      toilet: "排尿5回・排便1回",
      mood_health: "視診で体温36.6℃、活発で気になる点なし",
      child_focus: "自分から体を動かそうとする意欲が高まっていた",
      self_review: "転倒に備えマットと広い動線を用意できた",
    },
    {
      date: "2026-06-30",
      weather: "晴れ",
      practice_record: "少人数で絵本を読み、指さしや発声に応じた。",
      observed_state: "絵本の動物を指さして声を出し、保育者に見せようとした",
      tags: ["身近な人と気持ちが通じ合う"],
      meal: "完了期の給食を全量摂取、麦茶90ml",
      sleep: "12:15〜14:10 午睡",
      toilet: "排尿4回・排便1回",
      mood_health: "視診で体温36.6℃、機嫌よく変化なし",
      child_focus: "好きなものを見つけ、伝えたい気持ちが育っていた",
      self_review: "発見に共感的に応答し、繰り返しを楽しめるようにした",
    },
  ];
  return days.map((d) => ({
    date: d.date,
    age_band: "0-2",
    weather: d.weather,
    attendance: [{ child_id: childId, present: true, reason: null }],
    practice_record: d.practice_record,
    individual_notes: [
      {
        child_id: childId,
        age_months: "1歳3か月",
        observed_state: d.observed_state,
        tags: d.tags,
        life_record: { meal: d.meal, sleep: d.sleep, toilet: d.toilet, mood_health: d.mood_health },
      },
    ],
    evaluation: { child_focus: d.child_focus, self_review: d.self_review },
  }));
}

// 前月のクラスの日誌の仮名サンプル（クラス月案＝L2 還流のデモ seed）。個別月案（1児）と違い、
// クラス全体なので**複数の仮名児**を登場させる（digest がクラス全登場児ぶんになり、0–2 は個人目標が
// 児ごとに生成される）。年齢帯で内容を切替（0–2＝3視点・生活記録あり／3–5＝5領域・生活記録なし）。
function sampleClassPrevEntries(ageBand) {
  const roster =
    ageBand === "3-5"
      ? [
          { child: "さくらちゃん", months: "4歳2か月", state: "鬼ごっこでルールを友だちに説明し、つかまった子に優しく声をかけていた", tags: ["人間関係"] },
          { child: "れんくん", months: "4歳5か月", state: "積み木で友だちと大きな街を作り、役割を分担して遊びを続けた", tags: ["言葉", "人間関係"] },
          { child: "みおちゃん", months: "4歳0か月", state: "散歩で見つけた葉の色や形の違いに気づき、図鑑で調べようとした", tags: ["環境"] },
        ]
      : [
          { child: "はるとくん", months: "1歳3か月", state: "歩行が安定し、好きな玩具を自分で選んで保育者に手渡した", tags: ["健やかに伸び伸びと育つ"], life: { meal: "完了期を全量摂取", sleep: "12:15〜14:10 午睡", toilet: "排尿4回・排便1回", mood_health: "体温36.5℃・機嫌よし" } },
          { child: "ゆいちゃん", months: "1歳1か月", state: "砂場でスコップに砂をすくっては空け、こぼれる様子をじっと見つめた", tags: ["身近なものと関わり感性が育つ"], life: { meal: "後期食を8割", sleep: "12:20〜14:20 午睡", toilet: "排尿5回・排便1回", mood_health: "体温36.6℃・変化なし" } },
          { child: "そうたくん", months: "0歳11か月", state: "絵本の動物を指さして声を出し、保育者に見せようとした", tags: ["身近な人と気持ちが通じ合う"], life: { meal: "後期食を9割", sleep: "12:10〜14:00 午睡", toilet: "排尿4回・排便1回", mood_health: "体温36.5℃・機嫌よし" } },
        ];
  const dates = ["2026-06-12", "2026-06-26"];
  const entries = [];
  for (const d of dates) {
    for (const r of roster) {
      entries.push({
        date: d,
        age_band: ageBand,
        weather: "晴れ",
        attendance: [{ child_id: r.child, present: true, reason: null }],
        practice_record: "クラスの子どもの興味に応じた遊びを用意した。",
        individual_notes: [
          {
            child_id: r.child,
            age_months: r.months,
            observed_state: r.state,
            tags: r.tags,
            life_record: r.life || {},
          },
        ],
        evaluation: { child_focus: "興味の対象に自分から関わっていた", self_review: "発達に合わせた環境を用意できた" },
      });
    }
  }
  return entries;
}

// 期間中の日誌の仮名サンプル（保育経過記録＝L3 還流のデモ seed）。3ヶ月にわたる発達の推移（月ごとに姿が
// 進む）を含め、保育経過記録の「点の記録→期の育ちの線」への再構成が見えるようにする（§14/§19）。
// 0–2（既定）と 3–5（さくらちゃん＝5領域・生活記録なし）で内容を切り替える（全年齢対応）。
function samplePeriodEntries(childId) {
  const ageBand = ageBandOf(childId);
  const days =
    ageBand === "3-5"
      ? [
          { date: "2026-04-10", months: "4歳0か月", state: "新しいクラスに少し緊張しながらも、朝の支度を自分で進めた", tags: ["健康"], practice: "進級後の生活の流れを一緒に確認した。" },
          { date: "2026-04-24", months: "4歳0か月", state: "好きな電車の絵本を友だちに見せ、言葉で説明しようとした", tags: ["言葉"], practice: "好きな遊びを介した友だちとの橋渡しをした。" },
          { date: "2026-05-15", months: "4歳1か月", state: "鬼ごっこでルールを守れず悔しがる友だちに「もう1回やろう」と声をかけた", tags: ["人間関係"], practice: "集団遊びのルールを子どもたちと話し合った。" },
          { date: "2026-05-29", months: "4歳1か月", state: "飼育しているカブトムシの幼虫を毎日観察し、変化を保育者に報告した", tags: ["環境"], practice: "飼育・観察のコーナーを継続して設けた。" },
          { date: "2026-06-12", months: "4歳2か月", state: "音楽に合わせて自分で考えた動きを披露し、友だちの動きも真似て楽しんだ", tags: ["表現"], practice: "リズム遊びで自由な表現を受け止めた。" },
          { date: "2026-06-26", months: "4歳2か月", state: "当番活動で号令をかけ、帰りの会で今日の出来事をみんなの前で話した", tags: ["言葉", "人間関係"], practice: "当番活動の役割を任せ、発表の場を作った。" },
        ]
      : [
          { date: "2026-04-10", months: "1歳1か月", state: "つかまり立ちから伝い歩きで棚に沿って移動し、玩具に手を伸ばした", tags: ["健やかに伸び伸びと育つ"], practice: "つかまり立ちを促す安全な環境を整えた。", life: { meal: "離乳食後期を7割", sleep: "12:00〜14:00 午睡", toilet: "排尿4回・排便1回", mood: "体温36.5℃・機嫌よし" } },
          { date: "2026-04-24", months: "1歳1か月", state: "保育者の歌に合わせて体を揺らし、目が合うと声を出して笑った", tags: ["身近な人と気持ちが通じ合う"], practice: "ふれあい遊びで応答的に関わった。", life: { meal: "離乳食後期を8割", sleep: "12:10〜14:05 午睡", toilet: "排尿4回・排便1回", mood: "体温36.6℃・変化なし" } },
          { date: "2026-05-15", months: "1歳2か月", state: "両手を離して2〜3歩歩き、保育者のもとへ進もうとした", tags: ["健やかに伸び伸びと育つ"], practice: "広い動線とマットで歩行を支えた。", life: { meal: "完了期へ移行し8割", sleep: "12:15〜14:20 午睡", toilet: "排尿5回・排便1回", mood: "体温36.5℃・機嫌よし" } },
          { date: "2026-05-29", months: "1歳2か月", state: "砂場でスコップに砂をすくっては空け、こぼれる様子をじっと見つめた", tags: ["身近なものと関わり感性が育つ"], practice: "砂・水の感触遊びを用意した。", life: { meal: "完了期を8割・麦茶80ml", sleep: "12:15〜14:15 午睡", toilet: "排尿4回・排便1回", mood: "体温36.6℃・変化なし" } },
          { date: "2026-06-12", months: "1歳3か月", state: "絵本の動物を指さして「わんわん」と声を出し、保育者に見せようとした", tags: ["身近な人と気持ちが通じ合う", "身近なものと関わり感性が育つ"], practice: "少人数で絵本を読み指さしに応じた。", life: { meal: "完了期を9割", sleep: "12:20〜14:30 午睡", toilet: "排尿5回・排便1回", mood: "体温36.6℃・機嫌よし" } },
          { date: "2026-06-26", months: "1歳3か月", state: "安定して歩き、好きな玩具を自分で選んで保育者に手渡した", tags: ["健やかに伸び伸びと育つ"], practice: "自分で選べる玩具棚の配置にした。", life: { meal: "完了期を全量摂取", sleep: "12:15〜14:10 午睡", toilet: "排尿4回・排便1回", mood: "体温36.5℃・機嫌よし" } },
        ];
  return days.map((d) => ({
    date: d.date,
    age_band: ageBand,
    weather: "晴れ",
    attendance: [{ child_id: childId, present: true, reason: null }],
    practice_record: d.practice,
    individual_notes: [
      {
        child_id: childId,
        age_months: d.months,
        observed_state: d.state,
        tags: d.tags,
        life_record: d.life
          ? { meal: d.life.meal, sleep: d.life.sleep, toilet: d.life.toilet, mood_health: d.life.mood }
          : {},
      },
    ],
    evaluation: { child_focus: "興味の対象に自分から関わっていた", self_review: "発達に合わせた環境を用意できた" },
  }));
}

// 保育要録（L4）の seed＝最終年度（年長=3–5）の保育経過記録サンプル。1年を年度4期（各3か月）に区切り、育ちの推移
// （自己発揮→協同→就学期待）を含める＝要録の「期の記録→1年の育ちの線」への再構成が見える（§14/§19）。
// scripts/run_youroku.py の _sample_record_entries と同趣旨（ChildRecord の配列）。
function sampleRecordEntries(childId) {
  const periods = [
    { period: "2026-04〜2026-06", months: "5歳3か月",
      dev: [["進級当初は新しい環境に戸惑いも見られたが、生活の流れが分かると安心して過ごした", "健康"],
            ["鬼ごっこなど走る遊びを好み、気の合う友だちと関わって遊んだ", "人間関係"]],
      overall: "新しい環境に慣れ、好きな遊びを見つけて自分を発揮し始めた", next: "友だちとの関わりを広げていく" },
    { period: "2026-07〜2026-09", months: "5歳6か月",
      dev: [["製作活動で自分なりの思いを描き加えながら満足感を味わった", "表現"],
            ["散歩で摘んできた草花に興味をもち、図鑑で名前や色を調べようとした", "環境"]],
      overall: "自分の思いを表現しようとする姿が増え、探究する意欲が育った", next: "言葉で伝え合う楽しさを広げる" },
    { period: "2026-10〜2026-12", months: "5歳9か月",
      dev: [["メッセージボード作りが友だちに広がり、伝え合う喜びを味わった", "言葉"],
            ["当番活動に責任をもって取り組み、友だちと声を掛け合った", "人間関係"]],
      overall: "自信をもって表現し、仲間と役割を担う姿が育った", next: "就学への期待を高める" },
    { period: "2027-01〜2027-03", months: "6歳0か月",
      dev: [["小学校見学を通して就学への期待を高め、見通しをもって準備した", "環境"],
            ["生活発表会で友だちと協力し、最後までやり遂げた", "表現"]],
      overall: "就学への期待を力に変え、自信をもって卒園を迎える姿が育った", next: "小学校生活を楽しみに待つ" },
  ];
  return periods.map((p) => ({
    period: p.period,
    age_band: "3-5",
    child_id: childId,
    age_months: p.months,
    development_notes: p.dev.map(([description, tag]) => ({ description, tags: [tag] })),
    care_notes: "",
    family_liaison: "",
    overall_note: p.overall,
    next_aims: p.next,
  }));
}

// 期の開始年月から保育年度を解く（4月始まり。1〜3月は前年の年度）。
function fiscalYearOfPeriod(period) {
  const match = /^(\d{4})-(\d{2})/.exec(String(period || ""));
  if (!match) return "";
  const year = Number(match[1]);
  const month = Number(match[2]);
  if (!year || month < 1 || month > 12) return "";
  return String(month >= 4 ? year : year - 1);
}

function fiscalYearsOf(entries) {
  return [...new Set((entries || []).map((entry) => fiscalYearOfPeriod(entry.period)).filter(Boolean))].sort(
    (a, b) => Number(b) - Number(a),
  );
}

const $ = (id) => document.getElementById(id);

/* ============================================================
   テーマ（auto / light / dark・localStorage 保存）
   ============================================================ */
function effectiveTheme() {
  const t = document.documentElement.getAttribute("data-theme");
  if (t) return t;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
function applyTheme(t) {
  const html = document.documentElement;
  if (t) html.setAttribute("data-theme", t);
  else html.removeAttribute("data-theme");
  const btn = $("theme-toggle");
  if (btn) btn.querySelector("span").innerHTML = iconHTML(effectiveTheme() === "dark" ? "sun" : "moon");
}
function setupTheme() {
  let saved = null;
  try {
    saved = localStorage.getItem("hoiku-theme");
  } catch {
    /* localStorage 不可でも動く */
  }
  applyTheme(saved);
  $("theme-toggle").onclick = () => {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    try {
      localStorage.setItem("hoiku-theme", next);
    } catch {
      /* noop */
    }
    applyTheme(next);
  };
}

/* ============================================================
   ステータスライン（ambient：モデル・対象児・進行・降格）
   ============================================================ */
let slEls = {};
function buildStatusline() {
  const sl = $("statusline");
  sl.innerHTML = "";
  const subject = el("span", "sl-item hidden");
  const phase = el("span", "sl-item hidden");
  const budget = el("span", "sl-item hidden");
  sl.append(subject, phase, budget);
  slEls = { dot: null, subject, phase, budget };
}
const status = {
  setSubject(name) {
    if (!slEls.subject) return;
    if (!name) {
      slEls.subject.classList.add("hidden");
      return;
    }
    slEls.subject.classList.remove("hidden");
    slEls.subject.innerHTML = `${iconHTML("caregiver")}対象児 <b>${esc(name)}</b>`;
  },
  setPhase(text, state) {
    if (!slEls.phase) return;
    slEls.phase.classList.remove("hidden");
    const color = { working: "var(--state-working)", waiting: "var(--state-waiting)", done: "var(--state-done)" }[state] || "var(--muted)";
    const live = state === "working" ? " live" : "";
    slEls.phase.innerHTML = `<span class="dotc${live}" style="background:${color}"></span><span class="sl-phase">${esc(text)}</span>`;
    if (slEls.dot) slEls.dot.classList.toggle("live", state === "working");
  },
  clearPhase() {
    if (slEls.phase) slEls.phase.classList.add("hidden");
    if (slEls.dot) slEls.dot.classList.remove("live");
  },
  setBudget(budget) {
    if (!slEls.budget || !budget || !budget.available) return;
    slEls.budget.classList.remove("hidden");
    const exhausted = budget.remaining_yen <= 0;
    slEls.budget.innerHTML = `${iconHTML("sparkle")}AI利用枠 <b>${esc(String(budget.remaining_yen))}円</b> / ${esc(String(budget.limit_yen))}円`;
    slEls.budget.classList.toggle("is-budget-limit", exhausted);
    slEls.budget.title = exhausted ? "上限に達しました。次の時間帯に再開できます。" : "1時間ごとのAI利用可能額です。";
  },
};

/* ============================================================
   タブ・チップ・ゲート
   ============================================================ */
function activateTab(tab) {
  document.querySelectorAll(".tab").forEach((t) => {
    t.classList.remove("is-active");
    t.setAttribute("aria-selected", "false");
  });
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("is-active"));
  tab.classList.add("is-active");
  tab.setAttribute("aria-selected", "true");
  $("tab-" + tab.dataset.tab).classList.add("is-active");
  status.clearPhase();
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.onclick = () => activateTab(tab);
  });
}

// 上位タブを名前（data-tab）で切り替える（プログラム用＝クリックの副作用〔records.refresh 等〕を起こさない。
// 「未記入の日誌へ飛んで記入」導線が使う＝視覚切替のみ。呼び出し側が openDoc で自前に読み込む）。
function switchTab(name) {
  const tab = document.querySelector(`.tab[data-tab="${name}"]`);
  if (tab) activateTab(tab);
}

// サブタブ（「育てる」タブ内の 指針を育てる／表記ルール）。上位タブと同じ流儀で、押した親パネル内の
// .subtab/.subpanel だけを切り替える（他タブに副作用を出さない＝仕組みは分離のまま・presentation の統合②）。
function setupSubTabs() {
  document.querySelectorAll(".subtab").forEach((tab) => {
    tab.onclick = () => {
      const parent = tab.closest(".panel");
      parent.querySelectorAll(".subtab").forEach((t) => {
        t.classList.remove("is-active");
        t.setAttribute("aria-selected", "false");
      });
      parent.querySelectorAll(".subpanel").forEach((p) => p.classList.remove("is-active"));
      tab.classList.add("is-active");
      tab.setAttribute("aria-selected", "true");
      $("subtab-" + tab.dataset.subtab).classList.add("is-active");
    };
  });
}

// 選択式チップ群を作り、選択中の値を返すゲッターを提供。
// iconName は文字列（全チップ共通）か、値→アイコン名の関数。labelOf は値→表示ラベル（既定は値そのもの）。
// 返り値 getter() は選択中の値。getter.set(v) はクリック相当（onPick も発火）、getter.select(v) は表示だけ差し替え（onPick 不発火）。
function chipGroup(container, values, onPick, iconName, labelOf) {
  let selected = values[0];
  const chips = new Map();
  container.innerHTML = "";
  const activate = (v) => {
    container.querySelectorAll(".chip").forEach((c) => c.classList.remove("is-active"));
    const c = chips.get(v);
    if (c) c.classList.add("is-active");
    selected = v;
  };
  values.forEach((v, i) => {
    const ic = typeof iconName === "function" ? iconName(v) : iconName;
    const label = labelOf ? labelOf(v) : v;
    const chip = el("button", "chip" + (i === 0 ? " is-active" : ""), (ic ? iconHTML(ic) : "") + esc(label));
    chip.type = "button";
    chip.onclick = () => {
      activate(v);
      onPick && onPick(v);
    };
    chips.set(v, chip);
    container.appendChild(chip);
  });
  const getter = () => selected;
  getter.set = (v) => {
    if (!chips.has(v) || v === selected) return;
    activate(v);
    onPick && onPick(v);
  };
  getter.select = (v) => {
    if (chips.has(v)) activate(v);
  };
  return getter;
}

// 書類作成の種別セレクタ（案A：カテゴリ別グループ表示）。categories を歩いてカテゴリ見出し＋チップ行を描く。
// ready チップは選択可（onPick）、soon チップは灰色の非選択 placeholder（クリックで onSoon＝一言案内・
// 選択状態は変えない）。契約は chipGroup と同じ＝選択中の ready key を返すゲッター（.select(key) も持つ）。
// setSegBusy が `#doc-kind .chip` の disabled を切るので、生成中は soon も含め全チップがロックされる。
function renderDocMenu(container, categories, { onPick, onSoon } = {}) {
  container.innerHTML = "";
  let selected = null;
  const chips = new Map(); // ready key -> chip 要素
  const activate = (key) => {
    container.querySelectorAll(".chip.is-active").forEach((c) => c.classList.remove("is-active"));
    const c = chips.get(key);
    if (c) c.classList.add("is-active");
    selected = key;
  };
  for (const cat of categories) {
    const group = el("div", "doc-cat");
    group.appendChild(el("div", "doc-cat-head", iconHTML(cat.icon) + esc(cat.label)));
    const row = el("div", "doc-cat-row");
    for (const it of cat.items) {
      const meta = DOC_TYPE_OF[it.key];
      const ready = it.status === "ready";
      const label = it.label || (meta && meta.label) || it.key;
      const icon = it.icon || (meta && meta.icon) || cat.icon;
      const chip = el(
        "button",
        "chip" + (ready ? "" : " is-soon"),
        iconHTML(icon) + esc(label) + (ready ? "" : '<span class="chip-soon">近日</span>'),
      );
      chip.type = "button";
      if (ready) {
        chip.onclick = () => {
          activate(it.key);
          onPick && onPick(it.key);
        };
        chips.set(it.key, chip);
      } else {
        // 非選択だが click は拾って案内を出す（disabled にすると無反応になるため aria で伝える）。
        chip.setAttribute("aria-disabled", "true");
        chip.title = "この書類は今後対応予定です";
        chip.onclick = () => onSoon && onSoon({ ...it, label });
      }
      row.appendChild(chip);
    }
    group.appendChild(row);
    container.appendChild(group);
  }
  const getter = () => selected;
  getter.select = (key) => {
    if (chips.has(key)) activate(key);
  };
  return getter;
}

// 前方一致の共通部分を <b> で強調した候補ラベル HTML を返す（残りは通常字）。
function highlightPrefix(name, query) {
  if (query && name.startsWith(query)) return "<b>" + esc(query) + "</b>" + esc(name.slice(query.length));
  return esc(name);
}

// 対象児コンボボックス：入力欄＋前方一致の候補ドロップダウン＋Tab/Enter/クリックで補完。
// チップ全列挙（chipGroup）が 30 人規模で破綻するのを避ける入力式。契約は chipGroup と同じ＝
// 確定中の表示名を返すゲッターを返す（onPick は確定が変わったとき呼ぶ）。
function childCombo(container, names, { onPick, labelId, onAddChild } = {}) {
  container.classList.add("combo");
  container.classList.remove("chips");
  container.innerHTML = "";
  const listId = container.id + "-list";
  const icon = el("span", "combo-ic", iconHTML("caregiver"));
  icon.setAttribute("aria-hidden", "true");
  const input = el("input", "combo-input");
  input.type = "text";
  input.autocomplete = "off";
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-controls", listId);
  input.placeholder = "名前を入力";
  if (labelId) input.setAttribute("aria-labelledby", labelId);
  const list = el("ul", "combo-list");
  list.id = listId;
  list.setAttribute("role", "listbox");
  list.hidden = true;
  container.append(icon, input, list);

  // 書類作成時に特定の児童を勝手に対象にしない。候補は入力欄にフォーカスすると表示する。
  let selected = "";
  let visible = []; // 現在表示中の候補名
  let active = -1; // ハイライト中の候補（visible 上の index）
  let formOpen = false; // 新規児の登録フォーム表示中か（blur の巻き戻しを止める）
  input.value = selected;

  const close = () => {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  };
  const setActive = (i) => {
    active = i;
    [...list.children].forEach((li, idx) => {
      const on = idx === i;
      li.classList.toggle("is-active", on);
      li.setAttribute("aria-selected", on ? "true" : "false");
      if (on) {
        input.setAttribute("aria-activedescendant", li.id);
        li.scrollIntoView({ block: "nearest" });
      }
    });
  };
  const commit = (name) => {
    selected = name;
    input.value = name;
    close();
    onPick && onPick(name);
  };
  const render = () => {
    const q = input.value.trim();
    // 前方一致（先頭から一致・§ユーザー指定）。空欄なら全件（一覧から選べる）。
    visible = q ? names.filter((n) => n.startsWith(q)) : names.slice();
    list.innerHTML = "";
    if (!visible.length) {
      // 該当なし＝未登録の名前。onAddChild があれば「新規に追加」を促す（元の要望：まだ無い名前を足す）。
      if (onAddChild && q) {
        const li = el(
          "li",
          "combo-option combo-add-cue",
          iconHTML("check") + `<span>「<b>${esc(q)}</b>」を新しい対象児として追加</span>`,
        );
        li.id = listId + "-add";
        li.setAttribute("role", "option");
        li.addEventListener("mousedown", (e) => {
          e.preventDefault();
          openAddForm(q);
        });
        list.appendChild(li);
      } else {
        list.appendChild(el("li", "combo-empty", "該当なし"));
      }
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      active = -1;
      return;
    }
    visible.forEach((n, i) => {
      const li = el("li", "combo-option", highlightPrefix(n, q));
      li.id = listId + "-opt-" + i;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", "false");
      // mousedown（click より前・blur より前）で確定＝候補押下時に入力欄の blur で消えない。
      li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        commit(n);
      });
      li.addEventListener("mouseenter", () => setActive(i));
      list.appendChild(li);
    });
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    setActive(0);
  };

  input.addEventListener("input", render);
  input.addEventListener("focus", render);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (list.hidden) render();
      else if (visible.length) setActive(Math.min(active + 1, visible.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (visible.length) setActive(Math.max(active - 1, 0));
    } else if (e.key === "Enter") {
      if (!list.hidden && active >= 0) {
        e.preventDefault();
        commit(visible[active]);
      }
    } else if (e.key === "Tab") {
      // Tab 補完：ハイライト中の候補で確定する（フォーカス移動は妨げない＝そのまま次欄へ）。
      if (!list.hidden && active >= 0) commit(visible[active]);
    } else if (e.key === "Escape") {
      input.value = selected;
      close();
    }
  });
  input.addEventListener("blur", () => {
    // 妥当な表示名でなければ確定値へ戻す（不正な自由入力を送らない）。mousedown 確定を待って次tick。
    setTimeout(() => {
      if (formOpen) return; // 登録フォームを開いた＝巻き戻さない（フォーム側で確定/取消する）
      const typed = input.value.trim();
      if (typed !== selected) {
        if (names.includes(typed)) commit(typed);
        else {
          input.value = selected;
          close();
        }
      } else close();
    }, 0);
  });

  // 新規児の登録フォーム（本名＝姓/名＋性別）。名＋敬称（性別導出）＝表示名を合成し onAddChild へ渡す。
  // 敬称の「くん/ちゃん問題」は性別セレクタで一意化＝入力ゆれ・重複児を構造で防ぐ。
  function openAddForm(prefillGiven) {
    formOpen = true;
    close();
    let gender = "male"; // 既定は男の子（プレビューで即分かるので取り違えは起きにくい）
    const panel = el("div", "combo-add");

    const family = el("input", "combo-input combo-add-input");
    family.type = "text";
    family.placeholder = "姓（任意・氏名欄用）";
    const given = el("input", "combo-input combo-add-input");
    given.type = "text";
    given.placeholder = "名（呼び名）";
    given.value = (prefillGiven || "").trim();
    const nameRow = el("div", "combo-add-names");
    nameRow.append(family, given);

    // 生年月日（任意）。登録すると保育経過記録などの「歳児」欄を満年齢（○歳○か月）で自動表示できる。
    const birth = el("input", "combo-input combo-add-input");
    birth.type = "date";
    birth.setAttribute("aria-label", "生年月日（任意）");
    const birthRow = el("label", "combo-add-birth", "生年月日（任意）");
    birthRow.append(birth);

    const genderRow = el("div", "combo-add-gender");
    const genderBtns = GENDER_OPTIONS.map((g) => {
      const b = el("button", "chip", iconHTML("caregiver") + g.label);
      b.type = "button";
      b.onclick = () => {
        gender = g.value;
        genderBtns.forEach((x) => x.el.classList.toggle("is-active", x.value === gender));
        syncPreview();
      };
      genderRow.append(b);
      return { el: b, value: g.value };
    });
    genderBtns.forEach((x) => x.el.classList.toggle("is-active", x.value === gender));

    const preview = el("div", "combo-add-preview");
    const errBox = el("div", "combo-add-error");
    errBox.hidden = true;
    const addBtn = el("button", "btn btn-primary", iconHTML("check") + "追加");
    addBtn.type = "button";
    const cancelBtn = el("button", "btn btn-ghost", "キャンセル");
    cancelBtn.type = "button";
    const actions = el("div", "combo-add-actions");
    actions.append(addBtn, cancelBtn);

    function syncPreview() {
      const dn = composeDisplayName(given.value, gender);
      preview.innerHTML = dn
        ? `呼び名：<b>${esc(dn)}</b>`
        : `<span class="muted">名を入力してください</span>`;
    }
    given.addEventListener("input", syncPreview);
    syncPreview();

    function removeForm() {
      formOpen = false;
      panel.remove();
      input.focus();
    }
    cancelBtn.onclick = removeForm;

    addBtn.onclick = async () => {
      const g = given.value.trim();
      errBox.hidden = true;
      if (!g) {
        errBox.textContent = "名（呼び名）を入力してください。";
        errBox.hidden = false;
        given.focus();
        return;
      }
      const displayName = composeDisplayName(g, gender);
      if (names.includes(displayName)) {
        // 既に居る＝そのまま選ぶ（重複を作らない）。
        formOpen = false;
        panel.remove();
        commit(displayName);
        return;
      }
      addBtn.disabled = true;
      const res = await onAddChild({
        family_name: family.value.trim(),
        given_name: g,
        gender,
        birthdate: birth.value || "",
      });
      addBtn.disabled = false;
      if (!res || !res.ok) {
        errBox.textContent = (res && res.message) || "登録に失敗しました。";
        errBox.hidden = false;
        return;
      }
      const dn = res.displayName || displayName;
      if (!names.includes(dn)) names.push(dn);
      formOpen = false;
      panel.remove();
      commit(dn);
    };

    panel.append(nameRow, genderRow, birthRow, preview, actions, errBox);
    container.append(panel);
    given.focus();
    given.setSelectionRange(given.value.length, given.value.length);
  }

  return () => selected;
}

function sampleChips(container, samples, onPick) {
  container.innerHTML = "";
  samples.forEach((s, i) => {
    const chip = el("button", "chip", iconHTML("memo") + "例" + (i + 1));
    chip.type = "button";
    chip.title = s;
    chip.onclick = () => onPick(s);
    container.appendChild(chip);
  });
}

/* ============================================================
   起動
   ============================================================ */
const DATA_INITIALIZED_KEY_PREFIX = "hoiku_data_initialized:";

function dataInitializedKey(cfg) {
  return DATA_INITIALIZED_KEY_PREFIX + cfg.default_user_id;
}

function hasInitializedData(cfg) {
  try {
    return localStorage.getItem(dataInitializedKey(cfg)) === "1";
  } catch {
    return false;
  }
}

function rememberDataInitialized(cfg) {
  try {
    localStorage.setItem(dataInitializedKey(cfg), "1");
  } catch {
    // localStorage が使えない環境でも、現在の画面ではボタンを消して初期化結果を見せる。
  }
}

// ヘッダの担当者欄。Google サインイン時は「自分の表示名（users.display_name）」を DB に登録/編集する欄になり
// （証跡の actor はサーバが検証済み email＋この表示名で残す＝§13）、未サインイン時は従来の自己申告
// （localStorage・認証導入までのつなぎ）。config を見てモードを切り替える（config 読込後に呼ぶ）。
function setupActor(cfg) {
  const inp = $("actor-name");
  if (!inp) return;
  const field = inp.closest(".actor-field");
  const email = cfg && cfg.user_email;
  const logout = $("logout");
  const resetData = $("reset-data");
  if (email) {
    // サインイン済み＝表示名の登録/編集。値は DB（user_display_name）が正。未登録は email をプレースホルダに出して促す。
    inp.value = cfg.user_display_name || "";
    inp.placeholder = email;
    const tip = `サインイン: ${email}（この名前が保存・承認の記録に残ります）`;
    inp.title = tip;
    inp.setAttribute("aria-label", `表示名（${email} として記録されます）`);
    if (field) field.title = tip;
    let saved = inp.value.trim();
    inp.addEventListener("change", async () => {
      const name = inp.value.trim();
      if (name === saved) return;
      const r = await adk.setUserProfile(name);
      if (r.status === "ok") {
        saved = name;
        flashActor(field, name ? "表示名を保存しました" : "表示名をクリアしました");
      } else if (r.status === "skipped") {
        flashActor(field, "未接続のため保存できません", true);
      } else {
        flashActor(field, r.detail || "保存に失敗しました", true);
      }
    });
    if (logout) {
      logout.classList.remove("hidden");
      logout.onclick = async () => {
        await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
        window.location.assign("/");
      };
    }
    // データの初期化＝workspace の書類・園児・クラス・フィードバック・指針/表記のカスタムを即時に消して
    // デフォルトの初期サンプルへ戻す（ログインは継続・reload で全タブが初期状態）。DB 未接続時は
    // サーバが skipped を返すので正直に案内する（アカウント削除の受付 API とは別物）。
    if (resetData && cfg.records_connected && !hasInitializedData(cfg)) {
      resetData.classList.remove("hidden");
      resetData.onclick = async () => {
        const ok = window.confirm(
          "この画面の書類・園児・クラス・フィードバック・指針/表記のカスタムをすべて消して、初期サンプルデータに戻します。よろしいですか？"
        );
        if (!ok) return;
        resetData.disabled = true;
        try {
          const r = await fetch("/api/account/reset", { method: "POST" });
          const j = await r.json().catch(() => ({}));
          if (!r.ok || j.status !== "ok") {
            window.alert(j.reason || j.detail || "データを初期化できませんでした。");
            return;
          }
          rememberDataInitialized(cfg);
          resetData.classList.add("hidden");
          window.alert("初期サンプルデータに戻しました。");
          window.location.reload();
        } finally {
          resetData.disabled = false;
        }
      };
    }
  } else {
    // 未サインイン（ローカル/デモ）＝自己申告を localStorage に永続（従来動作）。
    inp.value = localStorage.getItem("hoiku_actor") || "";
    inp.addEventListener("change", () => localStorage.setItem("hoiku_actor", inp.value.trim()));
  }
}

// 表示名の保存結果をヘッダに一瞬だけ出す（絶対配置でレイアウトを動かさない小さな確認）。
function flashActor(field, text, isErr = false) {
  if (!field) return;
  let note = field.querySelector(".actor-note");
  if (!note) {
    note = el("span", "actor-note");
    field.appendChild(note);
  }
  note.textContent = text;
  note.classList.toggle("is-err", isErr);
  note.classList.remove("show");
  void note.offsetWidth; // reflow を挟み連続保存でも再アニメーション
  note.classList.add("show");
  clearTimeout(note._t);
  note._t = setTimeout(() => note.classList.remove("show"), 1800);
}

async function main() {
  hydrateIcons();
  setupTheme();
  setupTabs();
  setupSubTabs();

  let cfg;
  try {
    cfg = await adk.loadConfig();
  } catch {
    $("statusline").textContent = "設定の読込に失敗";
    return;
  }
  buildStatusline();
  status.setBudget(cfg.llm_budget);
  window.addEventListener("llm-budget", (event) => status.setBudget(event.detail));
  setupActor(cfg); // config 後＝Google サインイン有無でモードを決める（表示名編集 / 自己申告）

  // 保育経過記録は年度4期・各3か月固定。選択肢と現在期は harness 由来の /api/config をそのまま描き、
  // フロントで終了月計算や期判定を重複実装しない。
  const recordPeriod = $("record-period");
  for (const period of cfg.child_record_periods || []) {
    const option = el("option", "");
    option.value = period.value;
    option.textContent = period.label;
    recordPeriod.appendChild(option);
  }
  if (cfg.current_child_record_period) recordPeriod.value = cfg.current_child_record_period;

  // 子ども選択肢：DB 接続時は児童マスタが正（0件なら空のまま「園児が未登録」を正直に案内＝
  // 架空児をあたかも実在の候補のように出さない）。未接続だけデモ用の仮名ロスターへ降格。
  // 配列は childCombo と閉包共有＝ in-place 更新でタブ切替後の再取得（loadDiaryClasses）が候補に追従する
  // （クラス・園児タブで登録した児がリロード無しで対象児コンボに出る）。
  const recordChildNames = cfg.records_connected ? [] : [...RECORD_CHILDREN];
  function updateChildEmptyNote() {
    $("doc-child-empty").hidden = !(cfg.records_connected && recordChildNames.length === 0);
  }
  function applyDbChildren(dbChildren) {
    recordChildNames.length = 0;
    for (const c of dbChildren) {
      recordChildNames.push(c.display_name);
      // 誕生日を控えておき、年齢帯（0-2/3-5）を満年齢で自動判定できるようにする（ageBandOf）。
      if (c.birthdate) BIRTHDATE_OF[c.display_name] = c.birthdate;
    }
    updateChildEmptyNote();
  }
  updateChildEmptyNote();

  // ══ 書類を作る（日誌/月案/保育経過記録を種別セグメントで統合） ══════════════════
  // フロー本体（HITL・ステッパー・編集フォーム・承認・PDF・アーカイブ）は makeDocFlow 1実装の共用で、
  // 種別で違うのは入力欄と seed の組み立てだけ（バックエンドの DocTypeRouter＝doc_type 分岐と 1:1）。

  // 対象児コンボは1つに統合（種別を切り替えても選び直し不要）。候補は DB 接続時は児童マスタ、
  // 未接続は仮名ロスター（3–5 児さくらちゃんを含む＝全年齢デモ）。日誌/月案でも 3–5 児を選べる。
  const docChild = childCombo($("doc-children"), recordChildNames, {
    onPick: (name) => onChildChange(name),
    labelId: "doc-child-label",
    // 未登録名を選んだら本名（姓/名）＋性別で新規登録（呼び名＋敬称はサーバが合成＝重複児を防ぐ）。
    onAddChild: async ({ family_name, given_name, gender, birthdate }) => {
      // アーカイブ未接続はセッション内だけ選択肢へ足す（本名/性別/生年月日は保存されない＝氏名欄は呼び名へ降格）。
      if (!cfg.records_connected) {
        const dn = composeDisplayName(given_name, gender);
        // 生年月日はセッション内でも控える（再読込までは ageBandOf が満年齢で年齢帯を判定できる）。
        if (birthdate) BIRTHDATE_OF[dn] = birthdate;
        return { ok: true, displayName: dn };
      }
      const res = await adk.addChild({ family_name, given_name, gender, birthdate });
      if (!res || res.status === "error") {
        return { ok: false, message: (res && res.detail) || "登録に失敗しました。" };
      }
      // 登録直後に BIRTHDATE_OF を更新（次の /api/children 読込を待たず年齢帯を満年齢で判定＝
      // 3–5 児がフォールバックの 0-2 に誤判定され author プロンプト・タグ語彙がずれるのを防ぐ）。
      const dn = res.display_name || composeDisplayName(given_name, gender);
      if (birthdate) BIRTHDATE_OF[dn] = birthdate;
      $("doc-child-empty").hidden = true; // 1人登録された＝「園児が未登録」の案内を畳む
      return { ok: true, displayName: res.display_name };
    },
  });

  // 日誌（手入力）：クラスを選ぶと在籍児が並ぶ。クラス未登録/DB 未接続は年齢帯チップへ降格。記録日の既定は今日。
  const diaryAge = chipGroup($("diary-ageband"), AGE_BANDS, null, null);
  $("diary-date").value = todayISO();
  let diaryClasses = [];
  const diaryRosterOf = {}; // class_id -> [表示名]
  async function loadDiaryClasses() {
    if (!cfg.records_connected) return;
    const [cl, kids] = await Promise.all([adk.getClasses(), adk.getChildren()]);
    diaryClasses = cl.classes || [];
    for (const k of Object.keys(diaryRosterOf)) delete diaryRosterOf[k];
    for (const k of kids) if (k.class_id) (diaryRosterOf[k.class_id] ||= []).push(k.display_name);
    // 同じ取得で対象児コンボ（経過記録/要録）も追従させる＝クラス・園児タブで登録した児を
    // 「書類を作る」タブへ戻った時点で反映（起動時1回構築の取り残しを解消）。
    applyDbChildren(kids);
    renderDiaryClassSelector();
  }
  function renderDiaryClassSelector() {
    const hasClasses = diaryClasses.length > 0;
    $("diary-class-wrap").hidden = !hasClasses;
    $("diary-ageband-wrap").hidden = hasClasses;
    if (!hasClasses) return;
    const sel = $("diary-class");
    sel.innerHTML = "";
    diaryClasses.forEach((c) => {
      const roster = diaryRosterOf[c.id] || [];
      // DB 由来のクラス名・導出年齢帯は textContent で入れる（innerHTML だと option へ HTML が
      // 実 DOM 化し stored XSS になる＝classes.js の classCard と同じくエスケープ徹底）。
      const o = el("option", "");
      o.textContent = `${c.name}（${classAgeBandSummary(c)}・${roster.length}名）`;
      o.value = c.id;
      sel.appendChild(o);
    });
    sel.onchange = () => {
      updateDiaryAgeBandVisibility();
      updateDiaryRosterNote();
    };
    updateDiaryAgeBandVisibility();
    updateDiaryRosterNote();
  }
  function updateDiaryAgeBandVisibility() {
    const selected = diaryClasses.find((c) => c.id === $("diary-class").value);
    // 単一年齢帯なら在籍児から決定。異年齢/生年月日未登録なら、書類としての対象年齢帯を保育士が選ぶ。
    $("diary-ageband-wrap").hidden = !!selected && (selected.age_bands || []).length === 1;
  }
  function updateDiaryRosterNote() {
    const roster = diaryRosterOf[$("diary-class").value] || [];
    $("diary-roster-text").textContent = roster.length
      ? `在籍児 ${roster.length}名：${roster.join("・")}（フォームで追加・削除もできます）`
      : "このクラスに在籍児がいません。フォームで追加するか「クラス・園児」タブで登録できます。";
  }
  await loadDiaryClasses();

  // クラス月案の年齢帯チップ（クラス＝0-2/3-5）。切替で前月サンプルの件数表示を追従する。
  const classAge = chipGroup($("class-ageband"), AGE_BANDS, (label) => onClassAgeChange(label), null);
  function onClassAgeChange(label) {
    const band = AGE_BAND_VALUE[label] || "0-2";
    $("monthly-seed-count").textContent = sampleClassPrevEntries(band).length + " 件";
  }

  // 対象児が変わったら：保育経過記録/要録の seed 件数を更新し、日誌の年齢帯チップを満年齢で自動追従（手動上書き可）。
    // クラス月案は文書の年齢帯で集計するため、対象児に依存しない。
  let childChangeSeq = 0;
  async function onChildChange(name) {
    $("record-seed-count").textContent = samplePeriodEntries(name).length + " 件";
    $("youroku-seed-count").textContent = sampleRecordEntries(name).length + " 件";
    const yearSelect = $("youroku-year");
    const seq = ++childChangeSeq;
    yearSelect.disabled = true;
    yearSelect.innerHTML = "";
    if (!name) {
      yearSelect.innerHTML = '<option value="">対象児を選択してください</option>';
      return;
    }
    const entries = cfg.records_connected
      ? await adk.getChildRecordEntries(name)
      : sampleRecordEntries(name);
    if (seq !== childChangeSeq) return;
    const years = fiscalYearsOf(entries);
    if (!years.length) {
      yearSelect.innerHTML = '<option value="">保育経過記録のある年度がありません</option>';
      return;
    }
    years.forEach((year) => yearSelect.appendChild(new Option(`${year}年度`, year)));
    yearSelect.value = years[0];
    yearSelect.disabled = false;
  }

  // 月の初日/末日（"YYYY-MM"）。seed の範囲クエリ用（アーカイブ＝/api/records/diary-entries）。
  const monthFirst = (ym) => `${ym}-01`;
  const monthLast = (ym) => {
    const [y, m] = ym.split("-").map(Number);
    return new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10); // 翌月0日＝当月末日
  };
  const prevMonth = (ym) => {
    const [y, m] = ym.split("-").map(Number);
    return m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, "0")}`;
  };
  // seed の解決：アーカイブ接続時は保存済み日誌（期間内）を使い、空/未接続はサンプルへ降格。
  // どちらを使ったかを {entries, source} で返し、UI が正直に表示する。
  async function seedEntries(fromYm, toYm, fallback) {
    if (cfg.records_connected) {
      const entries = await adk.getDiaryEntries(monthFirst(fromYm), monthLast(toYm));
      if (entries.length) return { entries, source: "アーカイブ" };
    }
    return { entries: fallback, source: "サンプル" };
  }

  // 日誌は手入力フォーム（AI 生成しない＝ヒアリング 2026-07：日誌は自分の言葉で打つ一次情報の蓄積口）。
  // クラスの在籍児を空欄で並べ、検査・整形・保存・帳票は既存の決定的経路（finalize-edit / records /
  // 帳票PDF・Word）を再利用する＝AI を一切通さない。他の書類（月案/経過記録/要録）は従来の作成フロー。
  const diaryForm = makeDiaryForm({ area: $("diary-flow"), status, onNewDocument: resetDocumentCreation });
  // 月案セグメント＝クラス月案（園の実様式・§18）。flow kind は "class_monthly"（DocTypeRouter の
  // doc_type "クラス月案" に対応）。前月集計（L2）・確定・編集フォーム・PDF/Word は共通フローで動く。
  const monthlyFlow = makeDocFlow({
    area: $("monthly-flow"),
    button: $("doc-run"),
    stepper: $("monthly-stepper"),
    steps: ["蓄積の集計", "指針を取り込む", "情報を集める", "下書き", "レビュー", "確定"],
    showDigest: true,
    kind: "class_monthly",
    status,
    onBusy: setSegBusy,
    onNewDocument: resetDocumentCreation,
  });
  const recordFlow = makeDocFlow({
    area: $("record-flow"),
    button: $("doc-run"),
    stepper: $("record-stepper"),
    steps: ["期間の集計", "指針を取り込む", "情報を集める", "下書き", "レビュー", "確定"],
    showDigest: true,
    kind: "child_record",
    status,
    onBusy: setSegBusy,
    onNewDocument: resetDocumentCreation,
  });
  const yourokuFlow = makeDocFlow({
    area: $("youroku-flow"),
    button: $("doc-run"),
    stepper: $("youroku-stepper"),
    steps: ["これまでの集計", "情報を集める", "下書き", "レビュー", "確定"],
    showDigest: true,
    kind: "nursery_record",
    status,
    onBusy: setSegBusy,
    onNewDocument: resetDocumentCreation,
  });

  // 種別ごとの実行（seed 組み立て＋ flow.run／日誌は手入力フォームを開く）。
  function runDiary() {
    // クラスが単一年齢帯なら在籍児から決定。異年齢/未確定なら文書用チップで年齢帯を選ぶ。
    const date = $("diary-date").value || todayISO();
    let className = "";
    let ageBand = null;
    let roster = [];
    if (diaryClasses.length) {
      const c = diaryClasses.find((x) => x.id === $("diary-class").value);
      if (c) {
        className = c.name;
        if ((c.age_bands || []).length === 1) ageBand = c.age_bands[0];
        roster = diaryRosterOf[c.id] || [];
      }
    }
    if (!ageBand) ageBand = AGE_BAND_VALUE[diaryAge()] || "0-2";
    diaryForm.open({ className, ageBand, date, roster });
  }
  async function runMonthly() {
    // クラス月案はクラス単位（対象児を取らない）。年齢帯＝クラスと対象月で回す。
    const month = $("monthly-month").value || "2026-07";
    const ageBandLabel = classAge();
    const ageBand = AGE_BAND_VALUE[ageBandLabel] || "0-2";
    status.setSubject(ageBandLabel);
    // seed 3系統＋在籍児名簿（依存モデル 2026-07）＝①クラス児童の保育経過記録すべて ②それまでのクラス月案
    // ③経過記録に未反映の期間の日誌（境界計算はサーバ側 harness に1つ）④クラスの在籍児名簿
    // （クラス・園児マスタ＝0–2 個人目標の対象）。未接続/該当なしは③だけ仮名サンプルへ降格
    // （①②は 0 件＝digest が降格メッセージ・④は空＝「名簿未登録」を正直表示し記録の登場児で作る）。
    const pm = prevMonth(month);
    let source = "アーカイブ";
    let seed3 = {
      class_diary_entries: [],
      class_record_entries: [],
      past_class_plans: [],
      class_roster: [],
    };
    if (cfg.records_connected) seed3 = await adk.getClassMonthlySeed(ageBand, month);
    seed3.class_roster ||= [];
    if (!seed3.class_diary_entries.length && !seed3.class_record_entries.length) {
      seed3.class_diary_entries = sampleClassPrevEntries(ageBand);
      source = "サンプル";
    }
    const rosterNote = seed3.class_roster.length
      ? `在籍児 ${seed3.class_roster.length}名（名簿）`
      : "名簿未登録（記録の登場児で作成）";
    $("monthly-seed-count").textContent =
      `経過記録 ${seed3.class_record_entries.length}・月案 ${seed3.past_class_plans.length}・` +
      `日誌 ${seed3.class_diary_entries.length} 件（${source}）・${rosterNote}`;
    // 前月日誌で評価・反省が未記入のものを検出して記入導線を出す（生成はブロックしない＝並行）。
    checkPrevMonthEvaluations(pm, ageBand);
    const seed = { doc_type: "クラス月案", ...seed3 };
    monthlyFlow.run(
      seed,
      `${month} の ${ageBandLabel}（年齢帯 ${ageBand}）のクラス月案（月間指導計画）を作成してください。` +
        `month には「${month}」、age_band には「${ageBand}」をそのまま書いてください。`,
    );
  }

  // 対象月（前月・当該クラス）の日誌のうち評価・反省が未記入のものを検出し、記入導線カードを描く。
  // クラス月案は前月の振り返りをふまえて作られる（決定B）ので、月末に前月日誌を締めるこの地点で促す。
  // 未接続（アーカイブ無し）は検出できないので黙って何もしない（サンプル seed のときは対象外）。
  async function checkPrevMonthEvaluations(pm, ageBand) {
    const notice = $("monthly-eval-notice");
    notice.classList.add("hidden");
    notice.innerHTML = "";
    if (!cfg.records_connected) return;
    const metas = (await adk.getDiaryMeta(monthFirst(pm), monthLast(pm))).filter(
      (m) => (m.age_band || "0-2") === ageBand, // このクラス（年齢帯）の日誌だけ
    );
    const unfilled = metas.filter((m) => m.evaluation_complete === false);
    if (!unfilled.length) return; // 全部記入済み／該当なし＝出さない（うるさくしない）。

    const head = el("div", "eval-notice-head");
    head.innerHTML =
      `<span class="eval-notice-title">${iconHTML("alert")}前月の日誌で評価・反省が未記入のものがあります（${unfilled.length}件）</span>` +
      `<p class="eval-notice-sub">クラス月案は前月の振り返り（評価・反省）をふまえて作られます。記入すると反映されます（未記入でも作成はできます）。</p>`;
    notice.appendChild(head);

    const chips = el("div", "eval-notice-chips");
    for (const m of unfilled) {
      const b = el("button", "eval-chip", `${iconHTML("edit")}${esc(mdLabel(m.date))} を記入`);
      b.type = "button";
      // 書類管理タブへ切替＋当該日誌を編集モード（評価欄へフォーカス）で開く。
      b.onclick = () => {
        switchTab("records");
        records.openDoc(m.id, { edit: true, focus: "evaluation" });
      };
      chips.appendChild(b);
    }
    notice.appendChild(chips);
    notice.classList.remove("hidden");
  }

  // "2026-06-03" → "6/3"（未記入チップの短いラベル）。読めなければ原文。
  function mdLabel(iso) {
    const m = /^\d{4}-(\d{2})-(\d{2})$/.exec(iso || "");
    return m ? `${Number(m[1])}/${Number(m[2])}` : iso || "";
  }
  async function runRecord() {
    const child = docChild();
    if (!child) {
      status.setPhase("対象児を選択してください", "waiting");
      return;
    }
    const period = recordPeriod.value;
    if (!period) {
      status.setPhase("対象期間を選択してください", "waiting");
      return;
    }
    const ageBand = ageBandOf(child);
    status.setSubject(child);
    // L3 seed＝期間の日誌。アーカイブに保存済みがあればそれを使う（無ければサンプルに降格）。
    const { entries, source } = await seedEntries(start, end, samplePeriodEntries(child));
    // 前回までの保育経過記録（自己履歴・作成対象の期は除外＝依存モデル 2026-07）。未接続/初回は 0 件降格。
    const prevRecords = cfg.records_connected
      ? await adk.getChildRecordEntries(child, period)
      : [];
    $("record-seed-count").textContent =
      `日誌 ${entries.length} 件（${source}）・前回までの経過記録 ${prevRecords.length} 件`;
    const seed = { doc_type: "保育経過記録", period_entries: entries, prev_record_entries: prevRecords };
    recordFlow.run(
      seed,
      `対象期間 ${period} の ${child}（年齢帯 ${ageBand}）の保育経過記録を作成してください。period には「${period}」をそのまま書いてください。`,
    );
  }
  async function runYouroku() {
    const child = docChild();
    if (!child) {
      status.setPhase("対象児を選択してください", "waiting");
      return;
    }
    const fiscalYear = $("youroku-year").value;
    if (!fiscalYear) {
      status.setPhase("対象児の保育経過記録がある年度を選択してください", "waiting");
      return;
    }
    status.setSubject(child);
    // L4 seed＝最終年度の保育経過記録。アーカイブに保存済みがあればそれを使う（無ければサンプルに降格）。
    let entries = null;
    let source = "サンプル";
    if (cfg.records_connected) {
      const archived = await adk.getChildRecordEntries(child);
      if (archived.length) {
        entries = archived;
        source = "アーカイブ";
      }
    }
    if (!entries) entries = sampleRecordEntries(child);
    $("youroku-seed-count").textContent = `${entries.length} 件（${source}）`;
    const seed = { doc_type: "保育要録", record_entries: entries };
    yourokuFlow.run(
      seed,
      `${fiscalYear}年度の ${child} の保育要録（保育所児童保育要録）を作成してください。fiscal_year には「${fiscalYear}」をそのまま書いてください。`,
    );
  }
  const RUN = { diary: runDiary, monthly: runMonthly, record: runRecord, youroku: runYouroku };

  // 種別セレクタ（カテゴリ別グループ表示・案A）：ready の切替で入力欄・結果エリア・説明文・ボタンラベルを
  // 追従（結果エリアは種別ごとに保持）。soon（今後対応予定）はクリックで一言案内を出すだけ（選択は変えない）。
  const docKind = renderDocMenu($("doc-kind"), DOC_CATEGORIES, {
    onPick: (key) => switchDocType(key),
    onSoon: (it) => showSoonNotice(it),
  });
  // 完了画面の「新しく書類を作る」から、前回結果を残さない初期状態へ戻す。
  // 書類種別は初期値の日誌に戻し、入力カードが見える位置までスクロールする。
  function resetDocumentCreation() {
    for (const d of DOC_TYPES) {
      $(`${d.key}-flow`).innerHTML = "";
      const stepper = $(`${d.key}-stepper`);
      stepper.innerHTML = "";
      stepper.classList.add("hidden");
    }
    docKind.select("diary");
    switchDocType("diary");
    status.setSubject(null);
    status.clearPhase();
    $("doc-run").disabled = false;
    setSegBusy(false);
    $("doc-kind").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  function switchDocType(key) {
    for (const d of DOC_TYPES) {
      const on = d.key === key;
      $("doc-fields-" + d.key).hidden = !on;
      $("doc-area-" + d.key).hidden = !on;
    }
    const t = DOC_TYPE_OF[key];
    // クラス月案はクラス単位なので上部の対象児コンボを隠す（他書類は対象児を使う）。
    // .field-label は display:block を持つため [hidden] 属性では隠れない＝.hidden クラス（!important）で隠す。
    const needsChild = t.needsChild !== false;
    $("doc-child-label").classList.toggle("hidden", !needsChild);
    $("doc-children").classList.toggle("hidden", !needsChild);
    const dd = $("doc-desc");
    dd.textContent = t.desc;
    dd.classList.remove("is-soon-note"); // ready 選択で soon 案内をクリア
    $("doc-run-label").textContent = t.runLabel;
    status.clearPhase();
  }
  // soon 書類のクリック案内（無反応にしない）。ready 選択はそのまま＝説明文欄に一言だけ出す。
  function showSoonNotice(it) {
    const dd = $("doc-desc");
    dd.textContent = `「${it.label}」は今後対応予定です。現在は作成できません。`;
    dd.classList.add("is-soon-note");
  }
  // 生成中は種別セグメントを固定（切替ロック）。対象児コンボ・入力欄はロックしない。
  function setSegBusy(busy) {
    $("doc-kind")
      .querySelectorAll(".chip")
      .forEach((c) => {
        c.disabled = busy;
        c.classList.toggle("is-locked", busy);
      });
  }
  $("doc-run").onclick = () => RUN[docKind()]();
  docKind.select("diary"); // 既定チップを点灯
  switchDocType("diary"); // 初期表示（既定＝保育日誌）
  onChildChange(docChild()); // 初期の seed 件数・年齢帯を対象児に合わせる
  onClassAgeChange(classAge()); // クラス月案の前月サンプル件数を初期表示（クラス＝年齢帯）

  // ── 指針を育てる ──
  sampleChips($("policy-samples"), POLICY_SAMPLES, (s) => ($("policy-memo").value = s));
  const policy = makePolicy({
    grid: $("policy-grid"),
    history: $("policy-history"),
    flow: $("policy-flow"),
    button: $("policy-run"),
    stepper: $("policy-stepper"),
    status,
  });
  await policy.init();

  // 対象書類セレクタ：デッキ（いまの指針カード）を「共通＋その書類」に絞り込み、提案 scope の既定にする。
  // 「すべて」は絞り込みなし＝従来動作（AI が対象を判断）。反映先が保育士に見えるようにする（Thread A）。
  const policyTarget = chipGroup(
    $("policy-target"),
    POLICY_TARGETS.map((t) => t.key),
    (key) => onPolicyTargetChange(key),
    null,
    (key) => POLICY_TARGET_OF[key].label,
  );
  function onPolicyTargetChange(key) {
    const t = POLICY_TARGET_OF[key];
    const badge = $("policy-scope-badge");
    badge.textContent = t.docTypes ? "この書類に効く指針のみ" : "";
    badge.classList.toggle("hidden", !t.docTypes);
    policy.setFilter(t.docTypes);
  }
  onPolicyTargetChange(policyTarget()); // 初期（既定＝すべて＝絞り込みなし）

  $("policy-run").onclick = () => {
    const memo = $("policy-memo").value.trim();
    if (!memo) {
      $("policy-memo").focus();
      return;
    }
    status.setSubject(null);
    policy.run(memo, POLICY_TARGET_OF[policyTarget()].scope);
  };

  // ── 表記ルール（ひらがな表記DX＝保育士が育てる辞書） ──
  const notation = makeNotation({
    list: $("notation-list"),
    store: $("notation-store"),
    msg: $("notation-msg"),
    patternInput: $("notation-pattern"),
    replacementInput: $("notation-replacement"),
    kindSelect: $("notation-kind"),
    noteInput: $("notation-note"),
    addBtn: $("notation-add"),
  });
  await notation.init();

  // ── クラス・園児（園の名簿管理＝クラス定義＋園児登録/割当・日誌 roster の素） ──
  const classes = makeClasses({
    list: $("classes-list"),
    store: $("classes-store"),
    msg: $("class-msg"),
    nameInput: $("class-name"),
    fiscalInput: $("class-fiscal"),
    addBtn: $("class-add"),
  });
  await classes.init();
  // タブを開くたびに最新化（他タブで登録した児がすぐ反映される）。
  $("tabbtn-classes").addEventListener("click", () => classes.refresh());
  // 「書類を作る」に戻るたび、日誌のクラス選択も最新化（クラス・園児タブで足したクラス/児を反映）。
  $("tabbtn-docs").addEventListener("click", () => loadDiaryClasses());

  // ── 書類を見る（アーカイブ閲覧＝作成済みの確定書類・参照データの点検） ──
  const records = makeRecords({
    tree: $("records-tree"),
    store: $("records-store"),
    detail: $("records-detail"),
    childRecordPeriods: cfg.child_record_periods,
    currentChildRecordPeriod: cfg.current_child_record_period,
  });
  await records.init();
  // タブを開くたびに最新化（他タブで確定・承認した書類がすぐ反映される）。
  $("tabbtn-records").addEventListener("click", () => records.refresh());
}

main();
