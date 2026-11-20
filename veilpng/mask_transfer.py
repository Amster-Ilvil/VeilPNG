"""Precisely transfer a binary concealment/edit mask between registered scans.

The csv matrix maps SOURCE (e.g. low-resolution Chinese scan) to TARGET
(e.g. high-resolution Japanese scan).  Masks must always be warped with the
same geometric correspondence as their images, *not* merely resized.

No external repository code is embedded. OpenCV/Numpy are optional deps.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class RegistrationPair:
    pair_id: str
    source_image: str
    target_image: str
    source_size: tuple[int, int]
    target_size: tuple[int, int]
    matrix_source_to_target: tuple[tuple[float, float, float], ...]
    confidence: float


def load_pair(pairs_csv: str | Path, pair_id: str) -> RegistrationPair:
    """Load the exact pair id, rejecting ambiguous or ill-formed manifests."""
    import math

    with Path(pairs_csv).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        matches = [r for r in reader if r.get("pair_id", "").strip() == pair_id.strip()]
    if len(matches) != 1:
        raise ValueError(f"Pair {pair_id!r}: expected exactly one row, found {len(matches)}")
    row = matches[0]
    matrix = json.loads(row["matrix_3x3_json"])
    if len(matrix) != 3 or any(not isinstance(r, list) or len(r) != 3 for r in matrix):
        raise ValueError("Registration matrix must be 3 x 3")
    values = tuple(tuple(float(x) for x in r) for r in matrix)
    if not all(math.isfinite(v) for r in values for v in r):
        raise ValueError("Registration matrix contains nonfinite values")
    sizes = tuple(int(row[k]) for k in ("source_width", "source_height", "target_width", "target_height"))
    if any(x < 1 or x > 100000 for x in sizes):
        raise ValueError("Invalid registration dimensions")
    return RegistrationPair(
        pair_id=pair_id.strip(),
        source_image=row["source_image"], target_image=row["target_image"],
        source_size=sizes[:2], target_size=sizes[2:],
        matrix_source_to_target=values,
        confidence=float(row.get("registration_confidence") or 0),
    )


def transfer_mask(mask: Image.Image, pair: RegistrationPair, *, from_space: str,
                  expand_px: int = 0) -> Image.Image:
    """Warp a binary selection between registered source and target pixel grids.

    `from_space='target'` transfers a JP target mask to the CN source;
    `from_space='source'` transfers a CN mask to the JP target. `expand_px`
    optionally extends the mask in destination pixels to prevent undercoverage
    at boundaries (this is privacy conservative, but can occlude more artwork).
    """
    try:
        import cv2
        import numpy as np
    except ImportError as e:
        raise RuntimeError("Install the 'ai' optional dependencies for mask registration") from e
    if from_space not in ("source", "target"):
        raise ValueError("from_space must be 'source' or 'target'")
    if not (0 <= expand_px <= 50):
        raise ValueError("expand_px must be between 0 and 50")
    expected = pair.source_size if from_space == "source" else pair.target_size
    target_size = pair.target_size if from_space == "source" else pair.source_size
    if mask.size != expected:
        raise ValueError(f"Input mask dimensions {mask.size} differ from manifest {expected}")
    arr = np.asarray(mask.convert("L"))
    mask_array = (arr >= 128).astype(np.uint8) * 255
    matrix = np.asarray(pair.matrix_source_to_target, np.float64)
    determinant = np.linalg.det(matrix)
    if not np.isfinite(determinant) or abs(determinant) < 1e-10:
        raise ValueError("Singular registration matrix")
    if from_space == "target":
        matrix = np.linalg.inv(matrix)
    warped = cv2.warpPerspective(mask_array, matrix, target_size,
                                 flags=cv2.INTER_NEAREST,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    if expand_px:
        size = 2 * expand_px + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))
        warped = cv2.dilate(warped, kernel)
    return Image.fromarray(warped, "L")
