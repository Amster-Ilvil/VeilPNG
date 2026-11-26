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
    ret=sub.add_parser('restore-return',help='Restore Gemini return using a local original and mask or a saved workspace')
    ret.add_argument('--original',type=Path);ret.add_argument('--mask',type=Path)
    ret.add_argument('--project-dir',type=Path);ret.add_argument('--page',default='1');ret.add_argument('--side',default='source',choices=('source','target'))
    ret.add_argument('--returned',required=True,type=Path);ret.add_argument('--output',required=True,type=Path)
    ret.add_argument('--shade',default='#000000');ret.add_argument('--exact',action='store_true')
    transfer = sub.add_parser("pair-mask", help="Project a concealment mask through a SOURCE-to-TARGET registration matrix")
    transfer.add_argument("--pairs-csv", required=True, type=Path)
    transfer.add_argument("--pair-id", required=True)
    transfer.add_argument("-m", "--mask", required=True, type=Path)
    transfer.add_argument("--from-space", choices=("source", "target"), required=True)
    transfer.add_argument("--expand-px", type=int, default=1, help="Optional destination-pixel safety margin")
    transfer.add_argument("-o", "--output", required=True, type=Path)

    manga_init = sub.add_parser("manga-init", help="Create a registered JP/CN manga pair project with both dual-layer PNGs and AI public previews")
    manga_init.add_argument("--pairs-csv", required=True, type=Path)
    manga_init.add_argument("--pair-id", required=True)
    manga_init.add_argument("--source-image", required=True, type=Path)
    manga_init.add_argument("--target-image", required=True, type=Path)
    manga_init.add_argument("--mask", required=True, type=Path, help="Binary concealment mask drawn in --mask-space")
    manga_init.add_argument("--mask-space", choices=("source", "target"), required=True)
    manga_init.add_argument("--roi-mask", type=Path, help="Optional GPT-editable ROI drawn in the same space as --mask")
    manga_init.add_argument("--expand-px", type=int, default=1)
    manga_init.add_argument("--style", choices=("solid", "noise", "mosaic"), default="solid")
    manga_init.add_argument("--block", type=int, default=18)
    manga_init.add_argument("--color", type=normalize_solid_color, default=DEFAULT_SOLID_COLOR)
    manga_init.add_argument("-o", "--output-dir", required=True, type=Path)

    manga_resolve = sub.add_parser("manga-resolve", help="Resolve AI-returned images for a manga pair project and output decrypted no-cover results")
    manga_resolve.add_argument("--project-dir", required=True, type=Path)
    manga_resolve.add_argument("--source-ai-preview", type=Path)
    manga_resolve.add_argument("--target-ai-preview", type=Path)
    manga_resolve.add_argument("--mode", choices=("A1", "A2"), default="A2")
    manga_resolve.add_argument("--extraction", choices=("color", "monochrome", "difference", "patch"), default="monochrome")
    manga_resolve.add_argument("--alignment", choices=("auto", "resize"), default="auto")
    manga_resolve.add_argument("--threshold", type=int, default=45)
    manga_resolve.add_argument("--edge-guard-px", type=int, default=1)
    manga_resolve.add_argument("--min-component-pixels", type=int, default=20)
    manga_resolve.add_argument("--max-change-fraction", type=float, default=.20)
    manga_resolve.add_argument("--style", choices=("solid", "noise", "mosaic"), default="solid")
    manga_resolve.add_argument("--block", type=int, default=18)
    manga_resolve.add_argument("--color", type=normalize_solid_color, default=None)
    manga_resolve.add_argument("--allow-unsafe-full-merge", action="store_true",
                               help="Opt in to unrestricted A2 visible-area replacement without a green ROI; not recommended")

    manga_a3 = sub.add_parser("manga-transfer", help="A3: transfer Gemini edits from CN public preview into JP high-resolution base")
    manga_a3.add_argument("--project-dir", required=True, type=Path)
    manga_a3.add_argument("--source-ai", required=True, type=Path, help="AI/Gemini output made from the source CN public preview")
    manga_a3.add_argument("--output-dir", type=Path, help="Separate A3 output directory; never overwrites source containers")
    manga_a3.add_argument("--extraction", choices=("monochrome", "difference", "color", "patch"), default="monochrome")
    manga_a3.add_argument("--alignment", choices=("auto", "resize"), default="auto")
    manga_a3.add_argument("--threshold", type=int, default=45)
    manga_a3.add_argument("--edge-guard-px", type=int, default=2)
    manga_a3.add_argument("--feather-px", type=int, default=6)
    manga_a3.add_argument("--expand-changes-px", type=int, default=1)
    manga_a3.add_argument("--max-change-fraction", type=float, default=.20)
    manga_a3.add_argument("--allow-entire-roi", action="store_true", help="Required to overwrite Japanese glyphs in the entire green ROI with AI source pixels")

    a4 = sub.add_parser('manga-visible-transfer', help='A4: preserve full Gemini-visible picture, fill cover using original JP, output ordinary PNG')
    a4.add_argument('--project-dir', required=True, type=Path)
    a4.add_argument('--source-ai', required=True, type=Path)
    a4.add_argument('--output-dir', type=Path)
    a4.add_argument('--alignment', choices=('auto','matrix'), default='auto')
    a4.add_argument('--recover-expand-px', type=int, default=22)
    a4.add_argument('--feather-px', type=int, default=6)

    translate = sub.add_parser("translation-transfer", help="JP image base + Gemini Chinese ROIs -> ordinary PNG (no encryption)")
    translate.add_argument("--japanese", required=True, type=Path)
    translate.add_argument("--gemini", required=True, type=Path)
    translate.add_argument("--translation-mask", required=True, type=Path)
    translate.add_argument("--erase-mask", type=Path, help="Manual JP lettering removal mask")
    translate.add_argument("--protect-mask", type=Path, help="Protected original JP artwork, always takes priority")
    translate.add_argument("--clean-base", type=Path, help="Optional JP delettered image; used ONLY inside --erase-mask")
    translate.add_argument("--matrix", type=Path, help="Optional saved 3x3 .npy matrix, JP -> Gemini; otherwise SIFT")
    translate.add_argument("--transfer", choices=("patch","ink"), default="patch")
    translate.add_argument("--feather-px", type=int, default=3)
    translate.add_argument("--ink-threshold", type=int, default=155)
    translate.add_argument("--output", required=True, type=Path)
    translate.add_argument("--report", type=Path)
    translate.add_argument("--quality-dir", type=Path, help="Optional separate directory for non-OCR residual-ink/seam review files")

    phantom = sub.add_parser("phantom-create", help="Create a two-appearance transparent PNG (not encryption)")
    phantom.add_argument("--surface", required=True, type=Path, help="Image displayed on a WHITE background")
    phantom.add_argument("--hidden", required=True, type=Path, help="Image displayed on a BLACK background")
    phantom.add_argument("-o", "--output", required=True, type=Path, help="Transparent output PNG")
    phantom.add_argument("--mode", choices=("grayscale", "color"), default="grayscale")
    phantom.add_argument("--fit", choices=("cover", "contain", "stretch"), default="cover")
    phantom.add_argument("--white-base", type=int, default=190)
    phantom.add_argument("--white-gain", type=float, default=.22)
    phantom.add_argument("--black-gain", type=float, default=.24)
    phantom.add_argument("--preview-dir", type=Path, help="Export white/black/gray previews, report and offline HTML")

    phantom_inspect = sub.add_parser("phantom-inspect", help="Inspect a transparent phantom-tank PNG without decrypting")
    phantom_inspect.add_argument("-i", "--input", required=True, type=Path)
    phantom_inspect.add_argument("--preview-dir", type=Path)

    platform_prepare = sub.add_parser("phantom-platform-prepare", help="Export offline QQ/WeChat/XHS alpha candidate, fallback, previews, and test instructions")
    platform_prepare.add_argument("-i", "--input", required=True, type=Path)
    platform_prepare.add_argument("--platform", required=True, choices=("qq", "wechat", "xhs"))
    platform_prepare.add_argument("-o", "--output-dir", required=True, type=Path)
    platform_prepare.add_argument("--max-long-side", type=int, help="Override local size candidate; not an official platform limit")

    platform_audit = sub.add_parser("phantom-platform-audit", help="Check an image downloaded back from QQ/WeChat/XHS for lost or damaged Alpha")
    platform_audit.add_argument("--original", required=True, type=Path, help="upload_alpha.png produced by prepare command")
    platform_audit.add_argument("--returned", required=True, type=Path, help="Actual image saved/downloaded from target platform")
    platform_audit.add_argument("--report", type=Path)
    platform_audit.add_argument("--evidence-dir", type=Path, help="Create white/black comparison, alpha heatmap and offline HTML; requires a new/empty separate directory")

    workspace_init = sub.add_parser("workspace-init", help="Create a unified-workspace project for GUI/CLI parity")
    source_group = workspace_init.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--single", type=Path, help="Single image for simple mode")
    source_group.add_argument("--images", nargs='+', type=Path, help="Explicit image list for batch mode")
    source_group.add_argument("--folder", type=Path, help="Folder of static images for batch mode")
    source_group.add_argument("--pair-bundle", type=Path, help="Folder containing registration_pairs.csv and source/target images")
    workspace_init.add_argument("--project-dir", required=True, type=Path)
    workspace_init.add_argument("--portable", action="store_true", help="Copy private source images into project")

    workspace_show = sub.add_parser("workspace-show", help="Print a saved unified-workspace project summary")
    workspace_show.add_argument("--project-dir", required=True, type=Path)

    workspace_apply = sub.add_parser("workspace-apply-mask", help="Apply or update one page mask inside a unified-workspace project")
    workspace_apply.add_argument("--project-dir", required=True, type=Path)
    workspace_apply.add_argument("--page", required=True, help="1-based page index, exact label, exact pair ID, index:N or id:ID")
    workspace_apply.add_argument("--side", choices=("auto","single","cn","jp"), default="auto")
    workspace_apply.add_argument("--operation", choices=("replace","union","subtract"), default="replace")
    ws_src = workspace_apply.add_mutually_exclusive_group(required=True)
    ws_src.add_argument("--mask", type=Path, help="Binary mask PNG matching the selected side image size")
    ws_src.add_argument("--rect", nargs=4, type=int, metavar=("X0","Y0","X1","Y1"), help="Convenience rectangle in selected-side pixels")
    ws_src.add_argument("--clear", action="store_true", help="Replace current page mask with an empty mask on the chosen side")

    workspace_export = sub.add_parser("workspace-export", help="Export ordinary masked PNGs from a unified-workspace project")
    workspace_export.add_argument("--project-dir", required=True, type=Path)
    workspace_export.add_argument("--output-dir", required=True, type=Path)
    workspace_export.add_argument("--color", type=normalize_solid_color, default="#000000")
    workspace_export.add_argument("--page", help="Export only this page (same naming as GUI export current)")
    replay = sub.add_parser("workspace-replay", help="Replay committed mask snapshots and export with hashes")
    replay.add_argument("--project-dir", required=True, type=Path)
    replay.add_argument("--output-dir", required=True, type=Path)
    replay.add_argument("--color", type=normalize_solid_color, default="#000000")
    replay.add_argument("--page", help="Replay/export only this page")
    pack = sub.add_parser("workspace-pack", help="Create a new portable private project with identical source files")
    pack.add_argument("--project-dir", required=True, type=Path)
    pack.add_argument("--output-dir", required=True, type=Path)
    check = sub.add_parser("workspace-verify", help="Verify saved redaction exports against a workspace recipe")
    check.add_argument("--project-dir", required=True, type=Path)
    check.add_argument("--export-dir", required=True, type=Path)
    check.add_argument("--color", type=normalize_solid_color, default="#000000")
    check.add_argument("--page", help="Verify one selected page export")
    translation_project = sub.add_parser("translation-project-render", help="Render a saved manual translation workbench project")
    translation_project.add_argument("--project-dir", required=True, type=Path)
    translation_project.add_argument("--output", required=True, type=Path)
    translation_project.add_argument("--report", type=Path)


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
            q.add_argument("--extraction", choices=("color", "monochrome", "difference", "patch"), default="color")
            q.add_argument("--alignment", choices=("auto", "resize"), default="auto")
            q.add_argument("--threshold", type=int, default=45)
            q.add_argument("--edge-guard-px", type=int, default=0, help="Keep this many pixels untouched along ROI boundaries (0..24)")
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


def _workspace_side(page, label: str) -> int:
    if label in ('auto','single'):
        return 0
    if label == 'cn':
        return 0
    if label == 'jp':
        if not page.pair:
            raise ValueError('当前页面不是中日配对，不能选择 jp 侧')
        return 1
    raise ValueError('未知 side')


def main():
    a = _args()
    if a.command == 'restore-return':
        from .return_restore import restore_return
        from .imaging import load_image,image_to_png_bytes
        if a.project_dir:
            if a.original or a.mask:raise ValueError('Use workspace OR original/mask')
            from .simple_project import load_workspace_project,resolve_page_selector
            state=load_workspace_project(a.project_dir);p=state['pages'][resolve_page_selector(state['pages'],a.page)];side=_workspace_side(p,a.side)
            original=p.read(side);mask=p.get_mask(side);inputs=list(p.paths)
        else:
            if not a.original or not a.mask:raise ValueError('Specify original and mask')
            original=load_image(a.original.read_bytes());mask=load_image(a.mask.read_bytes()).convert('L');inputs=[a.original,a.mask]
        if a.output.suffix.lower()!='.png' or a.output.resolve() in [v.resolve() for v in inputs+[a.returned]]:raise ValueError('Output must be a separate PNG')
        image,report=restore_return(original,load_image(a.returned.read_bytes()),mask,shade=a.shade,exact=a.exact)
        _atomic_write(a.output,image_to_png_bytes(image));print(json.dumps(report,ensure_ascii=False,indent=2));return
    if a.command == "doctor":
        from .platform_check import doctor
        print(json.dumps(doctor(), ensure_ascii=False, indent=2))
        return
    if a.command == 'workspace-init':
        from .simple_project import image_pages, pair_pages, save_workspace_project, workspace_summary
        if a.single:
            pages = image_pages([a.single]); mode = 0
        elif a.images:
            pages = image_pages(a.images); mode = 1
        elif a.folder:
            images = sorted([p for p in a.folder.iterdir() if p.is_file() and p.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff'}], key=lambda p: p.name)
            pages = image_pages(images); mode = 1
        else:
            pages = pair_pages(a.pair_bundle); mode = 2
        report = save_workspace_project(pages, mode, a.project_dir, portable=a.portable, new=True)
        report['pages_detail'] = [p.label for p in pages]
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if a.command == 'workspace-show':
        from .simple_project import load_workspace_project, workspace_summary
        state = load_workspace_project(a.project_dir)
        report = workspace_summary(state['pages'], mode=state['mode'])
        report.update({'project_dir': str(state['project_dir']), 'active_index': state['active_index'], 'active_side': state['active_side'], 'search_query': state['search_query'], 'pages_detail': [p.label for p in state['pages']], 'portable':state['portable'], 'revision':state['revision'], 'commits':sum(len(p.history) for p in state['pages'])})
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if a.command == 'workspace-apply-mask':
        from PIL import Image as _Image
        from .simple_project import load_workspace_project, save_workspace_project, resolve_page_selector, apply_mask, apply_rect
        state = load_workspace_project(a.project_dir)
        idx = resolve_page_selector(state['pages'], a.page)
        page = state['pages'][idx]
        side = _workspace_side(page, a.side)
        if a.clear:
            size = page.sizes.get(side) if side in page.sizes else page.read(side).size
            mask = _Image.new('L', size, 0)
            apply_mask(page, side, mask, operation='replace')
        elif a.mask:
            with _Image.open(a.mask) as m:
                m.load()
                apply_mask(page, side, m, operation=a.operation)
        else:
            apply_rect(page, side, tuple(a.rect), operation=a.operation)
        state['active_index'] = idx
        state['active_side'] = side
        report = save_workspace_project(state['pages'], state['mode'], state['project_dir'], active_index=idx, active_side=side, search_query=state['search_query'],portable=state['portable'],expected_revision=state['revision'])
        report.update({'page_index': idx + 1, 'page_label': page.label, 'side': side, 'operation': 'clear' if a.clear else a.operation})
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if a.command == 'workspace-export':
        from .simple_project import load_workspace_project, export_pages, resolve_page_selector
        state = load_workspace_project(a.project_dir)
        pages=state['pages'] if a.page is None else [state['pages'][resolve_page_selector(state['pages'],a.page)]]
        dest, report = export_pages(pages, a.output_dir, color=a.color)
        payload = {'project_dir': str(state['project_dir']), 'output_dir': str(dest), **report}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if a.command == 'workspace-verify':
        from .simple_project import load_workspace_project, resolve_page_selector
        from .workspace_verify import verify_workspace_export
        state=load_workspace_project(a.project_dir)
        pages=state['pages'] if a.page is None else [state['pages'][resolve_page_selector(state['pages'],a.page)]]
        report=verify_workspace_export(pages,a.export_dir,color=a.color)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        if not report['passed']: raise SystemExit(2)
        return
    if a.command == 'workspace-pack':
        from .simple_project import load_workspace_project,save_workspace_project
        state=load_workspace_project(a.project_dir)
        report=save_workspace_project(state['pages'],state['mode'],a.output_dir,active_index=state['active_index'],active_side=state['active_side'],search_query=state['search_query'],portable=True,new=True)
        print(json.dumps(report,ensure_ascii=False,indent=2));return
    if a.command == 'workspace-replay':
        from .simple_project import load_workspace_project,replay_workspace
        state=load_workspace_project(a.project_dir)
        dest,report=replay_workspace(state,a.output_dir,color=a.color,page=a.page)
        print(json.dumps({'output_dir':str(dest),**report},ensure_ascii=False,indent=2));return
    if a.command == 'translation-project-render':
        from .translation_project import export_translation_project
        report=export_translation_project(a.project_dir,a.output,a.report)
        print(json.dumps(report,ensure_ascii=False,indent=2));return
    if a.command == "phantom-platform-prepare":
        from .phantom_platform import prepare_platform_package
        report = prepare_platform_package(a.input, a.output_dir, a.platform,
                                          max_long_side=a.max_long_side)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return
    if a.command == "phantom-platform-audit":
        from .phantom_platform import audit_platform_return
        report = audit_platform_return(a.original,a.returned)
        if a.evidence_dir:
            from .phantom_platform import write_platform_audit_evidence
            evidence = write_platform_audit_evidence(a.original,a.returned,a.evidence_dir)
            report['evidence_files'] = evidence['files']
        if a.report:
            a.report.parent.mkdir(parents=True,exist_ok=True)
            _atomic_write(a.report,json.dumps(report,ensure_ascii=False,indent=2).encode('utf-8'))
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return
    if a.command == 'translation-transfer':
        import io
        import numpy as np
        from .translation_core import align_translation_images, render_translation
        names=[a.japanese,a.gemini,a.translation_mask,*([a.erase_mask] if a.erase_mask else []),
               *([a.protect_mask] if a.protect_mask else []),
               *([a.clean_base] if a.clean_base else []),
               *([a.matrix] if a.matrix else [])]
        outputs=[a.output,*([a.report] if a.report else [])]
        if a.quality_dir:
            outputs.extend(a.quality_dir/p for p in ('translation_quality_overlay.png','translation_quality_flags.png','translation_quality_report.json'))
        if len({p.resolve() for p in outputs}) != len(outputs) or any(o.resolve()==i.resolve() for o in outputs for i in names):
            raise ValueError('Translation outputs must not overwrite inputs or each other')
        if a.quality_dir and a.quality_dir.exists():
            if not a.quality_dir.is_dir() or any(a.quality_dir.iterdir()):
                raise ValueError('Quality directory must be new or empty; refuse to overwrite existing evidence')
        matrix=np.load(a.matrix,allow_pickle=False) if a.matrix else None
        aligned=align_translation_images(japanese=a.japanese,gemini=a.gemini,
                                         matrix_jp_to_gemini=matrix)
        result=render_translation(aligned=aligned,translation_mask=a.translation_mask,
                                  erase_japanese_mask=a.erase_mask, protect_mask=a.protect_mask,
                                  cleaned_japanese_base=a.clean_base,transfer=a.transfer,
                                  feather_px=a.feather_px,ink_threshold=a.ink_threshold)
        buf=io.BytesIO(); result.image.save(buf,'PNG')
        _atomic_write(a.output,buf.getvalue())
        if a.report:
            _atomic_write(a.report,json.dumps(result.report,ensure_ascii=False,indent=2).encode('utf-8'))
        if a.quality_dir:
            from .quality_review import review_translation
            quality = review_translation(aligned=aligned, result=result,
                                         translation_mask=a.translation_mask,
                                         erase_japanese_mask=a.erase_mask,
                                         protect_mask=a.protect_mask)
            import io as _io
            a.quality_dir.mkdir(parents=True, exist_ok=True)
            for file, image in [('translation_quality_overlay.png', quality.overlay),
                                ('translation_quality_flags.png', quality.issue_mask)]:
                b=_io.BytesIO(); image.save(b,'PNG')
                _atomic_write(a.quality_dir/file,b.getvalue())
            _atomic_write(a.quality_dir/'translation_quality_report.json',
                          json.dumps(quality.report,ensure_ascii=False,indent=2).encode('utf-8'))
            result.report['quality_review'] = quality.report['candidate_counts']
        print(json.dumps(result.report,ensure_ascii=False,indent=2))
        return
    if a.command in ("phantom-create", "phantom-inspect"):
        from .phantom_tank import (PhantomOptions, create_phantom, inspect_phantom,
                                   to_png_bytes, write_preview_assets)
        if a.command == "phantom-create":
            if a.output.suffix.casefold() != ".png":
                raise ValueError("Phantom output must be PNG to preserve Alpha")
            if a.output.resolve() in (a.surface.resolve(), a.hidden.resolve()):
                raise ValueError("Phantom output cannot overwrite either source image")
            with Image.open(a.surface) as surface, Image.open(a.hidden) as hidden:
                result = create_phantom(surface, hidden, PhantomOptions(
                    mode=a.mode, fit=a.fit, white_base=a.white_base,
                    white_gain=a.white_gain, black_gain=a.black_gain))
            _atomic_write(a.output, to_png_bytes(result.image))
            output = a.output
        else:
            with Image.open(a.input) as img:
                result = inspect_phantom(img)
            output = a.input
        if a.preview_dir:
            previews = (a.preview_dir / "preview_white.png", a.preview_dir / "preview_black.png",
                        a.preview_dir / "preview_gray.png", a.preview_dir / "comparison.png",
                        a.preview_dir / "report.json", a.preview_dir / "phantom.png")
            sources = [a.input] if a.command == "phantom-inspect" else [a.surface, a.hidden, a.output]
            if any(p.resolve() == v.resolve() for p in previews for v in sources):
                raise ValueError("Preview directory would overwrite an input or main output")
            write_preview_assets(result, output, a.preview_dir)
        print(json.dumps(result.report, ensure_ascii=False, indent=2))
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
    if a.command == "manga-init":
        from .manga_mode import create_manga_project
        manifest = create_manga_project(output_dir=a.output_dir, pairs_csv=a.pairs_csv, pair_id=a.pair_id,
                                        source_image=a.source_image, target_image=a.target_image,
                                        mask=a.mask, mask_space=a.mask_space, password=_password(confirm=True),
                                        roi_mask=a.roi_mask, expand_px=a.expand_px, style=a.style,
                                        block=a.block, solid_color=a.color)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    if a.command == "manga-resolve":
        from .manga_mode import resolve_manga_project
        summary = resolve_manga_project(project_dir=a.project_dir, password=_password(),
                                        source_ai_preview=a.source_ai_preview, target_ai_preview=a.target_ai_preview,
                                        mode=a.mode, extraction=a.extraction, alignment=a.alignment,
                                        threshold=a.threshold, edge_guard_px=a.edge_guard_px,
                                        min_component_pixels=a.min_component_pixels,
                                        max_change_fraction=a.max_change_fraction, style=a.style,
                                        block=a.block, solid_color=a.color,
                                        allow_unsafe_full_merge=a.allow_unsafe_full_merge)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if a.command == "manga-transfer":
        from .cross_pair_edit import transfer_and_save
        report = transfer_and_save(project_dir=a.project_dir,
                                   gemini_image_path=a.source_ai,
                                   output_dir=a.output_dir, password=_password(),
                                   extraction=a.extraction, alignment=a.alignment,
                                   threshold=a.threshold, edge_guard_px=a.edge_guard_px,
                                   feather_px=a.feather_px, expand_changes_px=a.expand_changes_px,
                                   max_change_fraction=a.max_change_fraction,
                                   allow_entire_roi=a.allow_entire_roi)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    if a.command == 'manga-visible-transfer':
        from .cross_pair_edit import save_gemini_visible_result
        report = save_gemini_visible_result(project_dir=a.project_dir,
                    gemini_image_path=a.source_ai, password=_password(),
                    output_dir=a.output_dir, alignment=a.alignment,
                    recover_expand_px=a.recover_expand_px, feather_px=a.feather_px)
        print(json.dumps(report, ensure_ascii=False, indent=2))
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
                     edge_guard_px=a.edge_guard_px,
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
