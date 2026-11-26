"""Offscreen Qt tests for *real* two-canvas manga interactions and paired workflow.

All test images and registration tables are constructed in-memory and written to
pytest temporary directories. No private manga assets are bundled.
"""
from __future__ import annotations
import csv
import json
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

if not os.getenv('DISPLAY') and not os.getenv('WAYLAND_DISPLAY') and os.name != 'nt':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PySide6')
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from veilpng.core import preview_only, unseal_bytes
from veilpng.gui import MainWindow
from veilpng.png_container import extract_private_chunk


@pytest.fixture(scope='module')
def app():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_data(tmp_path: Path):
    cn_dir = tmp_path / 'cn'; jp_dir = tmp_path / 'jp'
    cn_dir.mkdir(); jp_dir.mkdir()
    rows = []
    for index in (1, 2):
        image = Image.new('RGB', (240, 160), '#EEEEEE')
        draw = ImageDraw.Draw(image)
        draw.rectangle((15, 12, 88, 75), fill='#666666')
        draw.ellipse((115, 60, 210, 145), fill='#D9D9D9', outline='#222222', width=4)
        draw.line((0, 120, 230, 120), fill='#121212', width=3)
        cn = cn_dir / f'CN{index:04}.png'; image.save(cn)
        jp = jp_dir / f'JP{index:04}.png'
        image.resize((480, 320), Image.Resampling.NEAREST).save(jp)
        rows.append({
            'pair_id': f'{index:04}',
            'source_image': cn.name, 'target_image': jp.name,
            'source_width': 240, 'source_height': 160,
            'target_width': 480, 'target_height': 320,
            'matrix_3x3_json': '[[2,0,0],[0,2,0],[0,0,1]]',
            'registration_confidence': '.99',
        })
    csv_path = tmp_path / 'pairs.csv'
    with csv_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, rows[0].keys())
        writer.writeheader(); writer.writerows(rows)
    return csv_path, cn_dir, jp_dir


@pytest.fixture
def pair_window(app, tmp_path: Path, monkeypatch):
    csv_path, cn_dir, jp_dir = _make_data(tmp_path)
    w = MainWindow()
    w.resize(1480, 950); w.show(); app.processEvents()
    w.manga_pairs_csv.setText(str(csv_path))
    w.manga_source_root.setText(str(cn_dir))
    w.manga_target_root.setText(str(jp_dir))
    monkeypatch.setattr(w, '_error', lambda *a: pytest.fail(f'GUI error {a!r}'))
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(w, '_get_password', lambda confirm=False: 'SyntheticPassword2026!')
    w.manga_refresh_list()
    w.manga_pair_list.setCurrentRow(0)
    app.processEvents()
    yield w, cn_dir, jp_dir, tmp_path
    w.close(); app.processEvents()


def _mouse(view, event_type, xy, *, drag=False):
    point = QPointF(view.mapFromScene(QPointF(*xy)))
    pressed = event_type in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)
    released = event_type == QEvent.Type.MouseButtonRelease
    button = Qt.MouseButton.LeftButton if pressed or released else Qt.MouseButton.NoButton
    buttons = Qt.MouseButton.NoButton if released else Qt.MouseButton.LeftButton if (drag or pressed) else Qt.MouseButton.NoButton
    event = QMouseEvent(event_type, point, view.viewport().mapToGlobal(point.toPoint()),
                        button, buttons, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view.viewport(), event)
    QApplication.processEvents()


def _stroke(view, points):
    _mouse(view, QEvent.Type.MouseButtonPress, points[0])
    for p in points[1:-1]:
        _mouse(view, QEvent.Type.MouseMove, p, drag=True)
    _mouse(view, QEvent.Type.MouseButtonRelease, points[-1])


def test_pair_list_and_central_dual_canvas(pair_window, app):
    w, cn_dir, jp_dir, tmp_path = pair_window
    assert w.manga_pair_list.count() == 2
    assert w.side_tabs.currentIndex() == 2
    assert w.workspace_stack.currentIndex() == 1
    assert w.manga_dual.loaded
    assert w.manga_dual.pair.pair_id == '0001'
    assert w.manga_dual.source_canvas.original.size == (240,160)
    assert w.manga_dual.target_canvas.original.size == (480,320)
    w.manga_pair_search.setText('0002')
    assert w.manga_pair_list.item(0).isHidden()
    assert not w.manga_pair_list.item(1).isHidden()


def test_real_mouse_sync_cn_to_jp_and_back(pair_window, app):
    w, cn_dir, jp_dir, tmp_path = pair_window
    panel = w.manga_dual
    panel.tool_combo.setCurrentIndex(2)  # rectangle
    _stroke(panel.source_canvas, [(38, 20), (85, 76)])
    assert panel.source_canvas.mask.getpixel((50, 40)) == 255
    assert panel.target_canvas.mask.getpixel((100, 80)) == 255
    assert panel.target_canvas.mask.getpixel((300, 200)) == 0
    before = panel.mask_for('source','conceal').tobytes()
    panel.tool_combo.setCurrentIndex(0)  # brush
    panel.brush_spin.setValue(18)
    _stroke(panel.target_canvas, [(320, 170), (355, 200), (375, 225)])
    assert panel.target_canvas.mask.getpixel((350, 200)) == 255
    assert panel.source_canvas.mask.getpixel((175, 100)) == 255
    assert panel.last_side == 'target'
    assert panel.mask_for('source','conceal').tobytes() != before


def test_roi_independent_and_pair_state_persists(pair_window, app):
    w, cn_dir, jp_dir, tmp_path = pair_window
    panel = w.manga_dual
    panel.tool_combo.setCurrentIndex(2)
    _stroke(panel.source_canvas, [(55, 60), (110, 110)])
    red_before = panel.mask_for('source','conceal').tobytes()
    panel.layer_combo.setCurrentIndex(1)
    assert panel.mode == 'roi'
    assert not panel.preview_check.isEnabled()
    _stroke(panel.target_canvas, [(260, 70), (410, 110)])
    assert panel.target_canvas.mask.getpixel((330, 85)) == 255
    assert panel.source_canvas.mask.getpixel((165, 43)) == 255
    assert panel.source_canvas.mask.getpixel((80,80)) == 0
    assert panel.mask_for('source','conceal').tobytes() == red_before
    # Switch to a second pair and back; both masks must be preserved.
    w.manga_pair_list.setCurrentRow(1); app.processEvents()
    assert w.manga_dual.pair.pair_id == '0002'
    w.manga_pair_list.setCurrentRow(0); app.processEvents()
    assert w.manga_dual.pair.pair_id == '0001'
    assert w.manga_dual.mask_for('source','conceal').tobytes() == red_before
    assert w.manga_dual.mask_for('source','roi').getpixel((165,43)) == 255
    w.manga_dual.layer_combo.setCurrentIndex(0)
    w.manga_dual.preview_check.setChecked(True)
    assert w.manga_dual.source_canvas.show_cover
    assert w.manga_dual.target_canvas.show_cover
    assert not w.manga_dual.source_canvas.base_item.pixmap().isNull()


def test_both_pages_create_and_decrypt_from_gui(pair_window, app):
    w, cn_dir, jp_dir, tmp_path = pair_window
    panel = w.manga_dual
    panel.tool_combo.setCurrentIndex(2)
    _stroke(panel.source_canvas, [(60, 30), (105, 85)])
    panel.layer_combo.setCurrentIndex(1)
    _stroke(panel.source_canvas, [(175, 50), (220, 90)])
    panel.layer_combo.setCurrentIndex(0)
    project = tmp_path / 'project'
    w.manga_project_dir.setText(str(project))
    w.manga_init_from_current()
    app.processEvents()
    manifest = json.loads((project / 'manga_project.json').read_text('utf-8'))
    assert manifest['pair_id'] == '0001'
    assert Path(manifest['source']['container']).exists()
    assert Path(manifest['target']['container']).exists()
    assert manifest['editable_roi']['source']['covered_pixels'] > 0
    assert manifest['editable_roi']['target']['covered_pixels'] > 0
    for side in ('source', 'target'):
        ctn = Path(manifest[side]['container']).read_bytes()
        public = Path(manifest[side]['public_preview']).read_bytes()
        assert extract_private_chunk(ctn) is not None
        assert extract_private_chunk(public) is None
        asset = unseal_bytes(ctn, 'SyntheticPassword2026!')
        assert asset.original_bytes == Path(manifest[side]['image']).read_bytes()
        assert preview_only(ctn) == public
    assert (project/'assets'/'CN0001.png').exists()  # private local asset; do not publish project folder


def test_gui_a2_both_returns_and_recovers_masked_area(pair_window, app):
    w, cn_dir, jp_dir, tmp_path = pair_window
    panel = w.manga_dual
    panel.tool_combo.setCurrentIndex(2)
    _stroke(panel.source_canvas, [(60, 30), (105, 85)])
    panel.layer_combo.setCurrentIndex(1)
    _stroke(panel.source_canvas, [(170, 35), (219, 67)])
    panel.layer_combo.setCurrentIndex(0)
    project = tmp_path / 'project'
    w.manga_project_dir.setText(str(project))
    w.manga_init_from_current()
    manifest = json.loads((project/'manga_project.json').read_text('utf-8'))
    ai_paths = {}
    for side in ('source','target'):
        img = Image.open(manifest[side]['public_preview']).convert('RGBA')
        if side == 'source':
            box = (180,42,208,56)
        else:
            box = (360,84,416,112)
        ImageDraw.Draw(img).rectangle(box, fill=(8,8,8,255))
        result_path = tmp_path/f'{side}_ai.png'; img.save(result_path)
        ai_paths[side] = result_path
    w.manga_source_ai_path.setText(str(ai_paths['source']))
    w.manga_target_ai_path.setText(str(ai_paths['target']))
    w.manga_alignment_combo.setCurrentIndex(1) # explicitly confirmed resize for synthetic perfectly aligned images
    w.extraction_combo.setCurrentIndex(3) # patch restricted to ROI
    w.edge_guard_spin.setValue(0)
    w.manga_resolve_project()
    summary=json.loads((project/'resolved_outputs'/'resolve_summary.json').read_text('utf-8'))
    for side in ('source', 'target'):
        result = summary['results'][side]
        assert result['status'] == 'processed'
        restored = Image.open(result['decrypted_output']).convert('RGB')
        covered = Image.open(manifest[side]['conceal_mask']).convert('L')
        orig = Image.open(manifest[side]['image']).convert('RGB')
        # Cryptographic decryption must return original pixels inside masked region.
        import numpy as np
        delta = np.any(np.asarray(restored) != np.asarray(orig), axis=2)
        protected = np.asarray(covered) > 0
        assert np.count_nonzero(delta & protected) == 0
        assert np.count_nonzero(delta & ~protected) > 0
