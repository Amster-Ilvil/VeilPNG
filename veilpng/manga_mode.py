"""Pair-oriented manga workflow for registered JP/CN image sets.

This module builds on existing VeilPNG primitives to treat a registered
source/target pair as one project: the same concealment mask and optional AI
editable ROI are transferred through the exact registration matrix, both pages
are sealed together, public previews are exported for AI, and returned images
can later be resolved back into authenticated containers and decrypted outputs.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from typing import Any

from PIL import Image

from .core import merge_ai_preview, preview_only, repack_preview, seal_bytes, unseal_bytes
from .imaging import DEFAULT_SOLID_COLOR, image_to_png_bytes, load_image, normalize_solid_color
from .mask_transfer import load_pair, transfer_mask
from .smart_edit import smart_edit


@dataclass(frozen=True)
class PairPaths:
    source_image: Path
    target_image: Path
    source_mask: Path
    target_mask: Path
    source_roi: Path | None = None
    target_roi: Path | None = None


PROJECT_FILE = 'manga_project.json'


def resolve_project_file(project_dir: str | Path, recorded: str | Path | None,
                         fallback: str | tuple[str, ...]) -> Path:
    """Resolve old absolute-path manifests after a project is moved.

    Preserve backward compatibility with v0.5.0-v0.5.8 manifests while
    falling back to files bundled inside the project directory.  In
    particular, a copied project can still find its registration CSV.
    """
    root = Path(project_dir)
    # The project-local asset is authoritative when both it and an old
    # absolute reference exist; otherwise copying a project would silently
    # keep editing the original project instead of the copied one.
    fallbacks = (fallback,) if isinstance(fallback, str) else fallback
    for relative_name in fallbacks:
        candidate = root / relative_name
        if candidate.is_file():
            return candidate
    if recorded:
        original = Path(recorded)
        if original.is_file():
            return original
        relative = root / original
        if relative.is_file():
            return relative
    raise FileNotFoundError(f'Project file missing: {fallbacks[0]}. Re-link the original file if necessary')


def _write_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format='PNG')


def _stats(mask: Image.Image) -> dict[str, Any]:
    mask = mask.convert('L')
    covered = mask.histogram()[255]
    total = mask.width * mask.height
    return {
        'size': [mask.width, mask.height],
        'covered_pixels': int(covered),
        'coverage_percent': round(100.0 * covered / total, 4) if total else 0.0,
    }


def _validate_named_image(path: Path, expected_name: str, expected_size: tuple[int, int]) -> bytes:
    if path.name.casefold() != Path(expected_name).name.casefold():
        raise ValueError(f'Expected image name {expected_name!r}, got {path.name!r}')
    raw = path.read_bytes()
    size = load_image(raw).size
    if size != expected_size:
        raise ValueError(f'Image {path.name} size {size} does not match registration manifest {expected_size}')
    return raw


def create_manga_project(*, output_dir: str | Path, pairs_csv: str | Path, pair_id: str,
                         source_image: str | Path, target_image: str | Path,
                         mask: str | Path, mask_space: str,
                         password: str, roi_mask: str | Path | None = None,
                         expand_px: int = 1, style: str = 'solid', block: int = 18,
                         solid_color: str = DEFAULT_SOLID_COLOR) -> dict[str, Any]:
    """Create a pair project with sealed JP/CN containers and AI-ready previews."""
    if mask_space not in ('source', 'target'):
        raise ValueError('mask_space must be source or target')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if (output_dir / PROJECT_FILE).exists():
        raise FileExistsError('This manga project already exists; choose a new folder to avoid overwriting source assets')
    pair = load_pair(pairs_csv, pair_id)
    src_path = Path(source_image)
    tgt_path = Path(target_image)
    src_raw = _validate_named_image(src_path, pair.source_image, pair.source_size)
    tgt_raw = _validate_named_image(tgt_path, pair.target_image, pair.target_size)
    with Image.open(mask) as m:
        m.load()
        base_mask = m.convert('L')
    if mask_space == 'source' and base_mask.size != pair.source_size:
        raise ValueError(f'Source-space mask size {base_mask.size} does not match {pair.source_size}')
    if mask_space == 'target' and base_mask.size != pair.target_size:
        raise ValueError(f'Target-space mask size {base_mask.size} does not match {pair.target_size}')

    if mask_space == 'source':
        src_mask = base_mask
        tgt_mask = transfer_mask(base_mask, pair, from_space='source', expand_px=expand_px)
    else:
        tgt_mask = base_mask
        src_mask = transfer_mask(base_mask, pair, from_space='target', expand_px=expand_px)

    src_roi = tgt_roi = None
    if roi_mask is not None:
        with Image.open(roi_mask) as r:
            r.load()
            roi = r.convert('L')
        if mask_space == 'source':
            if roi.size != pair.source_size:
                raise ValueError(f'Source-space ROI size {roi.size} does not match {pair.source_size}')
            src_roi = roi
            tgt_roi = transfer_mask(roi, pair, from_space='source', expand_px=0)
        else:
            if roi.size != pair.target_size:
                raise ValueError(f'Target-space ROI size {roi.size} does not match {pair.target_size}')
            tgt_roi = roi
            src_roi = transfer_mask(roi, pair, from_space='target', expand_px=0)

    solid_color = normalize_solid_color(solid_color)
    src_container = seal_bytes(src_raw, src_path.name, src_mask, password, style, block, solid_color=solid_color)
    tgt_container = seal_bytes(tgt_raw, tgt_path.name, tgt_mask, password, style, block, solid_color=solid_color)
    src_preview = preview_only(src_container)
    tgt_preview = preview_only(tgt_container)

    assets_dir = output_dir / 'assets'
    previews_dir = output_dir / 'public_previews'
    masks_dir = output_dir / 'masks'
    rois_dir = output_dir / 'editable_rois'
    containers_dir = output_dir / 'containers'

    for d in (assets_dir, previews_dir, masks_dir, containers_dir):
        d.mkdir(parents=True, exist_ok=True)
    if src_roi is not None or tgt_roi is not None:
        rois_dir.mkdir(parents=True, exist_ok=True)

    # Different folders often contain identically named source/target scans.
    # Never let target silently overwrite source images, masks or containers.
    collision = src_path.stem.casefold() == tgt_path.stem.casefold()
    src_tag = f'source_{src_path.stem}' if collision else src_path.stem
    tgt_tag = f'target_{tgt_path.stem}' if collision else tgt_path.stem
    src_copy = assets_dir / 'source' / src_path.name if collision else assets_dir / src_path.name
    tgt_copy = assets_dir / 'target' / tgt_path.name if collision else assets_dir / tgt_path.name
    src_copy.parent.mkdir(parents=True,exist_ok=True)
    tgt_copy.parent.mkdir(parents=True,exist_ok=True)
    src_copy.write_bytes(src_raw)
    tgt_copy.write_bytes(tgt_raw)

    src_mask_path = masks_dir / f'{src_tag}_conceal.png'
    tgt_mask_path = masks_dir / f'{tgt_tag}_conceal.png'
    _write_png(src_mask, src_mask_path)
    _write_png(tgt_mask, tgt_mask_path)

    src_roi_path = tgt_roi_path = None
    if src_roi is not None and tgt_roi is not None:
        src_roi_path = rois_dir / f'{src_tag}_roi.png'
        tgt_roi_path = rois_dir / f'{tgt_tag}_roi.png'
        _write_png(src_roi, src_roi_path)
        _write_png(tgt_roi, tgt_roi_path)

    src_container_path = containers_dir / f'{src_tag}_sealed.png'
    tgt_container_path = containers_dir / f'{tgt_tag}_sealed.png'
    src_container_path.write_bytes(src_container)
    tgt_container_path.write_bytes(tgt_container)

    src_preview_path = previews_dir / f'{src_tag}_AI_public.png'
    tgt_preview_path = previews_dir / f'{tgt_tag}_AI_public.png'
    src_preview_path.write_bytes(src_preview)
    tgt_preview_path.write_bytes(tgt_preview)
    # Keep the registration manifest inside the PRIVATE project so the
    # project remains usable when moved between Windows, macOS and Linux.
    # It may contain private filenames, so it must never enter public source.
    bundled_pairs = output_dir / 'registration_pairs.csv'
    if Path(pairs_csv).resolve() != bundled_pairs.resolve():
        shutil.copyfile(pairs_csv, bundled_pairs)

    manifest = {
        'version': '0.6.0',
        'kind': 'manga_pair_project',
        'pair_id': pair.pair_id,
        'pairs_csv': str(Path(pairs_csv)),
        'mask_space': mask_space,
        'expand_px': int(expand_px),
        'style': style,
        'block': int(block),
        'solid_color': solid_color,
        'source': {
            'image': str(src_copy), 'container': str(src_container_path), 'public_preview': str(src_preview_path),
            'conceal_mask': str(src_mask_path), 'roi_mask': str(src_roi_path) if src_roi_path else None,
            'name': src_path.name, 'size': list(pair.source_size),
        },
        'target': {
            'image': str(tgt_copy), 'container': str(tgt_container_path), 'public_preview': str(tgt_preview_path),
            'conceal_mask': str(tgt_mask_path), 'roi_mask': str(tgt_roi_path) if tgt_roi_path else None,
            'name': tgt_path.name, 'size': list(pair.target_size),
        },
        'coverage': {'source': _stats(src_mask), 'target': _stats(tgt_mask)},
        'editable_roi': {'source': _stats(src_roi) if src_roi else None, 'target': _stats(tgt_roi) if tgt_roi else None},
        'registration': {
            'confidence': pair.confidence,
            'source_image': pair.source_image,
            'target_image': pair.target_image,
            'source_size': list(pair.source_size),
            'target_size': list(pair.target_size),
        },
    }
    (output_dir / PROJECT_FILE).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def _result_ext(path_str: str) -> str:
    ext = Path(path_str).suffix or '.png'
    return ext if len(ext) < 8 else '.png'


def _load_manifest(project_dir: str | Path) -> tuple[Path, dict[str, Any]]:
    project_dir = Path(project_dir)
    manifest_path = project_dir / PROJECT_FILE
    if not manifest_path.exists():
        raise FileNotFoundError(f'Missing {PROJECT_FILE} in {project_dir}')
    return project_dir, json.loads(manifest_path.read_text(encoding='utf-8'))


def resolve_manga_project(*, project_dir: str | Path, password: str,
                          source_ai_preview: str | Path | None = None,
                          target_ai_preview: str | Path | None = None,
                          mode: str = 'A2', extraction: str = 'monochrome',
                          alignment: str = 'auto', threshold: int = 45,
                          edge_guard_px: int = 1,
                          min_component_pixels: int = 20,
                          max_change_fraction: float = 0.20,
                          style: str = 'solid', block: int = 18,
                          solid_color: str | None = None,
                          allow_unsafe_full_merge: bool = False) -> dict[str, Any]:
    """Process one or both AI-returned pages and write decrypted outputs."""
    project_dir, manifest = _load_manifest(project_dir)
    results_dir = project_dir / 'resolved_outputs'
    results_dir.mkdir(exist_ok=True)
    solid_color = normalize_solid_color(solid_color or manifest.get('solid_color', DEFAULT_SOLID_COLOR))

    def _one(side: str, ai_path: str | Path | None) -> dict[str, Any]:
        side_meta = manifest[side]
        stem=Path(side_meta['name']).stem
        container_path = resolve_project_file(project_dir, side_meta['container'],
                                              (f"containers/{side}_{stem}_sealed.png",
                                               f"containers/{stem}_sealed.png"))
        container_bytes = container_path.read_bytes()
        report: dict[str, Any] = {
            'side': side,
            'container': str(container_path),
            'ai_preview': str(ai_path) if ai_path else None,
            'mode': mode,
            'status': 'skipped' if not ai_path else 'processed',
        }
        if not ai_path:
            report['reason'] = 'No AI return provided for this side'
            return report
        ai_bytes = Path(ai_path).read_bytes()
        roi_mask_path = (resolve_project_file(project_dir, side_meta['roi_mask'],
                         (f"editable_rois/{side}_{stem}_roi.png",
                          f"editable_rois/{stem}_roi.png"))
                         if side_meta.get('roi_mask') else None)
        base_name = Path(side_meta['name']).stem
        resolved_container = results_dir / f'{base_name}_{side}_{mode}_resolved.png'
        resolved_plain = results_dir / f'{base_name}_{side}_{mode}_decrypted.png'
        resolved_public = results_dir / f'{base_name}_{side}_{mode}_public.png'
        delta_mask = results_dir / f'{base_name}_{side}_{mode}_delta.png'
        detail_report = results_dir / f'{base_name}_{side}_{mode}_report.json'
        if roi_mask_path:
            with Image.open(roi_mask_path) as roi:
                roi.load()
                result_obj = smart_edit(container_bytes, ai_bytes, password, roi,
                                        mode=mode, extraction=extraction, alignment=alignment,
                                        threshold=threshold, min_component_pixels=min_component_pixels,
                                        edge_guard_px=edge_guard_px,
                                        max_global_fraction=max_change_fraction,
                                        style=style, solid_color=solid_color)
            resolved_container.write_bytes(result_obj.container_png)
            resolved_public.write_bytes(result_obj.preview_png)
            delta_mask.write_bytes(result_obj.delta_mask_png)
            detail_report.write_text(json.dumps(result_obj.report, ensure_ascii=False, indent=2), encoding='utf-8')
            unsealed = unseal_bytes(result_obj.container_png, password)
            img = load_image(unsealed.original_bytes)
            resolved_plain.write_bytes(image_to_png_bytes(img))
            report.update({
                'resolved_container': str(resolved_container),
                'decrypted_output': str(resolved_plain),
                'public_output': str(resolved_public),
                'delta_mask': str(delta_mask),
                'detail_report': str(detail_report),
                'changed_pixels': result_obj.report.get('changed_pixels'),
                'alignment_accepted': result_obj.report.get('alignment', {}).get('accepted'),
                'strategy': 'smart-edit',
            })
        else:
            if mode == 'A1':
                resolved = repack_preview(container_bytes, ai_bytes, password=password)
            elif mode == 'A2':
                if not allow_unsafe_full_merge:
                    raise ValueError('A2 manga merge requires an explicit green ROI mask; '
                                     'refusing unrestricted whole-visible-area replacement')
                resolved = merge_ai_preview(container_bytes, ai_bytes, password, style=style, block=block, solid_color=solid_color)
            else:
                raise ValueError('Without ROI masks, mode must be A1 or A2')
            resolved_container.write_bytes(resolved)
            resolved_public.write_bytes(preview_only(resolved))
            unsealed = unseal_bytes(resolved, password)
            img = load_image(unsealed.original_bytes)
            resolved_plain.write_bytes(image_to_png_bytes(img))
            report.update({
                'resolved_container': str(resolved_container),
                'decrypted_output': str(resolved_plain),
                'public_output': str(resolved_public),
                'strategy': 'merge' if mode == 'A2' else 'repack',
            })
        return report

    summary = {
        'version': '0.6.0',
        'project_dir': str(project_dir),
        'pair_id': manifest['pair_id'],
        'mode': mode,
        'results': {
            'source': _one('source', source_ai_preview),
            'target': _one('target', target_ai_preview),
        }
    }
    (results_dir / 'resolve_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary
