#!/bin/zsh
set -e
cd "$(dirname "$0")/.."
if ! command -v python3 >/dev/null 2>&1; then
  echo '请先安装 Python 3.10 或更高版本。'
  read -k 1 '?按任意键退出...'
  exit 1
fi
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
if ! python -c 'import PySide6, PIL, cryptography, argon2, cv2, numpy' >/dev/null 2>&1; then
  python -m pip install -e '.[full]'
fi
python -m veilpng.gui
