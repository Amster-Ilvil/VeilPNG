"""Local replay of manually selected translation workbench projects.

No remote calls, no inferred selection regions. The stored matrix and masks
are the explicit recipe; source and mask hashes protect reproducibility.
"""
from pathlib import Path
import hashlib, json, io
import numpy as np
from PIL import Image
from . import __version__
from .simple_project import _atomic, _put_asset, _inside
from .translation_core import align_translation_images, render_translation, mask_array

KEYS=('translation','erase','protect')
MANIFEST='translation_project.json'


def digest(blob): return hashlib.sha256(blob).hexdigest()


def save_translation_project(folder, *, japanese, gemini, clean_base, matrix, masks, transfer, feather):
    folder=Path(folder).resolve(); folder.mkdir(parents=True,exist_ok=True)
    manifest=folder/MANIFEST
    if any(folder.iterdir()) and (not manifest.is_file() or json.loads(manifest.read_text(encoding='utf8')).get('kind')!='translation_transfer'):
        raise ValueError('Choose a new/empty translation project directory')
    sources={k:Path(v).resolve() for k,v in [('japanese',japanese),('gemini',gemini),('clean_base',clean_base)] if v}
    if not {'japanese','gemini'}<=sources.keys(): raise ValueError('Missing inputs')
    cfg={'version':__version__,'kind':'translation_transfer','matrix_jp_to_gemini':np.asarray(matrix,dtype=float).tolist(),
         'transfer':transfer,'feather':int(feather),'mask_files':{},'mask_sha256':{},'source_sha256':{}}
    for k,v in sources.items():
        if v==manifest: raise ValueError('Input conflicts with project manifest')
        cfg[k]=v.relative_to(folder).as_posix() if v.is_relative_to(folder) else str(v)
        cfg['source_sha256'][k]=digest(v.read_bytes())
    cfg.setdefault('clean_base','')
    for k in KEYS:
        b=io.BytesIO(); masks[k].save(b,'PNG'); data=b.getvalue(); h=digest(data)
        name=f'{k}-{h}.png'
        if (folder/name).resolve() in sources.values(): raise ValueError('Mask conflicts with input')
        cfg['mask_files'][k]=_put_asset(folder,name,data); cfg['mask_sha256'][k]=h
    _atomic(manifest,json.dumps(cfg,ensure_ascii=False,indent=2).encode())
    return cfg


def read_translation_recipe(folder, *, source_overrides=None):
    folder=Path(folder).resolve(); cfg=json.loads((folder/MANIFEST).read_text(encoding='utf8'))
    if cfg.get('kind')!='translation_transfer': raise ValueError('Not a translation project')
    files=cfg.get('mask_files',{})
    if set(files)!=set(KEYS): raise ValueError('Incomplete mask set')
    masks={}; inputs={folder/MANIFEST}
    for k,name in files.items():
        if not isinstance(name,str) or Path(name).name!=name or '\\' in name or Path(name).suffix.lower()!='.png':
            raise ValueError('选区文件必须是项目目录中的 PNG 文件名，不允许目录穿越')
        path=_inside(folder,name); blob=path.read_bytes()
        if k in cfg.get('mask_sha256',{}) and digest(blob)!=cfg['mask_sha256'][k]: raise ValueError('Mask hash mismatch')
        with Image.open(io.BytesIO(blob)) as im: masks[k]=im.copy()
        inputs.add(path)
    sources={}; hashes={}
    for key in ('japanese','gemini','clean_base'):
        raw=cfg.get(key,'')
        if not raw:
            if key!='clean_base': raise ValueError('Missing source path')
            continue
        override=(source_overrides or {}).get(key)
        path=Path(override).resolve() if override else (Path(raw).resolve() if Path(raw).is_absolute() else _inside(folder,raw))
        blob=path.read_bytes(); h=digest(blob)
        if key in cfg.get('source_sha256',{}) and h!=cfg['source_sha256'][key]: raise ValueError(f'Source hash mismatch: {key}')
        hashes[key]=h;sources[key]=blob;inputs.add(path)
    verified=(set(cfg.get('source_sha256',{}))==set(sources) and set(cfg.get('mask_sha256',{}))==set(KEYS))
    return cfg,sources,masks,inputs,verified,hashes


def render_translation_project(folder):
    cfg,sources,masks,inputs,verified,hashes=read_translation_recipe(folder)
    aligned=align_translation_images(japanese=sources['japanese'],gemini=sources['gemini'],matrix_jp_to_gemini=np.asarray(cfg['matrix_jp_to_gemini'],dtype=np.float64))
    result=render_translation(aligned=aligned,translation_mask=masks['translation'],erase_japanese_mask=masks['erase'],
       protect_mask=masks['protect'],cleaned_japanese_base=sources.get('clean_base'),transfer=cfg.get('transfer','patch'),feather_px=int(cfg.get('feather',3)))
    result.report.update({'recipe_hashes_verified':verified,'source_sha256':hashes,'pixel_sha256':digest(result.image.tobytes())})
    return result,inputs


def export_translation_project(folder,output,report=None):
    result,inputs=render_translation_project(folder)
    output=Path(output).resolve(); report=Path(report).resolve() if report else None
    outputs=[output]+([report] if report else [])
    if output.suffix.lower()!='.png' or len(set(outputs))!=len(outputs) or any(p in inputs or p.exists() for p in outputs):
        raise ValueError('Use new, distinct output paths; image must be PNG')
    b=io.BytesIO();result.image.save(b,'PNG');data=b.getvalue()
    result.report['output_sha256']=digest(data)
    _atomic(output,data)
    if report:_atomic(report,json.dumps(result.report,ensure_ascii=False,indent=2).encode())
    return result.report
