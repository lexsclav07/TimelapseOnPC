#!/usr/bin/env bash
# First run creates a virtual environment and installs dependencies.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip >/dev/null
    .venv/bin/pip install -r requirements.txt
fi
exec .venv/bin/python -m studylapse "$@"
