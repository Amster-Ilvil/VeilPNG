"""Build a portable unsigned package on *the current operating system*.

Use GitHub Actions to produce other OS/architecture binaries: PyInstaller
cannot cross-compile. Zip/tar output is placed in artifacts/.
"""
from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parent.parent


def build():
    system = platform.system()
    arch = platform.machine().lower()
    if system not in ("Darwin", "Windows", "Linux"):
        raise RuntimeError(f"Unsupported packaging platform: {system}")
    artifact_dir = ROOT / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
           "--name", "VeilPNG", "--distpath", str(ROOT / "dist"),
           "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build"),
           "--paths", str(ROOT),
           "--hidden-import", "cv2", "--collect-submodules", "cv2",
           str(ROOT / "scripts" / "gui_entry.py")]
    subprocess.run(cmd, cwd=ROOT, check=True)
    machine_tag = "arm64" if arch in ("aarch64", "arm64") else "x64"
    if system == "Darwin":
        app = ROOT / "dist" / "VeilPNG.app"
        if not app.exists():
            raise RuntimeError("Expected macOS .app bundle not produced")
        out = artifact_dir / f"VeilPNG-v0.4.1-macOS-{machine_tag}-unsigned.zip"
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(out)], check=True)
    elif system == "Windows":
        source = ROOT / "dist" / "VeilPNG"
        if not (source / "VeilPNG.exe").exists():
            raise RuntimeError("Expected Windows executable not produced")
        prefix = artifact_dir / f"VeilPNG-v0.4.1-Windows-{machine_tag}-portable"
        out = Path(shutil.make_archive(str(prefix), "zip", root_dir=source.parent, base_dir=source.name))
    else:
        source = ROOT / "dist" / "VeilPNG"
        if not (source / "VeilPNG").exists():
            raise RuntimeError("Expected Linux executable not produced")
        out = artifact_dir / f"VeilPNG-v0.4.1-Linux-{machine_tag}-portable.tar.gz"
        with tarfile.open(out, "w:gz") as tar:
            tar.add(source, arcname="VeilPNG")
    print(f"Built {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    build()
