#!/usr/bin/env bash
# uc-cycle ブートストラップ：ユースケース試行の環境を冪等に用意する。
# 2026-07-16 の試行で確定した手順（.env コピー→uv sync→ローカル throwaway Postgres→migrate→seed）を固めたもの。
# DB＋seed が無いと content 系 UC（書類作成/アーカイブ/クラス・園児/初期化）は設計どおり生成をブロックして試せない。
#
# 使い方（試行用 worktree の中で実行）:
#   bash .claude/skills/uc-cycle/bootstrap.sh
#   # 環境変数で上書き可: UC_PG_PORT(既定5433) / UC_PG_CONTAINER(既定 hoiku-pg-uc)
# 実行後に `uvicorn server:app` を起動し、agent-browser で /app/ を操作する。
set -euo pipefail

PORT="${UC_PG_PORT:-5433}"           # 5432 は他プロジェクト（supabase 等）と衝突しやすいので 5433 既定
CONTAINER="${UC_PG_CONTAINER:-hoiku-pg-uc}"
DBURL="postgresql+psycopg://postgres:postgres@127.0.0.1:${PORT}/hoiku"

# 実行中 worktree（cwd）と primary checkout を特定する。
WT="$(pwd)"
MAIN="$(cd "$(dirname "$(git rev-parse --git-common-dir)")" && pwd)"
echo "worktree      = ${WT}"
echo "primary main  = ${MAIN}"

# 1) .env を primary checkout からコピー（gitignore 済み・commit しない）。
if [[ ! -f "${WT}/.env" ]]; then
  if [[ -f "${MAIN}/.env" ]]; then
    cp "${MAIN}/.env" "${WT}/.env"
    echo "✓ .env をコピーした"
  else
    echo "⚠ primary checkout に .env が無い。cp .env.example .env して GCP 設定を記入してください" >&2
  fi
fi

# 2) 依存を worktree に同期。
uv sync --extra dev >/dev/null
echo "✓ uv sync 完了"

# 3) ローカル throwaway Postgres を docker で用意（既存 DATABASE_URL があればそれを尊重）。
if grep -q '^DATABASE_URL=' "${WT}/.env" 2>/dev/null; then
  echo "✓ .env に DATABASE_URL 既設（docker は起こさず既設を使う）"
  DBURL="$(grep '^DATABASE_URL=' "${WT}/.env" | head -1 | cut -d= -f2-)"
elif command -v docker >/dev/null 2>&1; then
  if ! docker ps --format '{{.Names}}' | grep -qx "${CONTAINER}"; then
    docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
    docker run -d --name "${CONTAINER}" -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=hoiku \
      -p "${PORT}:5432" postgres:16 >/dev/null
    echo "✓ Postgres 起動（${CONTAINER} :${PORT}）"
  else
    echo "✓ Postgres 稼働中（${CONTAINER}）"
  fi
  printf '\nDATABASE_URL=%s\n' "${DBURL}" >> "${WT}/.env"
  echo "✓ .env に DATABASE_URL 追記"
else
  echo "⚠ docker が無く DATABASE_URL も未設定＝降格モード。content 系 UC は試せない（降格 UC のみ）" >&2
  exit 0
fi

# 4) Postgres が接続を受けるまで待つ。
echo -n "waiting for postgres"
for _ in $(seq 1 30); do
  if docker exec "${CONTAINER}" pg_isready -U postgres -d hoiku >/dev/null 2>&1; then echo " ready"; break; fi
  sleep 1; echo -n "."
done

# 5) スキーマ適用＋デフォルト seed（仮名10人・クラス2・確定書類167件）を既定 workspace へ。
DATABASE_URL="${DBURL}" uv run alembic upgrade head >/dev/null
echo "✓ alembic upgrade head"
DATABASE_URL="${DBURL}" uv run python scripts/seed_documents.py | tail -1
echo "✓ demo_seed 投入"

echo ""
echo "DATABASE_URL=${DBURL}"
echo "次: uv run uvicorn server:app --host 127.0.0.1 --port 8000  → agent-browser で http://127.0.0.1:8000/app/"
echo "後片付け: docker rm -f ${CONTAINER}"
