import numpy as np
import pytest
from PIL import Image,ImageDraw,ImageFilter
from veilpng.return_restore import restore_boundary, restore_return
from veilpng.imaging import rectangle_mask

@pytest.mark.parametrize('shade,width',[(0,5),(255,9),(0,12)])
def test_halo_and_exact(shade,width):
    y,x=np.indices((160,180));a=np.stack([80+x%100,90+y%110,110+(x+y)%90,np.full_like(x,255)],axis=2).astype('uint8')
    m=rectangle_mask((180,160),[(50,42,130,110)]);mask=np.asarray(m)>0
    cover=m.filter(ImageFilter.MaxFilter(2*width+1));b=np.array(Image.composite(Image.new('RGBA',m.size,(shade,shade,shade,255)),Image.fromarray(a),cover));b[5,5]=[23,43,63,255]
    r,stats=restore_boundary(Image.fromarray(a),Image.fromarray(b),m);o=np.asarray(r);assert stats['halo_px']>=width;assert np.array_equal(o[np.asarray(cover)>0],a[np.asarray(cover)>0]);assert np.array_equal(o[5,5],b[5,5]);assert np.array_equal(o[mask],a[mask])
    e,_=restore_boundary(Image.fromarray(a),Image.fromarray(b),m,exact=True);assert np.array_equal(np.asarray(e)[~mask],b[~mask])

def test_touching_edge_and_brush():
    a=Image.new('RGBA',(140,150),'#98acbb');m=Image.new('L',a.size);d=ImageDraw.Draw(m);d.ellipse((-20,20,70,130),fill=255);d.rectangle((90,80,120,120),fill=255)
    b=Image.composite(Image.new('RGBA',a.size,'black'),a,m.filter(ImageFilter.MaxFilter(15)));r,_=restore_boundary(a,b,m);assert r.tobytes()==a.tobytes()

def test_no_halo_and_empty_mask():
    a=Image.new('RGBA',(100,100),'white');m=rectangle_mask(a.size,[(25,25,75,75)]);b=Image.composite(Image.new('RGBA',a.size,'black'),a,m);r,stats=restore_return(a,b,m);assert r.tobytes()==a.tobytes();assert stats['halo_px']==0
    with pytest.raises(ValueError):restore_boundary(a,b,Image.new('L',a.size))
