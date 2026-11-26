import hashlib,json,shutil,subprocess,sys,os
from pathlib import Path
import numpy as np
import pytest
from PIL import Image,ImageDraw
from veilpng.simple_project import (image_pages,pair_pages,apply_rect,save_workspace_project,load_workspace_project,export_pages,replay_workspace,resolve_page_selector)
from veilpng.translation_project import save_translation_project,render_translation_project,export_translation_project
from veilpng.translation_core import align_translation_images,render_translation

ROOT=Path(__file__).resolve().parents[1]
def call(*args):
    return json.loads(subprocess.check_output([sys.executable,'-m','veilpng',*map(str,args)],cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT)},text=True))
def img(path,size=(120,160),color='white'):
    path.parent.mkdir(parents=True,exist_ok=True)
    m=Image.new('RGB',size,color); d=ImageDraw.Draw(m);d.rectangle((10,10,60,60),fill='orange');d.ellipse((70,80,100,130),fill='blue');m.save(path);return m

def test_portable_replay_subprocess(tmp_path):
    f=tmp_path/'source'/'page.png';img(f)
    project=tmp_path/'project';call('workspace-init','--single',f,'--project-dir',project)
    for operation,rect in [('replace',(10,10,60,60)),('union',(70,80,100,130)),('subtract',(15,15,20,20))]:
        call('workspace-apply-mask','--project-dir',project,'--page',1,'--rect',*rect,'--operation',operation)
    dest=tmp_path/'out';dest.mkdir()
    first=call('workspace-export','--project-dir',project,'--output-dir',dest)
    portable=tmp_path/'portable';call('workspace-pack','--project-dir',project,'--output-dir',portable)
    shutil.rmtree(f.parent);shutil.rmtree(project);moved=tmp_path/'moved';portable.rename(moved)
    second=call('workspace-replay','--project-dir',moved,'--output-dir',dest)
    assert second['replayed_commits']==3
    assert first['sha256']==second['sha256'] and first['pixel_sha256']==second['pixel_sha256']
    assert (Path(first['output_dir'])/first['files'][0]).read_bytes()==(Path(second['output_dir'])/second['files'][0]).read_bytes()

def test_saved_pair_replay_both_sides(tmp_path):
    src=tmp_path/'bundle/source/001.png';tgt=tmp_path/'bundle/target/001.png';img(src);img(tgt,(240,320))
    (tmp_path/'bundle/registration_pairs.csv').write_text('pair_id,source_image,target_image,source_width,source_height,target_width,target_height,matrix_3x3_json,registration_confidence\n17,001.png,001.png,120,160,240,320,"[[2,0,0],[0,2,0],[0,0,1]]",1\n')
    pages=pair_pages(tmp_path/'bundle');p=pages[0]
    apply_rect(p,0,(10,10,25,30));apply_rect(p,1,(80,90,100,110),operation='union')
    assert resolve_page_selector(pages,'id:17')==0 and resolve_page_selector(pages,'17')==0
    a,ra=export_pages(pages,tmp_path);save_workspace_project(pages,2,tmp_path/'project',portable=True)
    state=load_workspace_project(tmp_path/'project');b,rb=replay_workspace(state,tmp_path)
    assert rb['replayed_commits']==2 and ra['sha256']==rb['sha256'] and len(rb['files'])==2

def test_atomic_save_keeps_old_manifest(tmp_path):
    p=tmp_path/'x.png';img(p);pages=image_pages([p]);apply_rect(pages[0],0,(10,10,20,20));project=tmp_path/'proj';save_workspace_project(pages,0,project)
    prev=(project/'workspace.json').read_bytes();img(p,color='red')
    with pytest.raises(ValueError):save_workspace_project(pages,0,project)
    assert (project/'workspace.json').read_bytes()==prev

def test_hash_and_path_rejection(tmp_path):
    f=tmp_path/'x.png';img(f);pages=image_pages([f]);apply_rect(pages[0],0,(10,10,20,20));project=tmp_path/'proj';save_workspace_project(pages,0,project)
    m=project/'workspace.json';cfg=json.loads(m.read_text());mask=project/cfg['pages'][0]['masks']['0'];mask.write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='hash mismatch'):load_workspace_project(project)
    cfg['pages'][0]['masks']['0']='../x.png';m.write_text(json.dumps(cfg))
    with pytest.raises(ValueError,match='escapes'):load_workspace_project(project)

def test_project_does_not_delete_unrelated_files(tmp_path):
    f=tmp_path/'x.png';img(f);project=tmp_path/'existing';project.mkdir();(project/'note.txt').write_text('keep')
    with pytest.raises(ValueError):save_workspace_project(image_pages([f]),0,project)
    assert (project/'note.txt').read_text()=='keep'

def test_translation_recipe_matches_core_and_cli(tmp_path):
    j=tmp_path/'jp.png'; g=tmp_path/'edited.png';base=img(j);edited=base.copy();ImageDraw.Draw(edited).rectangle((72,20,104,40),fill='red');edited.save(g)
    masks={k:Image.new('L',base.size,0) for k in ('translation','erase','protect')};ImageDraw.Draw(masks['translation']).rectangle((68,16,108,44),fill=255)
    aligned=align_translation_images(japanese=j,gemini=g,matrix_jp_to_gemini=np.eye(3))
    expected=render_translation(aligned=aligned,translation_mask=masks['translation'],erase_japanese_mask=masks['erase'],protect_mask=masks['protect'],feather_px=2)
    project=tmp_path/'project';save_translation_project(project,japanese=j,gemini=g,clean_base=None,matrix=np.eye(3),masks=masks,transfer='patch',feather=2)
    out=tmp_path/'final.png';report=call('translation-project-render','--project-dir',project,'--output',out)
    with Image.open(out) as im:assert np.array_equal(np.asarray(im),np.asarray(expected.image))
    assert report['recipe_hashes_verified'] and report['output_sha256']==hashlib.sha256(out.read_bytes()).hexdigest()
    with pytest.raises(ValueError):export_translation_project(project,j)
    img(g,color='black')
    with pytest.raises(ValueError,match='Source hash mismatch'):render_translation_project(project)
