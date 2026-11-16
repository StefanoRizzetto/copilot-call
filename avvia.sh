#!/bin/bash
# Avvia Copilota call. Al primo avvio crea l'ambiente Python e installa le dipendenze.
set -e
cd "$(dirname "$0")"

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Serve Python 3.11 o più recente. Installalo con: brew install python@3.12"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Primo avvio: creo l'ambiente e installo le dipendenze (qualche minuto)…"
  "$PY" -m venv .venv
  .venv/bin/pip install --upgrade pip -q
  .venv/bin/pip install -r requirements.txt
fi

exec .venv/bin/python -m copilota "$@"
