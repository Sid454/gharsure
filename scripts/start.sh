#!/usr/bin/env bash
# Production start (Render).
#  - With DATABASE_URL set (Supabase/Neon Postgres): real mode, data is permanent, no demo data.
#  - Without it and GHARSURE_DEMO=1: demo mode on a temporary SQLite file, re-seeded on each start.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${DATABASE_URL:-}" ] && [ "${GHARSURE_DEMO:-0}" = "1" ] && [ ! -f data/rentshield.db ]; then
  python -W ignore -m scripts.seed_demo
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
