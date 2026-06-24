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

- `schema_check.py` … `validate_fields`：必須欄＋年齢分岐（0–2＝3つの視点 / 3–5＝5領域）。
- `draft.py` … `write_draft`：pydantic（`DiaryEntry` 等）→ 様式整形。確定出力は pipeline 末尾で実行。
- `aggregate.py` … `aggregate_by_child`：月⇄日の集積（child_id 別）。要約生成は author に委ねる。
- `pipeline.py` … author → review_loop → 確定/HITL の順序制御（旧 `workflow/document_pipeline.py`）。
  APPROVED 早期終了の**判定**はここ（制御＝決定的）、レビュー内容の**生成**は reviewer。
- `git_ops.py` … branch/commit/`gh pr`/構造化編集の適用。**これはプロダクトが回す git 操作**で、
  開発者自身のブランチ運用（グローバル CLAUDE.md）とは別物。混同しない。

## スタブを埋めるとき

場当たりで埋めない。`TODO(設計)` は設計コンテキスト §5/§6/§10 を読んでから既存の型に沿って実装する。
