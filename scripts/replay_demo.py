"""Non-sensitive standalone reproduction test, using real CLI subprocesses."""
from pathlib import Path
import json, os, subprocess, sys, shutil, hashlib
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]

def main():
    out=Path(sys.argv[1]).resolve();out.mkdir(parents=True,exist_ok=False)
    def cli(name,*args):
        command=[sys.executable,'-m','veilpng',*map(str,args)]
        result=json.loads(subprocess.check_output(command,cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT)},text=True))
        (out/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        return result
    img=Image.new('RGB',(640,480),'#edf4ff');d=ImageDraw.Draw(img)
    d.rectangle((60,100,220,280),fill='#315c85');d.ellipse((330,110,510,290),fill='#e4b244');d.text((60,40),'Sample artwork / local replay',fill='black')
    src=out/'sample.png';img.save(src);project=out/'linked';exports=out/'exports';exports.mkdir()
    cli('01_init','workspace-init','--single',src,'--project-dir',project)
    cli('02_rect','workspace-apply-mask','--project-dir',project,'--page',1,'--rect',60,100,220,280)
    cli('03_union','workspace-apply-mask','--project-dir',project,'--page',1,'--rect',330,110,510,290,'--operation','union')
    cli('04_subtract','workspace-apply-mask','--project-dir',project,'--page',1,'--rect',390,160,450,220,'--operation','subtract')
    a=cli('05_export','workspace-export','--project-dir',project,'--output-dir',exports)
    cli('06_pack','workspace-pack','--project-dir',project,'--output-dir',out/'portable')
    # All inputs here were created by this script. Remove only temporary demo copies.
    shutil.rmtree(project);src.unlink();(out/'portable').rename(out/'moved_portable')
    b=cli('07_replay','workspace-replay','--project-dir',out/'moved_portable','--output-dir',exports)
    assert a['sha256']==b['sha256'] and a['pixel_sha256']==b['pixel_sha256'] and b['replayed_commits']==3
    first=Path(a['output_dir'])/a['files'][0];last=Path(b['output_dir'])/b['files'][0]
    assert first.read_bytes()==last.read_bytes()
    shutil.copyfile(last,out/'result.png')
    (out/'verification.json').write_text(json.dumps({'commits':3,'moved_portable_project':True,'original_path_removed':True,'equal_bytes':True,'sha256':hashlib.sha256(last.read_bytes()).hexdigest()},indent=2))
    print('Replay verified:',out)
if __name__=='__main__':main()
