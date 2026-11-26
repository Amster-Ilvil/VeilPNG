"""A3: transfer ONLY approved AI edits from a registered source scan to its target.

Intended for a SOURCE Chinese public preview edited externally (GPT/Gemini)
with the original high-resolution Japanese TARGET scan as the immutable base.

No cloud submission happens here. The authenticated source/target encrypted PNGs
remain unchanged. All outputs stay local and must not be published accidentally.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image

from .core import inspect_container, preview_only, seal_bytes, unseal_bytes
from .imaging import image_to_png_bytes, load_image, normalize_solid_color
from .mask_transfer import load_pair
from .manga_mode import resolve_project_file
from .smart_edit import align_gpt_image, _changes_from_gpt, _computer_vision


@dataclass
class A3Result:
    sealed_png: bytes
    decrypted_png: bytes
    public_png: bytes
    source_edit_mask_png: bytes
    target_edit_mask_png: bytes
    transferred_patch_png: bytes
    report: dict


def transfer_ai_changes_to_japanese(
    *, project_dir: str | Path, gemini_result: bytes, password: str,
    extraction: str = 'monochrome', alignment: str = 'auto',
    threshold: int = 45, min_component_pixels: int = 20,
    edge_guard_px: int = 2, expand_changes_px: int = 1,
    feather_px: int = 6, max_change_fraction: float = 0.20,
    allow_entire_roi: bool = False,
) -> A3Result:
    """Move permitted source AI changes into the target base, then re-encrypt.

    The cross-page registration matrix is read from the exact project pairs.csv.
    Invariant: every target pixel outside mapped changes (including all protected
    pixels and all pixels outside green edit ROI) equals the original target.

    `extraction='patch'` intentionally copies the entire source green ROI; it
    requires allow_entire_roi=True because the original JP lettering in that
    region will be replaced by lower-res source/Gemini pixels.
    """
    if extraction not in ('monochrome', 'color', 'difference', 'patch'):
        raise ValueError('Unknown extraction mode')
    if extraction == 'patch' and not allow_entire_roi:
        raise ValueError('Full ROI patch is destructive; pass allow_entire_roi=True explicitly')
    if alignment not in ('auto', 'resize'):
        raise ValueError('Unsupported alignment')
    if not (0 <= expand_changes_px <= 8):
        raise ValueError('expand_changes_px must be within 0..8')
    if not (0 <= edge_guard_px <= 24):
        raise ValueError('edge_guard_px must be within 0..24')
    if not (0 <= feather_px <= 24):
        raise ValueError('feather_px must be within 0..24')
    if not (0 < max_change_fraction <= 0.50):
        raise ValueError('Invalid max_change_fraction')

    cv2, np = _computer_vision()
    project_dir = Path(project_dir)
    manifest_path = project_dir / 'manga_project.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('kind') != 'manga_pair_project':
        raise ValueError('Not a VeilPNG manga pair project')
    pair = load_pair(resolve_project_file(project_dir, manifest['pairs_csv'],
                                         'registration_pairs.csv'), manifest['pair_id'])
    if pair.source_image != manifest['registration']['source_image'] or pair.target_image != manifest['registration']['target_image']:
        raise ValueError('Manifest registration files changed; refusing to cross-transfer')
    src_meta, tgt_meta = manifest['source'], manifest['target']
    src_roi_path, tgt_roi_path = src_meta.get('roi_mask'), tgt_meta.get('roi_mask')
    if not src_roi_path or not tgt_roi_path:
        raise ValueError('A3 requires saved green ROIs on BOTH pages')

    src_stem=Path(src_meta['name']).stem
    tgt_stem=Path(tgt_meta['name']).stem
    src_container = resolve_project_file(project_dir, src_meta['container'],
                                         (f"containers/source_{src_stem}_sealed.png",f"containers/{src_stem}_sealed.png")).read_bytes()
    tgt_container = resolve_project_file(project_dir, tgt_meta['container'],
                                         (f"containers/target_{tgt_stem}_sealed.png",f"containers/{tgt_stem}_sealed.png")).read_bytes()
    src_asset = unseal_bytes(src_container, password)
    tgt_asset = unseal_bytes(tgt_container, password)
    if (src_asset.image().size != pair.source_size or tgt_asset.image().size != pair.target_size):
        raise ValueError('Source or target image dimensions differ from pair matrix')
    if (src_asset.mask.size != pair.source_size or tgt_asset.mask.size != pair.target_size):
        raise ValueError('Source or target protection mask size is inconsistent')
    with Image.open(resolve_project_file(project_dir, src_roi_path,
                    (f"editable_rois/source_{src_stem}_roi.png",f"editable_rois/{src_stem}_roi.png"))) as im:
        im.load(); src_roi = im.convert('L')
    with Image.open(resolve_project_file(project_dir, tgt_roi_path,
                    (f"editable_rois/target_{tgt_stem}_roi.png",f"editable_rois/{tgt_stem}_roi.png"))) as im:
        im.load(); tgt_roi = im.convert('L')
    if src_roi.size != pair.source_size or tgt_roi.size != pair.target_size:
        raise ValueError('ROI sizes do not match registration manifest')
    if not src_roi.getbbox() or not tgt_roi.getbbox():
        raise ValueError('Empty source/target ROI; select a green edit region first')

    # Gemini is aligned only against the PUBLIC Chinese preview. No original
    # protected information from either page is submitted to the AI.
    with Image.open(BytesIO(preview_only(src_container))) as im:
        im.load(); src_public = im.convert('RGBA')
    with Image.open(BytesIO(gemini_result)) as im:
        im.load(); gpt = im.convert('RGBA')
    aligned, src_valid, align_stats = align_gpt_image(src_public, gpt, src_asset.mask, src_roi, method=alignment)

    edit_mask, n_source_edit, n_source_allowed = _changes_from_gpt(
        src_public, aligned, np.asarray(src_valid, dtype=np.uint8),
        src_asset.mask, src_roi, extraction=extraction,
        threshold=threshold, min_component_pixels=min_component_pixels,
        edge_guard_px=edge_guard_px,
    )
    if n_source_edit < 1:
        raise ValueError('No eligible Gemini edits in source ROI; Japanese image left unchanged')
    if n_source_edit / (pair.source_size[0] * pair.source_size[1]) > max_change_fraction:
        raise ValueError('Source changes exceed max_change_fraction; refusing broad repaint')

    src_edit = np.asarray(edit_mask, np.uint8).copy()
    if expand_changes_px:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*expand_changes_px+1, 2*expand_changes_px+1))
        src_edit = cv2.dilate(src_edit, k)
        allowed_src = (np.asarray(src_roi) > 0) & (np.asarray(src_asset.mask.convert('L')) == 0) & (np.asarray(src_valid) > 0)
        if edge_guard_px:
            erode_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*edge_guard_px+1,2*edge_guard_px+1))
            allowed_src &= cv2.erode((np.asarray(src_roi)>0).astype('uint8'), erode_kernel) > 0
        src_edit[~allowed_src] = 0

    matrix = np.asarray(pair.matrix_source_to_target, dtype=np.float64)
    if not np.isfinite(matrix).all() or abs(np.linalg.det(matrix)) < 1.e-12:
        raise ValueError('Invalid registration matrix')
    tw, th = pair.target_size
    tgt_edit = cv2.warpPerspective(src_edit, matrix, (tw,th), flags=cv2.INTER_NEAREST,
                                   borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    warped_valid = cv2.warpPerspective(np.asarray(src_valid, np.uint8),matrix,(tw,th),flags=cv2.INTER_NEAREST,
                                      borderMode=cv2.BORDER_CONSTANT,borderValue=0)
    permitted_tgt = (np.asarray(tgt_roi)>0) & (np.asarray(tgt_asset.mask.convert('L'))==0) & (warped_valid>0)
    if edge_guard_px:
        k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*edge_guard_px+1,2*edge_guard_px+1))
        permitted_tgt &= cv2.erode((np.asarray(tgt_roi)>0).astype('uint8'),k) > 0
    tgt_edit[~permitted_tgt] = 0
    target_edit_n=int(np.count_nonzero(tgt_edit))
    if not target_edit_n:
        raise ValueError('No edits survive mapping to allowed target area')
    if target_edit_n/(tw*th)>max_change_fraction:
        raise ValueError('Target changes exceed max_change_fraction; refusing broad repaint')

    rgb_src = np.asarray(aligned.convert('RGB'))
    warped_patch = cv2.warpPerspective(rgb_src, matrix, (tw,th),flags=cv2.INTER_CUBIC,
                                       borderMode=cv2.BORDER_CONSTANT, borderValue=(255,255,255))
    original_target = np.asarray(tgt_asset.image().convert('RGB'))
    result_target = original_target.copy()
    selected = tgt_edit>0
    if feather_px:
        # Blend strictly INSIDE the approved edit mask. This softens the visible
        # rectangle seam without altering even one non-edit target pixel.
        distance = cv2.distanceTransform(selected.astype('uint8'),cv2.DIST_L2,5)
        alpha = np.clip(distance / float(feather_px), 0., 1.).astype('float32')
        mixed = np.rint(original_target.astype('float32')*(1-alpha[...,None])
                        +warped_patch.astype('float32')*alpha[...,None]).astype('uint8')
        result_target[selected] = mixed[selected]
    else:
        result_target[selected] = warped_patch[selected]
    actual_changed = np.any(result_target != original_target,axis=2)
    forbidden_tgt = np.asarray(tgt_asset.mask.convert('L'))>0
    roi_tgt = np.asarray(tgt_roi)>0
    unauthorized = int(np.count_nonzero(actual_changed & (~selected)))
    protected = int(np.count_nonzero(actual_changed & forbidden_tgt))
    outside_roi = int(np.count_nonzero(actual_changed & (~roi_tgt)))
    if unauthorized or protected or outside_roi:
        raise AssertionError('A3 change escaped approved region')

    # Pack A2-style: a fresh encrypted TARGET image, with the original TARGET
    # conceal mask. Decryption shows the complete unmasked Japanese-based result.
    plain_png = image_to_png_bytes(Image.fromarray(result_target, 'RGB'))
    info=inspect_container(tgt_container)
    result_container = seal_bytes(
        plain_png, f'{Path(tgt_asset.filename).stem}_A3_JP_based.png',
        tgt_asset.mask, password, style=info.get('preview_style','solid'),
        block=int(info.get('preview_block',18)),
        solid_color=normalize_solid_color(info.get('preview_solid_color','#000000')),
    )
    decoded = unseal_bytes(result_container, password)
    if decoded.original_bytes != plain_png:
        raise AssertionError('Re-encrypted target did not restore exact merged PNG bytes')
    if decoded.mask.tobytes() != tgt_asset.mask.tobytes():
        raise AssertionError('Target protection mask changed during re-encryption')

    source_edit_png=image_to_png_bytes(Image.fromarray(src_edit, 'L'))
    target_edit_png=image_to_png_bytes(Image.fromarray(tgt_edit, 'L'))
    patch_png=image_to_png_bytes(Image.fromarray(warped_patch,'RGB'))
    report={
        'operation':'A3_source_Gemini_edits_to_JP_base',
        'version':'0.6.0',
        'pair_id':pair.pair_id,
        'source_image':src_asset.filename,
        'target_base':tgt_asset.filename,
        'gemini_dimensions':list(gpt.size),
        'source_size':list(pair.source_size),
        'target_size':list(pair.target_size),
        'extraction':extraction,
        'transfer_scope': 'complete_explicit_green_roi' if extraction == 'patch' else 'detected_source_differences',
        'feather_px':feather_px,
        'edge_guard_px':edge_guard_px,
        'source_alignment':align_stats,
        'pair_matrix_source_to_target': matrix.tolist(),
        'source_candidate_pixels':n_source_edit,
        'source_authorized_pixels':n_source_allowed,
        'mapped_target_mask_pixels':target_edit_n,
        'actual_japanese_image_changed_pixels':int(np.count_nonzero(actual_changed)),
        'outside_mapped_edit_pixels_changed':unauthorized,
        'protected_pixels_changed':protected,
        'outside_green_roi_changed':outside_roi,
        'target_image_sha256':tgt_asset.source_sha256,
        'result_decrypt_sha256':decoded.source_sha256,
        'warning':('Full green ROI copy: these are Gemini-returned pixels, not necessarily pixels that Gemini changed relative to CN. JP lettering and texture inside that ROI are replaced. Inspect seams.' if extraction=='patch' else 'Detected differences can include model resampling artifacts; inspect the output carefully.'),
    }
    return A3Result(
        sealed_png=result_container,
        decrypted_png=plain_png,
        public_png=preview_only(result_container),
        source_edit_mask_png=source_edit_png,
        target_edit_mask_png=target_edit_png,
        transferred_patch_png=patch_png,
        report=report,
    )


def transfer_and_save(*, project_dir: str | Path, gemini_image_path: str | Path,
                      password: str, output_dir: str | Path | None = None, **kwargs) -> dict:
    """Write A3 artifacts separately; never overwrite either source container."""
    project_dir=Path(project_dir)
    if output_dir is None:
        output_dir=project_dir/'resolved_outputs'/'A3_JP_base'
    output_dir=Path(output_dir)
    if output_dir.resolve() in (project_dir.resolve(), (project_dir/'containers').resolve()):
        raise ValueError('A3 results must be saved separately from project containers')
    result=transfer_ai_changes_to_japanese(project_dir=project_dir,
               gemini_result=Path(gemini_image_path).read_bytes(),password=password,**kwargs)
    output_dir.mkdir(parents=True, exist_ok=True)
    names={
        'new_double_layer_png':'A3_JP_based_sealed.png',
        'decrypted_japanese_image':'A3_JP_based_decrypted.png',
        'public_preview':'A3_JP_based_public.png',
        'source_diff_mask':'A3_CN_detected_changes.png',
        'target_diff_mask':'A3_JP_mapped_changes.png',
        'transferred_patch':'A3_JP_aligned_Gemini_patch.png',
    }
    payloads=[result.sealed_png,result.decrypted_png,result.public_png,result.source_edit_mask_png,
              result.target_edit_mask_png,result.transferred_patch_png]
    paths={}
    for (key,name),payload in zip(names.items(),payloads):
        p=output_dir/name
        p.write_bytes(payload)
        paths[key]=str(p)
    report=dict(result.report)
    report['artifacts']=paths
    (output_dir/'A3_transfer_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


@dataclass
class A4VisibleResult:
    """A4 uses Gemini pixels in *all* visible regions, JP only to recover cover."""
    final_png: bytes
    aligned_gemini_png: bytes
    recovery_mask_png: bytes
    report: dict


def transfer_gemini_visible_to_japanese(*, project_dir: str | Path,
                                        gemini_result: bytes, password: str,
                                        alignment: str = 'auto',
                                        recover_expand_px: int = 22,
                                        feather_px: int = 6) -> A4VisibleResult:
    """Deliver a PLAIN PNG that looks like Gemini with the black cover restored.

    Unlike A3, A4 transfers the entire Gemini-visible image, including middle
    dialogue and bottom sound effects. The encrypted Japanese image is used
    only underneath the original concealment mask and at invalid image borders.
    No double-layer container is created in this method.

    Geometry: Gemini -> Chinese source dimensions -> exact registered Japanese
    target. In `auto` mode, feature-based translation/scale/rotation refinement
    is validated against the target; `matrix` is explicitly unchecked geometry.
    """
    if alignment not in ('auto', 'matrix'):
        raise ValueError('A4 alignment must be auto or matrix')
    if not 0 <= recover_expand_px <= 50:
        raise ValueError('recover_expand_px must be 0..50')
    if not 0 <= feather_px <= 24:
        raise ValueError('feather_px must be 0..24')
    cv2, np = _computer_vision()
    project_dir = Path(project_dir)
    manifest = json.loads((project_dir / 'manga_project.json').read_text(encoding='utf-8'))
    if manifest.get('kind') != 'manga_pair_project':
        raise ValueError('Not a manga_pair_project')
    pair = load_pair(resolve_project_file(project_dir, manifest['pairs_csv'],
                                         'registration_pairs.csv'), manifest['pair_id'])
    target_meta = manifest['target']
    if (Path(target_meta['name']).name != Path(pair.target_image).name or
            target_meta['size'] != list(pair.target_size)):
        raise ValueError('Project registration metadata differs from pairing manifest')
    stem=Path(target_meta['name']).stem
    asset = unseal_bytes(resolve_project_file(project_dir, target_meta['container'],
                         (f"containers/target_{stem}_sealed.png",f"containers/{stem}_sealed.png")).read_bytes(), password)
    base_img = asset.image().convert('RGB')
    if base_img.size != pair.target_size or asset.mask.size != pair.target_size:
        raise ValueError('Target protected image size differs from registration')
    with Image.open(BytesIO(gemini_result)) as im:
        im.load()
        gem = im.convert('RGB')
    if gem.width < 64 or gem.height < 64:
        raise ValueError('Gemini output image too small')

    tw, th = pair.target_size
    src_w, src_h = pair.source_size
    geo = np.asarray(pair.matrix_source_to_target, np.float64)
    if not np.isfinite(geo).all() or abs(np.linalg.det(geo)) < 1.e-10:
        raise ValueError('Invalid registration matrix')
    gm_to_src = np.diag([src_w / gem.width, src_h / gem.height, 1.0])
    initial_h = geo @ gm_to_src
    gem_arr = np.asarray(gem, np.uint8)
    base_arr = np.asarray(base_img, np.uint8)
    warped_init = cv2.warpPerspective(gem_arr, initial_h, (tw, th), flags=cv2.INTER_CUBIC,
                                      borderMode=cv2.BORDER_CONSTANT, borderValue=(255,255,255))
    protect = np.asarray(asset.mask.convert('L')) >= 128
    align_stats = {'mode': alignment, 'matches': 0, 'inliers': 0, 'inlier_ratio': 0.0,
                   'alignment_refinement': [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
                   'accepted': alignment == 'matrix'}
    refined_h = initial_h.copy()
    if alignment == 'auto':
        # Exclude original protected pixels, which Gemini renders as black,
        # and image-wide differences in these blocks from correspondence tests.
        stable = np.where(protect, 0, 255).astype(np.uint8)
        stable = cv2.erode(stable, np.ones((29,29),np.uint8), iterations=1)
        orb = cv2.ORB_create(nfeatures=7500, edgeThreshold=15, fastThreshold=13)
        fixed_gray = cv2.cvtColor(base_arr, cv2.COLOR_RGB2GRAY)
        moving_gray = cv2.cvtColor(warped_init, cv2.COLOR_RGB2GRAY)
        kfixed, dfixed = orb.detectAndCompute(fixed_gray, stable)
        kmoving, dmoving = orb.detectAndCompute(moving_gray, stable)
        if dfixed is None or dmoving is None:
            raise ValueError('A4 auto-registration rejected: insufficient features')
        try:
            pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(dmoving, dfixed, k=2)
            good = [a for pair_match in pairs if len(pair_match)==2
                    for a,b in [pair_match] if a.distance < 0.74*b.distance]
        except cv2.error as err:
            raise ValueError('A4 auto-registration matching failed') from err
        if len(good) < 35:
            raise ValueError('A4 auto-registration rejected: fewer than 35 good features')
        pts_moving = np.float32([kmoving[m.queryIdx].pt for m in good]).reshape(-1,1,2)
        pts_fixed = np.float32([kfixed[m.trainIdx].pt for m in good]).reshape(-1,1,2)
        aff, inliers = cv2.estimateAffinePartial2D(pts_moving, pts_fixed,
                    method=cv2.RANSAC, ransacReprojThreshold=3.0,
                    confidence=0.996, maxIters=4000)
        if aff is None or inliers is None:
            raise ValueError('A4 auto-registration rejected: no affine transform')
        count = int(np.count_nonzero(inliers))
        ratio = count / len(good)
        scale = float(np.hypot(aff[0,0], aff[1,0]))
        angle = float(np.degrees(np.arctan2(aff[1,0],aff[0,0])))
        displacement = float(np.hypot(aff[0,2],aff[1,2]))
        if (count < 30 or ratio < 0.64 or not (0.96 < scale < 1.04)
                or abs(angle) > 2.0 or displacement > 30.0):
            raise ValueError(f'A4 auto-registration rejected: matches {count}, ratio {ratio:.3f}, '
                             f'scale {scale:.4f}, angle {angle:.2f}, shift {displacement:.2f}')
        refined_h = np.vstack([aff, [0.0,0.0,1.0]]) @ initial_h
        align_stats = {'mode':'auto', 'matches':len(good), 'inliers':count,
                       'inlier_ratio':round(ratio,5), 'scale':round(scale,6),
                       'angle_degrees':round(angle,6),
                       'translation_px':round(displacement,5),
                       'alignment_refinement':aff.tolist(), 'accepted':True}

    aligned_arr = cv2.warpPerspective(gem_arr, refined_h, (tw,th),
                                     flags=cv2.INTER_LANCZOS4,
                                     borderMode=cv2.BORDER_CONSTANT, borderValue=(255,255,255))
    valid = cv2.warpPerspective(np.ones(gem_arr.shape[:2],np.uint8)*255,
                                refined_h,(tw,th),flags=cv2.INTER_NEAREST,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=0)>0

    # Exact original protected pixels and a soft ring OUTSIDE the protection
    # mask are sourced from the original JP page. Expansion removes any
    # remaining black halo introduced by Gemini rendering/resampling.
    if recover_expand_px > 0:
        disk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                         (2*recover_expand_px+1,2*recover_expand_px+1))
        expanded = cv2.dilate(protect.astype(np.uint8), disk)>0
    else:
        expanded = protect.copy()
    softness = np.zeros((th,tw),np.float32)
    softness[expanded] = 1.0
    if feather_px:
        # Gaussian falloff outside the expanded region, but ALL protected
        # pixels remain exact original JP bytes.
        softness = cv2.GaussianBlur(softness,(0,0),sigmaX=feather_px/2.0)
    softness[protect] = 1.0
    softness[~valid] = 1.0
    result = np.rint(aligned_arr.astype(np.float32)*(1-softness[...,None])
                      +base_arr.astype(np.float32)*softness[...,None]).clip(0,255).astype(np.uint8)
    result[protect] = base_arr[protect]
    changed = np.any(result != base_arr,axis=2)
    if np.any(changed & protect):
        raise AssertionError('Protected original JP area was modified')
    if np.any(result[~valid] != base_arr[~valid]):
        raise AssertionError('Invalid sampling region changed')
    img = Image.fromarray(result,mode='RGB')
    final_png = image_to_png_bytes(img)
    aligned_png = image_to_png_bytes(Image.fromarray(aligned_arr,mode='RGB'))
    recovery_png = image_to_png_bytes(Image.fromarray(np.uint8(expanded)*255,mode='L'))
    report = {'version':'0.6.0', 'mode':'A4_complete_Gemini_visible_with_JP_cover_recovery',
              'output_type':'ordinary_png_no_encrypted_layer',
              'pair_id':pair.pair_id, 'target_japanese_base':asset.filename,
              'gemini_source_size':list(gem.size), 'final_size':[tw,th],
              'project_registration_matrix':geo.tolist(),
              'final_gemini_to_target_homography':refined_h.tolist(),
              'alignment':align_stats,
              'restored_exact_japanese_pixels':int(np.count_nonzero(protect)),
              'expanded_recovery_pixels':int(np.count_nonzero(expanded)),
              'changed_vs_japanese_base':int(np.count_nonzero(changed)),
              'protected_pixels_changed':int(np.count_nonzero(changed & protect)),
              'warning':('This mode intentionally uses Gemini for ALL visible artwork, not '
                         'only changed text. JP is used under the concealment mask. '
                         'Generated linework may differ from JP and is NOT genuine JP high-res detail.')}
    return A4VisibleResult(final_png,aligned_png,recovery_png,report)


def save_gemini_visible_result(*, project_dir: str | Path,
                               gemini_image_path: str | Path, password: str,
                               output_dir: str | Path | None = None,
                               **kwargs) -> dict:
    """Save ordinary PNG and evidence without generating a new double-layer PNG."""
    project_dir=Path(project_dir)
    output_dir=Path(output_dir) if output_dir else project_dir/'resolved_outputs'/'A4_Gemini_visible'
    if output_dir.resolve() in (project_dir.resolve(), (project_dir/'containers').resolve()):
        raise ValueError('Do not overwrite original project or encrypted containers')
    result=transfer_gemini_visible_to_japanese(project_dir=project_dir,
                    gemini_result=Path(gemini_image_path).read_bytes(),
                    password=password,**kwargs)
    output_dir.mkdir(parents=True,exist_ok=True)
    output_name='A4_Gemini_visible_JP_uncovered_FINAL.png'
    result_path=output_dir/output_name
    result_path.write_bytes(result.final_png)
    (output_dir/'A4_aligned_Gemini.png').write_bytes(result.aligned_gemini_png)
    (output_dir/'A4_JP_recovery_mask.png').write_bytes(result.recovery_mask_png)
    report=dict(result.report)
    report['final_image']=str(result_path)
    (output_dir/'A4_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
