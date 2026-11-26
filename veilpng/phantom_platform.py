"""Platform-oriented, OFFLINE exports and post-upload diagnostics for phantom PNGs.

No platform endpoints are called. A preset is a conservative packaging
preference, NOT a claim that QQ/WeChat/XHS retains transparency or a guarantee
of two-appearance rendering. Browser userscripts cannot change mobile apps.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image, ImageOps

from .phantom_tank import inspect_phantom, reveal_on_background, to_png_bytes
from .phantom_audit_html import offline_return_audit_html

PROFILES = ("qq", "wechat", "xhs")


@dataclass(frozen=True)
class PlatformPreset:
    id: str
    label: str
    max_long_side: int
    guidance: str
    guarantee: str = "未知：上传后须重新下载图片核验透明度；无法保证聊天缩略图与大图使用不同背景。"


PRESETS = {
    "qq": PlatformPreset("qq", "QQ 聊天/图片", 1600,
                        "先试原始透明 PNG，检查聊天缩略图、点开大图及下载的图片；手机/电脑版本分别验证。"),
    "wechat": PlatformPreset("wechat", "微信聊天/图片", 1280,
                             "尝试按图片发送并检查缩略图与大图；另用文件传输验证原始 PNG 是否保留，不代表聊天图可切换。"),
    "xhs": PlatformPreset("xhs", "小红书图文", 1080,
                          "图文普通发布存在转码/压平风险。无法保留 Alpha 时优先发布并排对比图，或视频而非声称幻影坦克可切换。"),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_phantom(path: str | Path) -> tuple[Image.Image, bytes]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with Image.open(path) as source:
        source.load()
        if source.format != "PNG":
            raise ValueError("Source must be a PNG with an Alpha channel")
        inspected = inspect_phantom(source)
    return inspected.image, path.read_bytes()


def _shrink_rgba(im: Image.Image, max_side: int) -> Image.Image:
    if not (128 <= max_side <= 8192):
        raise ValueError("max_long_side must be 128..8192")
    if max(im.size) <= max_side:
        return im.copy()
    size = (max(1, round(im.width*max_side/max(im.size))),
            max(1, round(im.height*max_side/max(im.size))))
    return im.resize(size, Image.Resampling.LANCZOS)


def _render_comparison(transparent: Image.Image, mode: str) -> Image.Image:
    white = reveal_on_background(transparent, (255,255,255))
    black = reveal_on_background(transparent, (0,0,0))
    from PIL import ImageDraw
    w,h = transparent.size
    # At most 3200px total width for accessible social-media fallback.
    max_side=1024
    if max(w,h) > max_side:
        ratio=max_side/max(w,h)
        w,h=max(1,round(w*ratio)),max(1,round(h*ratio))
        white=white.resize((w,h),Image.Resampling.LANCZOS)
        black=black.resize((w,h),Image.Resampling.LANCZOS)
    result=Image.new('RGB',(w*2+36,h+60),'#ffffff')
    result.paste(white,(12,45));result.paste(black,(w+24,45))
    draw=ImageDraw.Draw(result)
    draw.text((12,12),'WHITE background',fill='black')
    draw.text((w+24,12),'BLACK background',fill='black')
    return result


def _offline_preview_html(image_name: str) -> str:
    # Fixed filename; never put user-supplied strings into HTML tags.
    assert image_name == 'upload_alpha.png'
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>VeilPNG 平台预览</title>
<style>body{font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif;margin:0;padding:20px;background:#e6edf5;color:#243144}main{max-width:960px;margin:auto}button{padding:9px 18px;margin:4px;cursor:pointer}#stage{display:flex;min-height:340px;align-items:center;justify-content:center;border:1px solid #9aa7b5;border-radius:12px;background:white}img{max-width:100%;max-height:72vh;object-fit:contain}p{line-height:1.6}</style></head><body><main><h2>VeilPNG 平台兼容预览（纯本地）</h2><p>同一张 RGBA 图片切换背景。不能证明微信/QQ/小红书服务器保留透明度。</p><button data-bg="#ffffff">白底</button><button data-bg="#000000">黑底</button><button data-bg="#808080">灰底</button><div id="stage"><img src="upload_alpha.png" alt="透明幻影坦克"></div><p>请将上传后下载回的文件交给 VeilPNG 的“平台回收图验收”，检测 Alpha 是否被压平。</p></main><script>document.querySelectorAll('button[data-bg]').forEach(b=>b.addEventListener('click',()=>{document.getElementById('stage').style.background=b.dataset.bg}));</script></body></html>'''


def prepare_platform_package(input_png: str | Path, output_dir: str | Path,
                             platform: str, *, max_long_side: int | None = None) -> dict:
    if platform not in PRESETS:
        raise ValueError(f"platform must be one of {PROFILES}")
    src = Path(input_png).resolve()
    dst = Path(output_dir).resolve()
    if dst == src.parent:
        raise ValueError("Choose a separate output directory to avoid clobbering inputs")
    if dst == src or src.is_relative_to(dst):
        raise ValueError("Output directory must not contain input")
    size_limit = PRESETS[platform].max_long_side if max_long_side is None else max_long_side
    source, original_bytes = _read_phantom(src)
    prepared = _shrink_rgba(source,size_limit)
    if np.all(np.asarray(prepared.getchannel('A'))==255):
        raise ValueError("Resizing would remove meaningful Alpha: abort")
    result = inspect_phantom(prepared)
    dst.mkdir(parents=True, exist_ok=True)
    upload = dst/'upload_alpha.png'
    upload.write_bytes(to_png_bytes(prepared))
    # An explicit unmodified copy helps diagnose whether platform conversion was the culprit.
    (dst/'original_unmodified.png').write_bytes(original_bytes)
    result.white_preview.save(dst/'white_background_reference.jpg',format='JPEG',quality=94)
    result.black_preview.save(dst/'black_background_reference.jpg',format='JPEG',quality=94)
    _render_comparison(prepared,platform).save(dst/'fallback_side_by_side.jpg',format='JPEG',quality=94)
    (dst/'view_offline.html').write_text(_offline_preview_html('upload_alpha.png'),encoding='utf-8')
    (dst/'verify_return_offline.html').write_text(offline_return_audit_html(),encoding='utf-8')
    report={
        'platform':platform,
        'profile':asdict(PRESETS[platform]),
        'status':'LOCAL_CANDIDATE_NOT_PLATFORM_VERIFIED',
        'source_sha256':_sha(original_bytes),
        'source_size':list(source.size),
        'prepared_size':list(prepared.size),
        'upload_sha256':_sha(upload.read_bytes()),
        'alpha_min':result.report['alpha_min'],
        'alpha_max':result.report['alpha_max'],
        'mean_white_black_difference':result.report['mean_white_black_difference'],
        'files':{'candidate_png':upload.name,'original_png':'original_unmodified.png',
                 'white_preview':'white_background_reference.jpg','black_preview':'black_background_reference.jpg',
                 'fallback':'fallback_side_by_side.jpg','viewer':'view_offline.html',
                 'local_return_verifier':'verify_return_offline.html'},
        'verification_steps':[
            'Send upload_alpha.png as an ordinary image in the target application; preserve the file as PNG.',
            'Check thumbnail and expanded view on each intended receiver device; do not assume backgrounds differ.',
            'Download/save the actual delivered image from that application.',
            'Open verify_return_offline.html in Safari/Chrome or run veilpng phantom-platform-audit --original <upload_alpha.png> --returned <downloaded-image>.',
            'If Alpha was lost, publish fallback_side_by_side.jpg or a video; scripts cannot reconstruct lost pixels.'
        ]
    }
    (dst/'platform_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def audit_platform_return(original_png: str | Path, returned: str | Path) -> dict:
    original_path=Path(original_png)
    returned_path=Path(returned)
    orig, o_bytes = _read_phantom(original_path)
    r_bytes=returned_path.read_bytes()
    try:
        with Image.open(BytesIO(r_bytes)) as img:
            img.load()
            reported_format=img.format
            has_alpha = 'A' in img.getbands() or 'transparency' in img.info
            r=img.convert('RGBA')
    except Exception as exc:
        raise ValueError('Returned image is not a readable image') from exc
    alpha_orig=np.asarray(orig.getchannel('A'),dtype=np.float32)
    alpha_returned=np.asarray(r.getchannel('A'),dtype=np.float32)
    alpha_dynamic = bool(np.any(alpha_returned < 255))
    size_changed = r.size!=orig.size
    aspect_mismatch=abs(r.width/r.height-orig.width/orig.height)>0.02
    if size_changed:
        resized=orig.resize(r.size, Image.Resampling.LANCZOS)
    else:
        resized=orig
    alpha_resized=np.asarray(resized.getchannel('A'),dtype=np.float32)
    alpha_mae=float(np.mean(np.abs(alpha_resized-alpha_returned)))
    comp_error={}
    for key,bg in [('white',(255,255,255)),('black',(0,0,0))]:
        ref=np.asarray(reveal_on_background(resized,bg),dtype=np.int16)
        got=np.asarray(reveal_on_background(r,bg),dtype=np.int16)
        comp_error[key]=round(float(np.mean(np.abs(ref-got))),3)
    byte_equal=_sha(o_bytes)==_sha(r_bytes)
    if not has_alpha or not alpha_dynamic:
        verdict='ALPHA_LOST'
        reason='The returned image is fully opaque or its alpha channel is missing; two-background effect cannot be recovered from this version.'
    elif aspect_mismatch:
        verdict='GEOMETRY_CHANGED'
        reason='Alpha exists but image aspect ratio changed; viewer content may be cropped or distorted.'
    elif alpha_mae<=2 and comp_error['white']<=5 and comp_error['black']<=5:
        verdict='PRESERVED' if not size_changed else 'PRESERVED_RESIZED'
        reason='Measured alpha and both background renders are close; real client thumbnail/viewer backgrounds still require inspection.'
    else:
        verdict='DEGRADED'
        reason='Transparency remains, but render differences are significant. Do not claim correct platform presentation.'
    return {
        'verdict':verdict,'reason':reason,
        'original_size':list(orig.size),'returned_size':list(r.size),
        'returned_format':reported_format,'returned_has_alpha':has_alpha,
        'returned_nonopaque_pixels':int(np.count_nonzero(alpha_returned<255)),
        'original_nonopaque_pixels':int(np.count_nonzero(alpha_orig<255)),
        'alpha_mae':round(alpha_mae,3),
        'white_render_mae':comp_error['white'],'black_render_mae':comp_error['black'],
        'byte_identical':byte_equal,
        'app_native_preview_verified':False,
        'warning':'This tests a returned file, not app thumbnail/fullscreen render paths or other users’ devices.'
    }


def write_platform_audit_evidence(original_png: str | Path, returned: str | Path,
                                  output_dir: str | Path) -> dict:
    """Write local visual evidence for a platform-returned image.

    Outputs are derived previews and diagnostic results, never copied original
    files. No network requests or platform integrations are used.
    """
    original_png, returned = Path(original_png).resolve(), Path(returned).resolve()
    directory = Path(output_dir).resolve()
    if directory in (original_png, returned) or directory in (original_png.parent, returned.parent):
        raise ValueError('Choose a separate evidence directory, not the input folder')
    if directory.is_relative_to(original_png) or directory.is_relative_to(returned):
        raise ValueError('Evidence path cannot be inside an input file')
    if directory.exists() and any(directory.iterdir()):
        raise ValueError('Choose a new or empty evidence directory to prevent overwriting prior results')
    report = audit_platform_return(original_png, returned)
    orig, _ = _read_phantom(original_png)
    with Image.open(returned) as f:
        f.load()
        ret = f.convert('RGBA')
    # Compare at returned image geometry to match the numeric audit.
    aligned = orig.resize(ret.size, Image.Resampling.LANCZOS) if orig.size != ret.size else orig
    from PIL import ImageDraw
    preview_width=480
    scale=min(1.0,preview_width/max(aligned.size))
    pane_size=(max(1,round(aligned.width*scale)),max(1,round(aligned.height*scale)))
    panels=[]
    for bg in ((255,255,255),(0,0,0)):
        for im in (aligned,ret):
            v=reveal_on_background(im,bg)
            v.thumbnail(pane_size,Image.Resampling.LANCZOS)
            panels.append(v)
    pw=max(v.width for v in panels);ph=max(v.height for v in panels)
    spacing=16; head=44
    board=Image.new('RGB',(pw*2+spacing*3,(ph+head)*2+spacing*3),(240,246,252))
    dr=ImageDraw.Draw(board)
    labels=('原始·白底','返回·白底','原始·黑底','返回·黑底')
    for i,panel in enumerate(panels):
        row,col=divmod(i,2)
        x=spacing+(pw+spacing)*col;y=spacing+(ph+head+spacing)*row
        dr.rectangle((x,y,x+pw,y+head+ph),fill=(255,255,255))
        dr.text((x+12,y+12),labels[i],fill=(31,52,85))
        board.paste(panel,(x+(pw-panel.width)//2,y+head+(ph-panel.height)//2))
    before_alpha=np.asarray(aligned.getchannel('A'),dtype=np.int16)
    after_alpha=np.asarray(ret.getchannel('A'),dtype=np.int16)
    delta=np.abs(before_alpha-after_alpha).astype('uint8')
    # Red indicates large changes to alpha, black no change. Original source is
    # not encoded into heatmap; this is a diagnostic raster only.
    heat=np.zeros((*delta.shape,3),dtype=np.uint8)
    heat[...,0]=delta
    # Blue shows changes on fully transparent pixels too, to help diagnose
    # a flatten-to-white or flatten-to-black conversion.
    heat[...,2]=np.minimum(delta//3,85)
    directory.mkdir(parents=True,exist_ok=True)
    board.save(directory/'white_black_before_after.jpg',format='JPEG',quality=91)
    Image.fromarray(heat,'RGB').save(directory/'alpha_change_heatmap.png')
    (directory/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (directory/'verify_return_offline.html').write_text(offline_return_audit_html(),encoding='utf-8')
    (directory/'READ_ME.txt').write_text(
        'VeilPNG local platform-return evidence\n'
        'white_black_before_after.jpg: computed black/white background comparisons.\n'
        'alpha_change_heatmap.png: red = increased alpha difference; black = none.\n'
        'audit.json: numeric file-level verdict; NOT native-app viewing proof.\n'
        'verify_return_offline.html: select your two local images in Safari/Chrome.\n'
        'Original and returned image files are NOT copied into this folder.\n',encoding='utf-8')
    return {'verdict':report['verdict'],'evidence_dir':str(directory),'files':[
        'white_black_before_after.jpg','alpha_change_heatmap.png','audit.json',
        'verify_return_offline.html','READ_ME.txt']}
