"""Read-only verification of ordinary redacted workspace exports."""
from pathlib import Path
import json
from .simple_project import masked_output, _sha256_bytes, _inside
from .imaging import image_to_png_bytes, load_image, normalize_solid_color
from .png_container import extract_private_chunk


def verify_workspace_export(pages, output_dir, *, color='#000000'):
    """Regenerate expected redacted pixels from explicit saved masks in memory.

    Verify exact names, dimensions, pixels and file hashes. Never modify files.
    A matching report alone is not sufficient: compare with the source recipe.
    """
    color=normalize_solid_color(color)
    root=Path(output_dir).resolve()
    if not root.is_dir(): raise ValueError('Export directory missing')
    expected={}
    for index,page in enumerate(pages,1):
        if not page.ready: continue
        for side in range(len(page.paths)):
            name,image=masked_output(page,index,side,color)
            expected[name]=(image.size,_sha256_bytes(image.tobytes()),_sha256_bytes(image_to_png_bytes(image)))
    if not expected: raise ValueError('No marked pages to verify')
    report_path=root/'report.json'
    try:
        if report_path.is_symlink(): raise ValueError('Symlink report')
        saved=json.loads(report_path.read_text(encoding='utf8'))
        if not isinstance(saved,dict) or any(not isinstance(saved.get(k),dict) for k in ('sha256','pixel_sha256')):
            raise ValueError('Malformed export report')
        report_ok=(set(saved['files'])==set(expected) and len(saved['files'])==len(expected)
                   and saved['exported']==len(expected) and saved['color']==color
                   and saved.get('skipped')==sum(not p.ready for p in pages)
                   and set(saved['sha256'])==set(expected) and set(saved['pixel_sha256'])==set(expected))
    except (OSError,ValueError,KeyError,TypeError): saved={};report_ok=False
    extra=sorted(p.name for p in root.iterdir() if p.name!='report.json' and p.name not in expected)
    rows=[]
    for name,(size,pixel_sha,file_sha) in expected.items():
        row={'name':name,'expected_pixel_sha256':pixel_sha,'expected_sha256':file_sha}
        try:
            path=_inside(root,name)
            if (root/name).is_symlink(): raise ValueError('Symlink export')
            raw=path.read_bytes()
            if not raw.startswith(b'\x89PNG\r\n\x1a\n') or extract_private_chunk(raw) is not None:
                raise ValueError('Not an ordinary public PNG')
            actual=load_image(raw)
            actual_sha=_sha256_bytes(raw); actual_pixel=_sha256_bytes(actual.tobytes())
            pixels=actual.size==size and actual_pixel==pixel_sha
            row.update({'size':list(actual.size),'sha256':actual_sha,'pixel_sha256':actual_pixel,
                        'status':('EXACT' if actual_sha==file_sha else 'PIXELS_MATCH') if pixels else 'PIXELS_DIFFER'})
            row['report_matches']=saved.get('sha256',{}).get(name)==actual_sha and saved.get('pixel_sha256',{}).get(name)==actual_pixel
        except Exception as exc:
            row.update({'status':'INVALID_OR_MISSING','error':str(exc),'report_matches':False})
        rows.append(row)
    pixels_ok=all(r['status'] in ('EXACT','PIXELS_MATCH') for r in rows)
    report_ok=report_ok and all(r['report_matches'] for r in rows)
    return {'passed':pixels_ok and not extra and report_ok,'pixels_match':pixels_ok,
            'bytes_match':all(r['status']=='EXACT' for r in rows),'report_matches':report_ok,
            'unexpected_files':extra,'files':rows,'color':color}
