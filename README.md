# VeilPNG v0.4.1

VeilPNG is a local-first dual-layer PNG privacy editor built with Python and PySide6.
It shows a censored preview in ordinary image viewers while storing the original
file encrypted in a private ancillary PNG chunk (AES-256-GCM + Argon2id).

## Features

- Select protected areas with rectangle, freehand brush, lasso, polygon and eraser.
- Hide regions with opaque solid color, mosaic or noise. Color is configurable.
- Reopen the container with a password to restore the original image bytes.
- Export a **public-only** image without ciphertext for third-party AI editors.
- Repack an externally edited preview (A1) without changing the encrypted original.
- Merge authorized visible edits into a new encrypted original (A2).
- Register differing image resolutions and transfer region masks through an
  external 3x3 registration matrix manifest (optional, supplied by the user).
- GUI follows a blue-and-white workstation layout with separate protection and
  AI/registration tabs, plus optional side-by-side public-preview comparison.
- Canvas-focused tool shortcuts: B brush, E eraser, R rectangle, L lasso,
  P polygon, H pan. Brush redraws are coalesced for large images.

**Important:** Editing and resaving an encrypted PNG using other applications
may discard its encrypted chunk. Keep the original container stored safely and
use VeilPNG's import/repack workflow for third-party image outputs. A public-only
preview has no recoverable hidden image by itself. Never upload a container if
its ciphertext must remain private: export the public-only preview instead.

## Install (Python 3.10+)

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows: .venv\Scripts\activate
python -m pip install -e '.[full]'
python -m veilpng.gui
```

CLI: `python -m veilpng --help` or `veilpng --help`.
Use `python -m veilpng doctor` to inspect local dependencies.

For a portable executable, build **on each target OS**:

```bash
python -m pip install -e '.[full,build]'
python scripts/build_release.py
```

GitHub Actions includes native build jobs for Windows, Linux, and both macOS
architectures. Packages are unsigned and are not notarized.

## Privacy and publishing

The repository intentionally does not include *any* sample images, edited
images, encrypted containers, real registration manifests, OCR data, test files,
private passwords, local reports, cloud logs, or binary wheels. Users must
provide their own input images and secrets locally. See `.gitignore`.

This project encrypts the original file using authenticated encryption, but
does not prevent visual inference from the unhidden part of a public preview.
External AI editors cannot directly decrypt the hidden image or preserve its
private PNG chunk when they re-encode the picture.

## License

MIT (see LICENSE).

## v0.4.1 changes

Improved GUI navigation and comparison preview, reduced brush redraw overhead
without changing the encrypted PNG format, and added Linux Qt EGL runtime
installation to the cross-platform CI workflow.
