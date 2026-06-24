---
name: run-pipeline
description: hoiku-agent のルートパイプライン（root_agent）をローカル起動する。adk run / adk web の正しい起動方法（agents dir = src/）を内包し、起動ミスを防ぐ。ADKエージェントをローカルで動かす・対話する・ブラウザUIで試すときに使う。
argument-hint: "[cli|web]"
---

# hoiku-agent をローカル起動する

ADK の root_agent（`src/hoiku_agent/agent.py`）を起動する。**agents dir は `src/`**、agent package は
`hoiku_agent/`。リポジトリ root で `adk web` を叩くと dropdown に出ないので注意（設計コンテキスト §11）。

## 手順

1. 依存が未導入なら `uv sync`（初回のみ）。`.env` 未作成なら `cp .env.example .env` して GCP 設定を記入し、
   `gcloud auth application-default login` 済みか確認する。
2. 起動モード（引数 $0、未指定なら cli）:
   - `cli` → `adk run src/hoiku_agent`（CLI 対話）
   - `web` → `src/` を agents dir として `adk web src`（ブラウザ UI。dropdown で hoiku_agent を選ぶ）
3. 二階（改善エージェント improver）は root_agent とは**別エントリ・手動起動**。このスキルは一階
   （document_pipeline）専用。improver はモジュール指定 or 専用スクリプトで別途起こす。

注: 実行はモデル呼び出し（Gemini）を伴う。架空児データのみで試す（§14）。
