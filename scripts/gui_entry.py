"""Frozen entrypoint for PyInstaller; keep the same GUI as python -m veilpng.gui."""
from multiprocessing import freeze_support
from veilpng.gui import main

if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
