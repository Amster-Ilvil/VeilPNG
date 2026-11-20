#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
source .venv/bin/activate
if ! python -c 'import PySide6, PIL, cryptography, argon2, cv2, numpy' >/dev/null 2>&1; then
  python -m pip install -e '.[full]'
fi
python -m veilpng.gui
