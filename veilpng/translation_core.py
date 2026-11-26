"""Non-generative JP-clean-base + Gemini Chinese text translation transfer.

Coordinates for masks and the output are in the destination canvas (by default
Gemini's image size, to match external edits). The Japanese image is always
used as the visual base. The protected region always has priority over all
clearing and transfer operations. No encrypted PNG is needed in the final step.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps


@dataclass
class TranslationAligned:
    japanese: Image.Image
    gemini: Image.Image
    valid_mask: Image.Image
    matrix_jp_to_canvas: np.ndarray
    report: dict[str, Any]


@dataclass
class TranslationResult:
    image: Image.Image
    clean_base: Image.Image
    transferred_mask: Image.Image
    report: dict[str, Any]


def load_rgb(source: Image.Image | str | Path | bytes) -> Image.Image:
    if isinstance(source, Image.Image):
        if getattr(source, 'n_frames', 1) != 1:
            raise ValueError('Animated or multipage source images are not supported')
        return ImageOps.exif_transpose(source).convert('RGB')
    if isinstance(source, bytes):
        with Image.open(BytesIO(source)) as im:
            if getattr(im, 'n_frames', 1) != 1:
                raise ValueError('Animated or multipage source images are not supported')
            im.load()
            return ImageOps.exif_transpose(im).convert('RGB')
    with Image.open(source) as im:
        if getattr(im, 'n_frames', 1) != 1:
            raise ValueError('Animated or multipage source images are not supported')
        im.load()
        return ImageOps.exif_transpose(im).convert('RGB')


def mask_array(mask: Image.Image | str | Path | None, size: tuple[int, int], *, name: str) -> np.ndarray:
    if mask is None:
        return np.zeros((size[1], size[0]), dtype=np.uint8)
    if not isinstance(mask, Image.Image):
        with Image.open(mask) as im:
            im.load(); mask = im.convert('L')
    if mask.size != size:
        raise ValueError(f'{name} size {mask.size} differs from destination canvas {size}; no implicit mask scaling')
    return (np.asarray(mask.convert('L')) > 127).astype('uint8')


def _warp(img: np.ndarray, matrix: np.ndarray, size: tuple[int,int], *, linear: bool = True) -> np.ndarray:
    flags = cv2.INTER_CUBIC if linear else cv2.INTER_NEAREST
    return cv2.warpPerspective(img, matrix, size, flags=flags,
                               borderMode=cv2.BORDER_CONSTANT,
                               borderValue=(255,255,255) if img.ndim == 3 else 0)


def _derive_homography(jp: Image.Image, gem: Image.Image, *, max_features: int = 6500) -> tuple[np.ndarray,dict]:
    jgray = np.asarray(jp.convert('L')); ggray = np.asarray(gem.convert('L'))
    sift = cv2.SIFT_create(nfeatures=max_features)
    kp_j, desc_j = sift.detectAndCompute(jgray, None)
    kp_g, desc_g = sift.detectAndCompute(ggray, None)
    if desc_j is None or desc_g is None:
        raise ValueError('No feature descriptors: select a different source image or provide saved alignment')
    knn = cv2.BFMatcher(cv2.NORM_L2).knnMatch(desc_j, desc_g, k=2)
    # knnMatch may return just one neighbour for sparse/degenerate feature
    # sets.  Such inputs are invalid for the ratio test, not a reason for an
    # IndexError / a half-created GUI project.
    good=[pair[0] for pair in knn if len(pair) == 2 and
          pair[0].distance < 0.70 * pair[1].distance]
    if len(good) < 12:
        raise ValueError('Too few registration matches; provide saved 3x3 matrix')
    a=np.float32([kp_j[m.queryIdx].pt for m in good])
    b=np.float32([kp_g[m.trainIdx].pt for m in good])
    matrix, inliers = cv2.findHomography(a,b,cv2.RANSAC,3.5,maxIters=3000,confidence=0.998)
    if matrix is None:
        raise ValueError('Homography calculation failed')
    n=int(np.count_nonzero(inliers))
    rate=n/max(1,len(good))
    if n<12 or rate < .45:
        raise ValueError(f'Unreliable alignment: {n}/{len(good)} inliers')
    return matrix, {'method':'sift_ransac','matched_features':len(good),'inliers':n,
                    'inlier_ratio':round(rate,5)}


def align_translation_images(*, japanese: Image.Image | str | Path | bytes,
                             gemini: Image.Image | str | Path | bytes,
                             matrix_jp_to_gemini: np.ndarray | None = None,
                             canvas: str = 'gemini') -> TranslationAligned:
    """Register Japanese artwork to edited Gemini output; no text changes yet.

    By default output uses Gemini canvas coordinates, but actual pixels are
    warped from the immutable Japanese original. A 3x3 saved matrix may be
    supplied to avoid re-registering each GUI preview.
    """
    if canvas not in ('gemini','japanese'):
        raise ValueError('canvas must be gemini or japanese')
    jp=load_rgb(japanese); gem=load_rgb(gemini)
    if matrix_jp_to_gemini is None:
        H, stats=_derive_homography(jp, gem)
    else:
        H=np.asarray(matrix_jp_to_gemini,dtype=np.float64)
        stats={'method':'provided_matrix','matched_features':None,'inliers':None,'inlier_ratio':None}
    if H.shape != (3,3) or not np.isfinite(H).all() or abs(np.linalg.det(H)) < 1e-12:
        raise ValueError('Invalid image registration matrix')
    # Homographies with a projective horizon intersecting the source image
    # can generate enormous/undefined coordinates even when det(H) != 0.
    corners = np.array([[0, 0, 1], [jp.width, 0, 1],
                        [0, jp.height, 1], [jp.width, jp.height, 1]],
                       dtype=np.float64)
    denominators = (H @ corners.T)[2]
    if (np.any(np.abs(denominators) < 1e-9) or
            (np.min(denominators) < 0 < np.max(denominators))):
        raise ValueError('Invalid image registration matrix: projective horizon intersects the page')
    if canvas == 'japanese':
        output_size=jp.size
        canvas_matrix=np.eye(3,dtype=np.float64)
        gem_matrix=np.linalg.inv(H)
        jp_aligned=jp
        gem_arr=_warp(np.asarray(gem), gem_matrix, output_size)
        valid=_warp(np.full((gem.height,gem.width),255,dtype='uint8'),gem_matrix,output_size,linear=False)
    else:
        output_size=gem.size
        canvas_matrix=H
        jp_aligned=Image.fromarray(_warp(np.asarray(jp), H, output_size),'RGB')
        gem_arr=np.asarray(gem)
        valid=_warp(np.full((jp.height,jp.width),255,dtype='uint8'),H,output_size,linear=False)
    stats.update({'japanese_size':list(jp.size),'gemini_size':list(gem.size),
                  'output_size':list(output_size),'canvas':canvas,
                  'matrix_jp_to_gemini':H.tolist(),
                  'valid_pixels':int(np.count_nonzero(valid))})
    return TranslationAligned(japanese=jp_aligned, gemini=Image.fromarray(gem_arr,'RGB'),
                              valid_mask=Image.fromarray(valid,'L'),
                              matrix_jp_to_canvas=canvas_matrix,report=stats)


def render_translation(*, aligned: TranslationAligned,
                       translation_mask: Image.Image | str | Path,
                       erase_japanese_mask: Image.Image | str | Path | None = None,
                       protect_mask: Image.Image | str | Path | None = None,
                       cleaned_japanese_base: Image.Image | str | Path | None = None,
                       transfer: str = 'patch',
                       feather_px: int = 2,
                       ink_threshold: int = 155,
                       inpaint_radius: int = 3,
                       max_area_fraction: float = .55) -> TranslationResult:
    """Compose one normal PNG, preserving all pixels outside manual edits.

    `patch`: preserve all Gemini pixels inside authorized text ROIs (including
    white outlines over dark manga backgrounds); feather strictly inside ROI.
    `ink`: use only dark Chinese ink strokes; best for white speech bubbles.
    Optional erase mask uses local inpainting *before* Chinese ink is added.
    A trusted delettered Japanese base can be supplied instead of inpainting.
    """
    if transfer not in ('patch','ink'):
        raise ValueError('transfer must be patch or ink')
    if not 0<=feather_px<=24 or not 0<=ink_threshold<=254 or not 1<=inpaint_radius<=12:
        raise ValueError('Invalid transfer settings')
    if not 0<max_area_fraction<=1:
        raise ValueError('Invalid max_area_fraction')
    size=aligned.japanese.size
    src_j=np.asarray(aligned.japanese.convert('RGB'))
    src_g=np.asarray(aligned.gemini.convert('RGB'))
    paste=mask_array(translation_mask,size,name='translation_mask')>0
    erase=mask_array(erase_japanese_mask,size,name='erase_japanese_mask')>0
    protect=mask_array(protect_mask,size,name='protect_mask')>0
    valid=np.asarray(aligned.valid_mask.convert('L'))>127
    overlap_protected_paste=int(np.count_nonzero(paste & protect))
    overlap_protected_erase=int(np.count_nonzero(erase & protect))
    if not np.any(paste):
        raise ValueError('No approved translation regions; use rectangle, polygon or brush')
    if paste.mean()>max_area_fraction:
        raise ValueError(f'Translation area {paste.mean():.1%} exceeds configured safe limit {max_area_fraction:.0%}')
    if not np.any(paste & ~protect & valid):
        raise ValueError('All translation pixels are protected or outside registered image')
    if np.any(paste & ~valid):
        raise ValueError('Translation mask includes unregistered canvas pixels')
    erase &= valid & ~protect
    paste &= valid & ~protect
    # Erasing JP glyphs is never allowed to alter a protected pixel.
    if cleaned_japanese_base is None:
        erase_u8=(erase.astype('uint8')*255)
        if np.any(erase):
            # Slight dilation removes JPEG antialiasing halos around original ink.
            erase_u8=cv2.dilate(erase_u8,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3)))
            erase_u8[protect|(~valid)]=0
            candidate=cv2.inpaint(src_j,erase_u8,float(inpaint_radius),cv2.INPAINT_TELEA)
            # Dilation is only a context tool for inpainting, never an
            # authorization to modify pixels outside the manual orange mask.
            cleaned=src_j.copy()
            cleaned[erase]=candidate[erase]
        else:
            cleaned=src_j.copy()
    else:
        clean=load_rgb(cleaned_japanese_base)
        if clean.size!=size: raise ValueError('Delettered Japanese base must be on output canvas')
        clean_arr=np.asarray(clean)
        cleaned=src_j.copy()
        cleaned[erase]=clean_arr[erase]
    cleaned[protect]=src_j[protect]
    output=cleaned.copy()
    chosen=paste.copy()
    if transfer=='ink':
        gray=cv2.cvtColor(src_g,cv2.COLOR_RGB2GRAY)
        chosen&=(gray<ink_threshold)
        if not np.any(chosen):
            raise ValueError('No dark translation ink strokes inside ROI')
    if feather_px and transfer=='patch':
        distance=cv2.distanceTransform(chosen.astype('uint8'),cv2.DIST_L2,5)
        alpha=np.clip(distance/feather_px,0,1)
        mixed=np.rint(cleaned.astype('float32')*(1-alpha[...,None]) +
                       src_g.astype('float32')*alpha[...,None]).astype('uint8')
        output[chosen]=mixed[chosen]
    else:
        output[chosen]=src_g[chosen]
    # Protection is repeated as a final safety invariant.
    output[protect]=src_j[protect]
    changed=np.any(output!=src_j,axis=2)
    edit_scope=paste|erase
    forbidden=int(np.count_nonzero(changed & ~edit_scope))
    protected=int(np.count_nonzero(changed & protect))
    if forbidden or protected:
        raise AssertionError(f'Edit escaped scope (outside={forbidden}, protected={protected})')
    rep={
      'mode':'JP_delettered_base_plus_Gemini_Chinese_translation',
      'encrypted_output':False,
      'output_size':list(size),'transfer':transfer,'feather_px':feather_px,
      'paste_mask_pixels':int(np.count_nonzero(paste)),
      'erase_mask_pixels':int(np.count_nonzero(erase)),
      'protected_pixels':int(np.count_nonzero(protect)),
      'paste_mask_protected_overlap_pixels':overlap_protected_paste,
      'erase_mask_protected_overlap_pixels':overlap_protected_erase,
      'protected_pixels_changed':protected,'outside_edit_scope_changed':forbidden,
      'changed_pixels':int(np.count_nonzero(changed)),
      'effective_transferred_pixels':int(np.count_nonzero(chosen)),
      'alignment':aligned.report,
      'warning':'Manual ROIs are required; text correctness and delettering seams need visual proofing. This is not OCR or AI semantic recognition.',
    }
    return TranslationResult(image=Image.fromarray(output,'RGB'),
                             clean_base=Image.fromarray(cleaned,'RGB'),
                             transferred_mask=Image.fromarray((chosen.astype('uint8')*255),'L'),
                             report=rep)
