"""Compact, task-first Qt workspace. No network or image generation."""
from __future__ import annotations
from pathlib import Path
from threading import Event
from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QAction, QKeySequence, QPixmap
from PySide6.QtWidgets import (QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,
    QLabel,QPushButton,QButtonGroup,QListWidget,QListWidgetItem,QSplitter,QFileDialog,
    QMessageBox,QDialog,QDialogButtonBox,QScrollArea,QComboBox,QSpinBox,QCheckBox,QLineEdit,QProgressDialog,QSizePolicy,QInputDialog)
from .canvas import MaskCanvas
from .simple_project import image_pages,pair_pages,export_pages,save_workspace_project,load_workspace_project,EXTS
from .gui_theme import STYLESHEET
from . import __version__

FILTER='图片 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)'
TOOLS=('rect','brush','erase','lasso','polygon','pan')

class ExportThread(QThread):
    progress=Signal(int,int)
    success=Signal(str,object)
    failure=Signal(str)
    def __init__(self,pages,folder,parent=None):
        super().__init__(parent); self.pages=pages; self.folder=folder; self.stop=Event()
    def run(self):
        try:
            p,r=export_pages(self.pages,self.folder,progress=self.progress.emit,cancelled=self.stop.is_set)
            self.success.emit(str(p),r)
        except Exception as exc: self.failure.emit(str(exc))

class VerifyThread(QThread):
    success=Signal(str,object)
    failure=Signal(str)
    def __init__(self,pages,folder,parent=None):
        super().__init__(parent); self.pages=pages; self.folder=folder
    def run(self):
        try:
            from .workspace_verify import verify_workspace_export
            report=verify_workspace_export(self.pages,self.folder)
            self.success.emit(str(self.folder),report)
        except Exception as exc:self.failure.emit(str(exc))

class SimpleWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle(f'VeilPNG {__version__} · 图片工作台')
        self.resize(1160,780); self.setMinimumSize(760,520)
        self.mode=0; self.pages=[]; self.index=-1; self.active_side=0; self.busy=False; self.loading=False; self.dirty=False; self.worker=None; self.advanced=None; self.commit_action=None; self.project_path=None; self.project_revision=None
        self.setStyleSheet(STYLESHEET+'\nQWidget#projectRail {background:#FFFFFF;} QListWidget {background:white;border:1px solid #DCE5F1;border-radius:7px;} QListWidget::item {padding:8px;} QListWidget::item:selected {background:#E5EFFF;color:#1649B8;}')
        self._build(); self._refresh()
    def button(self,text,slot,primary=False):
        b=QPushButton(text); b.clicked.connect(slot)
        if primary:b.setObjectName('primary')
        return b
    def _build(self):
        root=QWidget(); root.setObjectName('workspaceRoot'); self.setCentralWidget(root)
        outer=QVBoxLayout(root); outer.setContentsMargins(12,10,12,10); outer.setSpacing(8)
        head=QHBoxLayout(); brand=QLabel('VeilPNG'); brand.setObjectName('title'); head.addWidget(brand)
        self.modes=QButtonGroup(self); self.modes.setExclusive(True)
        for i,name in enumerate(('单张','批量','中日配对')):
            b=self.button(name,lambda checked=False,i=i:self.switch_mode(i)); b.setCheckable(True); self.modes.addButton(b,i); head.addWidget(b)
        self.modes.button(0).setChecked(True); head.addStretch(1)
        self.folder_btn=self.button('导入文件夹',self.import_folder); head.addWidget(self.folder_btn)
        self.import_btn=self.button('导入图片',self.import_dialog,True); head.addWidget(self.import_btn)
        outer.addLayout(head)
        self.split=QSplitter(Qt.Orientation.Horizontal); outer.addWidget(self.split,1)
        rail=QWidget(); rail.setObjectName('projectRail'); rail.setMinimumWidth(150)
        left=QVBoxLayout(rail); left.setContentsMargins(8,8,8,8)
        self.queue_title=QLabel('图片列表'); self.queue_title.setObjectName('workspaceTitle'); left.addWidget(self.queue_title)
        self.search=QLineEdit(); self.search.setPlaceholderText('搜索文件名'); self.search.textChanged.connect(self._filter); left.addWidget(self.search)
        self.list=QListWidget(); self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle); left.addWidget(self.list,1)
        self.list.currentRowChanged.connect(self.select_page)
        nav=QHBoxLayout(); nav.addWidget(self.button('上一页',lambda:self._move(-1))); nav.addWidget(self.button('下一页',lambda:self._move(1))); left.addLayout(nav)
        self.queue_note=QLabel(); self.queue_note.setWordWrap(True); self.queue_note.setObjectName('muted'); left.addWidget(self.queue_note)
        self.split.addWidget(rail)
        work=QWidget(); layout=QVBoxLayout(work); layout.setContentsMargins(4,0,0,0); layout.setSpacing(6)
        self.page_title=QLabel('导入图片开始'); self.page_title.setWordWrap(True); self.page_title.setObjectName('workspaceTitle'); layout.addWidget(self.page_title)
        grid=QGridLayout(); grid.setSpacing(5)
        self.tool=QComboBox(); self.tool.addItems(['矩形','画笔','橡皮擦','套索','多边形','平移']); self.tool.currentIndexChanged.connect(self._tool)
        grid.addWidget(self.tool,0,0,1,2)
        self.brush=QSpinBox(); self.brush.setRange(2,250); self.brush.setValue(32); self.brush.setPrefix('笔刷 '); self.brush.valueChanged.connect(self._tool); grid.addWidget(self.brush,0,2,1,2)
        self.preview=QCheckBox('纯黑预览'); self.preview.toggled.connect(self._preview); grid.addWidget(self.preview,0,4,1,2)
        for col,(name,fn) in enumerate((('撤销',lambda:self._on_canvas('undo')),('重做',lambda:self._on_canvas('redo')),('清空',self._clear),('适应',self.fit))): grid.addWidget(self.button(name,fn),1,col)
        self.side=QComboBox(); self.side.addItems(['中文侧','日文侧']); self.side.currentIndexChanged.connect(self._side); grid.addWidget(self.side,1,4,1,2)
        for col in range(6):grid.setColumnStretch(col,1)
        layout.addLayout(grid)
        self.views=QSplitter(Qt.Orientation.Horizontal); self.canvases=[]; self.panes=[]; self.labels=[]
        for side in range(2):
            pane=QWidget(); p=QVBoxLayout(pane); p.setContentsMargins(0,0,0,0)
            label=QLabel('图片' if not side else '日文'); label.setObjectName('previewCaption'); p.addWidget(label)
            c=MaskCanvas(); c.setMinimumSize(90,100); c.set_conceal_style('solid',18,'#000000'); c.set_tool('rect'); p.addWidget(c,1)
            c.changed.connect(lambda i=side:self._changed(i)); self.canvases.append(c); self.panes.append(pane); self.labels.append(label); self.views.addWidget(pane)
        self.views.setStretchFactor(0,1); self.views.setStretchFactor(1,1); layout.addWidget(self.views,1); self.split.addWidget(work)
        self.split.setStretchFactor(0,0); self.split.setStretchFactor(1,1); self.split.setSizes([220,910])
        self.hint=QLabel('在画布上框选或涂抹，打开纯黑预览检查。配对模式在任一侧绘制后同步另一侧。'); self.hint.setWordWrap(True); self.hint.setObjectName('muted'); outer.addWidget(self.hint)
        bottom=QHBoxLayout(); self.summary=QLabel(); self.summary.setWordWrap(True); bottom.addWidget(self.summary,1)
        self.restore_exact=QCheckBox('严格原选区'); self.restore_exact.setToolTip('不修复选区外残影；适合必须保留邻近修改的页面'); bottom.addWidget(self.restore_exact)
        self.restore_current=self.button('导入 Gemini 图并恢复',self.restore_return_dialog); bottom.addWidget(self.restore_current)
        self.export_current=self.button('导出当前',lambda:self.export(False)); bottom.addWidget(self.export_current)
        self.export_all=self.button('导出已标记',lambda:self.export(True),True); bottom.addWidget(self.export_all); outer.addLayout(bottom)
        file_menu=self.menuBar().addMenu('文件')
        act=QAction('打开工作台项目…',self); act.triggered.connect(self.open_project_dialog); file_menu.addAction(act)
        act=QAction('保存工作台项目…',self); act.setShortcut(QKeySequence('Ctrl+S')); act.triggered.connect(lambda _checked=False:self.save_project_dialog()); file_menu.addAction(act)
        act=QAction('另存便携项目（包含私人原图）…',self); act.triggered.connect(lambda _checked=False:self.save_project_dialog(portable=True)); file_menu.addAction(act)
        file_menu.addSeparator()
        act=QAction('核验已有导出…',self); act.triggered.connect(self.verify_export_dialog); file_menu.addAction(act)
        act=QAction('导出说明：CLI 可直接读取当前工作台项目',self); act.setEnabled(False); file_menu.addAction(act)
        menu=self.menuBar().addMenu('专业工具'); act=QAction('打开经典工作台（加密、解密、中文移植等）',self); act.triggered.connect(self.open_advanced); menu.addAction(act)
        act=QAction('手动选择配准清单及目录…',self); act.triggered.connect(self.manual_pairs); menu.addAction(act)
        for title,shortcut,fn in [('导入','Ctrl+O',self.import_dialog),('撤销','Ctrl+Z',lambda:self._on_canvas('undo')),('重做','Ctrl+Shift+Z',lambda:self._on_canvas('redo')),('适应画布','Ctrl+0',self.fit)]:
            a=QAction(title,self); a.setShortcut(QKeySequence(shortcut)); a.triggered.connect(fn); self.addAction(a)
    def _confirm_discard(self):
        return not self.dirty or QMessageBox.question(self,'未保存选区','替换或关闭当前列表会丢失本次选区，确定继续？',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes
    def switch_mode(self,i):
        if self.busy or i==self.mode:
            self.modes.button(self.mode).setChecked(True); return
        if not self._confirm_discard(): self.modes.button(self.mode).setChecked(True); return
        self.mode=i; self._install([])
    def _install(self,pages):
        self.loading=True
        try:
            self.pages=pages; self.index=-1; self.dirty=False; self.project_path=None; self.project_revision=None; self.list.clear()
            self.search.blockSignals(True); self.search.clear(); self.search.blockSignals(False)
            for p in pages:self.list.addItem(QListWidgetItem(p.label))
            for c in self.canvases:
                c.original=None; c.mask=None; c.base_item.setPixmap(type(c.base_item.pixmap())()); c.overlay_item.setPixmap(type(c.overlay_item.pixmap())()); c.cancel_polygon()
            self.panes[1].setVisible(self.mode==2); self.side.setVisible(self.mode==2)
            self.modes.button(self.mode).setChecked(True)
        finally:self.loading=False
        if pages:self.list.setCurrentRow(0)
        self._refresh()
    def load_images(self,paths):
        pages=image_pages(paths)
        if self.mode==0 and len(pages)!=1:raise ValueError('单张模式只能导入一张图片')
        self._install(pages)
    def load_pairs(self,folder=None,**kwargs):
        pages=pair_pages(folder,**kwargs); self.mode=2; self._install(pages)
    def import_dialog(self):
        if self.busy:return
        try:
            if self.mode==2:
                folder=QFileDialog.getExistingDirectory(self,'选择已解压的 Folirina 配准目录')
                if folder and self._confirm_discard():self.load_pairs(folder)
            elif self.mode==0:
                path,_=QFileDialog.getOpenFileName(self,'选择图片','',FILTER)
                if path and self._confirm_discard():self.load_images([path])
            else:
                paths,_=QFileDialog.getOpenFileNames(self,'选择多张图片','',FILTER)
                if paths and self._confirm_discard():self.load_images(paths)
        except Exception as exc:self._error(exc)
    def import_folder(self):
        if self.busy or self.mode!=1:return
        folder=QFileDialog.getExistingDirectory(self,'选择批量图片文件夹（不含子目录）')
        if not folder or not self._confirm_discard():return
        try:self.load_images([p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in EXTS])
        except Exception as exc:self._error(exc)
    def manual_pairs(self):
        if self.busy:return
        csv,_=QFileDialog.getOpenFileName(self,'配准清单','','CSV (*.csv)')
        if not csv:return
        cn=QFileDialog.getExistingDirectory(self,'中文图片目录');
        if not cn:return
        jp=QFileDialog.getExistingDirectory(self,'日文图片目录');
        if not jp or not self._confirm_discard():return
        try:self.load_pairs(manifest=csv,source=cn,target=jp)
        except Exception as exc:self._error(exc)
    def _filter(self,q):
        for i,p in enumerate(self.pages):
            item=self.list.item(i)
            if item is not None:item.setHidden(q.casefold() not in p.label.casefold())
    def _move(self,delta):
        if self.busy:return
        i=self.index+delta
        while 0<=i<len(self.pages):
            if not self.list.item(i).isHidden():self.list.setCurrentRow(i); return
            i+=delta
    def select_page(self,i):
        if self.loading or self.busy or i<0 or i>=len(self.pages):return
        p=self.pages[i]
        try:
            images=[p.read(s) for s in range(len(p.paths))]; masks=[p.get_mask(s) for s in range(len(images))]
        except Exception as exc:
            self.list.blockSignals(True); self.list.setCurrentRow(self.index); self.list.blockSignals(False); self._error(exc);return
        self.loading=True
        try:
            self.index=i; self.active_side=0; self.side.setCurrentIndex(0)
            for s,img in enumerate(images):
                c=self.canvases[s]; c.set_document(img,masks[s]); c.set_preview(self.preview.isChecked()); self.labels[s].setText(('中文' if not s else '日文') if p.pair else '原图 / 遮盖预览')
            self.panes[1].setVisible(bool(p.pair)); self.side.setVisible(bool(p.pair)); self.page_title.setText(p.label)
        finally:self.loading=False
        self._tool(); self._refresh(); QTimer.singleShot(0,self.fit)
    def _changed(self,s):
        if self.loading or self.index<0 or self.busy:return
        p=self.pages[self.index]; c=self.canvases[s]
        if s>=len(p.paths) or c.mask is None:return
        self.loading=True
        try:
            p.update(s,c.mask,action=self.commit_action or c.tool); self.active_side=s; self.side.setCurrentIndex(s); self.dirty=True
            if p.pair:
                other=self.canvases[1-s]; other.mask=p.get_mask(1-s); other.undo_stack.clear(); other.redo_stack.clear(); other._refresh_overlay()
        except Exception as exc:
            c.mask=p.get_mask(s); c.undo_stack.clear(); c.redo_stack.clear(); c._refresh_overlay(); self._error(exc)
        finally:self.loading=False
        self._refresh()
    def _side(self,s):
        if not self.loading:self.active_side=s if self.mode==2 else 0
    def _tool(self,*_):
        for c in self.canvases:c.set_tool(TOOLS[self.tool.currentIndex()]); c.brush_size=self.brush.value()
    def _preview(self,on):
        for c in self.canvases:c.set_preview(on)
    def _on_canvas(self,action):
        if self.index>=0 and not self.busy:
            self.commit_action=action
            try:getattr(self.canvases[self.active_side],action)()
            finally:self.commit_action=None
    def _clear(self):
        if self.index>=0 and QMessageBox.question(self,'清空选区','清空当前页（配对时两侧）的遮盖？',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes:self._on_canvas('clear_mask')
    def fit(self):
        for c in self.canvases:
            if c.original is not None and c.isVisible():c.zoom_fit()
    def _refresh(self):
        n=sum(p.ready for p in self.pages)
        for i,p in enumerate(self.pages):self.list.item(i).setText(('✓ ' if p.ready else '○ ')+p.label)
        self.queue_note.setText(f'{n} / {len(self.pages)} 已标记\n切页保留本次选区')
        self.summary.setText(f'已标记 {n} / {len(self.pages)} · 未标记页不导出')
        self.import_btn.setText(('导入图片','导入多张','导入配准目录')[self.mode]); self.queue_title.setText(('当前图片','批量列表','配对列表')[self.mode])
        self.restore_current.setEnabled(self.index>=0 and bool(self.pages[self.index].masks) and not self.busy); self.export_current.setEnabled(self.index>=0 and self.pages[self.index].ready and not self.busy); self.export_all.setEnabled(n>0 and not self.busy)
        self.folder_btn.setVisible(self.mode==1); self.export_all.setVisible(self.mode!=0); self.panes[1].setVisible(self.mode==2); self.side.setVisible(self.mode==2)
        if self.index<0:self.page_title.setText('导入图片开始')
    def restore_return_dialog(self):
        if self.busy or self.index<0:return
        p=self.pages[self.index]; side=self.active_side
        if side not in p.masks:return self._error(ValueError('当前侧没有遮盖记录'))
        filename,_=QFileDialog.getOpenFileName(self,'选择当前侧 Gemini 回传图','',FILTER)
        if not filename:return
        try:
            from .return_restore import restore_return
            from .imaging import load_image,image_to_png_bytes
            result,report=restore_return(p.read(side),load_image(Path(filename).read_bytes()),p.get_mask(side),exact=self.restore_exact.isChecked())
            data=image_to_png_bytes(result)
            dlg=QDialog(self);dlg.setWindowTitle('恢复结果 · 请核对接缝');dlg.resize(900,720)
            v=QVBoxLayout(dlg);v.addWidget(QLabel(f"外侧修复 {report['exterior_changed']} 像素 · 修复 {report['halo_px']} px · 过渡 {report['feather_px']} px · 请检查文字和线条"))
            scroll=QScrollArea();label=QLabel();pix=QPixmap();pix.loadFromData(data);label.setPixmap(pix);scroll.setWidget(label);v.addWidget(scroll,1)
            buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);v.addWidget(buttons)
            if dlg.exec()!=QDialog.DialogCode.Accepted:return
            path,_=QFileDialog.getSaveFileName(self,'保存恢复 PNG',p.paths[side].stem+'_restored.png','PNG (*.png)')
            if not path:return
            dst=Path(path)
            if dst.suffix.lower()!='.png':dst=dst.with_suffix('.png')
            if dst.resolve() in (p.paths[side].resolve(),Path(filename).resolve()):raise ValueError('不能覆盖输入图片')
            dst.write_bytes(data);self.statusBar().showMessage('已保存 '+str(dst))
        except Exception as exc:self._error(exc)

    def export(self,all_pages):
        if self.busy or self.index<0:return
        folder=QFileDialog.getExistingDirectory(self,'选择输出目录（新建结果子目录）');
        if not folder:return
        selected=self.pages if all_pages else [self.pages[self.index]]
        self.busy=True; self.centralWidget().setEnabled(False); self._refresh()
        self.progress=QProgressDialog('正在导出普通遮盖 PNG…','取消',0,sum(len(p.paths) for p in selected if p.ready),self)
        self.progress.setWindowModality(Qt.WindowModality.WindowModal); self.progress.setAutoClose(False); self.progress.setAutoReset(False)
        self.worker=ExportThread(selected,folder,self); self.worker.progress.connect(lambda n,t:self.progress.setValue(n)); self.progress.canceled.connect(self.worker.stop.set)
        self.worker.success.connect(self._export_ok); self.worker.failure.connect(self._export_fail); self.worker.finished.connect(self._export_done); self.progress.show(); self.worker.start()
    def verify_export_dialog(self):
        if self.busy or self.index<0:return
        scope,ok=QInputDialog.getItem(self,'核验范围','请选择之前导出时使用的范围',['全部已标记','当前页'],0,False)
        if not ok:return
        folder=QFileDialog.getExistingDirectory(self,'选择已导出的结果子目录（包含 report.json）')
        if not folder:return
        selected=self.pages if scope=='全部已标记' else [self.pages[self.index]]
        self.busy=True; self.centralWidget().setEnabled(False); self._refresh()
        self.progress=QProgressDialog('正在核验选区、图片和报告…','',0,0,self)
        self.progress.setCancelButton(None); self.progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress.setAutoClose(False); self.progress.setAutoReset(False)
        self.worker=VerifyThread(selected,folder,self)
        self.worker.success.connect(self._verify_ok); self.worker.failure.connect(self._export_fail); self.worker.finished.connect(self._export_done)
        self.progress.show(); self.worker.start()
    def _verify_ok(self,path,report):
        self.progress.hide()
        status='核验通过' if report['passed'] else '核验未通过'
        counts={}
        for item in report['files']: counts[item['status']]=counts.get(item['status'],0)+1
        text='\n'.join([f'{k}: {v}' for k,v in counts.items()])
        text+=f"\n报告一致：{'是' if report['report_matches'] else '否'}\n额外文件：{len(report['unexpected_files'])}\n{path}"
        (QMessageBox.information if report['passed'] else QMessageBox.warning)(self,status,text)
    def _export_ok(self,path,report):
        self.progress.hide(); QMessageBox.information(self,'导出完成',f'已导出 {report["exported"]} 张，跳过 {report["skipped"]} 页。\n{path}\n普通 PNG，不含加密原图。')
    def _export_fail(self,message):self.progress.hide(); QMessageBox.warning(self,'导出未完成',message)
    def _export_done(self):
        self.progress.close(); self.progress.deleteLater(); self.worker.deleteLater(); self.worker=None; self.busy=False; self.centralWidget().setEnabled(True); self._refresh()
    def save_project_dialog(self, *, portable=False):
        if self.busy or not self.pages:return
        if portable and QMessageBox.question(self,'私人项目','便携项目将包含完整原始图片。请仅保存在可信的本地位置，不要公开分享。',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        folder=QFileDialog.getExistingDirectory(self,'选择工作台项目目录（建议新建目录）',str(self.project_path or ''))
        if not folder:return
        try:
            dest=Path(folder).resolve()
            same=dest==self.project_path
            report=save_workspace_project(self.pages,self.mode,dest,active_index=self.index,active_side=self.active_side,search_query=self.search.text(),portable=portable,new=not same,expected_revision=self.project_revision if same else None)
            self.project_path=dest; self.project_revision=report['revision']
            self.dirty=False
            QMessageBox.information(self,'项目已保存',f"已保存到\n{report['project_dir']}\n可用 CLI：python -m veilpng workspace-export --project-dir {report['project_dir']} --output-dir <输出目录>")
        except Exception as exc:self._error(exc)
    def open_project_dialog(self):
        if self.busy:return
        folder=QFileDialog.getExistingDirectory(self,'选择工作台项目目录（包含 workspace.json）')
        if not folder or not self._confirm_discard():return
        try:
            state=load_workspace_project(folder)
            self.mode=state['mode']; self._install(state['pages'])
            self.project_path=state['project_dir']; self.project_revision=state['revision']
            self.search.setText(state['search_query'])
            if state['pages']:
                row=state['active_index'] if 0 <= state['active_index'] < len(state['pages']) else 0
                self.list.setCurrentRow(row)
                if self.mode==2:
                    self.side.setCurrentIndex(state['active_side'] if state['active_side'] in (0,1) else 0)
            self.dirty=False
        except Exception as exc:self._error(exc)
    def _error(self,exc):QMessageBox.warning(self,'操作未完成',str(exc))
    def open_advanced(self):
        if self.advanced is None:
            from .gui import MainWindow
            self.advanced=MainWindow()
        self.advanced.show(); self.advanced.raise_()
    def closeEvent(self,event):
        if self.busy or not self._confirm_discard():event.ignore()
        else:event.accept()
