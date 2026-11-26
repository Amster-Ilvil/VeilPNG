"""Conservative, non-OCR quality warnings for JP->Gemini translation transfer.

These pixel-based warnings are not semantic text recognition. Always review
marked regions manually, and never modify the final artwork automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .translation_core import TranslationAligned, TranslationResult, mask_array


@dataclass
class QualityReview:
    overlay: Image.Image
    issue_mask: Image.Image
    report: dict[str, Any]


def _components(source: np.ndarray, label: str, *, min_pixels: int, max_regions: int = 80) -> list[dict]:
    """Groups neighboring suspicious pixels; each region is a review hint."""
    if not np.any(source):
        return []
    clustered = cv2.dilate(source.astype(np.uint8), np.ones((5, 5), np.uint8), iterations=1)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(clustered, connectivity=8)
    out: list[dict] = []
    for i in range(1, n):
        x, y, w, h, _ = (int(v) for v in stats[i])
        pixels = int(np.count_nonzero(source[y:y+h, x:x+w]))
        if pixels < min_pixels or w < 3 or h < 3:
            continue
        out.append({'kind': label, 'bbox': [x, y, x+w, y+h], 'suspicious_pixels': pixels})
    out.sort(key=lambda x: x['suspicious_pixels'], reverse=True)
    return out[:max_regions]


def review_translation(*, aligned: TranslationAligned, result: TranslationResult,
                       translation_mask: Image.Image,
                       erase_japanese_mask: Image.Image | None = None,
                       protect_mask: Image.Image | None = None,
                       residual_threshold: int = 125,
                       seam_threshold: int = 42,
                       min_pixels: int = 10,
                       max_regions_per_kind: int = 80) -> QualityReview:
    """Flag *candidates* for unremoved original ink and hard ROI-edge seams.

    Residual candidate: source JP pixel is dark, remains similarly dark in
    the final image, and lies inside the erase mask but outside pasted Chinese.
    This cannot prove the ink is a Japanese character rather than line art.

    Seam candidate: pasted or erased pixels close to a manual ROI boundary
    differ strongly from the untouched Japanese base. This cannot prove a
    visible seam (e.g. a deliberately cropped character can trigger it).
    """
    if not 0 < residual_threshold < 255 or not 0 < seam_threshold < 255:
        raise ValueError('Review thresholds must be between 1 and 254')
    if not 1 <= min_pixels <= 10000 or not 1 <= max_regions_per_kind <= 500:
        raise ValueError('Invalid review region limits')
    size = aligned.japanese.size
    if result.image.size != size:
        raise ValueError('Result and aligned Japanese canvas must have the same size')
    jp = np.asarray(aligned.japanese.convert('RGB'))
    final = np.asarray(result.image.convert('RGB'))
    paste = mask_array(translation_mask, size, name='translation_mask').astype(bool)
    erase = mask_array(erase_japanese_mask, size, name='erase_japanese_mask').astype(bool)
    protect = mask_array(protect_mask, size, name='protect_mask').astype(bool)
    valid = np.asarray(aligned.valid_mask.convert('L')) > 127
    jp_gray = cv2.cvtColor(jp, cv2.COLOR_RGB2GRAY)
    final_gray = cv2.cvtColor(final, cv2.COLOR_RGB2GRAY)
    gem_gray = cv2.cvtColor(np.asarray(aligned.gemini.convert('RGB')), cv2.COLOR_RGB2GRAY)

    # Remaining source-looking dark ink in user-specified erasure area.
    # Require locally bright Japanese background to limit halftone false positives.
    background = cv2.GaussianBlur(jp_gray, (0, 0), 26)
    original_and_final_similar = cv2.absdiff(jp_gray, final_gray) < 28
    residue = (erase & ~paste & ~protect & valid &
               (jp_gray < residual_threshold) & (final_gray < residual_threshold+15) &
               original_and_final_similar & (background > 155) & (gem_gray > 210))

    # An unexpectedly abrupt transition at a patch/erase boundary. A filled
    # dark line intentionally reaching the ROI edge can also produce warnings.
    writable = (paste | erase) & ~protect & valid
    eroded = cv2.erode(writable.astype(np.uint8), np.ones((5,5), np.uint8), iterations=1)>0
    inner_edge = writable & ~eroded
    change = np.max(np.abs(final.astype(np.int16)-jp.astype(np.int16)), axis=2)
    seam = inner_edge & (change >= seam_threshold) & ~protect & valid

    residual_regions = _components(residue, 'possible_original_ink', min_pixels=min_pixels,
                                    max_regions=max_regions_per_kind)
    seam_regions = _components(seam, 'possible_patch_seam', min_pixels=min_pixels,
                                max_regions=max_regions_per_kind)
    issues = residual_regions + seam_regions
    issues.sort(key=lambda z: z['suspicious_pixels'], reverse=True)
    overlay = Image.fromarray(final, 'RGB').convert('RGBA')
    highlight = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    highlight[residue] = (236, 67, 53, 85)
    highlight[seam] = (255, 170, 0, 92)
    overlay = Image.alpha_composite(overlay, Image.fromarray(highlight, 'RGBA'))
    draw = ImageDraw.Draw(overlay)
    for i, item in enumerate(issues[:100], 1):
        x0,y0,x1,y1 = item['bbox']
        color = (236,67,53,255) if item['kind']=='possible_original_ink' else (245,163,0,255)
        draw.rectangle((x0,y0,x1,y1), outline=color, width=3)
        draw.text((x0,max(0,y0-13)), f'{i}', fill=color)
        item['number'] = i
    flagged = np.full((size[1], size[0], 3), 255, np.uint8)
    flagged[residue] = (225, 55, 55)
    flagged[seam] = (242, 169, 30)
    report = {
        'kind': 'non_ocr_translation_quality_review',
        'size': list(size),
        'status': 'manual_review_needed' if issues else 'no_candidates_found',
        'candidate_counts': {
            'possible_original_ink': len(residual_regions),
            'possible_patch_seam': len(seam_regions),
        },
        'suspicious_pixels': {
            'possible_original_ink': int(np.count_nonzero(residue)),
            'possible_patch_seam': int(np.count_nonzero(seam)),
        },
        'protected_translation_overlap_pixels': int(np.count_nonzero(paste & protect)),
        'protected_erasure_overlap_pixels': int(np.count_nonzero(erase & protect)),
        'issues': issues,
        'thresholds': {'residual': residual_threshold, 'seam': seam_threshold, 'min_pixels': min_pixels},
        'limitations': [
            'This is NOT OCR, text-language classification, or proof of remaining Japanese text.',
            'Detection is limited to JP-looking dark strokes within erase selections where Gemini looks bright; ink elsewhere can be missed.',
            'Dark manga artwork and intentional text touching an ROI edge can cause false positives.',
            'No candidates found does not establish publication-ready quality.',
            'Inspection never modifies the final image or protected original pixels.',
        ],
    }
    return QualityReview(overlay.convert('RGB'), Image.fromarray(flagged, 'RGB'), report)
