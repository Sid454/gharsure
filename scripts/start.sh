#!/usr/bin/env bash
# Production start (Render): seed demo data on a fresh disk, then serve on $PORT.
# Free hosting has no persistent disk, so the demo data is recreated after each restart.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f data/rentshield.db ]; then
  python -W ignore -m scripts.seed_demo
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
