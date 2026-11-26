import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from veilpng.cli import main
from veilpng.simple_project import load_workspace_project, save_workspace_project, image_pages, export_pages


def make_image(path: Path, size=(120, 160), color='white'):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new('RGB', size, color)
    ImageDraw.Draw(im).rectangle((10, 20, 45, 55), fill='#DA872B')
    im.save(path)
    return im


def run_cli(args, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['veilpng', *args])
    main()
    out = capsys.readouterr().out.strip()
    return json.loads(out)


def test_workspace_save_load_roundtrip(tmp_path):
    img = tmp_path / 'one.png'
    orig = make_image(img)
    pages = image_pages([img])
    pages[0].read(0)
    mask = Image.new('L', orig.size, 0)
    ImageDraw.Draw(mask).rectangle((8, 18, 49, 59), fill=255)
    pages[0].update(0, mask)
    report = save_workspace_project(pages, 0, tmp_path / 'project', active_index=0)
    assert report['ready_pages'] == 1
    state = load_workspace_project(tmp_path / 'project')
    assert state['mode'] == 0 and len(state['pages']) == 1 and state['pages'][0].ready
    out_dir, exported = export_pages(state['pages'], tmp_path)
    with Image.open(out_dir / exported['files'][0]) as im:
        arr = np.asarray(im.convert('RGBA'))
    assert np.all(arr[20:59, 8:49, :3] == 0)


def test_workspace_cli_single_rect_and_export(tmp_path, monkeypatch, capsys):
    img = tmp_path / 'single.png'
    make_image(img)
    project = tmp_path / 'project'
    report = run_cli(['workspace-init', '--single', str(img), '--project-dir', str(project)], monkeypatch, capsys)
    assert report['mode'] == 0 and report['pages'] == 1
    report = run_cli([
        'workspace-apply-mask', '--project-dir', str(project), '--page', '1', '--side', 'single',
        '--rect', '5', '6', '25', '35', '--operation', 'replace'
    ], monkeypatch, capsys)
    assert report['page_index'] == 1
    exports = tmp_path / 'exports'
    exports.mkdir()
    report = run_cli(['workspace-export', '--project-dir', str(project), '--output-dir', str(exports)], monkeypatch, capsys)
    assert report['exported'] == 1
    out = Path(report['output_dir']) / report['files'][0]
    with Image.open(out) as im:
        arr = np.asarray(im.convert('RGBA'))
    assert np.all(arr[6:35, 5:25, :3] == 0)


def test_workspace_cli_pair_rect_sync(tmp_path, monkeypatch, capsys):
    src = tmp_path / 'bundle' / 'source' / '001.png'
    tgt = tmp_path / 'bundle' / 'target' / '001.png'
    make_image(src)
    make_image(tgt, size=(240, 320))
    csv_path = tmp_path / 'bundle' / 'registration_pairs.csv'
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(
        'pair_id,source_image,target_image,source_width,source_height,target_width,target_height,matrix_3x3_json,registration_confidence\n'
        '001,001.png,001.png,120,160,240,320,"[[2,0,0],[0,2,0],[0,0,1]]",1\n',
        encoding='utf-8'
    )
    project = tmp_path / 'pair_project'
    report = run_cli(['workspace-init', '--pair-bundle', str(tmp_path / 'bundle'), '--project-dir', str(project)], monkeypatch, capsys)
    assert report['mode'] == 2 and report['pages'] == 1
    report = run_cli([
        'workspace-apply-mask', '--project-dir', str(project), '--page', '001', '--side', 'cn',
        '--rect', '10', '10', '20', '20', '--operation', 'replace'
    ], monkeypatch, capsys)
    assert report['side'] == 0
    state = load_workspace_project(project)
    assert state['pages'][0].get_mask(1).getpixel((20, 20)) == 255
