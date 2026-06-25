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
| `harness/pipeline.py` | `build_document_pipeline` / `ApprovalGate` / `FinalizeAgent` / `is_approved` / `persist_visit_to_memory`(+`_should_persist_visit`) | author → review_loop（reviewer→ApprovalGate で APPROVED 早期終了）→ finalize の順序制御（root_agent の実体）。`after_agent_callback`＝型成立の確定時のみ来園を Memory Bank へ書き戻す（§9/§13） |
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
| 子ども別 長期メモリ | Agent Engine Memory Bank（repo外） | 読み＝`get_child_memory`／書き戻し＝`persist_visit_to_memory`（pipeline の `after_agent_callback`）。配線は `--memory_service_uri=agentengine://<id>`（`config.memory_service_uri`／`server.py`）。未設定で降格 |
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
       ├─ finalize (BaseAgent) … state["draft"] を復元 → validate_fields/write_draft を確定実行
       │                          → state["final_document"]/["validation"]、awaiting_caregiver_approval=True（HITL）
       └─ [after_agent_callback] persist_visit_to_memory … 型成立の確定時のみ来園セッションを
                                  子の Memory Bank へ書き戻す（§9/§13。memory_service 未配線なら降格）
出力（確定書類）＋ 保育士の修正差分 → eval（層B・run_gate）→ improver が指針へ還元（HITL+ゲート）
```

## 実装状況（v0）と残課題

v0 で稼働する範囲は **保育日誌（0–2 個別）のみ**（§3「日誌先行」）。実装済み（決定的部分はテスト済み・
GCP/LLM 非依存で稼働）:
- レビュー APPROVED 早期終了（`ApprovalGate`／`is_approved`。判定は1行目の verdict で行う＝prompts.py）。
- HITL 関門：`ask_caregiver`＝`LongRunningFunctionTool`、確定段の `awaiting_caregiver_approval` フラグ。
- 出力の最終 validation／整形（`FinalizeAgent`＋`harness/finalize.py`。`validate_fields` ツールは draft JSON
  文字列を受け取り内部で復元→検査）。
- `git_ops`（`>` パスで一意解決する構造化編集の適用・competition 入力・branch/PR＝既定 dry_run・処理後は
  元ブランチへ復帰）、`improver`（propose＋競合検出／run_eval／open_pr）、eval ゲート（`eval/run_gate.py`）。
- **決定論E2E（結合テスト）**：`tests/test_e2e/`。`build_xxx(model=...)` に `FakeLlm`（`BaseLlm` スタブ）を
  注入し `document_pipeline` を実 ADK ランタイムで end-to-end に通す。連結（draft→review→final_document）・
  APPROVED 早期終了・巡回上限到達・確定3経路（成功／parse失敗／検証不足）・HITL 不発火を **creds 不要・
  無料・決定的**に検証（中身の品質採点は層B eval＝別系統）。起動は `/e2e` skill。
- **Memory Bank 配線（読み＋書き戻し）**：`config.memory_service_uri`（`agentengine://<id>`）→ 本番/ローカル共通の
  入口 `server.py`（`get_fast_api_app`・自前 Runner は組まず ADK の `--memory_service_uri` 自動配線に委ねる）。
  読み＝`get_child_memory`、書き戻し＝`persist_visit_to_memory`（`after_agent_callback`・型成立の確定時のみ）。
  `InMemoryMemoryService` 付き Runner で書き戻しの発火/スキップ/降格を決定論E2E に検証（creds 不要）。

残課題（外部リソース・実データ依存。コードは降格付きで配線済み）:
- **月案パスと L2 還流**（`aggregate_by_child` → state["prev_month_digest"] → 月案 author の gather）は次フェーズ。
  `aggregate_by_child` は集計の決定的実体としてテスト済みだが、まだどのパイプラインにも未配線（§3/§4/§10）。
  月案スキーマ（`MonthlyPlan` 等）・`doc_type` 分岐も未実装。
- Vertex RAG corpus の作成・接続（§9・config 設定で活性化）。
- **Memory Bank のライブ接続**：配線（読み＋書き戻し＋`server.py` 入口）＋プロビジョニング
  （`scripts/provision_memory_bank.py`＝生成モデル＋日本語/子の姿カスタマイズ。書き戻し→生成→読みの
  ライブ往復を実機確認済み）は済み。残は各自の GCP で同スクリプト実行＋`.env` の `AGENT_ENGINE_ID` 設定と、
  **真の承認ゲート**（v0 は "型成立の確定" を承認の代理トリガにする。保育士の明示承認で書き戻すのは次フェーズ）。
- **CI（層A）**：決定論 CI（`.github/workflows/ci.yml`＝ruff＋`pytest`。毎PR・creds 不要・無料で
  harness/決定論E2E/smoke を回す）は導入済み。**未了**は実 Gemini を使う eval ゲートCI（WIF 認証・
  nightly/手動。§12 の3軸 judge 接続＋GCP の WIF 設定が前提）と Cloud Run デプロイ。
- 実様式1枚の入手による `write_draft` 様式確定（§18）、現場の修正差分による eval ケース拡充（15–30件・§12）。
- **eval ゲートの本採点**：3軸 LLM-judge（`judges/*.md`）を ADK 評価設定（test_config/rubric）へ接続し、
  軸別 mean→3軸平均→main 比較→must_fix 集計を実装（§12・要 LLM 資格情報）。**それまで `run_gate` は採点でき
  ても `passed=None`（判定不能）を返し、偽の緑を出さない**（接続後に True/False を返すよう拡張）。
- ADK 2.3.0 で LoopAgent/SequentialAgent は deprecated（将来 Workflow へ）。設計（§6/§7）が前提とする API で
  2.3.0 の Workflow 代替は非公開のため v0 はこのまま使う（中期 TODO で移行）。
