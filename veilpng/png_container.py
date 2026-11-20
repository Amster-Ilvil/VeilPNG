"""Spec-compliant private ancillary PNG chunk reading/writing.

vpNg: ancillary, private, reserved uppercase letter, safe-to-copy.
The custom chunk lives immediately BEFORE IEND. Image pixel decoding works
without recognizing this chunk. Third-party re-encoders may still strip it.
"""
from __future__ import annotations

import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PRIVATE_CHUNK = b"vpNg"
MAX_PRIVATE_BYTES = 512 * 1024 * 1024


class ContainerError(ValueError):
    pass


def _iter_chunks(data: bytes):
    if not data.startswith(PNG_SIGNATURE):
        raise ContainerError("Not a PNG file")
    pos = len(PNG_SIGNATURE)
    end_seen = False
    while pos < len(data):
        if len(data) - pos < 12:
            raise ContainerError("Truncated PNG chunk")
        size = struct.unpack_from(">I", data, pos)[0]
        if size > 0x7FFFFFFF:
            raise ContainerError("PNG chunk too large")
        chunk_type = data[pos + 4 : pos + 8]
        after = pos + 12 + size
        if after > len(data):
            raise ContainerError("Truncated PNG chunk payload")
        payload = data[pos + 8 : pos + 8 + size]
        crc_expected = struct.unpack_from(">I", data, pos + 8 + size)[0]
        crc_actual = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        if crc_actual != crc_expected:
            raise ContainerError(f"PNG chunk CRC mismatch: {chunk_type!r}")
        yield pos, after, chunk_type, payload
        pos = after
        if chunk_type == b"IEND":
            end_seen = True
            if pos != len(data):
                raise ContainerError("Unexpected bytes after PNG IEND")
            break
    if not end_seen:
        raise ContainerError("Missing PNG IEND")


def _pack_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    if len(payload) > MAX_PRIVATE_BYTES:
        raise ContainerError("Encrypted payload exceeds 512 MiB limit")
    return (
        struct.pack(">I", len(payload))
        + chunk_type
        + payload
        + struct.pack(">I", zlib.crc32(chunk_type + payload) & 0xFFFFFFFF)
    )


def extract_private_chunk(png_bytes: bytes) -> bytes | None:
    matches = [payload for _, _, typ, payload in _iter_chunks(png_bytes) if typ == PRIVATE_CHUNK]
    if len(matches) > 1:
        raise ContainerError("Duplicated VeilPNG chunks")
    if matches and len(matches[0]) > MAX_PRIVATE_BYTES:
        raise ContainerError("Encrypted payload too large")
    return matches[0] if matches else None


def attach_private_chunk(png_bytes: bytes, payload: bytes) -> bytes:
    if not payload:
        raise ContainerError("Empty VeilPNG payload")
    parts = [PNG_SIGNATURE]
    found_iend = False
    for start, end, typ, _ in _iter_chunks(png_bytes):
        if typ == PRIVATE_CHUNK:
            continue  # Replace rather than duplicate old encryption envelope.
        if typ == b"IEND":
            parts.append(_pack_chunk(PRIVATE_CHUNK, payload))
            found_iend = True
        parts.append(png_bytes[start:end])
    if not found_iend:
        raise ContainerError("Missing PNG end marker")
    return b"".join(parts)


def strip_private_chunk(png_bytes: bytes) -> bytes:
    parts = [PNG_SIGNATURE]
    for start, end, typ, _ in _iter_chunks(png_bytes):
        if typ != PRIVATE_CHUNK:
            parts.append(png_bytes[start:end])
    return b"".join(parts)
