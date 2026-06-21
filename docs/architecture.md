# アーキテクチャ（プロダクト方針のコード対応）

正は Obsidian vault の `設計/プロダクト方針.md`。本ファイルはそれをコード構造に対応づけたもの。

## レイヤ対応

| プロダクト方針 | コード | 役割 |
|---|---|---|
| ワークフロー層（型の保証 §2） | `workflow/document_pipeline.py`（`SequentialAgent`/`LoopAgent`） | 書式・順序・必須項目の充足・レビュー巡回 |
| エージェント層・作成AI（中身決定 §2/§3） | `agents/author_agent.py`（`LlmAgent`＋tools） | 不足情報の質問生成 / Agentic RAG / 指針準拠で下書き |
| レビューAI（二軸 §3） | `agents/review_agent.py`（`LlmAgent`） | 別視点で点検しOKまで巡回 |
| B独自DB（§5） | `tools/knowledge_search.py` → Vertex RAG | 保育所保育指針・10の姿 |
| 育つ文書作成指針（§4＝回す） | `tools/guideline_tool.py` + `knowledge/文書作成指針.md` | 現場の勘所を吸収・改善 |
| 回す層B（§4） | `eval/` | 修正差分→評価セット→PRゲート |

## データフロー

```
入力（書類要件 DocumentSpec ＋ 過去資料/雛形）
  └─ workflow: document_pipeline (SequentialAgent)
       ├─ author (LlmAgent)         … 不足は質問 / search_guideline / 指針準拠で下書き → state["draft"]
       │     （HITL: 保育士がOK）   ← TODO: 明示的な関門
       └─ review_loop (LoopAgent)
             └─ reviewer (LlmAgent) … 指摘 → state["review"]、APPROVEDで終了（TODO）
出力（確定書類）＋ 保育士の修正差分 → eval（層B）
```

## 未実装の要所（設計フェーズで詰める）

- レビューの APPROVED 判定による Loop 早期終了（escalation）。
- author / review 間の HITL 関門（保育士OK）の置き方。
- Vertex RAG corpus の作成と接続、Agent Engine Memory Bank での園・担任ごとの個別化。
- 出力フォーマットの最終バリデーション（"型"の保証の仕上げ）。
