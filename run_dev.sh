#!/usr/bin/env bash
# Run Nexus Macro from source.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
    echo "ERROR: run ./build_linux.sh or create the environment with:"
    echo "  python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
    exit 1
fi
exec ./.venv/bin/python app.py "$@"
