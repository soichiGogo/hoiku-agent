# hoiku-agent を Cloud Run（scale-to-zero）で動かすコンテナ（設計コンテキスト §11）。
# 入口は repo root の server.py（get_fast_api_app）＝`uvicorn server:app`。Memory Bank / RAG は
# ADC（Cloud Run のサービスアカウント）＋ 環境変数（AGENT_ENGINE_ID / RAG_CORPUS 等）で配線する
# （未設定なら InMemory / 降格＝落ちない）。層A は「こなれた普通」で十分（§12）＝単段の素直な構成。

FROM python:3.12-slim

# uv（依存解決）を公式イメージから持ち込む。
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 依存だけ先に解決してレイヤキャッシュを効かせる（lock 固定＝再現可能ビルド）。
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# アプリ本体（入口＋実行時に読むファイル）。
# - server.py … uvicorn の入口。
# - knowledge/文書作成指針.json … read_policy / 改善エージェントが読む育つ指針＝構造化カードストア（§8/§9）。
#   保育所保育指針/（RAG ソース）は gitignore 済みで実行時不要（RAG は Vertex 経由）＝含めない。
COPY server.py ./
COPY knowledge/文書作成指針.json ./knowledge/文書作成指針.json

# .venv の実行ファイルを優先。
ENV PATH="/app/.venv/bin:$PATH"
# Vertex 経由（ADC）で Gemini/RAG/Memory を呼ぶ既定。プロジェクト等は Cloud Run の env で上書きする。
ENV GOOGLE_GENAI_USE_VERTEXAI=true
# Cloud Run は $PORT を注入する（既定 8080）。
ENV PORT=8080

EXPOSE 8080

# Cloud Run の $PORT を listen する（scale-to-zero）。
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
