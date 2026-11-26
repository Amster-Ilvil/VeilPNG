from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw

from veilpng.manga_mode import create_manga_project, resolve_manga_project


def _save(img: Image.Image, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def _pair_csv(path: Path, src_name: str, tgt_name: str, src_size: tuple[int,int], tgt_size: tuple[int,int]):
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['pair_id','source_image','target_image','source_width','source_height','target_width','target_height','matrix_3x3_json','registration_confidence'])
        w.writeheader()
        w.writerow({
            'pair_id':'T001','source_image':src_name,'target_image':tgt_name,
            'source_width':src_size[0],'source_height':src_size[1],
            'target_width':tgt_size[0],'target_height':tgt_size[1],
            'matrix_3x3_json':'[[2,0,0],[0,2,0],[0,0,1]]',
            'registration_confidence':'0.99',
        })


def test_manga_project_roundtrip(tmp_path: Path):
    src = Image.new('RGB', (128, 96), 'white')
    ImageDraw.Draw(src).rectangle((5,5,20,20), fill='red')
    tgt = src.resize((256, 192), Image.Resampling.NEAREST)
    src_path = tmp_path/'CN0001.png'; _save(src, src_path)
    tgt_path = tmp_path/'JP0001.png'; _save(tgt, tgt_path)

    mask = Image.new('L', src.size, 0)
    ImageDraw.Draw(mask).rectangle((25, 10, 55, 40), fill=255)
    mask_path = tmp_path/'mask.png'; _save(mask, mask_path)

    roi = Image.new('L', src.size, 0)
    ImageDraw.Draw(roi).rectangle((4, 30, 22, 50), fill=255)
    roi_path = tmp_path/'roi.png'; _save(roi, roi_path)

    pairs = tmp_path/'pairs.csv'
    _pair_csv(pairs, src_path.name, tgt_path.name, src.size, tgt.size)

    manifest = create_manga_project(output_dir=tmp_path/'project', pairs_csv=pairs, pair_id='T001',
                                   source_image=src_path, target_image=tgt_path, mask=mask_path,
                                   mask_space='source', password='pw123456', roi_mask=roi_path,
                                   solid_color='#000000')
    assert manifest['pair_id'] == 'T001'
    assert Path(manifest['source']['container']).exists()
    assert Path(manifest['target']['public_preview']).exists()

    # Simulate an AI returning the public preview with a localized black text box inside ROI.
    public_src = Image.open(manifest['source']['public_preview']).convert('RGBA')
    d = ImageDraw.Draw(public_src)
    d.rectangle((8, 34, 18, 44), fill=(0,0,0,255))
    ai_src = tmp_path/'ai_src.png'; _save(public_src, ai_src)

    summary = resolve_manga_project(project_dir=tmp_path/'project', password='pw123456',
                                    source_ai_preview=ai_src, mode='A2', extraction='monochrome',
                                    alignment='resize', edge_guard_px=0, threshold=20)
    src_result = summary['results']['source']
    assert src_result['status'] == 'processed'
    assert Path(src_result['resolved_container']).exists()
    assert Path(src_result['decrypted_output']).exists()
    out = Image.open(src_result['decrypted_output']).convert('RGBA')
    # concealed region should have been restored (not black preview rectangle)
    assert out.size == src.size
    assert out.getpixel((30,20))[:3] == (255,255,255)
    # AI text box inside ROI should exist after A2 merge
    assert out.getpixel((10,36))[:3] == (0,0,0)


def test_manga_a2_without_green_roi_refuses_unrestricted_copy(tmp_path: Path):
    src = Image.new('RGB', (128,96), '#FAFAFA')
    tgt = src.resize((256,192), Image.Resampling.NEAREST)
    sp=tmp_path/'CN0001.png'; tp=tmp_path/'JP0001.png'
    _save(src,sp); _save(tgt,tp)
    pairs=tmp_path/'pairs.csv'
    _pair_csv(pairs,sp.name,tp.name,src.size,tgt.size)
    m=Image.new('L',src.size,0)
    ImageDraw.Draw(m).rectangle((10,10,35,45),fill=255)
    mp=tmp_path/'mask.png';_save(m,mp)
    manifest=create_manga_project(output_dir=tmp_path/'p',pairs_csv=pairs,pair_id='T001',
        source_image=sp,target_image=tp,mask=mp,mask_space='source',password='pw123456',solid_color='#000000')
    import pytest
    with pytest.raises(ValueError,match='requires an explicit green ROI'):
        resolve_manga_project(project_dir=tmp_path/'p',password='pw123456',
            source_ai_preview=manifest['source']['public_preview'],mode='A2')
