"""Cross-platform dependency diagnostics; never reads images, passwords, or accounts."""
from __future__ import annotations

from . import __version__
import importlib.metadata
import importlib.util
import json
import platform
import sys


def doctor() -> dict:
    dependencies = {}
    for module, package in (("PIL", "Pillow"), ("cryptography", "cryptography"),
                            ("argon2", "argon2-cffi"), ("PySide6", "PySide6"),
                            ("cv2", "opencv-python-headless"), ("numpy", "numpy")):
        available = importlib.util.find_spec(module) is not None
        try:
            version = importlib.metadata.version(package) if available else None
        except importlib.metadata.PackageNotFoundError:
            version = "installed (distribution name unknown)" if available else None
        dependencies[module] = {"available": available, "version": version}
    return {
        "app": f"VeilPNG v{__version__}",
        "python": sys.version.split()[0],
        "system": platform.system(),
        "machine": platform.machine(),
        "dependencies": dependencies,
        "core_ready": all(dependencies[x]["available"] for x in ("PIL", "cryptography", "argon2")),
        "gui_ready": dependencies["PySide6"]["available"],
        "registration_ready": dependencies["cv2"]["available"] and dependencies["numpy"]["available"],
    }
