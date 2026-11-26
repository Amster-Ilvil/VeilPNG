"""Local Gemini return restoration. Never modifies input or private source."""
from __future__ import annotations
import numpy as np
from PIL import Image, ImageFilter
from .imaging import binary_mask, load_image, image_to_png_bytes


def restore_boundary(original, returned, mask, *, max_halo=16, feather=8, exact=False):
    """Aligned RGBA inputs; exact core and bounded, smoothly tapered exterior.

    A mask-edge mismatch activates a conservative full guard; the farthest
    elevated ring extends it. No pixel outside max_halo+feather can change.
    """
    if original.size != returned.size or original.size != mask.size:
        raise ValueError('Aligned image and mask sizes must match')
    if not 2 <= max_halo <= 24 or not 1 <= feather <= 12:
        raise ValueError('Invalid halo/feather')
    a=np.asarray(original.convert('RGBA')); b=np.asarray(returned.convert('RGBA'))
    m=np.asarray(binary_mask(mask, original.size))>0
    if not m.any() or m.all(): raise ValueError('Mask must leave visible context')
    out=b.copy(); out[m]=a[m]
    if exact: return Image.fromarray(out), {'core_pixels':int(m.sum()),'halo_px':0,'feather_px':0,'exterior_changed':0}
    # Restrict work to a cropped union bounding box plus maximum support.
    radius=max_halo+feather
    l,t,r,bt=binary_mask(mask,original.size).getbbox(); w,h=original.size
    l=max(0,l-radius);t=max(0,t-radius);r=min(w,r+radius);bt=min(h,bt+radius)
    aa=a[t:bt,l:r];bb=b[t:bt,l:r];mm=m[t:bt,l:r]
    diff=np.max(np.abs(aa[:,:,:3].astype(np.int16)-bb[:,:,:3].astype(np.int16)),axis=2)
    dist=np.full(mm.shape,radius+1,np.uint8);dist[mm]=0
    prev=mm.copy()
    for d in range(1,radius+1):
        p=np.pad(prev,1); hh,ww=prev.shape
        nxt=np.logical_or.reduce([p[y:y+hh,x:x+ww] for y in range(3) for x in range(3)])
        dist[nxt & ~prev]=d;prev=nxt
    baseline=diff[(dist>max_halo)&(dist<=radius)]
    noise=float(np.partition(baseline,baseline.size//2)[baseline.size//2]) if baseline.size else 0.
    threshold=max(8.,noise+6.)
    rates=[]
    for d in range(1,max_halo+1):
        q=diff[dist==d];rates.append(float(np.mean(q>=threshold)) if q.size else 0.)
    # At least 3% of a ring must differ; activate only near the actual mask.
    active=noise>=8 or any(v>=.03 for v in rates[:4]); guard=0
    if active:
        guard=max(4,max((i+1 for i,v in enumerate(rates) if v>=.03),default=0))
        z=np.clip((dist.astype(np.float32)-guard)/feather,0,1)
        weight=1-z*z*(3-2*z);weight[mm]=1
        patch=np.floor(aa*weight[:,:,None]+bb*(1-weight[:,:,None])+.5).astype(np.uint8)
        out[t:bt,l:r]=patch
    changed=np.any(out!=b,axis=2)&~m
    return Image.fromarray(out),{'core_pixels':int(m.sum()),'halo_px':guard,'feather_px':feather if active else 0,'exterior_changed':int(changed.sum()),'context_noise':noise,'review_required':bool(active and guard==max_halo)}


def restore_return(original, returned, mask, *, shade='#000000', exact=False):
    """Return in Gemini's coordinate space. Reject uncertain geometric matches."""
    original=original.convert('RGBA');returned=returned.convert('RGBA')
    mask=binary_mask(mask,original.size)
    if not mask.getbbox():raise ValueError('No mask')
    from .imaging import render_preview
    from .smart_edit import align_gpt_image
    size=returned.size
    if size[0]*size[1]>12000000:raise ValueError('Returned image too large')
    # Same geometry is accepted only if visible context matches well enough.
    source=original.resize(size,Image.Resampling.LANCZOS) if original.size!=size else original
    projected=mask.resize(size,Image.Resampling.NEAREST)
    ref=render_preview(source,projected,solid_color=shade)
    a=np.asarray(ref.convert('RGB'),dtype=np.int16);b=np.asarray(returned.convert('RGB'),dtype=np.int16)
    stable=np.asarray(projected.filter(ImageFilter.MaxFilter(33)))==0
    if stable.sum()<64:raise ValueError('Insufficient visible context')
    errors=np.max(np.abs(a-b),axis=2)[stable];med=float(np.median(errors)); inlier=float(np.mean(errors<=24))
    geometry='same-grid' if original.size==size else 'resize-verified'
    texture=np.zeros(stable.shape,bool);texture[1:,:] |= np.max(np.abs(a[1:]-a[:-1]),axis=2)>22;texture[:,1:] |= np.max(np.abs(a[:,1:]-a[:,:-1]),axis=2)>22
    textured=stable & texture; texture_agreement=float(np.mean(np.max(np.abs(a-b),axis=2)[textured]<=24)) if textured.sum()>=20 else None
    if inlier<.80 or med>8 or (texture_agreement is not None and texture_agreement<.70):
        # Register the original public preview onto the returned image. Only
        # the estimated matrix is reused for private source and its mask.
        import cv2
        _,valid,stats=align_gpt_image(returned,ref,projected,Image.new('L',size),method='auto')
        mat=np.asarray(stats['alignment_affine'],np.float32)
        source=Image.fromarray(cv2.warpAffine(np.asarray(source),mat,size,flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE))
        projected=Image.fromarray(cv2.warpAffine(np.asarray(projected),mat,size,flags=cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT))
        geometry='registered'
    result,report=restore_boundary(source,returned,projected,exact=exact)
    report.update({'geometry':geometry,'size':list(size),'visible_median_before':med,'visible_inlier_before':inlier,'texture_agreement_before':texture_agreement})
    return result,report
