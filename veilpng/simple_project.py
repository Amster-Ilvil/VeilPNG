"""Local redaction queue shared by single, batch and registered-pair views.

Only ordinary, opaque redacted PNGs are exported here. Legacy encrypted
containers and other specialist tools remain in the advanced workspace.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import csv, hashlib, io, json, re, shutil, tempfile, os, math
from contextlib import contextmanager
from PIL import Image, ImageChops
from .imaging import load_image, binary_mask, image_to_png_bytes, render_preview, normalize_solid_color, rectangle_mask
from .mask_transfer import RegistrationPair, load_pair, transfer_mask
from .pair_import import discover_bundle
from . import __version__

EXTS={'.png','.jpg','.jpeg','.webp','.bmp','.tif','.tiff'}
WORKSPACE_FORMAT='veilpng-simple-workspace-v2'
LEGACY_FORMAT='veilpng-simple-workspace-v1'
WORKSPACE_MANIFEST='workspace.json'


def natural_key(path):
    return tuple((1,int(x)) if x.isdigit() else (0,x.casefold()) for x in re.split(r'(\d+)', str(path)))


def _path(root, name):
    p=(root / Path(name.replace('\\','/')).name).resolve()
    if not p.is_relative_to(root) or not p.is_file():
        raise ValueError(f'图片缺失或路径越界：{name}')
    return p


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


@dataclass
class Page:
    label: str
    paths: tuple[Path,...]
    pair: RegistrationPair|None=None
    masks: dict[int,bytes]=field(default_factory=dict)
    fingerprints: dict[int,str]=field(default_factory=dict)
    sizes: dict[int,tuple[int,int]]=field(default_factory=dict)
    history: list[dict]=field(default_factory=list)

    def read(self, side):
        raw=self.paths[side].read_bytes()
        sha=hashlib.sha256(raw).hexdigest()
        if side in self.fingerprints and sha!=self.fingerprints[side]:
            raise ValueError(f'原图已变化，请重新导入：{self.paths[side].name}')
        image=load_image(raw)
        if self.pair and image.size != (self.pair.source_size,self.pair.target_size)[side]:
            raise ValueError(f'图片尺寸与配准清单不符：{self.paths[side].name}')
        if side in self.sizes and self.sizes[side]!=image.size:
            raise ValueError('Source decoded dimensions differ from saved project')
        self.fingerprints[side]=sha
        self.sizes[side]=image.size
        return image

    def get_mask(self, side):
        size=self.sizes[side] if side in self.sizes else self.read(side).size
        if side not in self.masks:
            return Image.new('L',size,0)
        with Image.open(io.BytesIO(self.masks[side])) as m:
            return binary_mask(m,size)

    def update(self, side, mask, *, action="mask-commit"):
        if not 0 <= side < len(self.paths): raise ValueError("Invalid side")
        # Stage both sides first; a failed warp must not leave half a pair edited.
        mask=binary_mask(mask,self.sizes[side] if side in self.sizes else self.read(side).size)
        staged={side:mask}
        if self.pair:
            staged[1-side]=transfer_mask(mask,self.pair,from_space=('source','target')[side],expand_px=1)
        new={i:image_to_png_bytes(m) for i,m in staged.items() if m.getbbox()}
        for i in staged:
            self.masks.pop(i,None)
        self.masks.update(new)
        if not self.history or self.history[-1]["masks"] != self.masks:
            self.history.append({"action":str(action), "side":side, "masks":dict(self.masks)})

    @property
    def ready(self):
        return all(i in self.masks for i in range(len(self.paths)))



def image_pages(paths):
    unique=sorted({Path(p).expanduser().resolve() for p in paths},key=lambda p:(natural_key(p),str(p)))
    if not unique or any(not p.is_file() or p.suffix.lower() not in EXTS for p in unique):
        raise ValueError('请选择有效的静态图片文件')
    return [Page(p.name,(p,)) for p in unique]



def pair_pages(folder=None, *, manifest=None, source=None, target=None):
    if folder is not None:
        manifest,source,target=discover_bundle(folder)
    manifest,source,target=Path(manifest).resolve(),Path(source).resolve(),Path(target).resolve()
    with manifest.open(encoding='utf-8-sig',newline='') as f:
        ids=[r.get('pair_id','').strip() for r in csv.DictReader(f)]
    if not ids or any(not i for i in ids) or len(set(ids))!=len(ids):
        raise ValueError('配准清单编号为空或重复')
    pages=[]
    for pid in ids:
        pair=load_pair(manifest,pid)
        paths=(_path(source,pair.source_image),_path(target,pair.target_image))
        if paths[0]==paths[1]:
            raise ValueError('中日两侧不能使用同一个文件')
        pages.append(Page(f'{pid} · {paths[0].name} ↔ {paths[1].name}',paths,pair))
    return pages



def masked_output(page,index,side,color):
    image=page.read(side); mask=page.get_mask(side)
    if not mask.getbbox(): raise ValueError('导出选区为空')
    path=page.paths[side]
    name=f'{index:05d}_{("CN_","JP_")[side] if page.pair else ""}{path.stem}_masked.png'
    result=render_preview(image,mask,'solid',solid_color=color)
    clean=Image.frombytes('RGBA',result.size,result.tobytes())
    return name,clean


def export_pages(pages, parent, *, color='#000000', progress=None, cancelled=None):
    """Export a NEW folder atomically; never overwrite inputs or prior outputs.

    Skip unmarked pages, including any pair with a missing side. Cancellation
    and failures remove the staging folder and publish no partial result.
    """
    color=normalize_solid_color(color)
    parent=Path(parent).resolve()
    if not parent.is_dir(): raise ValueError('请选择存在的输出目录')
    ready=[(i,p) for i,p in enumerate(pages,1) if p.ready]
    if not ready: raise ValueError('没有完整标记的图片可导出')
    stage=Path(tempfile.mkdtemp(prefix='.veilpng-',dir=parent))
    report={'exported':0,'skipped':len(pages)-len(ready),'files':[],'sha256':{},'pixel_sha256':{},'color':color}
    try:
        total=sum(len(p.paths) for _,p in ready)
        for index,p in ready:
            for side,path in enumerate(p.paths):
                if cancelled and cancelled(): raise InterruptedError('已取消导出')
                name,clean=masked_output(p,index,side,color)
                data=image_to_png_bytes(clean)
                (stage/name).write_bytes(data)
                report['sha256'][name]=_sha256_bytes(data)
                report['pixel_sha256'][name]=_sha256_bytes(clean.tobytes())
                report['files'].append(name); report['exported']+=1
                if progress: progress(report['exported'],total)
        if cancelled and cancelled(): raise InterruptedError('已取消导出')
        (stage/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        # Unique final directory, including concurrent exporters.
        import uuid
        dest=parent/('VeilPNG_'+uuid.uuid4().hex[:12])
        stage.rename(dest)
        return dest,report
    finally:
        if stage.exists(): shutil.rmtree(stage)



def _pair_to_json(pair: RegistrationPair) -> dict:
    return {
        'pair_id': pair.pair_id,
        'source_image': pair.source_image,
        'target_image': pair.target_image,
        'source_size': list(pair.source_size),
        'target_size': list(pair.target_size),
        'matrix_source_to_target': [list(r) for r in pair.matrix_source_to_target],
        'confidence': pair.confidence,
    }



def _pair_from_json(data: dict) -> RegistrationPair:
    import numpy as np
    matrix=np.asarray(data['matrix_source_to_target'],dtype=np.float64)
    if matrix.shape!=(3,3) or not np.isfinite(matrix).all() or abs(np.linalg.det(matrix))<1e-10:
        raise ValueError('Invalid saved registration matrix')
    for key in ('source_size','target_size'):
        size=data[key]
        if len(size)!=2 or any(type(v) is not int or not 1<=v<=100000 for v in size):
            raise ValueError('Invalid saved registration dimensions')
    if not math.isfinite(float(data.get('confidence') or 0)):
        raise ValueError('Invalid registration confidence')
    return RegistrationPair(
        pair_id=data['pair_id'],
        source_image=data['source_image'],
        target_image=data['target_image'],
        source_size=tuple(int(x) for x in data['source_size']),
        target_size=tuple(int(x) for x in data['target_size']),
        matrix_source_to_target=tuple(tuple(float(v) for v in row) for row in data['matrix_source_to_target']),
        confidence=float(data.get('confidence') or 0),
    )



def workspace_summary(pages, *, mode=None) -> dict:
    return {
        'mode': mode,
        'pages': len(pages),
        'ready_pages': sum(p.ready for p in pages),
        'paired_pages': sum(1 for p in pages if p.pair),
        'masked_sides': sum(len(p.masks) for p in pages),
    }



def _inside(root, rel):
    if not isinstance(rel,str) or Path(rel).is_absolute() or "\\" in rel:
        raise ValueError('Invalid project asset path')
    path=(root/rel).resolve()
    if not path.is_relative_to(root): raise ValueError('Project asset escapes directory')
    return path


def _atomic(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.vp-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def _put_asset(root, rel, data):
    path=_inside(root,rel)
    if path.exists():
        if not path.is_file() or path.read_bytes()!=data: raise ValueError('Project asset conflict')
    else: _atomic(path,data)
    return rel


def _check_shape(pages,mode):
    if mode not in (0,1,2) or not pages or (mode==0 and len(pages)!=1):
        raise ValueError('Invalid workspace mode or page count')
    if any((len(p.paths)!=(2 if mode==2 else 1)) or bool(p.pair)!=(mode==2) for p in pages):
        raise ValueError('Invalid workspace page structure')


@contextmanager
def _workspace_lock(root):
    """Cooperative single-writer lock; a crash leaves an explicit stale lock."""
    root=Path(root).expanduser().resolve()
    root.mkdir(parents=True,exist_ok=True)
    lock=root/'.workspace-write.lock'
    try:
        fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError as exc:
        raise ValueError('Workspace is locked by another writer; check before removing stale lock') from exc
    try:
        with os.fdopen(fd,'w') as f: f.write(str(os.getpid()))
        yield root
    finally:
        lock.unlink(missing_ok=True)


def save_workspace_project(pages,mode,project_dir,**kwargs):
    with _workspace_lock(project_dir) as root:
        return _save_workspace_project(pages,mode,root,**kwargs)


def _save_workspace_project(pages, mode, project_dir, *, active_index=0, active_side=0, search_query='', portable=False, new=False, expected_revision=None):
    """Commit immutable assets before atomically replacing the manifest. Never delete old masks."""
    _check_shape(pages,mode)
    if not 0<=active_index<len(pages) or not 0<=active_side<len(pages[active_index].paths):
        raise ValueError('Invalid active workspace selection')
    project_dir=Path(project_dir).expanduser().resolve()
    mp=project_dir/WORKSPACE_MANIFEST
    if mp.is_symlink(): raise ValueError('Workspace manifest must not be a symlink')
    if project_dir.exists():
        if not project_dir.is_dir(): raise ValueError('Project must be a directory')
        if any(p.name != '.workspace-write.lock' for p in project_dir.iterdir()):
            if new or not mp.is_file(): raise ValueError('Use a new/empty project directory')
            prior=json.loads(mp.read_text(encoding='utf-8'))
            if prior.get('format') not in (WORKSPACE_FORMAT,LEGACY_FORMAT):
                raise ValueError('Not a VeilPNG workspace')
            portable=bool(portable or prior.get('portable',False))
    if expected_revision is not None and (not mp.is_file() or _sha256_path(mp)!=expected_revision):
        raise ValueError('Workspace revision conflict: reload before saving')
    project_dir.mkdir(parents=True,exist_ok=True)
    manifest={'format':WORKSPACE_FORMAT,'version':__version__,'mode':mode,'active_index':int(active_index),
              'active_side':int(active_side),'search_query':str(search_query),'portable':bool(portable),'pages':[]}
    for p in pages:
        entry={'label':p.label,'paths':[],'pair':_pair_to_json(p.pair) if p.pair else None,
               'fingerprints':{},'sizes':{},'masks':{},'history':[]}
        for side,path in enumerate(p.paths):
            img=p.read(side) # validates actual file + registered dimensions before commit
            raw=path.read_bytes();sha=_sha256_bytes(raw)
            if sha!=p.fingerprints[side]: raise ValueError('Source changed during save')
            entry['fingerprints'][str(side)]=sha;entry['sizes'][str(side)]=list(img.size)
            if portable:
                rel=f'assets/{sha}/{path.name}'
                entry['paths'].append(_put_asset(project_dir,rel,raw))
            else:
                rp=path.resolve()
                entry['paths'].append(rp.relative_to(project_dir).as_posix() if rp.is_relative_to(project_dir) else str(rp))
        def store(masks):
            refs={}
            for side,blob in masks.items():
                if side not in p.sizes: raise ValueError('Invalid mask side')
                with Image.open(io.BytesIO(blob)) as m:
                    binary_mask(m,p.sizes[side])
                sha=_sha256_bytes(blob)
                refs[str(side)]=_put_asset(project_dir,f'masks/{sha}.png',blob)
            return refs
        entry['masks']=store(p.masks)
        history=p.history or ([{'action':'baseline','side':0,'masks':dict(p.masks)}] if p.masks else [])
        if history and history[-1]['masks']!=p.masks: raise ValueError('History/final mask mismatch')
        for event in history:
            entry['history'].append({'action':event['action'],'side':event['side'],'masks':store(event['masks'])})
        manifest['pages'].append(entry)
    _atomic(mp,json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8'))
    return {'project_dir':str(project_dir),'portable':bool(portable),'revision':_sha256_path(mp),**workspace_summary(pages,mode=mode)}


def load_workspace_project(project_dir):
    project_dir=Path(project_dir).expanduser().resolve()
    manifest_path=project_dir/WORKSPACE_MANIFEST
    if not manifest_path.is_file(): raise ValueError('Missing workspace.json')
    if manifest_path.is_symlink(): raise ValueError('Workspace manifest must not be a symlink')
    manifest_bytes=manifest_path.read_bytes()
    manifest=json.loads(manifest_bytes)
    fmt=manifest.get('format')
    if fmt not in (WORKSPACE_FORMAT,LEGACY_FORMAT): raise ValueError('Unsupported workspace format')
    pages=[]
    for entry in manifest['pages']:
        pair=_pair_from_json(entry['pair']) if entry.get('pair') else None
        if manifest.get('portable') and any(Path(x).is_absolute() for x in entry['paths']):
            raise ValueError('Portable project cannot reference absolute paths')
        paths=tuple(Path(x).resolve() if Path(x).is_absolute() else _inside(project_dir,x) for x in entry['paths'])
        page=Page(entry['label'],paths,pair)
        page.fingerprints={int(k):str(v) for k,v in entry['fingerprints'].items()}
        page.sizes={int(k):tuple(int(x) for x in v) for k,v in entry['sizes'].items()}
        if set(page.fingerprints)!=set(range(len(paths))) or set(page.sizes)!=set(range(len(paths))):
            raise ValueError('Incomplete source metadata')
        for side in range(len(paths)): page.read(side)
        def read_masks(refs):
            masks={}
            for k,v in refs.items():
                i=int(k)
                if i not in page.sizes: raise ValueError('Invalid mask side')
                path=_inside(project_dir,v)
                blob=path.read_bytes()
                if fmt==WORKSPACE_FORMAT and path.stem!=_sha256_bytes(blob): raise ValueError('Mask hash mismatch')
                with Image.open(io.BytesIO(blob)) as m: binary_mask(m,page.sizes[i])
                masks[i]=blob
            return masks
        page.masks=read_masks(entry.get('masks',{}))
        for event in entry.get('history',[]):
            side=int(event['side'])
            if side not in page.sizes: raise ValueError('Invalid history side')
            page.history.append({'action':str(event['action']),'side':side,'masks':read_masks(event['masks'])})
        if not page.history and page.masks:
            page.history=[{'action':'legacy-baseline','side':0,'masks':dict(page.masks)}]
        if page.history and page.history[-1]['masks']!=page.masks: raise ValueError('History/final mask mismatch')
        pages.append(page)
    mode=int(manifest['mode']);_check_shape(pages,mode)
    active_index=int(manifest.get('active_index',0));active_side=int(manifest.get('active_side',0))
    if not 0<=active_index<len(pages) or not 0<=active_side<len(pages[active_index].paths):
        raise ValueError('Invalid active workspace selection')
    return {'project_dir':project_dir,'mode':mode,'active_index':int(manifest.get('active_index',0)),
            'active_side':int(manifest.get('active_side',0)),'search_query':str(manifest.get('search_query','')),
            'portable':bool(manifest.get('portable',False)),'revision':_sha256_bytes(manifest_bytes),'pages':pages}


def replay_workspace(state, parent, *, color="#000000", page=None):
    """Replay committed mask snapshots, including both mapped sides. No mouse simulation."""
    import copy
    pages=copy.deepcopy(state['pages']);steps=0
    for item in pages:
        expected=dict(item.masks);item.masks={}
        for event in item.history:
            item.masks=dict(event['masks']);steps+=1
        if item.masks!=expected: raise ValueError('Replay mismatch')
    selected=pages if page is None else [pages[resolve_page_selector(pages,page)]]
    dest,report=export_pages(selected,parent,color=color)
    return dest,{'replayed_commits':steps,**report}


def resolve_page_selector(pages, selector: str|int) -> int:
    if isinstance(selector, int):
        idx=selector-1
        if 0 <= idx < len(pages):
            return idx
        raise ValueError('页码超出范围')
    text=str(selector).strip()
    if text.startswith('index:'): return resolve_page_selector(pages,int(text[6:]))
    if text.startswith('id:'):
        hits=[i for i,p in enumerate(pages) if p.pair and p.pair.pair_id==text[3:]]
    else:
        hits=[i for i,p in enumerate(pages) if p.label==text or (p.pair and p.pair.pair_id==text)]
    if len(hits)==1: return hits[0]
    if len(hits)>1: raise ValueError('Ambiguous page; use index:N')
    if text.isdigit(): return resolve_page_selector(pages,int(text))
    raise ValueError(f'找不到页面：{selector}')



def apply_mask(page: Page, side: int, mask: Image.Image, *, operation='replace'):
    mask=binary_mask(mask, page.sizes.get(side) if side in page.sizes else page.read(side).size)
    current=page.get_mask(side)
    if operation=='replace':
        merged=mask
    elif operation=='union':
        merged=ImageChops.lighter(current, mask)
    elif operation=='subtract':
        merged=ImageChops.subtract(current, mask)
    else:
        raise ValueError('不支持的蒙版操作')
    page.update(side, merged, action=operation)
    return page



def apply_rect(page: Page, side: int, rect: tuple[int,int,int,int], *, operation='replace'):
    size=page.sizes.get(side) if side in page.sizes else page.read(side).size
    x0,y0,x1,y1=rect
    if not (0<=x0<=x1<size[0] and 0<=y0<=y1<size[1]): raise ValueError("Rectangle outside image")
    return apply_mask(page, side, rectangle_mask(size, [rect]), operation=operation)
