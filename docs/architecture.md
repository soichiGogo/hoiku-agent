# アーキテクチャ（設計のコード対応）

最終的な正は Obsidian vault の `設計/プロダクト方針.md` / `設計/エージェント設計.md`（repo 外）。
リポジトリ内の設計参照は `docs/設計コンテキスト.md`（開発ハンドオフ）。本ファイルはそれをコード構造に
対応づけた索引。構造を変えたら本ファイルと `CLAUDE.md` を同じ変更内で更新する。

## 3責務 ↔ コード（設計コンテキスト §5 責務境界）

| 責務 | コード | 役割 | 性質 |
|---|---|---|---|
| ① 型の保証（§5） | `harness/` | 必須欄・年齢分岐・順序・集積・git適用。決定ロジックの唯一実装 | 決定的 |
| ② 中身の決定・作成AI（§6） | `agents/author_agent.py`（単一 `LlmAgent`＋tools） | 情報収集（Agentic RAG）・質問生成・「姿→ねらい/評価」変換 | Agentic |
| ② レビューAI（§7） | `agents/review_agent.py`（`LlmAgent`） | 別視点で点検・APPROVED まで巡回（制御は harness） | Agentic |
| ③ 改善エージェント（§8） | `improver/`（別エントリ・手動起動） | 修正差分→指針更新を自走提案・競合は保育士に二択 | Agentic |
| 番人（最終）（§12） | `eval/`（cases/・judges/） | 評価セットで回帰判定→緑のみ取り込み | 決定的（CI） |

## harness 内訳（§5 物理マッピング）

| ファイル | 関数 | 役割 |
|---|---|---|
| `harness/pipeline.py` | `build_document_pipeline` | author → review_loop → 確定/HITL の順序制御（root_agent の実体） |
| `harness/schema_check.py` | `validate_fields` | 必須欄＋年齢分岐（0–2＝3つの視点 / 3–5＝5領域） |
| `harness/draft.py` | `write_draft` | pydantic（DiaryEntry 等）→ 様式整形 |
| `harness/aggregate.py` | `aggregate_by_child` | 月⇔日の集積（child_id 別）。要約生成は author |
| `harness/git_ops.py` | `apply_structured_edit` / `open_pr` | 構造化編集の適用・branch/PR（プロダクトの git 操作） |

## ツール（§6・4–8個のプリミティブ）

`tools/`: `search_records` / `search_guideline`(RAG) / `read_policy`(育つ指針 HEAD) /
`get_child_memory`(Memory Bank) / `ask_caregiver`(HITL) / `validate_fields`・`write_draft`（harness の薄いラッパ）。
improver 固有: `improver/tools.py`（`propose_policy_change` / `run_eval`、`open_pr` は harness 経由）。

## メモリ3分類（§9）

| 対象 | 置き場 | 参照 |
|---|---|---|
| 子ども別 長期メモリ | Agent Engine Memory Bank（repo外） | `get_child_memory` |
| 育つ文書作成指針 | git `knowledge/文書作成指針.md` | agent は読み取り（HEAD）／improver が編集（HITL+ゲート） |
| 静的ナレッジ（指針解説・10の姿） | Vertex RAG（`knowledge/保育所保育指針/` は gitignore のソース） | `search_guideline` |

## データフロー

```
観察メモ（音声/手入力）
  └─ harness: document_pipeline (SequentialAgent)
       ├─ author (LlmAgent)  … 不足は ask_caregiver / RAG・記録・子メモリを収集 / 指針準拠で下書き → state["draft"]
       │     （HITL: 保育士OK）  ← TODO: 明示的な関門
       └─ review_loop (LoopAgent)
             └─ reviewer (LlmAgent) … 指摘 → state["review"]、APPROVED で早期終了（TODO）
   末尾: validate_fields / write_draft を harness が確定実行（TODO）
出力（確定書類）＋ 保育士の修正差分 → eval（層B）→ improver が指針へ還元（HITL+ゲート）
```

## 未実装の要所（設計フェーズで詰める）

- レビュー APPROVED 判定による Loop 早期終了（escalation）。
- author / review 間・確定段の HITL 関門（`ask_caregiver` の同期ツール／§6）。
- Vertex RAG corpus 接続・Agent Engine Memory Bank 接続（§9）。
- 出力フォーマットの最終 validation（pipeline 末尾の validate_fields/write_draft 確定実行）。
- `git_ops`（構造化編集の適用・branch/PR）、`improver` の propose/run_eval、eval ゲートの判定（§8/§12）。
