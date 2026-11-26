import csv,json
from pathlib import Path
import pytest
import numpy as np
from PIL import Image,ImageDraw
from veilpng.simple_project import image_pages,pair_pages,export_pages
from veilpng.png_container import extract_private_chunk

def make_image(p,size=(120,160),color='white'):
    p.parent.mkdir(parents=True,exist_ok=True)
    im=Image.new('RGB',size,color); ImageDraw.Draw(im).rectangle((10,20,45,55),fill='#da872b'); im.save(p)
    return im

def mask(size,box=(8,18,49,59)):
    m=Image.new('L',size); ImageDraw.Draw(m).rectangle(box,fill=255); return m

def bundle(root):
    src=root/'source'/'001.png'; tgt=root/'target'/'001.png'; make_image(src); make_image(tgt,(240,320))
    fields=['pair_id','source_image','target_image','source_width','source_height','target_width','target_height','matrix_3x3_json','registration_confidence']
    with (root/'registration_pairs.csv').open('w',newline='') as f:
        w=csv.writer(f); w.writerow(fields);w.writerow(['001','001.png','001.png',120,160,240,320,json.dumps([[2,0,0],[0,2,0],[0,0,1]]),1])
    return root

def assert_export(original,out,m):
    with Image.open(out) as im:a=np.asarray(im.convert('RGBA'))
    b=np.asarray(original.convert('RGBA')); selected=np.asarray(m)>0
    assert np.array_equal(a[~selected],b[~selected]); assert np.all(a[selected,:3]==0); assert np.all(a[selected,3]==255)
    assert extract_private_chunk(out.read_bytes()) is None

def test_single_export(tmp_path):
    path=tmp_path/'one.png'; orig=make_image(path); p=image_pages([path])[0]; p.read(0); m=mask(orig.size);p.update(0,m)
    dest,report=export_pages([p],tmp_path); assert report['exported']==1; assert_export(orig,dest/report['files'][0],m)

def test_batch_order_skip_duplicate_names(tmp_path):
    paths=[tmp_path/'a'/'10.png',tmp_path/'b'/'2.png',tmp_path/'b'/'10.png']; [make_image(p) for p in paths]
    pages=image_pages(paths+paths[:1]); assert len(pages)==3
    for p in pages[:2]:p.update(0,mask(p.read(0).size))
    dest,r=export_pages(pages,tmp_path); assert r['exported']==2 and r['skipped']==1; assert len(set(r['files']))==2
    assert all(p.is_file() for p in paths)

def test_per_page_mask_retained(tmp_path):
    paths=[tmp_path/f'{n}.png' for n in (10,2)];[make_image(p) for p in paths]
    a,b=image_pages(paths);assert a.label=='2.png';m=mask(a.read(0).size);a.update(0,m);b.read(0)
    assert np.array_equal(np.asarray(a.get_mask(0)),np.asarray(m));assert not b.get_mask(0).getbbox()

def test_paired_sync_export(tmp_path):
    p=pair_pages(bundle(tmp_path/'pair'))[0]; images=[p.read(i) for i in range(2)];m=mask(images[0].size);p.update(0,m)
    assert p.ready; assert p.get_mask(1).getpixel((24,48))==255
    dest,r=export_pages([p],tmp_path);assert r['exported']==2;assert len(set(r['files']))==2
    for i,name in enumerate(r['files']):assert_export(images[i],dest/name,p.get_mask(i))

def test_reverse_pair_sync(tmp_path):
    p=pair_pages(bundle(tmp_path/'pair'))[0]; p.read(0);p.read(1);p.update(1,mask((240,320),(30,50,80,110)));assert p.get_mask(0).getpixel((25,35))==255
    p.update(1,Image.new('L',(240,320)));assert not p.ready;assert not p.get_mask(0).getbbox()

def test_changed_source_aborts_without_partial_folder(tmp_path):
    path=tmp_path/'one.png';make_image(path);p=image_pages([path])[0];p.update(0,mask(p.read(0).size));make_image(path,color='blue')
    with pytest.raises(ValueError,match='原图已变化'):export_pages([p],tmp_path)
    assert not list(tmp_path.glob('VeilPNG_*'));assert not list(tmp_path.glob('.veilpng-*'))

def test_cancel_no_partial(tmp_path):
    path=tmp_path/'one.png';make_image(path);p=image_pages([path])[0];p.update(0,mask(p.read(0).size))
    with pytest.raises(InterruptedError):export_pages([p],tmp_path,cancelled=lambda:True)
    assert not list(tmp_path.glob('.veilpng-*'))

def test_empty_no_export(tmp_path):
    path=tmp_path/'one.png';make_image(path)
    with pytest.raises(ValueError):export_pages(image_pages([path]),tmp_path)

def test_exports_never_overwrite(tmp_path):
    path=tmp_path/'one.png';make_image(path);p=image_pages([path])[0];p.update(0,mask(p.read(0).size));a,_=export_pages([p],tmp_path);b,_=export_pages([p],tmp_path);assert a!=b and a.exists() and b.exists()

def test_invalid_pair_dimensions(tmp_path):
    root=bundle(tmp_path/'pair');make_image(root/'target'/'001.png',(120,160));p=pair_pages(root)[0]
    with pytest.raises(ValueError,match='尺寸'):p.read(1)
