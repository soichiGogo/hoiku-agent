# harness/ ＝ 決定的「型の保証」層（責務①）

ここで Claude がすること：**文書というモノの成立**（必須欄・年齢分岐・順序・集積・git適用）を
**決定的なコード**で保証する。設計コンテキスト §4「一階＝作成本体」/ §5「責務境界」。

## 越えてはいけない一線

- **LLM を呼ばない。** `LlmAgent`・プロンプト・「何を書くか」の判断をここに書かない。それは
  `../agents/` の責務。ここは純粋関数とワークフロー制御（順序・ループ・分岐）だけ。
- **決定的ロジックの実体はこの層に1つだけ。** `../tools/validate_fields.py` と
  `../tools/write_draft.py` は本層を呼ぶ**薄いラッパ**であり、ロジックを再実装しない（§5/§6）。
  ツール側にロジックが滲み出ていたらレビューで差し戻す。
- ここに書ける＝**`tests/test_harness/` から LLM 非依存・高速にテストできる**。テストが書けない
  なら agents/ の責務が混入している疑い。

## ファイルの責務

- `schema_check.py` … `validate_fields`（日誌）/ `validate_monthly_fields`（月案）：必須欄＋年齢分岐
  （0–2＝3つの視点 / 3–5＝5領域）。分岐の実体は `_required_tag_type` に1つ（日誌・月案で共用）。
- `draft.py` … `write_draft`（日誌）/ `write_monthly_draft`（月案）：pydantic → 様式整形。確定出力は
  pipeline 末尾で実行。
- `finalize.py` … `finalize_document`（日誌）/ `finalize_monthly_document`（月案）：復元→検査→整形。
  汎用本体 `_finalize` を parse/validate/write 差し替えで共用（二重実装しない）。
- `aggregate.py` … `aggregate_by_child`（Counter 版）/ `prev_month_digest`（state 用 serializable）/
  `format_digest_for_prompt`（L2 還流の人間可読テキスト）。要約生成は月案 author に委ねる（§10）。
- `pipeline.py` … 日誌：author → review_loop → 確定/HITL の順序制御（旧 `workflow/document_pipeline.py`）。
  APPROVED 早期終了の**判定**はここ（制御＝決定的）、レビュー内容の**生成**は reviewer。
  `FinalizeAgent(kind=...)` で日誌/月案の確定を切替（実体は finalize.py）。
- `monthly.py` … 月案：`MonthlyPrepAgent`（前月日誌を child_id 別集計＝L2 還流の決定的部分）→ 月案 author
  → review_loop → 確定。`build_monthly_pipeline`。集計＝harness／要約＝author（§10）。
- `router.py` … `DocTypeRouter` / `build_root_agent`：state["doc_type"] で日誌／月案を振り分ける
  決定的分岐（root_agent の実体・既定＝保育日誌＝§3）。
- `git_ops.py` … branch/commit/`gh pr`/構造化編集の適用。**これはプロダクトが回す git 操作**で、
  開発者自身のブランチ運用（グローバル CLAUDE.md）とは別物。混同しない。

## スタブを埋めるとき

場当たりで埋めない。`TODO(設計)` は設計コンテキスト §5/§6/§10 を読んでから既存の型に沿って実装する。
