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
| `harness/pipeline.py` | `build_document_pipeline` / `ApprovalGate` / `FinalizeAgent` / `is_approved` | author → review_loop（reviewer→ApprovalGate で APPROVED 早期終了）→ finalize の順序制御（root_agent の実体） |
| `harness/schema_check.py` | `validate_fields` | 必須欄＋年齢分岐（0–2＝3つの視点 / 3–5＝5領域） |
| `harness/draft.py` | `write_draft` | pydantic（DiaryEntry 等）→ 様式整形（10の姿/3つの視点/5領域タグ明示） |
| `harness/finalize.py` | `finalize_document` / `parse_draft_to_entry` | author 出力（DiaryEntry JSON）の復元 → 確定 validate/write（pipeline 末尾で実行する純ロジック） |
| `harness/aggregate.py` | `aggregate_by_child` | 月⇔日の集積（child_id 別）。要約生成は author |
| `harness/git_ops.py` | `apply_structured_edit` / `list_section_bullets` / `open_pr` | 構造化編集の適用・競合検出入力・branch/PR（プロダクトの git 操作。open_pr 既定 dry_run） |

## ツール（§6・4–8個のプリミティブ）

`tools/`: `search_records`(ローカル架空児記録ストア) / `search_guideline`(Vertex RAG・未設定で降格) /
`read_policy`(育つ指針 HEAD) / `get_child_memory`(Memory Bank・`tool_context.search_memory`・未接続で降格) /
`ask_caregiver`(HITL＝`LongRunningFunctionTool`) / `validate_fields`・`write_draft`（harness の薄いラッパ）。
improver 固有: `improver/tools.py`（`propose_policy_change`＋競合検出 / `run_eval`→`eval/run_gate.py`、
`open_pr` は harness 経由）。GCP 系（RAG/Memory）は config 未設定時に安全に降格する。

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
       ├─ author (LlmAgent)  … 不足は ask_caregiver(HITL) / RAG・記録・子メモリを収集 / 指針準拠で
       │                        下書き＋DiaryEntry JSON → state["draft"]
       ├─ review_loop (LoopAgent)
       │     ├─ reviewer (LlmAgent) … 指摘 → state["review"]
       │     └─ approval_gate (BaseAgent) … APPROVED を検知したら escalate（早期終了）
       └─ finalize (BaseAgent) … state["draft"] を復元 → validate_fields/write_draft を確定実行
                                  → state["final_document"]/["validation"]、awaiting_caregiver_approval=True（HITL）
出力（確定書類）＋ 保育士の修正差分 → eval（層B・run_gate）→ improver が指針へ還元（HITL+ゲート）
```

## 実装状況（v0）と残課題

v0 で実装済み（決定的部分はテスト済み・GCP/LLM 非依存で稼働）:
- レビュー APPROVED 早期終了（`ApprovalGate`／`is_approved`）。
- HITL 関門：`ask_caregiver`＝`LongRunningFunctionTool`、確定段の `awaiting_caregiver_approval` フラグ。
- 出力の最終 validation／整形（`FinalizeAgent`＋`harness/finalize.py`）。
- `git_ops`（構造化編集の適用・competition 入力・branch/PR＝既定 dry_run）、`improver`（propose＋競合検出／
  run_eval／open_pr）、eval ゲート判定（`eval/run_gate.py`）。

残課題（外部リソース・実データ依存。コードは降格付きで配線済み）:
- Vertex RAG corpus の作成・接続、Agent Engine Memory Bank の接続（§9・config 設定で活性化）。
- Cloud Run デプロイ・GitHub Actions×WIF の配信ループ（層A）。
- 実様式1枚の入手による `write_draft` 様式確定（§18）、現場の修正差分による eval ケース拡充（15–30件・§12）。
- eval の 3軸 LLM-judge（`judges/*.md`）を ADK 評価設定へ接続し軸別 mean を算出（§12・要 LLM 資格情報）。
