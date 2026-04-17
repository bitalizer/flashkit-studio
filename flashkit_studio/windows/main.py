"""Main window: menu bar, splitter with sidebar + editor, status bar."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
    QMainWindow, QPushButton, QSplitter, QStatusBar, QVBoxLayout,
    QWidget,
)

from .. import actions
from ..state import StudioState
from ..theme import Scale
from .editor import Editor
from .sidebar import Sidebar


class MainWindow(QMainWindow):
    def __init__(self, state: StudioState) -> None:
        super().__init__()
        self.state = state

        self.setWindowTitle("FlashKit Studio")
        self.resize(1360, 840)

        # Splitter: sidebar | editor.
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

        # Wire sidebar → state.
        self.sidebar.classClicked.connect(state.open_class)

        # Menu bar.
        self._build_menu()

        # Status bar.
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
        mb.setNativeMenuBar(False)  # keep our stylesheet on mac too

        # File
        m_file = mb.addMenu("File")

        act_open = QAction("Open SWF…", self)
        act_open.setShortcut(QKeySequence("Ctrl+O"))
        act_open.triggered.connect(self._open_dialog)
        m_file.addAction(act_open)

        self.m_export = m_file.addMenu("Export")
        self.act_export_sel = QAction("Export Selection…", self)
        self.act_export_sel.triggered.connect(self._export_selection_dialog)
        self.m_export.addAction(self.act_export_sel)
        self.act_export_all = QAction("Export All…", self)
        self.act_export_all.triggered.connect(self._export_all_dialog)
        self.m_export.addAction(self.act_export_all)

        m_file.addSeparator()

        self.act_close_swf = QAction("Close SWF", self)
        self.act_close_swf.setShortcut(QKeySequence("Ctrl+Shift+W"))
        self.act_close_swf.triggered.connect(self._close_current_swf)
        m_file.addAction(self.act_close_swf)

        m_file.addSeparator()

        act_exit = QAction("Exit", self)
        act_exit.setShortcut(QKeySequence("Alt+F4"))
        act_exit.triggered.connect(self.close)
        m_file.addAction(act_exit)

        # Edit
        m_edit = mb.addMenu("Edit")
        self.act_copy_view = QAction("Copy Current View", self)
        self.act_copy_view.setShortcut(QKeySequence("Ctrl+C"))
        self.act_copy_view.triggered.connect(self._copy_current_view)
        m_edit.addAction(self.act_copy_view)

        # Close tab shortcut — Ctrl+W, not in menu (intentional, the
        # right-click tab menu owns close actions).
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
        act_about = QAction("About FlashKit Studio", self)
        act_about.triggered.connect(self._show_about)
        m_help.addAction(act_about)

        # Keep menu item enabled-ness in sync with state.
        self.state.active_resource_changed.connect(self._refresh_menu_enabled)
        self.state.tabs_changed.connect(self._refresh_menu_enabled)
        self._refresh_menu_enabled()

    def _refresh_menu_enabled(self) -> None:
        r = self.state.active_resource()
        cls = self.state.active_class()
        has_swf = r is not None
        has_class = cls is not None
        # Disable the whole Export submenu when nothing's loaded so
        # the arrow chevron reads disabled too.
        self.m_export.menuAction().setEnabled(has_swf)
        self.act_export_sel.setEnabled(has_class)
        self.act_export_all.setEnabled(has_swf)
        self.act_close_swf.setEnabled(has_swf)
        self.act_copy_view.setEnabled(has_class)

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

    def _show_about(self) -> None:
        dlg = _AboutDialog(self)
        dlg.exec()

    def _set_sidebar_side(self, side: str) -> None:
        left = side == "left"
        self.act_side_left.setChecked(left)
        self.act_side_right.setChecked(not left)
        # Swap splitter order to move sidebar.
        sidebar = self.sidebar
        editor  = self.editor
        # Remove both widgets (without destroying) and re-add in the
        # new order. QSplitter keeps hidden references; we use
        # insertWidget to reorder.
        self.splitter.insertWidget(0 if left else 1, sidebar)
        self.splitter.insertWidget(0 if not left else 1, editor)
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


# ── About dialog ─────────────────────────────────────────────────────────


class _AboutDialog(QDialog):
    """Modal info panel shown from Help → About."""

    _REPO_URL = "https://github.com/bitalizer/flashkit"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About FlashKit Studio")
        self.setModal(True)
        self.setFixedWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(10)

        # Package version — pulled from the studio package metadata.
        try:
            from .. import __version__ as app_version
        except Exception:
            app_version = "0.1.0"

        title = QLabel("FlashKit Studio")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        subtitle = QLabel(f"Version {app_version}")
        subtitle.setStyleSheet("color: #a7abb3; font-size: 12px;")
        layout.addWidget(subtitle)

        layout.addSpacing(6)

        desc = QLabel(
            "A desktop SWF inspector built on the flashkit library.\n"
            "Open, browse, and decompile AVM2 bytecode",
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #e4e6ea;")
        layout.addWidget(desc)

        layout.addSpacing(6)

        repo_row = QHBoxLayout()
        repo_row.setSpacing(6)
        repo_label = QLabel("GitHub:")
        repo_label.setStyleSheet("color: #6d727b;")
        repo_row.addWidget(repo_label)

        repo_link = QLabel(
            f'<a style="color:#5e9ce6; text-decoration:none;" '
            f'href="{self._REPO_URL}">bitalizer/flashkit</a>',
        )
        repo_link.setOpenExternalLinks(True)
        repo_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        repo_row.addWidget(repo_link, 1)
        layout.addLayout(repo_row)

        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        # Also provide a button to open the repo in the default browser.
        open_btn = QPushButton("Open Repository")
        open_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(self._REPO_URL)),
        )
        buttons.addButton(open_btn, QDialogButtonBox.ActionRole)

        layout.addWidget(buttons)
