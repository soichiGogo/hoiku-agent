# hoiku-agent を Cloud Run（scale-to-zero）で動かすコンテナ（設計コンテキスト §11）。
# 入口は repo root の server.py（get_fast_api_app）＝`uvicorn server:app`。Memory Bank / RAG は
# ADC（Cloud Run のサービスアカウント）＋ 環境変数（AGENT_ENGINE_ID / RAG_CORPUS 等）で配線する
# （未設定なら InMemory / 降格＝落ちない）。層A は「こなれた普通」で十分（§12）＝単段の素直な構成。

# uv（依存解決）は公式イメージからバイナリだけ持ち込む。バージョンは global ARG で固定して
# 再現可能に（bump は1箇所）。`--from` は変数展開できないため、ARG 付き FROM で名前付きステージにする。
ARG UV_VERSION=0.11.6
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uvbin

# ベースは Debian リリースまで固定（`slim` 単独より再現性が高い）。供給網をさらに締めるなら
# digest 固定（`python:3.12-slim-bookworm@sha256:...`）が望ましい＝TODO（脆弱性スキャンと併せ運用で）。
FROM python:3.12-slim-bookworm

COPY --from=uvbin /uv /usr/local/bin/uv

WORKDIR /app

# 依存だけ先に解決してレイヤキャッシュを効かせる（lock 固定＝再現可能ビルド）。
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

# アプリ本体（入口＋実行時に読むファイル）。
# - server.py … uvicorn の入口。
# - knowledge/*.json … DB 未接続（DATABASE_URL 未設定）時にローカル降格で読むシード。DB 接続時は
#   Cloud SQL の *_books 行が正だが、未接続の公開デモでも機能が落ちないよう同梱する。
#   - 文書作成指針.json … 育つ指針＝構造化カードストア（read_policy / improver・§8/§9）。
#   - 表記ルール.json  … ひらがな表記DX＝表記正規化（finalize が確定時に適用・§5）。
#   - 様式テンプレート.json … 本文レイアウトの宣言的データ（draft.py が必須依存＝未同梱だと整形が落ちる・§18）。
#   保育所保育指針/（RAG ソース）は gitignore 済みで実行時不要（RAG は Vertex 経由）＝含めない。
COPY server.py ./
COPY knowledge/文書作成指針.json ./knowledge/文書作成指針.json
COPY knowledge/表記ルール.json ./knowledge/表記ルール.json
COPY knowledge/様式テンプレート.json ./knowledge/様式テンプレート.json

# .venv の実行ファイルを優先。
ENV PATH="/app/.venv/bin:$PATH"
# Vertex 経由（ADC）で Gemini/RAG/Memory を呼ぶ既定。プロジェクト等は Cloud Run の env で上書きする。
ENV GOOGLE_GENAI_USE_VERTEXAI=true
# Cloud Run は $PORT を注入する（既定 8080）。
ENV PORT=8080

# 非 root で実行する（最小権限＝コンテナ侵害時の被害局限）。/app を所有させ、DB 未接続時の
# 指針カードのローカル降格書込（knowledge/文書作成指針.json）も書けるようにする。
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080

# Cloud Run の $PORT を listen する（scale-to-zero）。`exec` で uvicorn を PID 1 に据え、
# Cloud Run が scale-down で送る SIGTERM を uvicorn が直接受けてグレースフル終了できるようにする
# （sh を挟むと信号が転送されず in-flight の SSE/LLM 応答を握ったまま SIGKILL されうる）。
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
