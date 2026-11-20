"""VeilPNG format v1: AES-GCM-sealed original and mask in one visible PNG.

Public preview is deliberately NOT authenticated with the ciphertext so the
preview can be replaced without invalidating decryption. This is a tradeoff:
preview tampering is detectable against the INITIAL preview hash, but not
prevented. Encrypted source bytes remain authenticated.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image, ImageChops

from .crypto import KDFParams, derive_key
from .imaging import (DEFAULT_SOLID_COLOR, binary_mask, image_to_png_bytes, load_image,
                      normalize_solid_color, protected_merge, render_preview, solid_rgba)
from .png_container import (
    ContainerError,
    MAX_PRIVATE_BYTES,
    attach_private_chunk,
    extract_private_chunk,
    strip_private_chunk,
)

MAGIC = b"VEILPNG1\0"
PAYLOAD_MAGIC = b"VPAY1"
MAX_METADATA_BYTES = 32 * 1024


@dataclass
class DecryptedAsset:
    original_bytes: bytes
    filename: str
    mask: Image.Image
    source_sha256: str

    def image(self) -> Image.Image:
        return load_image(self.original_bytes)


@dataclass(frozen=True)
class Envelope:
    header: dict
    header_bytes: bytes
    ciphertext: bytes


def _json_bytes(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_filename(name: str) -> str:
    # Path() on Unix doesn't recognize backslash Windows separators.
    name = name.replace("\\", "/").split("/")[-1].strip()
    if not name or name in (".", "..") or len(name) > 240:
        return "restored-image.bin"
    return name


def _encode_body(original_bytes: bytes, filename: str, mask: Image.Image) -> bytes:
    mask_png = image_to_png_bytes(mask.convert("L"))
    body_header = {
        "filename": _safe_filename(filename),
        "original_size": len(original_bytes),
        "original_sha256": _sha(original_bytes),
        "mask_size": len(mask_png),
        "width": mask.width,
        "height": mask.height,
    }
    metadata = _json_bytes(body_header)
    if len(metadata) > MAX_METADATA_BYTES:
        raise ValueError("Encrypted metadata too large")
    return PAYLOAD_MAGIC + struct.pack(">I", len(metadata)) + metadata + original_bytes + mask_png


def _decode_body(body: bytes) -> DecryptedAsset:
    if not body.startswith(PAYLOAD_MAGIC) or len(body) < len(PAYLOAD_MAGIC) + 4:
        raise ContainerError("Decrypted payload has an unknown version")
    at = len(PAYLOAD_MAGIC)
    count = struct.unpack_from(">I", body, at)[0]
    if count > MAX_METADATA_BYTES or at + 4 + count > len(body):
        raise ContainerError("Invalid encrypted metadata length")
    at += 4
    meta = json.loads(body[at:at + count].decode("utf-8"))
    at += count
    source_len = int(meta["original_size"])
    mask_len = int(meta["mask_size"])
    if source_len < 1 or mask_len < 1 or at + source_len + mask_len != len(body):
        raise ContainerError("Encrypted payload sizes do not match")
    original = body[at : at + source_len]
    mask_bytes = body[at + source_len :]
    if _sha(original) != meta["original_sha256"]:
        raise ContainerError("Source checksum mismatch")
    original_image = load_image(original)
    with Image.open(BytesIO(mask_bytes)) as mask_image:
        mask_image.load()
        mask = binary_mask(mask_image, original_image.size)
    if [mask.width, mask.height] != [meta["width"], meta["height"]]:
        raise ContainerError("Mask dimensions mismatch")
    return DecryptedAsset(original, _safe_filename(meta["filename"]), mask, _sha(original))


def _parse_envelope(png_bytes: bytes) -> Envelope:
    data = extract_private_chunk(png_bytes)
    if data is None:
        raise ContainerError("This PNG contains no VeilPNG encrypted layer")
    if not data.startswith(MAGIC) or len(data) < len(MAGIC) + 4:
        raise ContainerError("Unsupported VeilPNG container version")
    at = len(MAGIC)
    size = struct.unpack_from(">I", data, at)[0]
    at += 4
    if size > MAX_METADATA_BYTES or at + size >= len(data):
        raise ContainerError("Invalid VeilPNG header length")
    header_bytes = data[at : at + size]
    header = json.loads(header_bytes.decode("utf-8"))
    if header.get("format") != "VeilPNG" or header.get("version") != 1:
        raise ContainerError("Unsupported VeilPNG version")
    if header.get("kdf") != "argon2id" or header.get("cipher") != "aes-256-gcm":
        raise ContainerError("Unsupported encryption scheme")
    return Envelope(header, header_bytes, data[at + size :])


def _envelope_bytes(env: Envelope) -> bytes:
    return MAGIC + struct.pack(">I", len(env.header_bytes)) + env.header_bytes + env.ciphertext


def seal_bytes(
    original_bytes: bytes, filename: str, selection_mask: Image.Image, password: str,
    style: str = "solid", block: int = 18, kdf: KDFParams | None = None,
    *, solid_color: str = DEFAULT_SOLID_COLOR,
) -> bytes:
    """Seal original file byte-for-byte, with an encrypted binary selection mask."""
    if len(password) < 8:
        raise ValueError("Encryption password must contain at least 8 characters (12+ recommended)")
    image = load_image(original_bytes)
    mask = binary_mask(selection_mask, image.size)
    solid_color = normalize_solid_color(solid_color)
    public = image_to_png_bytes(render_preview(image, mask, style, block, solid_color))
    plaintext = _encode_body(original_bytes, filename, mask)
    params = kdf or KDFParams()
    params.validate()
    salt = os.urandom(16)
    nonce = os.urandom(12)
    header = {
        "format": "VeilPNG", "version": 1, "cipher": "aes-256-gcm", "kdf": "argon2id",
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "argon2_memory_kib": params.memory_kib,
        "argon2_time_cost": params.time_cost,
        "argon2_parallelism": params.parallelism,
        "initial_preview_sha256": _sha(public),
        "width": image.width, "height": image.height,
        "preview_style": style, "preview_block": int(block),
        "preview_solid_color": solid_color,
    }
    aad = _json_bytes(header)
    ciphertext = AESGCM(derive_key(password, salt, params)).encrypt(nonce, plaintext, aad)
    if len(ciphertext) + len(aad) + 16 > MAX_PRIVATE_BYTES:
        raise ValueError("Encrypted source exceeds maximum chunk size")
    return attach_private_chunk(public, _envelope_bytes(Envelope(header, aad, ciphertext)))


def unseal_bytes(container_png: bytes, password: str) -> DecryptedAsset:
    env = _parse_envelope(container_png)
    h = env.header
    try:
        salt = base64.b64decode(h["salt"], validate=True)
        nonce = base64.b64decode(h["nonce"], validate=True)
        params = KDFParams(int(h["argon2_memory_kib"]), int(h["argon2_time_cost"]), int(h["argon2_parallelism"]))
        params.validate()
        plaintext = AESGCM(derive_key(password, salt, params)).decrypt(nonce, env.ciphertext, env.header_bytes)
    except InvalidTag as exc:
        raise ValueError("Wrong password, or encrypted data failed authentication") from exc
    except (KeyError, TypeError, OverflowError, ValueError) as exc:
        raise ContainerError("Invalid encryption header or password") from exc
    result = _decode_body(plaintext)
    if list(result.image().size) != [h["width"], h["height"]]:
        raise ContainerError("Encrypted source dimensions do not match header")
    return result


def inspect_container(container_png: bytes) -> dict:
    env = _parse_envelope(container_png)
    with Image.open(BytesIO(container_png)) as preview:
        preview.load()
        dims = preview.size
    expected = (int(env.header["width"]), int(env.header["height"]))
    if dims != expected:
        raise ContainerError("Public preview dimensions differ from sealed original")
    return {
        "format": "VeilPNG v1", "dimensions": dims,
        "cipher": env.header["cipher"], "kdf": env.header["kdf"],
        "original_preview_unchanged": _sha(strip_private_chunk(container_png)) == env.header["initial_preview_sha256"],
        "ciphertext_bytes": len(env.ciphertext),
        "preview_style": env.header.get("preview_style", "solid"),
        "preview_block": env.header.get("preview_block", 18),
        "preview_solid_color": normalize_solid_color(
            env.header.get("preview_solid_color", DEFAULT_SOLID_COLOR)),
    }


def preview_only(container_png: bytes) -> bytes:
    """For AI uploads: strip ALL private layers and re-encode visible pixels."""
    _parse_envelope(container_png)
    with Image.open(BytesIO(container_png)) as preview:
        preview.load()
        return image_to_png_bytes(preview.convert("RGBA"))


def repack_preview(
    container_png: bytes, ai_preview_png: bytes, password: str | None = None,
) -> bytes:
    """A1: preserve the byte-identical encrypted payload while updating public pixels.

    With password (recommended), restores the *existing covered preview* for
    protected pixels before repacking. Without password, keeps the legacy API:
    the AI-produced pixels may be altered inside the protected preview area,
    although the encrypted source remains authenticated and unchanged.
    """
    info = inspect_container(container_png)
    with Image.open(BytesIO(ai_preview_png)) as img:
        img.load()
        if img.size != info["dimensions"]:
            raise ValueError(f"AI image must be {info['dimensions']}; resize or align it externally")
        updated = img.convert("RGBA")
    if password is not None:
        asset = unseal_bytes(container_png, password)
        with Image.open(BytesIO(container_png)) as original_public:
            original_public.load()
            updated = Image.composite(original_public.convert("RGBA"), updated, asset.mask)
    clean_preview = image_to_png_bytes(updated)
    secret_chunk = extract_private_chunk(container_png)
    assert secret_chunk is not None
    return attach_private_chunk(clean_preview, secret_chunk)


def audit_exported_preview(container_png: bytes, public_png: bytes, password: str) -> dict:
    """Audit mechanical masking properties, NOT semantic safety/AI acceptance."""
    info = inspect_container(container_png)
    asset = unseal_bytes(container_png, password)
    exported = load_image(public_png)
    expected = load_image(preview_only(container_png))
    if exported.size != info["dimensions"]:
        raise ValueError("Exported preview dimensions differ from the encrypted original")
    mask = binary_mask(asset.mask, exported.size)
    selected = mask.histogram()[255]
    no_secret = extract_private_chunk(public_png) is None
    # RGBA.getbbox() may consider alpha alone; inspect all four channels.
    match_diff = ImageChops.difference(exported, expected)
    matches_current_preview = all(channel.getbbox() is None for channel in match_diff.split())
    opaque_d = ImageChops.difference(exported.getchannel("A"), Image.new("L", exported.size, 255))
    covered_fully_opaque = Image.composite(opaque_d, Image.new("L", exported.size, 0), mask).getbbox() is None
    cover_rgb_matches = None
    if info["preview_style"] == "solid":
        color = Image.new("RGBA", exported.size, solid_rgba(info["preview_solid_color"]))
        diff = ImageChops.difference(exported, color)
        covered_diff = Image.composite(diff, Image.new("RGBA", exported.size), mask)
        cover_rgb_matches = all(channel.getbbox() is None for channel in covered_diff.split())
    return {
        "encrypted_payload_absent": no_secret,
        "matches_container_public_preview": matches_current_preview,
        "covered_area_opaque": covered_fully_opaque,
        "covered_area_uniform_color": cover_rgb_matches,
        "coverage_pixels": selected,
        "coverage_percent": round(selected * 100 / (exported.width * exported.height), 3),
        "style": info["preview_style"],
        "color": info["preview_solid_color"] if info["preview_style"] == "solid" else None,
        "mechanical_audit_pass": bool(no_secret and matches_current_preview and covered_fully_opaque and cover_rgb_matches is not False),
        "warning": "Only pixel masking and container separation were checked; surrounding context may still reveal information.",
    }


def merge_ai_preview(
    container_png: bytes, ai_preview_png: bytes, password: str,
    style: str = "solid", block: int = 18, kdf: KDFParams | None = None,
    *, solid_color: str = DEFAULT_SOLID_COLOR,
) -> bytes:
    """A2: put AI pixels into public (unselected) regions and re-encrypt result."""
    asset = unseal_bytes(container_png, password)
    with Image.open(BytesIO(ai_preview_png)) as img:
        img.load()
        ai_image = img.convert("RGBA")
    patched = protected_merge(asset.image(), ai_image, asset.mask)
    modified_png = image_to_png_bytes(patched)
    new_name = Path(asset.filename).stem + "_AI.png"
    return seal_bytes(modified_png, new_name, asset.mask, password, style, block, kdf, solid_color=solid_color)
