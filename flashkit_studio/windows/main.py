"""Main window: menu bar, splitter with sidebar + editor, status bar."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QInputDialog,
    QLabel, QMainWindow, QPushButton, QSplitter, QStatusBar,
    QVBoxLayout, QWidget,
)

from .. import actions, settings
from ..state import StudioState
from ..theme import Scale
from .editor import Editor
from .palette import SymbolPalette
from .sidebar import Sidebar


class MainWindow(QMainWindow):
    def __init__(self, state: StudioState) -> None:
        super().__init__()
        self.state = state

        self.setWindowTitle("FlashKit Studio")
        self.resize(1360, 840)
        self.setAcceptDrops(True)

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
        state.tabs_changed.connect(self._update_status_right)
        state.recent_changed.connect(self._rebuild_recent_menu)

        # Restore persisted window state if any.
        self._restore_window_state()

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

        self.m_recent = m_file.addMenu("Open Recent")
        self._rebuild_recent_menu()

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
        # Copy Current View copies the whole rendered text. No shortcut
        # — Ctrl+C is reserved for the native QPlainTextEdit selection
        # copy so a highlighted span copies only what's highlighted.
        self.act_copy_view = QAction("Copy Current View", self)
        self.act_copy_view.triggered.connect(self._copy_current_view)
        m_edit.addAction(self.act_copy_view)

        m_edit.addSeparator()

        self.act_find = QAction("Find…", self)
        self.act_find.setShortcut(QKeySequence.StandardKey.Find)
        self.act_find.triggered.connect(self._trigger_find)
        m_edit.addAction(self.act_find)

        self.act_find_all = QAction("Find in Files…", self)
        self.act_find_all.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self.act_find_all.triggered.connect(self._open_find_in_files)
        m_edit.addAction(self.act_find_all)

        m_edit.addSeparator()

        self.act_palette = QAction("Go to Symbol…", self)
        self.act_palette.setShortcut(QKeySequence("Ctrl+P"))
        self.act_palette.triggered.connect(self._open_palette)
        m_edit.addAction(self.act_palette)

        self.act_goto_line = QAction("Go to Line…", self)
        self.act_goto_line.setShortcut(QKeySequence("Ctrl+G"))
        self.act_goto_line.triggered.connect(self._open_goto_line)
        m_edit.addAction(self.act_goto_line)

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
        self.act_find.setEnabled(has_class)
        self.act_find_all.setEnabled(has_swf)
        self.act_palette.setEnabled(has_swf)
        self.act_goto_line.setEnabled(has_class)

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

    def _trigger_find(self) -> None:
        """Open the find bar inside whichever code view currently has
        the focused class tab."""
        r = self.state.active_resource()
        if r is None or not r.active_class_full_name:
            return
        editor_panel = self.editor
        code_view = editor_panel._editors.get(r.active_class_full_name)
        if code_view is None:
            return
        if hasattr(code_view, "_find"):
            code_view._find.show_and_focus()

    def _show_about(self) -> None:
        dlg = _AboutDialog(self)
        dlg.exec()

    def _set_sidebar_side(self, side: str) -> None:
        left = side == "left"
        self.act_side_left.setChecked(left)
        self.act_side_right.setChecked(not left)

        # Capture the *current* sidebar width so the user's resize
        # survives the swap — the old code hard-coded 280 and then
        # assigned it positionally, which put 280 on whichever widget
        # sat at index 0 (the editor, when moving to "right").
        sidebar_w = self.sidebar.width() or 280
        editor_w = max(self.width() - sidebar_w, 400)

        sidebar = self.sidebar
        editor  = self.editor
        # Remove both widgets (without destroying) and re-add in the
        # new order. QSplitter keeps hidden references; we use
        # insertWidget to reorder.
        self.splitter.insertWidget(0 if left else 1, sidebar)
        self.splitter.insertWidget(0 if not left else 1, editor)
        # Size vector must match the new *index* order, not the
        # widget identity, so we compose it from left-to-right.
        if left:
            self.splitter.setSizes([sidebar_w, editor_w])
        else:
            self.splitter.setSizes([editor_w, sidebar_w])
        settings.save_sidebar_side(side)

    def _open_palette(self) -> None:
        if self.state.active_resource() is None:
            return
        dlg = SymbolPalette(self.state, self)
        # Centre over the main window.
        geo = self.geometry()
        dlg.move(
            geo.x() + (geo.width() - dlg.width()) // 2,
            geo.y() + 120,
        )
        dlg.exec()

    def _open_find_in_files(self) -> None:
        if self.state.active_resource() is None:
            return
        # Late import to avoid a cycle when building the menu.
        from .find_all import FindInFilesDialog
        dlg = FindInFilesDialog(self.state, self)
        dlg.exec()

    def _open_goto_line(self) -> None:
        r = self.state.active_resource()
        if r is None or not r.active_class_full_name:
            return
        line, ok = QInputDialog.getInt(
            self, "Go to Line", "Line number:",
            1, 1, 999999, 1,
        )
        if ok:
            self.state.jump_requested.emit(
                r.active_class_full_name, "", int(line),
            )

    # ── recent SWFs ───────────────────────────────────────────────

    def _rebuild_recent_menu(self) -> None:
        self.m_recent.clear()
        recents = settings.recent_swfs()
        if not recents:
            placeholder = QAction("(no recent files)", self)
            placeholder.setEnabled(False)
            self.m_recent.addAction(placeholder)
            return
        for p in recents:
            act = QAction(str(p), self)
            act.triggered.connect(
                lambda _checked=False, path=str(p):
                    actions.open_swf(self.state, path),
            )
            self.m_recent.addAction(act)
        self.m_recent.addSeparator()
        clear = QAction("Clear Recent", self)
        clear.triggered.connect(self._clear_recent)
        self.m_recent.addAction(clear)

    def _clear_recent(self) -> None:
        settings.clear_recent_swfs()
        self._rebuild_recent_menu()

    # ── window state persistence ─────────────────────────────────

    def _restore_window_state(self) -> None:
        geo, state, splitter = settings.load_window_state()
        if geo:
            self.restoreGeometry(geo)
        if state:
            self.restoreState(state)
        if splitter:
            self.splitter.restoreState(splitter)
        # Restore sidebar side.
        side = settings.load_sidebar_side("left")
        if side == "right":
            # Call the same helper used by the menu so state + splitter
            # both update.
            self._set_sidebar_side("right")

    def closeEvent(self, event) -> None:
        settings.save_window_state(
            self.saveGeometry(),
            self.saveState(),
            self.splitter.saveState(),
        )
        super().closeEvent(event)

    # ── drag and drop (SWF files onto window) ────────────────────

    def dragEnterEvent(self, event) -> None:
        md = event.mimeData()
        if not md.hasUrls():
            event.ignore()
            return
        for url in md.urls():
            path = url.toLocalFile().lower()
            if path.endswith((".swf", ".swz")):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".swf", ".swz")):
                actions.open_swf(self.state, path)
        event.acceptProposedAction()

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
            return
        cls = self.state.active_class()
        if cls is None:
            self._status_right.setText(f"{len(r.classes)} classes")
            return
        ci = next(
            (c for c in r.resource.classes
             if c.qualified_name == cls.full_name),
            None,
        )
        if ci is None:
            self._status_right.setText(f"{len(r.classes)} classes")
            return
        methods = len(ci.all_methods)
        fields = len(ci.all_fields)
        self._status_right.setText(
            f"{len(r.classes)} classes  ·  "
            f"{cls.name}: {methods} methods, {fields} fields",
        )


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
