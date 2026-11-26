import json,subprocess,sys,os
from pathlib import Path
import pytest
from PIL import Image,ImageDraw
from veilpng.simple_project import (image_pages,apply_rect,save_workspace_project,load_workspace_project,export_pages)
from veilpng.workspace_verify import verify_workspace_export

ROOT=Path(__file__).resolve().parents[1]

def fixture(tmp_path):
    src=tmp_path/'page.png'; im=Image.new('RGB',(80,100),'white');ImageDraw.Draw(im).ellipse((15,15,50,60),fill='blue');im.save(src)
    pages=image_pages([src]);apply_rect(pages[0],0,(12,12,54,64));project=tmp_path/'project';save_workspace_project(pages,0,project)
    return project,pages

def test_verify_exact_and_tampered_report(tmp_path):
    project,pages=fixture(tmp_path);dest,r=export_pages(pages,tmp_path)
    a=verify_workspace_export(pages,dest);assert a['passed'] and a['bytes_match']
    report=dest/'report.json';v=json.loads(report.read_text());v['sha256'][r['files'][0]]='0'*64;report.write_text(json.dumps(v))
    a=verify_workspace_export(pages,dest);assert a['pixels_match'] and not a['passed'] and not a['report_matches']

def test_verify_reencoded_and_changed_pixels(tmp_path):
    project,pages=fixture(tmp_path);dest,r=export_pages(pages,tmp_path);p=dest/r['files'][0]
    with Image.open(p) as im: im.load(); im.save(p,compress_level=0)
    a=verify_workspace_export(pages,dest);assert a['pixels_match'] and not a['bytes_match'] and a['files'][0]['status']=='PIXELS_MATCH'
    with Image.open(p) as im: im.load();im.putpixel((0,0),(1,2,3,255));im.save(p)
    a=verify_workspace_export(pages,dest);assert not a['pixels_match'] and a['files'][0]['status']=='PIXELS_DIFFER'

def test_verify_missing_extra(tmp_path):
    project,pages=fixture(tmp_path);dest,r=export_pages(pages,tmp_path);(dest/r['files'][0]).unlink();(dest/'unexpected.txt').write_text('test')
    a=verify_workspace_export(pages,dest);assert not a['passed'] and a['unexpected_files']==['unexpected.txt'] and a['files'][0]['status']=='INVALID_OR_MISSING'

def test_revision_rejects_stale_writer(tmp_path):
    project,pages=fixture(tmp_path);a=load_workspace_project(project);b=load_workspace_project(project)
    apply_rect(a['pages'][0],0,(2,2,10,10),operation='union');r=save_workspace_project(a['pages'],0,project,expected_revision=a['revision']);assert r['revision']!=a['revision']
    prev=(project/'workspace.json').read_bytes();apply_rect(b['pages'][0],0,(20,20,30,30))
    with pytest.raises(ValueError,match='revision conflict'):save_workspace_project(b['pages'],0,project,expected_revision=b['revision'])
    assert (project/'workspace.json').read_bytes()==prev and not (project/'.workspace-write.lock').exists()

def test_cooperative_lock(tmp_path):
    project,pages=fixture(tmp_path);lock=project/'.workspace-write.lock';lock.write_text('other writer');before=(project/'workspace.json').read_bytes()
    with pytest.raises(ValueError,match='locked'):save_workspace_project(pages,0,project)
    assert lock.read_text()=='other writer' and before==(project/'workspace.json').read_bytes()

def test_invalid_active_selection(tmp_path):
    project,pages=fixture(tmp_path);manifest=project/'workspace.json';v=json.loads(manifest.read_text());v['active_index']=100;manifest.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='active workspace'):load_workspace_project(project)

def test_cli_verify_exit_codes(tmp_path):
    project,pages=fixture(tmp_path);dest,r=export_pages(pages,tmp_path)
    args=[sys.executable,'-m','veilpng','workspace-verify','--project-dir',str(project),'--export-dir',str(dest)]
    a=subprocess.run(args,cwd=ROOT,capture_output=True,text=True);assert a.returncode==0,a.stderr;assert json.loads(a.stdout)['passed']
    (dest/r['files'][0]).unlink();b=subprocess.run(args,cwd=ROOT,capture_output=True,text=True);assert b.returncode==2 and not json.loads(b.stdout)['passed']

def test_saved_v2_project_load_compatibility(tmp_path):
    project,pages=fixture(tmp_path);manifest=project/'workspace.json';v=json.loads(manifest.read_text());v['version']='0.6.2';manifest.write_text(json.dumps(v))
    assert load_workspace_project(project)['pages'][0].ready

def test_malformed_report_is_failure(tmp_path):
    project,pages=fixture(tmp_path);dest,r=export_pages(pages,tmp_path);(dest/'report.json').write_text('[]')
    result=verify_workspace_export(pages,dest);assert not result['passed'] and result['pixels_match']

def test_batch_and_selected_page_verification(tmp_path):
    for name in ['2.png','10.png','11.png']:
        Image.new('RGB',(60,80),'white').save(tmp_path/name)
    pages=image_pages([tmp_path/n for n in ['11.png','10.png','2.png']]);apply_rect(pages[0],0,(1,1,20,20));apply_rect(pages[2],0,(4,4,30,30))
    dest,r=export_pages(pages,tmp_path);assert r['exported']==2 and r['skipped']==1
    assert verify_workspace_export(pages,dest)['passed']
    dest,r=export_pages([pages[2]],tmp_path);assert verify_workspace_export([pages[2]],dest)['passed']

def test_paired_verification(tmp_path):
    from veilpng.simple_project import pair_pages
    root=tmp_path/'bundle'; (root/'source').mkdir(parents=True);(root/'target').mkdir()
    Image.new('RGB',(60,80),'white').save(root/'source/p.png');Image.new('RGB',(120,160),'white').save(root/'target/p.png')
    (root/'registration_pairs.csv').write_text('pair_id,source_image,target_image,source_width,source_height,target_width,target_height,matrix_3x3_json,registration_confidence\n17,p.png,p.png,60,80,120,160,"[[2,0,0],[0,2,0],[0,0,1]]",1\n')
    pages=pair_pages(root);apply_rect(pages[0],1,(20,20,60,60));dest,r=export_pages(pages,tmp_path)
    assert verify_workspace_export(pages,dest)['passed'] and len(r['files'])==2
