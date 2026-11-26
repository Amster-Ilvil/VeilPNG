from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

if os.name != 'nt' and not os.getenv('DISPLAY') and not os.getenv('WAYLAND_DISPLAY'):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication, QMessageBox

from veilpng.gui import MainWindow


@pytest.fixture(scope='module')
def app():
    inst = QApplication.instance() or QApplication([])
    yield inst


def _save(img: Image.Image, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def _pair_csv(path: Path, src_name: str, tgt_name: str, src_size: tuple[int, int], tgt_size: tuple[int, int]):
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['pair_id','source_image','target_image','source_width','source_height','target_width','target_height','matrix_3x3_json','registration_confidence'])
        w.writeheader()
        w.writerow({
            'pair_id': 'T051',
            'source_image': src_name,
            'target_image': tgt_name,
            'source_width': src_size[0], 'source_height': src_size[1],
            'target_width': tgt_size[0], 'target_height': tgt_size[1],
            'matrix_3x3_json': '[[2,0,0],[0,2,0],[0,0,1]]',
            'registration_confidence': '0.99',
        })


@pytest.fixture
def manga_env(tmp_path: Path, app):
    src = Image.new('RGB', (128, 96), '#f4f4f4')
    ds = ImageDraw.Draw(src)
    ds.rectangle((8, 8, 45, 36), fill='#bbbbbb')
    ds.ellipse((58, 10, 110, 64), fill='#909090')
    ds.line((0, 84, 127, 84), fill='black', width=2)
    ds.text((12, 46), 'CN', fill='black')
    tgt = src.resize((256, 192), Image.Resampling.NEAREST)
    dt = ImageDraw.Draw(tgt)
    dt.text((18, 92), 'JP', fill='black')

    src_path = tmp_path / 'CN0001.png'; _save(src, src_path)
    tgt_path = tmp_path / 'JP0001.png'; _save(tgt, tgt_path)
    pairs = tmp_path / 'pairs.csv'; _pair_csv(pairs, src_path.name, tgt_path.name, src.size, tgt.size)

    w = MainWindow()
    w.resize(1280, 860)
    w.show()
    app.processEvents()
    w._load_document(src_path.read_bytes(), src_path.name, None, None)
    app.processEvents()
    yield w, src_path, tgt_path, pairs, tmp_path
    w.close(); app.processEvents()


def test_gui_manga_create_project_from_current_page(manga_env, app, monkeypatch):
    w, src_path, tgt_path, pairs, tmp_path = manga_env
    ImageDraw.Draw(w.canvas.mask).rectangle((20, 52, 70, 92), fill=255)
    w.canvas.changed.emit()
    roi = Image.new('L', w.canvas.mask.size, 0)
    ImageDraw.Draw(roi).rectangle((8, 38, 48, 66), fill=255)
    w.ai_roi_mask = roi

    project_dir = tmp_path / 'project_gui'
    w.manga_project_dir.setText(str(project_dir))
    w.manga_pairs_csv.setText(str(pairs))
    w.manga_pair_id.setText('T051')
    w.manga_source_path.setText(str(src_path))
    w.manga_target_path.setText(str(tgt_path))

    infos = []
    monkeypatch.setattr(w, '_get_password', lambda confirm=False: 'pw123456')
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: infos.append(a[1]) or QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(w, '_error', lambda *a: pytest.fail(f'Unexpected GUI error: {a}'))

    w.manga_init_from_current()
    app.processEvents()

    manifest_path = project_dir / 'manga_project.json'
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['pair_id'] == 'T051'
    assert Path(manifest['source']['public_preview']).exists()
    assert Path(manifest['target']['public_preview']).exists()
    assert Path(manifest['target']['conceal_mask']).exists()
    assert Path(manifest['source']['roi_mask']).exists()
    assert '漫画模式项目已创建' in infos[-1]


def test_gui_manga_resolve_project_outputs_decrypted_results(manga_env, app, monkeypatch):
    w, src_path, tgt_path, pairs, tmp_path = manga_env
    ImageDraw.Draw(w.canvas.mask).rectangle((20, 52, 70, 92), fill=255)
    w.canvas.changed.emit()
    roi = Image.new('L', w.canvas.mask.size, 0)
    ImageDraw.Draw(roi).rectangle((6, 36, 54, 72), fill=255)
    w.ai_roi_mask = roi
    project_dir = tmp_path / 'project_gui_resolve'
    w.manga_project_dir.setText(str(project_dir))
    w.manga_pairs_csv.setText(str(pairs))
    w.manga_pair_id.setText('T051')
    w.manga_source_path.setText(str(src_path))
    w.manga_target_path.setText(str(tgt_path))
    monkeypatch.setattr(w, '_get_password', lambda confirm=False: 'pw123456')
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(w, '_error', lambda *a: pytest.fail(f'Unexpected GUI error: {a}'))
    w.manga_init_from_current(); app.processEvents()

    manifest = json.loads((project_dir / 'manga_project.json').read_text(encoding='utf-8'))
    src_public = Image.open(manifest['source']['public_preview']).convert('RGBA')
    ImageDraw.Draw(src_public).rectangle((10, 42, 44, 66), fill=(255,255,255,255), outline=(0,0,0,255), width=2)
    src_ai = tmp_path / 'src_ai.png'; _save(src_public, src_ai)
    tgt_public = Image.open(manifest['target']['public_preview']).convert('RGBA')
    ImageDraw.Draw(tgt_public).rectangle((20, 84, 88, 132), fill=(255,255,255,255), outline=(0,0,0,255), width=2)
    tgt_ai = tmp_path / 'tgt_ai.png'; _save(tgt_public, tgt_ai)

    w.manga_source_ai_path.setText(str(src_ai))
    w.manga_target_ai_path.setText(str(tgt_ai))
    w.manga_mode_combo.setCurrentIndex(0)  # A2
    w.manga_alignment_combo.setCurrentIndex(1)  # synthetic geometry is exactly aligned
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    w.extraction_combo.setCurrentIndex(1)  # monochrome
    w.edge_guard_spin.setValue(0)

    w.manga_resolve_project()
    app.processEvents()

    summary = json.loads((project_dir / 'resolved_outputs' / 'resolve_summary.json').read_text(encoding='utf-8'))
    assert summary['results']['source']['status'] == 'processed'
    assert summary['results']['target']['status'] == 'processed'
    src_out = Path(summary['results']['source']['decrypted_output'])
    tgt_out = Path(summary['results']['target']['decrypted_output'])
    assert src_out.exists() and tgt_out.exists()
    src_img = Image.open(src_out).convert('RGBA')
    # Concealed lower region should no longer be a solid black cover in decrypted output.
    assert src_img.getpixel((34, 72))[:3] != (0, 0, 0)
