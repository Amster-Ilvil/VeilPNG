"""Headless CLI for sealing, verification and AI round-tripping."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

from PIL import Image
from .imaging import DEFAULT_SOLID_COLOR, normalize_solid_color
from .core import (
    audit_exported_preview, inspect_container, merge_ai_preview, preview_only, repack_preview,
    seal_bytes, unseal_bytes,
)


def _password(confirm: bool = False) -> str:
    env = os.environ.get("VEILPNG_PASSWORD")
    if env is not None:
        return env
    value = getpass.getpass("VeilPNG password: ")
    if confirm and value != getpass.getpass("Confirm password: "):
        raise ValueError("Passwords do not match")
    return value


def _args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="veilpng", description="Dual-layer encrypted PNG toolkit")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Report core, GUI and AI registration dependencies without reading private files")
    transfer = sub.add_parser("pair-mask", help="Project a concealment mask through a SOURCE-to-TARGET registration matrix")
    transfer.add_argument("--pairs-csv", required=True, type=Path)
    transfer.add_argument("--pair-id", required=True)
    transfer.add_argument("-m", "--mask", required=True, type=Path)
    transfer.add_argument("--from-space", choices=("source", "target"), required=True)
    transfer.add_argument("--expand-px", type=int, default=1, help="Optional destination-pixel safety margin")
    transfer.add_argument("-o", "--output", required=True, type=Path)
    for command in ("create", "restore", "preview", "repack", "merge", "verify", "audit", "smart-edit"):
        q = sub.add_parser(command)
        q.add_argument("-i", "--input", required=True, type=Path)
        if command not in ("verify", "audit"):
            q.add_argument("-o", "--output", required=True, type=Path)
        if command == "create":
            q.add_argument("-m", "--mask", required=True, type=Path, help="White (255) pixels are concealed")
        if command in ("repack", "merge", "smart-edit"):
            q.add_argument("-p", "--ai-preview", required=True, type=Path)
        if command == "smart-edit":
            q.add_argument("--roi-mask", required=True, type=Path, help="White=allowed edits (separate from protection mask)")
            q.add_argument("--mode", choices=("A1", "A2"), default="A2")
            q.add_argument("--extraction", choices=("color", "difference"), default="color")
            q.add_argument("--alignment", choices=("auto", "resize"), default="auto")
            q.add_argument("--threshold", type=int, default=45)
            q.add_argument("--min-component-pixels", type=int, default=20)
            q.add_argument("--max-change-fraction", type=float, default=.20)
            q.add_argument("--report", type=Path)
            q.add_argument("--delta-mask", type=Path)
            q.add_argument("--preview-output", type=Path)
            q.add_argument("--restored-output", type=Path, help="Also write actual password-decrypted original (A1) or merged plaintext (A2)")
        if command == "audit":
            q.add_argument("-p", "--public-preview", required=True, type=Path)
        if command == "repack":
            q.add_argument("--unsafe-allow-covered-preview-changes", action="store_true",
                           help="Legacy mode: bypass covered-preview restoration without password")
        if command in ("create", "merge"):
            q.add_argument("--style", choices=("solid", "noise", "mosaic"), default="solid")
            q.add_argument("--block", type=int, default=18)
            q.add_argument("--color", type=normalize_solid_color, default=DEFAULT_SOLID_COLOR,
                           help="Opaque RGB color #RRGGBB for --style solid")
    return p.parse_args()


def _atomic_write(path: Path, content: bytes) -> None:
    """Avoid leaving a half-written encrypted container on interruption."""
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".veilpng-", dir=path.parent, delete=False) as f:
            name = f.name
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def main():
    a = _args()
    if a.command == "doctor":
        from .platform_check import doctor
        print(json.dumps(doctor(), ensure_ascii=False, indent=2))
        return
    if a.command == "pair-mask":
        from .mask_transfer import load_pair, transfer_mask
        if a.output.resolve() in (a.mask.resolve(), a.pairs_csv.resolve()):
            raise ValueError("Pair-mask output cannot overwrite input mask or registration manifest")
        pair = load_pair(a.pairs_csv, a.pair_id)
        with Image.open(a.mask) as m:
            m.load()
            mapped = transfer_mask(m, pair, from_space=a.from_space, expand_px=a.expand_px)
        a.output.parent.mkdir(parents=True, exist_ok=True)
        mapped.save(a.output, format="PNG")
        print(json.dumps({"pair_id": pair.pair_id, "from": a.from_space,
                          "to": "source" if a.from_space == "target" else "target",
                          "result_size": mapped.size, "covered_pixels": mapped.histogram()[255],
                          "source_image": pair.source_image, "target_image": pair.target_image,
                          "registration_confidence": pair.confidence}, ensure_ascii=False, indent=2))
        return
    data = a.input.read_bytes()
    if a.command == "create":
        with Image.open(a.mask) as m:
            m.load()
            result = seal_bytes(data, a.input.name, m, _password(confirm=True), a.style, a.block, solid_color=a.color)
    elif a.command == "restore":
        asset = unseal_bytes(data, _password())
        result = asset.original_bytes
        print(f"Original filename: {asset.filename}; SHA-256: {asset.source_sha256}")
    elif a.command == "preview":
        result = preview_only(data)
    elif a.command == "repack":
        pw = None if a.unsafe_allow_covered_preview_changes else _password()
        result = repack_preview(data, a.ai_preview.read_bytes(), password=pw)
    elif a.command == "merge":
        result = merge_ai_preview(data, a.ai_preview.read_bytes(), _password(), a.style, a.block, solid_color=a.color)
    elif a.command == "smart-edit":
        from .smart_edit import smart_edit
        with Image.open(a.roi_mask) as m:
            m.load()
            password = _password()
        result_obj = smart_edit(data, a.ai_preview.read_bytes(), password, m,
                     mode=a.mode, extraction=a.extraction, alignment=a.alignment,
                     threshold=a.threshold, min_component_pixels=a.min_component_pixels,
                     max_global_fraction=a.max_change_fraction)
        result = result_obj.container_png
        extras = [(a.report, json.dumps(result_obj.report, ensure_ascii=False, indent=2).encode()),
                  (a.delta_mask, result_obj.delta_mask_png),
                  (a.preview_output, result_obj.preview_png)]
        if a.restored_output:
            # Actual authenticated decryption, never a pixel-synthesis of the black cover.
            extras.append((a.restored_output, unseal_bytes(result, password).original_bytes))
        outputs = [a.output, *(path for path, content in extras if path)]
        normalized = [path.resolve() for path in outputs]
        forbidden_paths = {a.input.resolve(), a.ai_preview.resolve(), a.roi_mask.resolve()}
        if len(normalized) != len(set(normalized)) or any(x in forbidden_paths for x in normalized):
            raise ValueError("Outputs must be distinct and must not overwrite input container, AI image or ROI mask")
        for path, content in extras:
            if path:
                _atomic_write(path, content)
        print(json.dumps(result_obj.report, ensure_ascii=False, indent=2))
    elif a.command == "audit":
        audit = audit_exported_preview(data, a.public_preview.read_bytes(), _password())
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        if not audit["mechanical_audit_pass"]:
            raise SystemExit(2)
        return
    elif a.command == "verify":
        print(json.dumps(inspect_container(data), ensure_ascii=False, indent=2))
        asset = unseal_bytes(data, _password())
        print(f"AUTHENTICATED, source name: {asset.filename}, SHA-256: {asset.source_sha256}")
        return
    else:
        raise AssertionError(a.command)
    if a.output.resolve() == a.input.resolve():
        raise ValueError("Output must not overwrite input")
    _atomic_write(a.output, result)
    print(f"Saved {a.output} ({len(result):,} bytes)")


if __name__ == "__main__":
    main()
