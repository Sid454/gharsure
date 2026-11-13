#!/usr/bin/env bash
# One-command setup + run:  ./run.sh          (add --reset to recreate demo data)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt

# Build the C++ engine if it's missing or the source changed
if ! ls rentshield_core*.so >/dev/null 2>&1 || [ cpp/rentshield_core.cpp -nt "$(ls rentshield_core*.so | head -1)" ]; then
  echo "Building C++ core..."
  .venv/bin/python setup.py build_ext --inplace -q
fi

if [ ! -f data/rentshield.db ] || [ "${1:-}" = "--reset" ]; then
  .venv/bin/python -W ignore -m scripts.seed_demo
fi

echo "Open http://127.0.0.1:8000"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
