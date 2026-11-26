"""Independent Alpha-based 'phantom tank' effect (NOT encryption).

One RGBA PNG can have different appearances on white and black viewing
backgrounds. This module contains no source code from referenced repositories.

For opaque backgrounds W=(255,255,255) and B=(0,0,0), a pixel displays as:
  appearance_black = alpha * RGB
  appearance_white = alpha * RGB + (1-alpha) * 255
A single alpha value is shared by R/G/B. Two arbitrary full-colour images
cannot in general be independently reconstructed without some approximation.
"""
from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

MAX_PIXELS = 24_000_000
MODES = ("grayscale", "color")
FITS = ("cover", "contain", "stretch")


@dataclass(frozen=True)
class PhantomOptions:
    mode: str = "grayscale"
    fit: str = "cover"
    white_base: int = 190
    white_gain: float = .22
    black_gain: float = .24

    def validate(self):
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if self.fit not in FITS:
            raise ValueError(f"fit must be one of {FITS}")
        if not (150 <= self.white_base <= 235):
            raise ValueError("white_base must be 150..235")
        if not (.05 <= self.white_gain <= .40):
            raise ValueError("white_gain must be 0.05..0.40")
        if not (.05 <= self.black_gain <= .45):
            raise ValueError("black_gain must be 0.05..0.45")
        # Preserve the light/dark ordering needed for the grayscale solution.
        if self.white_base <= 255 * self.black_gain:
            raise ValueError("white_base must exceed black image peak brightness")


@dataclass
class PhantomResult:
    image: Image.Image
    white_preview: Image.Image
    black_preview: Image.Image
    gray_preview: Image.Image
    report: dict


def _as_rgba(image: Image.Image) -> Image.Image:
    # Animated formats are not accepted. Frames would create ambiguous results.
    if getattr(image, "n_frames", 1) != 1:
        raise ValueError("Only static images are supported")
    if image.width < 1 or image.height < 1 or image.width * image.height > MAX_PIXELS:
        raise ValueError(f"Image must contain 1..{MAX_PIXELS} pixels")
    image = ImageOps.exif_transpose(image)
    return image.convert("RGBA")


def _fit_image(image: Image.Image, size: tuple[int, int], fit: str,
               fill: tuple[int, int, int]) -> Image.Image:
    img = _as_rgba(image)
    if fit == "cover":
        img = ImageOps.fit(img, size, method=Image.Resampling.LANCZOS, centering=(.5, .5))
    elif fit == "contain":
        img = ImageOps.contain(img, size, method=Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", size, (*fill, 255))
        canvas.alpha_composite(img, ((size[0]-img.width)//2, (size[1]-img.height)//2))
        img = canvas
    else:
        img = img.resize(size, Image.Resampling.LANCZOS)
    # Flatten any source alpha before encoding; phantom alpha is derived fresh.
    bg = Image.new("RGBA", size, (*fill, 255))
    bg.alpha_composite(img)
    return bg.convert("RGB")


def reveal_on_background(image: Image.Image, background: tuple[int, int, int]) -> Image.Image:
    """Simulate normal image viewers' alpha compositing on a solid background."""
    rgba = _as_rgba(image)
    base = Image.new("RGBA", rgba.size, (*background, 255))
    base.alpha_composite(rgba)
    return base.convert("RGB")


def _metrics(appearance: np.ndarray, target: np.ndarray) -> dict:
    error = appearance.astype(np.float64) - target.astype(np.float64)
    return {"mae": round(float(np.mean(np.abs(error))), 4),
            "rmse": round(float(np.sqrt(np.mean(error*error))), 4)}


def create_phantom(surface: Image.Image, hidden: Image.Image,
                   options: PhantomOptions | None = None) -> PhantomResult:
    """Make one transparent PNG with distinct appearances on white and black.

    The WHITE-background image is the surface; the BLACK-background image is the
    hidden one. Each target is intentionally contrast-compressed to make two
    distinguishable pictures physically achievable with an RGBA pixel.
    """
    options = options or PhantomOptions()
    options.validate()
    size = ImageOps.exif_transpose(surface).size
    if size[0] < 1 or size[1] < 1 or size[0]*size[1] > MAX_PIXELS:
        raise ValueError("Invalid surface image size")
    s = np.asarray(_fit_image(surface, size, options.fit, (255,255,255)), dtype=np.float32)
    h = np.asarray(_fit_image(hidden, size, options.fit, (0,0,0)), dtype=np.float32)
    if options.mode == "grayscale":
        # Use Pillow's standard luminance coefficients, not a simple RGB mean.
        sw = (s[...,0]*.299 + s[...,1]*.587 + s[...,2]*.114)
        hb = (h[...,0]*.299 + h[...,1]*.587 + h[...,2]*.114)
        white = np.clip(options.white_base + options.white_gain*sw, 0, 255)
        black = np.clip(options.black_gain*hb, 0, 255)
        # Exact solution before PNG 8-bit quantization.
        a = np.clip((255.0-white+black)/255.0, 0, 1)
        rgb = np.divide(black, a, out=np.zeros_like(black), where=a>1e-8)
        rgb = np.clip(rgb, 0, 255)
        rgba = np.dstack((rgb, rgb, rgb, a*255.0))
        expected_white = np.repeat(white[...,None],3,axis=2)
        expected_black = np.repeat(black[...,None],3,axis=2)
    else:
        # Colour is a least-squares fit since R/G/B need different alpha
        # for arbitrary image pairs. A single per-pixel alpha is mandatory.
        white = np.clip(options.white_base + options.white_gain*s, 0, 255)
        black = np.clip(options.black_gain*h, 0, 255)
        a = np.clip(1.0 - np.mean(white-black, axis=2)/255.0, 1/255.0, 1.0)
        lower = np.maximum(black.max(axis=2)/255.0, (255.0-white).max(axis=2)/255.0)
        a = np.maximum(a, lower)
        a = np.clip(a, 1/255.0, 1.0)
        rgb = np.clip((black + white - (255.0*(1-a))[...,None])/(2*a[...,None]), 0, 255)
        rgba = np.dstack((rgb, a*255.0))
        expected_white = white
        expected_black = black

    image = Image.fromarray(np.rint(np.clip(rgba,0,255)).astype('uint8'), 'RGBA')
    white_preview = reveal_on_background(image, (255,255,255))
    black_preview = reveal_on_background(image, (0,0,0))
    gray_preview = reveal_on_background(image, (128,128,128))
    alpha = np.asarray(image.getchannel('A'), dtype=np.uint8)
    result_white = np.asarray(white_preview, dtype=np.uint8)
    result_black = np.asarray(black_preview, dtype=np.uint8)
    report = {
        'type': 'phantom_tank_rgba_not_encrypted',
        'size': list(size),
        'options': asdict(options),
        'alpha_min': int(alpha.min()), 'alpha_max': int(alpha.max()),
        'alpha_mean': round(float(alpha.mean()), 3),
        'transparent_or_partial_percent': round(float(np.mean(alpha < 255))*100, 3),
        'white_target_error': _metrics(result_white, expected_white),
        'black_target_error': _metrics(result_black, expected_black),
        'mean_white_black_difference': round(float(np.abs(result_white.astype(np.int16)-result_black.astype(np.int16)).mean()), 3),
        'note': 'Visual Alpha effect only; not encryption. 8-bit export introduces rounding; arbitrary color pairs only approximate.',
    }
    return PhantomResult(image, white_preview, black_preview, gray_preview, report)


def inspect_phantom(image: Image.Image) -> PhantomResult:
    """Open and inspect any static image with genuine RGBA transparency."""
    rgba = _as_rgba(image)
    if "A" not in image.getbands():
        raise ValueError('An alpha channel is required for a phantom-tank PNG')
    alpha = np.asarray(rgba.getchannel('A'))
    if np.all(alpha == 255):
        raise ValueError('All pixels are opaque; no background-dependent reveal exists')
    white = reveal_on_background(rgba, (255,255,255))
    black = reveal_on_background(rgba, (0,0,0))
    gray = reveal_on_background(rgba, (128,128,128))
    report = {"type":"phantom_tank_inspection", "size":list(rgba.size),
              "alpha_min":int(alpha.min()), "alpha_max":int(alpha.max()),
              "alpha_mean":round(float(alpha.mean()),3),
              "partial_alpha_percent":round(float(np.mean((alpha>0)&(alpha<255))*100),3),
              "mean_white_black_difference":round(float(np.mean(np.abs(np.asarray(white,dtype=np.int16)-np.asarray(black,dtype=np.int16)))),3)}
    return PhantomResult(rgba, white, black, gray, report)


def to_png_bytes(image: Image.Image) -> bytes:
    out=BytesIO()
    image.save(out,format='PNG')
    return out.getvalue()


def make_comparison(white: Image.Image, black: Image.Image) -> Image.Image:
    w,h=white.size
    if black.size != (w,h):
        raise ValueError('Preview sizes differ')
    canvas = Image.new('RGB',(w*2,h),'white')
    canvas.paste(white, (0,0))
    canvas.paste(black, (w,0))
    return canvas


def write_preview_assets(result: PhantomResult, png_path: str | Path,
                         directory: str | Path, *, include_html: bool = True) -> dict:
    """Write public preview assets; no originals, private files or base64 embeddings."""
    png_path = Path(png_path)
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    if png_path.resolve() in [directory.joinpath(n).resolve() for n in
            ('preview_white.png','preview_black.png','preview_gray.png','comparison.png','report.json','preview.html')]:
        raise ValueError('Output PNG must not overwrite a preview asset')
    result.white_preview.save(directory/'preview_white.png')
    result.black_preview.save(directory/'preview_black.png')
    result.gray_preview.save(directory/'preview_gray.png')
    make_comparison(result.white_preview,result.black_preview).save(directory/'comparison.png')
    (directory/'report.json').write_text(json.dumps(result.report,ensure_ascii=False,indent=2),encoding='utf-8')
    if include_html:
        # Use a filename relative to the preview directory. If the PNG is
        # outside, put a safe copy alongside, avoiding external asset links.
        png_dest=directory/'phantom.png'
        if png_dest.resolve()!=png_path.resolve():
            png_dest.write_bytes(png_path.read_bytes())
        (directory/'preview.html').write_text('''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>幻影坦克背景切换预览</title>
<style>body{font-family:system-ui;background:#f3f6fb;color:#202b39;text-align:center;margin:2rem}
.preview{height:min(72vh,800px);max-width:min(90vw,800px);margin:1rem auto;display:flex;align-items:center;justify-content:center;background:#fff;border:1px solid #9caab7;border-radius:12px;overflow:hidden}
.preview img{max-width:100%;max-height:100%;object-fit:contain}button{padding:.6rem 1.2rem;margin:.3rem;cursor:pointer}</style></head><body>
<h2>VeilPNG · 幻影坦克</h2><p>同一张透明 PNG；点击按钮仅切换背景颜色。</p>
<button onclick="setBg('white')">白底 · 表图</button><button onclick="setBg('#808080')">灰底</button><button onclick="setBg('black')">黑底 · 里图</button>
<div id="stage" class="preview"><img src="phantom.png" alt="透明幻影坦克 PNG"></div>
<p>此效果不是加密；压平、JPEG 转换或不支持 Alpha 的查看器可能失效。</p>
<script>function setBg(c){document.getElementById('stage').style.background=c;}</script></body></html>''',encoding='utf-8')
    return {'png':str(png_path),'preview_directory':str(directory)}
