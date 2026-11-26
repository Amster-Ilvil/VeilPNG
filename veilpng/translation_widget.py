"""GUI for manual, reproducible Japanese-base / Gemini-Chinese translation transfer.

Three independent editable masks: translation ROI, Japanese lettering erasure,
and protected original artwork. The GUI calls translation_core, not a temporary
script or a remote image-generation model. All files stay local.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from PIL import Image
from PySide6.QtCore import Qt, QRectF
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QSplitter, QPushButton, QLabel, QLineEdit, QComboBox, QSpinBox, QCheckBox,
    QFileDialog, QScrollArea, QGroupBox, QMessageBox, QGraphicsView,
    QGraphicsScene, QGraphicsPixmapItem, QSizePolicy)

from .canvas import MaskCanvas, _pixmap
from .translation_core import align_translation_images, render_translation, mask_array
from .quality_review import review_translation


class TranslationWorkbench(QWidget):
    MASK_NAMES = ('译文移植选区','日文去字选区','原图保护选区')
    MASK_KEYS = ('translation','erase','protect')
    TINTS = ((61,169,236,92),(246,149,39,95),(228,74,78,100))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.aligned = None
        self.result = None
        self.review = None
        self.project_dir: Path | None = None
        self.active_layer = 0
        self.masks: dict[str,Image.Image] = {}
        self.histories: dict[str,tuple[list[bytes],list[bytes]]] = {}
        self._dirty = True
        self._aligned_sources = None
        self._init_ui()

    def _button(self,text,callback):
        b=QPushButton(text);b.clicked.connect(callback);b.setMinimumHeight(31)
        return b

    def _init_ui(self):
        root=QVBoxLayout(self)
        root.setContentsMargins(9,8,9,8)
        root.setSpacing(7)
        banner=QLabel('中文翻译移植 · 先配准日文原图 → 分别圈定去字/中文/保护区 → 实时预览 → 输出普通 PNG')
        banner.setWordWrap(True)
        root.addWidget(banner)
        paths=QGridLayout()
        self.jp_path=QLineEdit();self.jp_path.setPlaceholderText('原始日文漫画图（用于底图和保护内容）')
        self.gem_path=QLineEdit();self.gem_path.setPlaceholderText('Gemini 返回的带中文图片')
        self.clean_path=QLineEdit();self.clean_path.setPlaceholderText('可选：已经去字、且与画布同尺寸的日文底图')
        self.jp_path.textChanged.connect(self._source_path_changed)
        self.gem_path.textChanged.connect(self._source_path_changed)
        self.clean_path.textChanged.connect(self._set_dirty)
        for r,(label,field) in enumerate((('日文底图',self.jp_path),('Gemini 中文图',self.gem_path),('去字底图（可选）',self.clean_path))):
            paths.addWidget(QLabel(label),r,0);paths.addWidget(field,r,1)
            field.setMinimumWidth(0); field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            paths.addWidget(self._button('浏览',lambda _=False, f=field: self._browse_image(f)),r,2)
        root.addLayout(paths)
        bar=QHBoxLayout()
        self.align_button=self._button('1 · 配准载入',self.prepare)
        self.align_button.setObjectName('translationAlignButton')
        bar.addWidget(self.align_button)
        bar.addWidget(self._button('打开选区项目',self.open_project))
        bar.addWidget(self._button('保存选区项目',self.save_project))
        root.addLayout(bar)
        opts=QGridLayout()
        opts.addWidget(QLabel('当前编辑'),0,0)
        self.layer_combo=QComboBox();self.layer_combo.addItems(self.MASK_NAMES)
        self.layer_combo.currentIndexChanged.connect(self._switch_layer)
        opts.addWidget(self.layer_combo,0,1)
        opts.addWidget(QLabel('移植方式'),1,0)
        self.transfer_combo=QComboBox()
        self.transfer_combo.addItems(('完整区域贴图（包括白描边效果字）','仅提取深色字形（白气泡推荐）'))
        self.transfer_combo.currentIndexChanged.connect(lambda _: self._set_dirty())
        opts.addWidget(self.transfer_combo,1,1)
        for combo in (self.layer_combo,self.transfer_combo):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
            combo.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        self.feather=QSpinBox();self.feather.setRange(0,24);self.feather.setValue(3)
        self.feather.valueChanged.connect(lambda _: self._set_dirty())
        opts.addWidget(QLabel('柔边 px'),0,2);opts.addWidget(self.feather,0,3)
        opts.setColumnStretch(1,1)
        root.addLayout(opts)
        tools=QGridLayout()
        for index,(name,tool) in enumerate( (('画笔','brush'),('擦除','erase'),('矩形','rect'),('套索','lasso'),('多边形','polygon'),('平移','pan'))):
            tools.addWidget(self._button(name,lambda _=False,t=tool:self.canvas.set_tool(t)),index//5,index%5)
        tools.addWidget(self._button('撤销',self.canvas_undo),1,1)
        tools.addWidget(self._button('重做',self.canvas_redo),1,2)
        tools.addWidget(self._button('清空',self.canvas_clear),1,3)
        root.addLayout(tools)
        mask_row=QHBoxLayout()
        mask_row.addWidget(self._button('导入当前层的 PNG 选区',self.import_mask))
        mask_row.addWidget(self._button('保存当前层选区 PNG',self.export_mask))
        self.status=QLabel('准备就绪。三层选区均在 Gemini 画布坐标中，保护区优先。')
        self.status.setWordWrap(True)
        root.addLayout(mask_row)
        root.addWidget(self.status)

        views=QSplitter(Qt.Orientation.Horizontal)
        self.canvas=MaskCanvas()
        self.canvas.setObjectName('translationEditCanvas')
        self.canvas.set_tool('brush')
        self.canvas.changed.connect(self._set_dirty)
        views.addWidget(self.canvas)
        right=QWidget();right_l=QVBoxLayout(right);right_l.setContentsMargins(1,1,1,1)
        info_row=QVBoxLayout()
        info_row.addWidget(QLabel('右侧预览'))
        self.preview_combo=QComboBox();self.preview_combo.addItems(('合成结果','Gemini 原图','去字日文底图','疑似残字／接缝标记'))
        self.preview_combo.currentIndexChanged.connect(self._refresh_preview)
        info_row.addWidget(self.preview_combo)
        self.issue_combo=QComboBox()
        self.issue_combo.addItem('选择疑似问题并放大定位')
        self.issue_combo.setMinimumWidth(0)
        for combo in (self.preview_combo,self.issue_combo):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(5)
            combo.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        self.issue_combo.currentIndexChanged.connect(self._jump_quality_issue)
        info_row.addWidget(self.issue_combo)
        right_l.addLayout(info_row)
        self.view=QGraphicsView()
        self.scene=QGraphicsScene(self.view);self.item=QGraphicsPixmapItem()
        self.scene.addItem(self.item);self.view.setScene(self.scene)
        right_l.addWidget(self.view,1)
        views.addWidget(right);views.setSizes([550,550])
        root.addWidget(views,1)
        out=QGridLayout()
        self.preview_btn=self._button('2 · 生成合成预览',self.generate_preview)
        self.export_btn=self._button('3 · 导出最终普通 PNG',self.export_final)
        self.export_btn.setObjectName('translationExportButton')
        out.addWidget(self.preview_btn,0,0);out.addWidget(self.export_btn,0,1)
        out.addWidget(self._button('4 · 标记疑似残字/接缝', self.run_quality_review),1,0)
        out.addWidget(self._button('导出复核报告', self.export_quality_review),1,1)
        root.addLayout(out)

    def _error(self, stage, exc):
        self.status.setText(f'{stage}失败：{exc}')
        QMessageBox.critical(self,stage,str(exc))

    def _browse_image(self,edit):
        p,_=QFileDialog.getOpenFileName(self,'选择图片','','Images (*.png *.jpeg *.jpg *.webp *.bmp *.tiff *.tif)')
        if p: edit.setText(p)

    def _set_dirty(self,*_):
        self._dirty=True
        self.result=None
        self.review=None
        if hasattr(self,'issue_combo'):
            self.issue_combo.blockSignals(True)
            self.issue_combo.clear()
            self.issue_combo.addItem('选择疑似问题并放大定位')
            self.issue_combo.blockSignals(False)

    @staticmethod
    def _source_signature(path):
        p=Path(path).expanduser().resolve()
        s=p.stat()
        import hashlib
        return (str(p),s.st_size,s.st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest())

    def _source_path_changed(self,*_):
        self._set_dirty()
        if self.aligned is not None:
            self.status.setText('原图路径已改变；请重新配准后再预览、导出或保存项目。原选区尚未丢弃。')

    def _check_sources_current(self):
        if self._aligned_sources is None:
            raise ValueError('未建立有效的配准源图片，请先执行配准')
        now=(self._source_signature(self.jp_path.text().strip()),
             self._source_signature(self.gem_path.text().strip()))
        if now != self._aligned_sources:
            raise ValueError('日文/Gemini 图片或其文件内容在配准后发生了变化；请重新配准')

    @staticmethod
    def _write_png_atomically(path: Path, img: Image.Image):
        """A failed save must never truncate a previous final output."""
        path.parent.mkdir(parents=True,exist_ok=True)
        tmp=None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.veilpng-',suffix='.png',delete=False) as f:
                tmp=Path(f.name)
            img.save(tmp,format='PNG')
            os.replace(tmp,path)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    def _save_layer(self):
        if self.aligned is not None and self.canvas.mask is not None:
            key=self.MASK_KEYS[self.active_layer]
            self.masks[key]=self.canvas.mask.copy()
            self.histories[key]=(self.canvas.undo_stack.copy(),self.canvas.redo_stack.copy())

    def _switch_layer(self,index):
        if index<0:return
        if self.aligned is not None:
            self._save_layer()
            self.active_layer=index
            key=self.MASK_KEYS[index]
            self.canvas.set_document(self.aligned.japanese,self.masks.get(key))
            undo,redo=self.histories.get(key,([],[]))
            self.canvas.undo_stack=undo.copy();self.canvas.redo_stack=redo.copy()
            self.canvas.set_selection_tint(self.TINTS[index])
        else:
            self.active_layer=index

    def prepare(self, *, saved_matrix=None, skip_reset_confirmation=False):
        try:
            if not self.jp_path.text().strip() or not self.gem_path.text().strip():
                raise ValueError('必须选择日文原图和 Gemini 中文图')
            aligned=align_translation_images(japanese=self.jp_path.text().strip(),
                gemini=self.gem_path.text().strip(),matrix_jp_to_gemini=saved_matrix)
            if self.clean_path.text().strip():
                with Image.open(self.clean_path.text().strip()) as im:
                    if im.size != aligned.japanese.size:
                        raise ValueError('去字底图尺寸必须等于配准输出尺寸')
            if not skip_reset_confirmation and self.aligned is not None:
                self._save_layer()
                if any(mask.getbbox() for mask in self.masks.values()):
                    confirm=QMessageBox.question(self,'确认重新配准',
                        '重新配准会清空当前三层选区与撤销历史。请先保存项目。确定继续？',
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No)
                    if confirm != QMessageBox.StandardButton.Yes:
                        return False
            self.aligned=aligned
            self._aligned_sources=(self._source_signature(self.jp_path.text().strip()),
                                   self._source_signature(self.gem_path.text().strip()))
            self.masks={k:Image.new('L',aligned.japanese.size,0) for k in self.MASK_KEYS}
            self.histories={k:([],[]) for k in self.MASK_KEYS}
            self.active_layer=self.layer_combo.currentIndex()
            self.canvas.set_document(aligned.japanese,self.masks[self.MASK_KEYS[self.active_layer]])
            self.canvas.set_selection_tint(self.TINTS[self.active_layer])
            self._set_dirty()
            self._refresh_preview()
            stats=aligned.report
            self.status.setText(f"配准完成 · {aligned.japanese.width}×{aligned.japanese.height} · "
                 f"{stats['method']} · 匹配 {stats.get('matched_features')}, 内点 {stats.get('inliers')}")
            return True
        except Exception as e:
            self._error('图像配准',e);return False

    def canvas_undo(self):self.canvas.undo()
    def canvas_redo(self):self.canvas.redo()
    def canvas_clear(self):self.canvas.clear_mask()

    def _refresh_preview(self,*_):
        if self.aligned is None:return
        idx=self.preview_combo.currentIndex()
        if idx==1:img=self.aligned.gemini
        elif idx==2:img=self.result.clean_base if self.result else self.aligned.japanese
        elif idx==3:img=self.review.overlay if self.review else (self.result.image if self.result else self.aligned.japanese)
        else:img=self.result.image if self.result else self.aligned.japanese
        self.item.setPixmap(_pixmap(img))
        self.scene.setSceneRect(0,0,img.width,img.height)
        self.view.fitInView(self.scene.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)

    def _jump_quality_issue(self,index):
        if index <= 0 or self.review is None:
            return
        issues=self.review.report.get('issues',[])
        if index-1 >= len(issues):
            return
        if self.preview_combo.currentIndex()!=3:
            self.preview_combo.setCurrentIndex(3)
        x0,y0,x1,y1=issues[index-1]['bbox']
        pad=max(14,int(max(x1-x0,y1-y0)*0.25))
        rect=QRectF(max(0,x0-pad),max(0,y0-pad),x1-x0+2*pad,y1-y0+2*pad)
        self.view.fitInView(rect,Qt.AspectRatioMode.KeepAspectRatio)
        self.status.setText(f'已定位第 {index} 个疑似问题：{issues[index-1]["kind"]}。请人工判断，检测不会修改原图。')

    def generate_preview(self):
        try:
            if self.aligned is None:raise ValueError('请先执行图像配准')
            self._check_sources_current()
            self._save_layer()
            clean=self.clean_path.text().strip() or None
            res=render_translation(aligned=self.aligned,
                translation_mask=self.masks['translation'],
                erase_japanese_mask=self.masks['erase'],
                protect_mask=self.masks['protect'],
                cleaned_japanese_base=clean,
                transfer='patch' if self.transfer_combo.currentIndex()==0 else 'ink',
                feather_px=self.feather.value())
            self.result=res;self.review=None;self._dirty=False
            self.preview_combo.setCurrentIndex(0)
            self._refresh_preview()
            overlap=res.report['paste_mask_protected_overlap_pixels']
            warning=f' 注意：有 {overlap:,} 个译文选区像素被红色保护区拦截，需复核文字是否残缺。' if overlap else ''
            self.status.setText(f"合成预览完成：改动 {res.report['changed_pixels']:,} 像素，"
                                f"保护区与许可范围外改动均为 0。{warning}")
            return res
        except Exception as e:
            self._error('生成译文合成预览',e);return None

    def run_quality_review(self):
        """Non-destructive pixel-based quality hints; not language OCR."""
        try:
            if self.aligned is None:
                raise ValueError('请先完成配准')
            self._check_sources_current()
            if self._dirty or self.result is None:
                if self.generate_preview() is None:
                    return None
            self._save_layer()
            self.review = review_translation(
                aligned=self.aligned, result=self.result,
                translation_mask=self.masks['translation'],
                erase_japanese_mask=self.masks['erase'],
                protect_mask=self.masks['protect'])
            counts = self.review.report['candidate_counts']
            self.issue_combo.blockSignals(True)
            self.issue_combo.clear()
            self.issue_combo.addItem('选择疑似问题并放大定位')
            for idx,issue in enumerate(self.review.report['issues'],1):
                kind = '残字' if issue['kind']=='possible_original_ink' else '接缝'
                x0,y0,x1,y1=issue['bbox']
                self.issue_combo.addItem(f'{idx}. {kind} ({x0},{y0}) ~ ({x1},{y1})')
            self.issue_combo.blockSignals(False)
            self.preview_combo.setCurrentIndex(3)
            self._refresh_preview()
            self.status.setText(
                f"疑似残字 {counts['possible_original_ink']} 处、"
                f"疑似边缘接缝 {counts['possible_patch_seam']} 处。"
                '红色和橙色仅为像素异常候选，不是 OCR 识别，必须人工复核。')
            return self.review
        except Exception as exc:
            self._error('检查残字与接缝', exc)
            return None

    def export_quality_review(self):
        try:
            if self.review is None:
                if self.run_quality_review() is None:
                    return
            self._check_sources_current()
            out = QFileDialog.getExistingDirectory(self,'选择质量复核报告输出目录')
            if not out:
                return
            dest = Path(out)
            outputs = [dest/'translation_quality_overlay.png',
                       dest/'translation_quality_flags.png',
                       dest/'translation_quality_report.json']
            protected_inputs = [self.jp_path.text(), self.gem_path.text(), self.clean_path.text()]
            if self.project_dir:
                protected_inputs.extend(str(self.project_dir/f'{k}.png') for k in self.MASK_KEYS)
                protected_inputs.append(str(self.project_dir/'translation_project.json'))
            protected = {Path(p).resolve() for p in protected_inputs if p}
            if any(p.resolve() in protected for p in outputs):
                raise ValueError('复核报告路径与源图片或项目文件冲突，已拒绝覆盖')
            self._write_png_atomically(outputs[0], self.review.overlay)
            self._write_png_atomically(outputs[1], self.review.issue_mask)
            data = json.dumps(self.review.report, ensure_ascii=False, indent=2).encode('utf-8')
            from .cli import _atomic_write
            _atomic_write(outputs[2], data)
            self.status.setText(f'质量复核结果已保存：{dest}；不会更改最终中文成品。')
        except Exception as exc:
            self._error('导出质量复核报告',exc)

    def export_final(self):
        if self.aligned is None:return self._error('导出','请先导入并配准图片')
        try:self._check_sources_current()
        except Exception as e:return self._error('导出',e)
        if self._dirty or self.result is None:
            if self.generate_preview() is None:return
        p,_=QFileDialog.getSaveFileName(self,'保存最终中文图片','final_translated.png','PNG (*.png)')
        if not p:return
        try:
            output_path=Path(p)
            if output_path.suffix.lower()!='.png':
                raise ValueError('最终图片必须保存为 PNG')
            report_path=output_path.with_suffix('.report.json')
            protected_inputs=[self.jp_path.text(),self.gem_path.text(),self.clean_path.text()]
            if self.project_dir:
                project_manifest=self.project_dir/'translation_project.json'
                if project_manifest.is_file():
                    cfg=json.loads(project_manifest.read_text(encoding='utf8'))
                    protected_inputs.extend(str(self.project_dir/name) for name in cfg.get('mask_files',{}).values())
                protected_inputs.append(str(project_manifest))
            reserved={Path(p).resolve() for p in protected_inputs if p}
            if output_path.resolve() in reserved or report_path.resolve() in reserved:
                raise ValueError('输出文件与输入图片/选区项目重名，已拒绝覆盖')
            self._write_png_atomically(output_path,self.result.image)
            report_path.write_text(json.dumps(self.result.report,ensure_ascii=False,indent=2),encoding='utf-8')
            self.status.setText(f'已导出普通 PNG（无加密层）：{p}')
        except Exception as e:self._error('导出最终中文图片',e)

    def import_mask(self):
        if self.aligned is None:return self._error('导入蒙版','请先完成配准')
        p,_=QFileDialog.getOpenFileName(self,'导入当前层的 PNG 蒙版','','PNG (*.png)')
        if not p:return
        try:
            with Image.open(p) as im:
                im.load()
                mask=Image.fromarray(mask_array(im,self.aligned.japanese.size,name='import mask')*255,'L')
            self.masks[self.MASK_KEYS[self.active_layer]]=mask
            self.histories[self.MASK_KEYS[self.active_layer]]=([],[])
            self.canvas.set_document(self.aligned.japanese,mask)
            self.canvas.set_selection_tint(self.TINTS[self.active_layer])
            self._set_dirty()
        except Exception as e:self._error('导入蒙版',e)

    def export_mask(self):
        if self.aligned is None:return self._error('导出蒙版','请先完成配准')
        self._save_layer()
        p,_=QFileDialog.getSaveFileName(self,'导出选区 PNG',f'{self.MASK_KEYS[self.active_layer]}.png','PNG (*.png)')
        if p:
            try:self.masks[self.MASK_KEYS[self.active_layer]].save(p,format='PNG')
            except Exception as e:self._error('导出蒙版',e)

    def save_project(self):
        if self.aligned is None:return self._error('保存项目','请先完成配准')
        p=QFileDialog.getExistingDirectory(self,'选择项目保存目录')
        if not p:return
        try:
            self._check_sources_current()
            self._save_layer()
            from .translation_project import save_translation_project
            folder=Path(p).resolve()
            save_translation_project(folder,japanese=self.jp_path.text().strip(),gemini=self.gem_path.text().strip(),
                clean_base=self.clean_path.text().strip(),matrix=self.aligned.report['matrix_jp_to_gemini'],masks=self.masks,
                transfer='patch' if self.transfer_combo.currentIndex()==0 else 'ink',feather=self.feather.value())
            self.project_dir=folder;self.status.setText(f'翻译选区项目已保存：{folder}')
        except Exception as e:self._error('保存项目',e)

    def open_project(self):
        p=QFileDialog.getExistingDirectory(self,'打开翻译移植项目目录')
        if not p:return
        try:
            folder=Path(p)
            cfg=json.loads((folder/'translation_project.json').read_text(encoding='utf-8'))
            if cfg.get('kind')!='translation_transfer':raise ValueError('不是翻译移植项目')
            files=cfg.get('mask_files')
            if not isinstance(files,dict) or set(files)!=set(self.MASK_KEYS):
                raise ValueError('项目缺少完整的三层蒙版清单')
            for name in files.values():
                if (not isinstance(name,str) or Path(name).name!=name or
                        '\\' in name or Path(name).suffix.lower()!='.png'):
                    raise ValueError('选区文件必须是项目目录中的 PNG 文件名，不允许目录穿越')
            # Moved project folders (Windows -> Mac etc.) can rebind file
            # sources without invalidating the saved pixel-space masks.
            def resolve_source(raw: str, caption: str) -> str:
                if not raw:
                    return ''
                candidate=Path(raw)
                if not candidate.is_absolute():
                    from .simple_project import _inside
                    candidate=_inside(folder.resolve(),raw)
                if not candidate.is_file():
                    local=folder/raw.replace('\\','/').split('/')[-1]
                    if local.is_file():
                        return str(local)
                    picked,_=QFileDialog.getOpenFileName(self,f'重新定位：{caption}',str(folder),
                                 '图片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)')
                    if not picked:
                        raise FileNotFoundError(f'{caption} 未找到，项目载入已取消')
                    return picked
                return str(candidate)
            selected={'japanese':resolve_source(cfg['japanese'],'日文原图'),
                      'gemini':resolve_source(cfg['gemini'],'Gemini 中文图'),
                      'clean_base':resolve_source(cfg.get('clean_base',''),'去字底图')}
            from .translation_project import read_translation_recipe
            read_translation_recipe(folder,source_overrides=selected)
            self.jp_path.setText(selected['japanese'])
            self.gem_path.setText(selected['gemini'])
            self.clean_path.setText(selected['clean_base'])
            if not self.prepare(saved_matrix=cfg['matrix_jp_to_gemini'],skip_reset_confirmation=True):return
            for k,rel in cfg['mask_files'].items():
                with Image.open(folder/rel) as im:
                    self.masks[k]=Image.fromarray(mask_array(im,self.aligned.japanese.size,name=k)*255,'L')
            self.transfer_combo.setCurrentIndex(0 if cfg.get('transfer')=='patch' else 1)
            self.feather.setValue(cfg.get('feather',3))
            self.canvas.set_document(self.aligned.japanese,self.masks[self.MASK_KEYS[self.active_layer]])
            self.canvas.set_selection_tint(self.TINTS[self.active_layer])
            self.project_dir=folder;self._set_dirty()
            self.status.setText(f'项目和三层选区已恢复：{folder}')
        except Exception as e:self._error('打开项目',e)
