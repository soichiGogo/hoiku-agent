// doc kind（フロントの書類種別）→ 指針カードの scope（harness の PolicyScope 値）の唯一の対応表。
// 「指針を取り込む」フィルタ（docflow）・👍👎→改善エージェントの target_scope（feedback）で共通に使う
// ＝同じ対応を各所で二重定義しない（app.js の POLICY_TARGETS は UI チップ設定・policy.js の SCOPE_DT は
// 逆引き〔scope→doc_type〕なので役割が別）。クラス月案は個別月案と同じ scope（月案）を流用する（勘所を共有・§18）。
export const POLICY_SCOPE_OF = {
  diary: "保育日誌",
  monthly: "月案",
  class_monthly: "月案",
  child_record: "保育経過記録",
  nursery_record: "保育要録",
};
