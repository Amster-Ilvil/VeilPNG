"""Local-only GPT edit registration and conservative ROI-limited compositing.

No cloud call. Inputs: unencrypted GPT-rendered public image and ORIGINAL
encrypted container. Only the precisely selected editable pixels may change.

OpenCV/numpy are OPTIONAL and imported lazily from the `.[ai]` extra.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from .core import (DEFAULT_SOLID_COLOR, _envelope_bytes, _parse_envelope,
                   _sha, inspect_container, seal_bytes, unseal_bytes)
from .imaging import binary_mask, image_to_png_bytes, load_image
from .png_container import attach_private_chunk


def _computer_vision():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Install AI alignment support: python -m pip install -e '.[ai]'") from exc
    return cv2, np


@dataclass
class SmartEditResult:
    container_png: bytes
    preview_png: bytes
    delta_mask_png: bytes
    report: dict


def align_gpt_image(reference: Image.Image, gpt: Image.Image,
                    forbidden_mask: Image.Image, edit_roi: Image.Image,
                    *, method: str = "auto"):
    """Return GPT pixels warped to original coordinates and registration stats.

    Auto mode deliberately rejects poorly matching/unrelated pictures instead
    of silently resizing and damaging a decrypted source.
    """
    cv2, np = _computer_vision()
    if method not in ("auto", "resize"):
        raise ValueError("Alignment must be 'auto' or explicit 'resize'")
    w, h = reference.size
    if gpt.width < 64 or gpt.height < 64:
        raise ValueError("GPT image is too small to register")
    a = np.asarray(reference.convert("RGB"))
    b = np.asarray(gpt.convert("RGB"))
    scaled = cv2.resize(b, (w, h), interpolation=cv2.INTER_LANCZOS4)
    valid = np.full((h, w), 255, np.uint8)
    affine = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    stats = {"method":method, "gpt_size":list(gpt.size), "target_size":[w,h],
             "matches":0, "inliers":0, "inlier_ratio":0.0,
             "alignment_affine":affine, "accepted":method == "resize"}
    if method == "resize":
        stats["warning"] = "Resize only is unverified geometry: user explicitly opted in"
        return Image.fromarray(scaled, "RGB").convert("RGBA"), valid, stats

    gray_a = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    gray_b = cv2.cvtColor(scaled, cv2.COLOR_RGB2GRAY)
    excluded = np.asarray(forbidden_mask.convert("L")) > 0
    excluded |= np.asarray(edit_roi.convert("L")) > 0
    # Keep a margin away from edit edges and protected contents. Correspondences
    # there may be visually plausible but semantically invalid.
    excluded = cv2.dilate(excluded.astype(np.uint8), np.ones((11,11),np.uint8)) > 0
    region = np.where(excluded,0,255).astype(np.uint8)
    orb = cv2.ORB_create(nfeatures=5000, edgeThreshold=13, fastThreshold=12)
    p1, d1 = orb.detectAndCompute(gray_a, region)
    p2, d2 = orb.detectAndCompute(gray_b, region)
    if d1 is None or d2 is None or len(p1) < 30 or len(p2) < 30:
        raise ValueError("Automatic registration rejected: insufficient unprotected stable features")
    matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d2, d1, k=2)
    good = [m for pair in matches if len(pair)==2 for m,n in [pair] if m.distance < 0.76*n.distance]
    if len(good) < 30:
        raise ValueError("Automatic registration rejected: fewer than 30 reliable image matches")
    src = np.float32([p2[m.queryIdx].pt for m in good])
    dst = np.float32([p1[m.trainIdx].pt for m in good])
    matrix, inlier = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC,
                                ransacReprojThreshold=4.0, maxIters=3500, confidence=0.995)
    if matrix is None or inlier is None:
        raise ValueError("Automatic registration rejected: no geometric fit")
    count = int(inlier.sum())
    ratio = float(count / len(good))
    sx = float((matrix[0,0]**2+matrix[1,0]**2)**0.5)
    import math
    angle = abs(math.degrees(math.atan2(matrix[1,0],matrix[0,0])))
    shift = float(math.hypot(matrix[0,2], matrix[1,2]))
    if count < 25 or ratio < .38 or not (.95 <= sx <= 1.05) or angle > 4.0 or shift > 0.07*min(w,h):
        raise ValueError(f"Automatic registration rejected: {count} inliers, ratio {ratio:.3f}, "
                         f"scale {sx:.3f}, angle {angle:.2f}, translation {shift:.1f}px")
    reg = cv2.warpAffine(scaled, matrix, (w,h), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT,borderValue=(0,0,0))
    valid = cv2.warpAffine(np.full((h,w),255,np.uint8),matrix,(w,h),
                           flags=cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
    stats.update({"matches":len(good),"inliers":count,"inlier_ratio":round(ratio,4),
                  "scale":round(sx,6),"rotation_degrees":round(angle,4),
                  "translation_px":round(shift,4),
                  "alignment_affine":matrix.tolist(),"accepted":True})
    return Image.fromarray(reg, "RGB").convert("RGBA"), valid, stats


def _changes_from_gpt(base_public, registered_gpt, valid, forbidden, roi,
                      *, extraction, threshold, min_component_pixels, edge_guard_px=0):
    cv2, np = _computer_vision()
    ref = np.asarray(base_public.convert("RGB"), dtype=np.uint8)
    edited = np.asarray(registered_gpt.convert("RGB"),dtype=np.uint8)
    forbid = np.asarray(forbidden.convert("L")) > 0
    allow = (np.asarray(roi.convert("L")) > 0) & (~forbid) & (valid>0)
    if not (0 <= edge_guard_px <= 24):
        raise ValueError("edge_guard_px must be within 0..24")
    if edge_guard_px:
        # Optional conservative interior: never place a generated seam against
        # the user's exact patch edge; no write may escape the original ROI.
        interior = cv2.erode((np.asarray(roi.convert("L")) > 0).astype(np.uint8),
                             cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                      (2*edge_guard_px+1, 2*edge_guard_px+1)))
        allow &= interior > 0
    if extraction == "color":
        src_max = ref.max(axis=2).astype(np.int16)
        src_min = ref.min(axis=2).astype(np.int16)
        src_chroma = src_max-src_min
        colorful_fraction = float((src_chroma[allow] >= 35).mean()) if allow.any() else 0.0
        if colorful_fraction > .1:
            raise ValueError("Color extraction requires mostly grayscale reference in ROI; use 'difference' intentionally")
        ed_chroma = edited.max(axis=2).astype(np.int16)-edited.min(axis=2).astype(np.int16)
        candidate = (ed_chroma >= threshold) & (ed_chroma > src_chroma+18)
    elif extraction == "difference":
        candidate = np.max(np.abs(edited.astype(np.int16)-ref.astype(np.int16)),axis=2) >= threshold
    elif extraction == "monochrome":
        # For greyscale lettering/line art. Low-amplitude resampling noise is
        # rejected before connected-component filtering. This is *not* OCR or
        # a semantic guarantee: only user-approved ROI may ever be written.
        ref_chroma = ref.max(axis=2).astype(np.int16)-ref.min(axis=2).astype(np.int16)
        edit_chroma = edited.max(axis=2).astype(np.int16)-edited.min(axis=2).astype(np.int16)
        if allow.any() and (float((ref_chroma[allow]>=25).mean()) > .05 or
                            float((edit_chroma[allow]>=25).mean()) > .10):
            raise ValueError("Monochrome extraction requires mostly grayscale reference and AI output in ROI")
        ref_gray = cv2.cvtColor(ref, cv2.COLOR_RGB2GRAY)
        edt_gray = cv2.cvtColor(edited, cv2.COLOR_RGB2GRAY)
        smooth_ref = cv2.GaussianBlur(ref_gray, (3,3), .6)
        smooth_edt = cv2.GaussianBlur(edt_gray, (3,3), .6)
        difference = np.abs(smooth_ref.astype(np.int16)-smooth_edt.astype(np.int16))
        ink_crossed = ((ref_gray < 170) != (edt_gray < 170)) | ((ref_gray < 225) != (edt_gray < 225))
        candidate = (difference >= threshold) & (ink_crossed | (difference >= max(75, threshold*2)))
    elif extraction == "patch":
        # Deterministic full-patch replacement. This intentionally copies all
        # pixels inside the explicit ROI, including background, so users can
        # remove old text rather than retaining ghost glyphs. Review edges.
        difference = np.max(np.abs(edited.astype(np.int16)-ref.astype(np.int16)),axis=2)
        if not np.any((difference >= threshold) & allow):
            raise ValueError("No eligible GPT changes found in the allowed area; file left unchanged")
        candidate = allow.copy()
    else:
        raise ValueError("Extraction must be 'color', 'monochrome', 'difference', or 'patch'")
    candidate &= allow
    # Remove disconnected isolated error pixels. Do not expand beyond the selected ROI.
    count, labels, stats, _ = cv2.connectedComponentsWithStats(candidate.astype(np.uint8),8)
    keep = np.zeros(candidate.shape, np.uint8)
    for k in range(1,count):
        if int(stats[k,cv2.CC_STAT_AREA]) >= min_component_pixels:
            keep[labels == k] = 255
    # anti-alias just around colorful overlay; still must be inside explicit ROI
    if extraction in ("color", "monochrome"):
        keep = cv2.dilate(keep,np.ones((3,3),np.uint8),iterations=1)
        keep[~allow] = 0
    return Image.fromarray(keep,"L"), int(keep.sum()//255), int(allow.sum())


def smart_edit(container_png: bytes, gpt_png: bytes, password: str,
               edit_roi: Image.Image, *, mode: str = "A2", extraction: str = "color",
               alignment: str = "auto", threshold: int = 45,
               min_component_pixels: int = 20, max_global_fraction: float = .20,
               edge_guard_px: int = 0, style: str | None = None, solid_color: str | None = None):
    """Run a guarded GPT A1/A2 edit; no changes outside chosen ROI.

    A1: original ciphertext remains bit-identical. A2: only authorized pixels
    are merged into plaintext, then it is sealed with fresh random salt/nonce.
    Returns the result PNG and reports; the report never includes image plaintext.
    """
    if mode not in ("A1", "A2"):
        raise ValueError("mode must be A1 or A2")
    if not (5 <= threshold <= 255):
        raise ValueError("threshold outside 5..255")
    if not (1 <= min_component_pixels <= 100000):
        raise ValueError("min_component_pixels outside 1..100000")
    if not (0 < max_global_fraction <= 0.5):
        raise ValueError("max_global_fraction outside (0,.5]")
    if not (0 <= edge_guard_px <= 24):
        raise ValueError("edge_guard_px outside 0..24")
    asset = unseal_bytes(container_png, password)
    info = inspect_container(container_png)
    roi = binary_mask(edit_roi, asset.image().size)
    if not roi.getbbox():
        raise ValueError("Empty editable ROI; explicitly select an area first")
    # Prevent trivial accidental whole-image merging.
    roi_pixels = roi.histogram()[255]
    total = roi.width*roi.height
    if roi_pixels > .65*total:
        raise ValueError("Edit ROI is larger than 65% of image; use smaller explicit patches")
    with Image.open(BytesIO(container_png)) as temp:
        temp.load()
        base_public = temp.convert("RGBA")
    gpt = load_image(gpt_png)
    if gpt.getchannel("A").getextrema()[0] != 255:
        raise ValueError("GPT input must be fully opaque; flatten transparent areas explicitly before import")
    aligned, valid, reg_report = align_gpt_image(base_public, gpt, asset.mask, roi,method=alignment)
    delta_mask, changed, allowed = _changes_from_gpt(
        base_public,aligned,valid,asset.mask,roi,
        extraction=extraction,threshold=threshold,min_component_pixels=min_component_pixels,edge_guard_px=edge_guard_px)
    if changed == 0:
        raise ValueError("No eligible GPT changes found in the allowed area; file left unchanged")
    if changed > total*max_global_fraction:
        raise ValueError("Too many modified pixels for conservative mode; file left unchanged")
    public_merged = Image.composite(aligned, base_public, delta_mask).convert("RGBA")
    if mode == "A1":
        old = _parse_envelope(container_png)
        result_png = attach_private_chunk(image_to_png_bytes(public_merged),_envelope_bytes(old))
        if unseal_bytes(result_png,password).original_bytes != asset.original_bytes:
            raise RuntimeError("A1 original payload changed unexpectedly")
        if _parse_envelope(result_png).ciphertext != old.ciphertext:
            raise RuntimeError("A1 ciphertext changed unexpectedly")
    else:
        new_plain = Image.composite(aligned,asset.image(),delta_mask).convert("RGBA")
        new_bytes = image_to_png_bytes(new_plain)
        result_png = seal_bytes(new_bytes,Path(asset.filename).stem+"_GPT_ROI.png",
                           asset.mask,password,style=style or info["preview_style"],
                           block=info["preview_block"],
                           solid_color=solid_color or info["preview_solid_color"])
        if unseal_bytes(result_png,password).original_bytes != new_bytes:
            raise RuntimeError("A2 decrypted content failed verification")
        # Public preview of A2 may have details outside ROI changed in a lossy
        # original JPEG converted to PNG, but DECRYPTED source pixels may not.
        from .imaging import render_preview
        public_merged = render_preview(new_plain,asset.mask,style or info["preview_style"],
                                       info["preview_block"],solid_color or info["preview_solid_color"])
    # Audit actual plaintext changes independent of nominal delta mask size.
    # Important when the source is a lossy JPEG and the input has been
    # converted to RGBA: compare decoded source pixels, not encoded file bytes.
    _, np = _computer_vision()
    original_pixels = np.asarray(asset.image().convert("RGBA"))
    if mode == "A2":
        decrypted_pixels = np.asarray(unseal_bytes(result_png, password).image().convert("RGBA"))
        actual_change = np.any(original_pixels != decrypted_pixels, axis=2)
        protected_arr = np.asarray(asset.mask.convert("L")) > 0
        roi_arr = np.asarray(roi.convert("L")) > 0
        actual_inside_protected = int(np.count_nonzero(actual_change & protected_arr))
        actual_outside_roi = int(np.count_nonzero(actual_change & ~roi_arr))
        actual_changed_pixels = int(np.count_nonzero(actual_change))
        if actual_inside_protected or actual_outside_roi:
            raise RuntimeError("A2 changed pixels outside its permitted region")
    else:
        actual_changed_pixels = 0
        actual_inside_protected = 0
        actual_outside_roi = 0
    protected = asset.mask.histogram()[255]
    report = {
        "version":"VeilPNG v0.6.0", "mode":mode,"extraction":extraction,
        "threshold":threshold,"minimum_component_pixels":min_component_pixels,
        "edge_guard_px":edge_guard_px,"actual_decrypted_changed_pixels":actual_changed_pixels,
        "geometry":reg_report,"editable_roi_pixels":roi_pixels,
        "eligible_unprotected_roi_pixels":allowed,"changed_pixels":changed,
        "changed_percent_of_whole":round(100*changed/total,4),
        "protected_pixels":protected,"written_pixels_outside_roi":actual_outside_roi,
        "written_pixels_in_protected_area":actual_inside_protected,
        "original_source_sha256":asset.source_sha256,
        "decrypted_source_sha256":unseal_bytes(result_png,password).source_sha256,
        "A1_original_byte_identical":mode=="A1",
        "warning":"ROI-constrained pixel extraction is not semantic OCR; grayscale text and patch boundaries require visual review.",
    }
    return SmartEditResult(result_png,image_to_png_bytes(public_merged),image_to_png_bytes(delta_mask),report)
