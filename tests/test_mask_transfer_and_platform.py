"""v0.4: exact pair geometry, rejection and headless cross-platform entrypoints."""
from __future__ import annotations

import csv
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image, ImageDraw

from veilpng.mask_transfer import RegistrationPair, load_pair, transfer_mask
from veilpng.platform_check import doctor


def _sample_pair():
    # Coordinates SOURCE(100x90) -> TARGET(200x180) with factor 2
    return RegistrationPair("0050", "images/source/CN0001.webp", "images/target/JP0001.jpeg",
                            (100, 90), (200,180),
                            ((2., 0., 0.), (0., 2., 0.), (0.,0.,1.)), 0.95)


def test_target_to_source_restores_matching_region():
    p = _sample_pair()
    jp_mask = Image.new("L", p.target_size)
    ImageDraw.Draw(jp_mask).rectangle((60, 40, 120, 110), fill=255)
    cn_mask = transfer_mask(jp_mask, p, from_space="target")
    assert cn_mask.size == p.source_size
    assert cn_mask.getpixel((45,35)) == 255
    assert cn_mask.getpixel((10,10)) == 0
    assert cn_mask.getbbox() == (30,20,61,56)


def test_source_to_target_transfer():
    p = _sample_pair()
    source = Image.new("L", p.source_size)
    ImageDraw.Draw(source).rectangle((20, 25, 40, 50), fill=255)
    target = transfer_mask(source, p, from_space="source")
    assert target.size == p.target_size
    assert target.getpixel((60,80)) == 255
    assert target.getpixel((20,20)) == 0


def test_expansion_only_adds_cover_and_is_reversible_geometry():
    p = _sample_pair()
    source = Image.new("L", p.source_size)
    ImageDraw.Draw(source).rectangle((20,20,40,40),fill=255)
    small = transfer_mask(source,p,from_space="source",expand_px=0)
    expanded = transfer_mask(source,p,from_space="source",expand_px=3)
    assert expanded.histogram()[255] > small.histogram()[255]
    assert np.all(np.asarray(expanded)>=np.asarray(small))


def test_reject_wrong_size_and_bad_matrix():
    p=_sample_pair()
    with pytest.raises(ValueError,match="dimensions"):
        transfer_mask(Image.new("L",(5,5)),p,from_space="target")
    with pytest.raises(ValueError,match="expand_px"):
        transfer_mask(Image.new("L",p.target_size),p,from_space="target",expand_px=51)
    broken=RegistrationPair("0","a","b",p.source_size,p.target_size,
                            ((0,0,0),(0,0,0),(0,0,0)),0)
    with pytest.raises(ValueError,match="Singular"):
        transfer_mask(Image.new("L",p.target_size),broken,from_space="target")


def test_load_pair_uses_exact_id_and_rejects_duplicates(tmp_path):
    csv_path=tmp_path/"pairs.csv"
    fields=["pair_id","source_image","target_image","source_width","source_height",
            "target_width","target_height","matrix_3x3_json","registration_confidence"]
    record={"pair_id":"0050","source_image":"images/source/CN0001.webp",
            "target_image":"images/target/JP0001.jpeg","source_width":"100","source_height":"90",
            "target_width":"200","target_height":"180","registration_confidence":"0.95",
            "matrix_3x3_json":json.dumps([[2,0,0],[0,2,0],[0,0,1]])}
    with csv_path.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fields);writer.writeheader();writer.writerow(record)
    assert load_pair(csv_path,"0050").source_size==(100,90)
    with pytest.raises(ValueError,match="found 0"):
        load_pair(csv_path,"0051")
    with csv_path.open('a',newline='',encoding='utf-8') as f:
        csv.DictWriter(f,fields).writerow(record)
    with pytest.raises(ValueError,match="found 2"):
        load_pair(csv_path,"0050")


def test_platform_doctor_and_cli_json():
    d=doctor()
    assert d["core_ready"]
    from veilpng import __version__
    assert d["app"]==f"VeilPNG v{__version__}"
    output=subprocess.check_output([sys.executable,"-m","veilpng","doctor"],text=True)
    assert json.loads(output)["core_ready"]
