"""Editor panel: class tabs, code view, bottom view switcher.

Structure:

    ┌ tabs ─────────────────────────────── ┐
    │ Main ×   Commands ×   SaveData ×     │
    ├──────────────────────────────────────┤
    │   package { ... }                    │
    │                                      │
    ├ Source  P-Code  Traits  ...  ────────┤
    └──────────────────────────────────────┘

Class tabs use a native ``QTabWidget`` with close buttons. The text
pane is a ``QPlainTextEdit`` with our AS3 highlighter. The bottom
view switcher is a row of checkable ``QToolButton``s styled as pills.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QFontMetrics
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QStackedWidget,
    QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import actions
from ..highlighter import As3Highlighter
from ..state import StudioState
from ..theme import Palette, Scale, code_font


_VIEWS = [
    ("Source",     "source"),
    ("P-Code",     "disasm"),
    ("Traits",     "traits"),
    ("Strings",    "strings"),
    ("Multinames", "multinames"),
]


class Editor(QWidget):
    def __init__(self, state: StudioState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.welcome = _Welcome()
        self.stack.addWidget(self.welcome)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabCloseRequested.connect(self._on_close)
        self.tabs.currentChanged.connect(self._on_current_changed)
        page_layout.addWidget(self.tabs, 1)

        self.view_bar = _ViewBar()
        self.view_bar.viewChanged.connect(self._on_view_changed)
        page_layout.addWidget(self.view_bar)

        self.stack.addWidget(page)

        self._editors: dict[str, _CodeView] = {}

        state.active_resource_changed.connect(self._rebuild)
        state.tabs_changed.connect(self._rebuild)
        state.view_changed.connect(self._on_state_view_changed)

        self._rebuild()

    def _rebuild(self) -> None:
        r = self.state.active_resource()
        if r is None:
            self.welcome.set_text("No SWF loaded", "Press Ctrl+O to open one.")
            self.stack.setCurrentIndex(0)
            return
        if not r.open_class_tabs:
            self.welcome.set_text(
                "No class open", "Pick one from the sidebar.",
            )
            self.stack.setCurrentIndex(0)
            self._sync_tabs([])
            return

        self.stack.setCurrentIndex(1)
        self._sync_tabs(r.open_class_tabs)

        if r.active_class_full_name:
            idx = self._index_of(r.active_class_full_name)
            if idx >= 0:
                self.tabs.blockSignals(True)
                self.tabs.setCurrentIndex(idx)
                self.tabs.blockSignals(False)
            self._refresh_current_text()

        self.view_bar.set_active(self.state.active_view)

    def _sync_tabs(self, open_names: list[str]) -> None:
        for i in reversed(range(self.tabs.count())):
            name = self.tabs.tabBar().tabData(i)
            if name not in open_names:
                w = self.tabs.widget(i)
                self.tabs.removeTab(i)
                if isinstance(w, _CodeView):
                    self._editors.pop(name, None)
                w.deleteLater()

        present = set()
        for i in range(self.tabs.count()):
            present.add(self.tabs.tabBar().tabData(i))

        r = self.state.active_resource()
        if r is None:
            return

        for name in open_names:
            if name in present:
                continue
            cls = next((c for c in r.classes if c.full_name == name), None)
            short = cls.name if cls else name
            editor = _CodeView(self)
            self._editors[name] = editor
            idx = self.tabs.addTab(editor, short)
            self.tabs.tabBar().setTabData(idx, name)
            self.tabs.setTabToolTip(idx, name)

    def _refresh_current_text(self) -> None:
        r = self.state.active_resource()
        if r is None or not r.active_class_full_name:
            return
        editor = self._editors.get(r.active_class_full_name)
        if editor is None:
            return
        text = actions.render_view(self.state, self.state.active_view)
        if editor.toPlainText() != text:
            editor.set_text(text)

    def _index_of(self, full_name: str) -> int:
        for i in range(self.tabs.count()):
            if self.tabs.tabBar().tabData(i) == full_name:
                return i
        return -1

    def _on_close(self, idx: int) -> None:
        name = self.tabs.tabBar().tabData(idx)
        if name:
            self.state.close_class_tab(name)

    def _on_current_changed(self, idx: int) -> None:
        if idx < 0:
            return
        name = self.tabs.tabBar().tabData(idx)
        if not name:
            return
        self.state.focus_class_tab(name)
        self._refresh_current_text()

    def _on_view_changed(self, key: str) -> None:
        self.state.set_active_view(key)
        self._refresh_current_text()

    def _on_state_view_changed(self, _key: str) -> None:
        self.view_bar.set_active(self.state.active_view)
        self._refresh_current_text()


# ── bottom view bar ──────────────────────────────────────────────────────


class _ViewBar(QFrame):
    viewChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ViewBar")
        self.setFixedHeight(34)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(Scale.S, 0, Scale.S, 0)
        layout.setSpacing(Scale.XS)

        self._buttons: dict[str, QToolButton] = {}
        for label, key in _VIEWS:
            btn = QToolButton(self)
            btn.setText(label)
            btn.setCheckable(True)
            btn.setProperty("class", "viewpill")
            btn.setCursor(QCursor(Qt.PointingHandCursor))
            btn.clicked.connect(lambda _checked, k=key: self._on_click(k))
            layout.addWidget(btn)
            self._buttons[key] = btn

        layout.addStretch(1)

    def set_active(self, key: str) -> None:
        for k, btn in self._buttons.items():
            btn.setChecked(k == key)

    def _on_click(self, key: str) -> None:
        self.set_active(key)
        self.viewChanged.emit(key)


# ── code view ────────────────────────────────────────────────────────────


class _CodeView(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CodeEditor")
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setFont(code_font())
        self.setTabStopDistance(QFontMetrics(self.font()).horizontalAdvance(" ") * 4)

        self._highlighter = As3Highlighter(self.document())

    def set_text(self, text: str) -> None:
        self.setPlainText(text)
        self.verticalScrollBar().setValue(0)


# ── welcome page ─────────────────────────────────────────────────────────


class _Welcome(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Scale.S)
        layout.addStretch(3)

        self.title = QLabel()
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setStyleSheet(
            f"color: {Palette.text_secondary}; font-size: 18px; font-weight: 600;"
        )
        layout.addWidget(self.title)

        self.hint = QLabel()
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setStyleSheet(
            f"color: {Palette.text_muted}; font-size: 13px;"
        )
        layout.addWidget(self.hint)

        layout.addStretch(5)

    def set_text(self, title: str, hint: str) -> None:
        self.title.setText(title)
        self.hint.setText(hint)
