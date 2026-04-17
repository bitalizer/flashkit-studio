"""Main window: menu bar, splitter with sidebar + editor, status bar."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog, QLabel, QMainWindow, QSplitter, QStatusBar, QWidget,
)

from .. import actions
from ..state import StudioState
from .editor import Editor
from .sidebar import Sidebar


class MainWindow(QMainWindow):
    def __init__(self, state: StudioState) -> None:
        super().__init__()
        self.state = state

        self.setWindowTitle("FlashKit Studio")
        self.resize(1360, 840)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(1)

        self.sidebar = Sidebar(state)
        self.editor  = Editor(state)

        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.editor)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([280, 1080])

        self.setCentralWidget(self.splitter)

        self.sidebar.classClicked.connect(state.open_class)

        self._build_menu()

        self.status = QStatusBar(self)
        self.setStatusBar(self.status)
        self._status_left = QLabel("Ready")
        self._status_right = QLabel("")
        self._status_right.setStyleSheet("color: #6d727b;")
        self.status.addWidget(self._status_left, 1)
        self.status.addPermanentWidget(self._status_right)

        state.status_changed.connect(self._on_status)
        state.resources_changed.connect(self._update_status_right)
        state.active_resource_changed.connect(self._update_status_right)

    # ── menu ───────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        mb = self.menuBar()
        mb.setNativeMenuBar(False)

        # File
        m_file = mb.addMenu("File")

        act_open = QAction("Open SWF…", self)
        act_open.setShortcut(QKeySequence("Ctrl+O"))
        act_open.triggered.connect(self._open_dialog)
        m_file.addAction(act_open)

        m_export = m_file.addMenu("Export")
        act_export_sel = QAction("Export Selection…", self)
        act_export_sel.triggered.connect(self._export_selection_dialog)
        m_export.addAction(act_export_sel)
        act_export_all = QAction("Export All…", self)
        act_export_all.triggered.connect(self._export_all_dialog)
        m_export.addAction(act_export_all)

        m_file.addSeparator()

        act_close_swf = QAction("Close SWF", self)
        act_close_swf.setShortcut(QKeySequence("Ctrl+Shift+W"))
        act_close_swf.triggered.connect(self._close_current_swf)
        m_file.addAction(act_close_swf)

        m_file.addSeparator()

        act_exit = QAction("Exit", self)
        act_exit.setShortcut(QKeySequence("Alt+F4"))
        act_exit.triggered.connect(self.close)
        m_file.addAction(act_exit)

        # Edit
        m_edit = mb.addMenu("Edit")
        act_copy_view = QAction("Copy Current View", self)
        act_copy_view.setShortcut(QKeySequence("Ctrl+C"))
        act_copy_view.triggered.connect(self._copy_current_view)
        m_edit.addAction(act_copy_view)

        act_close_tab = QAction(self)
        act_close_tab.setShortcut(QKeySequence("Ctrl+W"))
        act_close_tab.setShortcutContext(Qt.ApplicationShortcut)
        act_close_tab.triggered.connect(self._close_active_tab)
        self.addAction(act_close_tab)

        # View
        m_view = mb.addMenu("View")
        m_sidebar = m_view.addMenu("Sidebar Side")
        self.act_side_left  = QAction("Left",  self, checkable=True, checked=True)
        self.act_side_right = QAction("Right", self, checkable=True)
        self.act_side_left .triggered.connect(lambda: self._set_sidebar_side("left"))
        self.act_side_right.triggered.connect(lambda: self._set_sidebar_side("right"))
        m_sidebar.addAction(self.act_side_left)
        m_sidebar.addAction(self.act_side_right)

        # Help
        m_help = mb.addMenu("Help")
        act_about = QAction("About", self)
        act_about.triggered.connect(lambda: self.state.set_status(
            "FlashKit Studio — SWF inspector built on flashkit.",
        ))
        m_help.addAction(act_about)

    # ── actions ────────────────────────────────────────────────────

    def _open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open SWF", "",
            "SWF / SWZ (*.swf *.swz);;All Files (*)",
        )
        if path:
            actions.open_swf(self.state, path)

    def _export_all_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Export all classes to…", "",
        )
        if path:
            actions.export_all(self.state, path)

    def _export_selection_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Export selected class to…", "",
        )
        if path:
            actions.export_selection(self.state, path)

    def _close_current_swf(self) -> None:
        if self.state.active_resource_index is not None:
            self.state.close_resource(self.state.active_resource_index)

    def _copy_current_view(self) -> None:
        from PySide6.QtGui import QGuiApplication
        text = actions.render_view(self.state, self.state.active_view)
        QGuiApplication.clipboard().setText(text)
        self.state.set_status("Copied to clipboard")

    def _close_active_tab(self) -> None:
        r = self.state.active_resource()
        if r and r.active_class_full_name:
            self.state.close_class_tab(r.active_class_full_name)

    def _set_sidebar_side(self, side: str) -> None:
        left = side == "left"
        self.act_side_left.setChecked(left)
        self.act_side_right.setChecked(not left)
        self.splitter.insertWidget(0 if left else 1, self.sidebar)
        self.splitter.insertWidget(0 if not left else 1, self.editor)
        self.splitter.setSizes([280, self.width() - 280])

    # ── status bar ────────────────────────────────────────────────

    def _on_status(self, text: str, busy: bool, error: bool) -> None:
        prefix = "● " if busy else ""
        self._status_left.setText(prefix + text)
        if error:
            self._status_left.setStyleSheet("color: #ef6c6c;")
        else:
            self._status_left.setStyleSheet("color: #a7abb3;")
        self._update_status_right()

    def _update_status_right(self) -> None:
        r = self.state.active_resource()
        if r is None:
            self._status_right.setText("")
        else:
            self._status_right.setText(f"{len(r.classes)} classes")
