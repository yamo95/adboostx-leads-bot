#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then PYTHON="$candidate"; break; fi
done
if [ -z "$PYTHON" ]; then echo 'Install Python 3.11 or newer from python.org, then run this file again.'; exit 1; fi
if [ ! -d .venv ]; then "$PYTHON" -m venv .venv; fi
. .venv/bin/activate
python -m pip install -r requirements.txt
if [ ! -f .env ]; then cp .env.example .env; chmod 600 .env; fi
printf '\nOpen http://127.0.0.1:8000 in your browser. Keep this window open. Ctrl+C stops the app.\n\n'
exec python -m leadengine serve
