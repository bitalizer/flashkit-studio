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

import re

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction, QColor, QCursor, QFontMetrics, QKeySequence, QMouseEvent,
    QPainter, QPen, QShortcut, QTextCharFormat, QTextCursor, QTextDocument,
)
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QPlainTextEdit, QPushButton, QSizePolicy,
    QSplitter, QStackedWidget, QTabBar, QTabWidget, QTextEdit, QToolButton,
    QVBoxLayout, QWidget,
)

from .. import actions
from ..highlighter import As3Highlighter
from ..state import StudioState, ClassEntry
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

        # Tab bar + (later) welcome state live in a stacked widget.
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        # Page 0: welcome.
        self.welcome = _Welcome()
        self.stack.addWidget(self.welcome)

        # Page 1: breadcrumb ∪ (tabs + outline) ∪ view-bar.
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        self.breadcrumb = _Breadcrumb()
        page_layout.addWidget(self.breadcrumb)

        # Horizontal splitter: code area on the left, outline on the
        # right. Outline is user-resizable and remembers its width via
        # the parent window's splitter-state persistence (QSettings).
        self.mid_split = QSplitter(Qt.Horizontal)
        self.mid_split.setHandleWidth(1)
        self.mid_split.setChildrenCollapsible(False)
        page_layout.addWidget(self.mid_split, 1)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        # We supply our own per-tab close button (``_CloseButton``)
        # via ``QTabBar.setTabButton`` so the × glyph renders crisply
        # on HiDPI — Qt's default ``tabsClosable`` button is a small
        # raster pixmap that looks fuzzy on scaled displays.
        self.tabs.setTabsClosable(False)
        self.tabs.setMovable(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(self._on_current_changed)
        self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._on_tab_context_menu)
        # Tab bar also needs right-click for clicks on the bar itself.
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._on_tab_context_menu)
        self.mid_split.addWidget(self.tabs)

        self.outline = _Outline(state)
        self.mid_split.addWidget(self.outline)
        self.mid_split.setStretchFactor(0, 1)
        self.mid_split.setStretchFactor(1, 0)
        self.mid_split.setSizes([900, 240])

        # Bottom view bar.
        self.view_bar = _ViewBar()
        self.view_bar.viewChanged.connect(self._on_view_changed)
        page_layout.addWidget(self.view_bar)

        self.stack.addWidget(page)

        # ── state ─────────────────────────────────────────────
        self._editors: dict[str, _CodeView] = {}

        state.active_resource_changed.connect(self._rebuild)
        state.tabs_changed.connect(self._rebuild)
        state.view_changed.connect(self._on_state_view_changed)
        state.jump_requested.connect(self._on_jump_requested)

        self._rebuild()

    # ── wiring ───────────────────────────────────────────────────

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
            # Still clear any leftover tabs/editors.
            self._sync_tabs([])
            return

        self.stack.setCurrentIndex(1)
        self._sync_tabs(r.open_class_tabs)

        # Update text for the active tab.
        if r.active_class_full_name:
            idx = self._index_of(r.active_class_full_name)
            if idx >= 0:
                self.tabs.blockSignals(True)
                self.tabs.setCurrentIndex(idx)
                self.tabs.blockSignals(False)
            self._refresh_current_text()

        # View bar reflects active view.
        self.view_bar.set_active(self.state.active_view)

        # Breadcrumb + outline.
        self.breadcrumb.set_for(
            self.state.active_class(),
            package=(self.state.active_class().package
                     if self.state.active_class() else ""),
        )
        self.outline.set_for(r, r.active_class_full_name)

    def _sync_tabs(self, open_names: list[str]) -> None:
        """Make `self.tabs` mirror ``open_names``. Avoid rebuilding
        every frame — only add/remove where needed so the user's
        scroll position is preserved."""
        current_names = []
        for i in range(self.tabs.count()):
            current_names.append(self.tabs.tabBar().tabData(i))

        # Remove tabs that are no longer open.
        for i in reversed(range(self.tabs.count())):
            name = self.tabs.tabBar().tabData(i)
            if name not in open_names:
                w = self.tabs.widget(i)
                self.tabs.removeTab(i)
                if isinstance(w, _CodeView):
                    self._editors.pop(name, None)
                w.deleteLater()

        # Add newly-opened tabs.
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
            editor = _CodeView(self.state, self)
            self._editors[name] = editor
            idx = self.tabs.addTab(editor, short)
            self.tabs.tabBar().setTabData(idx, name)
            self.tabs.setTabToolTip(idx, name)

            # Attach our own HiDPI-crisp close button to the tab's
            # trailing (right-hand) side.
            close_btn = _CloseButton(self.tabs.tabBar())
            close_btn.clicked.connect(
                lambda _checked=False, n=name: self.state.close_class_tab(n)
            )
            self.tabs.tabBar().setTabButton(
                idx, QTabBar.ButtonPosition.RightSide, close_btn,
            )

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

    # ── slots ────────────────────────────────────────────────────

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

    def _on_jump_requested(self, full_name: str, member: str, line: int) -> None:
        """Called by the symbol palette, Find-in-Files, Go-to-Line, and
        jump-to-definition. Makes sure we're on source view, then
        scrolls the code view to ``line`` (1-based) or to the first
        occurrence of ``member`` as a definition keyword."""
        # Switch to Source — the line/member match only exists there.
        if self.state.active_view != "source":
            self.state.set_active_view("source")
        code = self._editors.get(full_name)
        if code is None:
            # Tab not yet built (just opened); _rebuild will run next.
            return
        if line > 0:
            code.scroll_to_line(line)
        elif member:
            code.scroll_to_member(member)

    def _on_tab_context_menu(self, pos) -> None:
        bar = self.tabs.tabBar()
        idx = bar.tabAt(pos)
        if idx < 0:
            return
        name = bar.tabData(idx)
        if not name:
            return

        menu = QMenu(self)
        act_close  = menu.addAction("Close")
        act_others = menu.addAction("Close Others")
        act_all    = menu.addAction("Close All")
        menu.addSeparator()
        act_copy   = menu.addAction("Copy Path")

        act_others.setEnabled(self.tabs.count() > 1)
        act_all.setEnabled(self.tabs.count() >= 1)

        chosen = menu.exec(bar.mapToGlobal(pos))
        if chosen is act_close:
            self.state.close_class_tab(name)
        elif chosen is act_others:
            self.state.close_other_class_tabs(name)
        elif chosen is act_all:
            self.state.close_all_class_tabs()
        elif chosen is act_copy:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(name)
            self.state.set_status(f"Copied {name} to clipboard")


# ── custom tab close button (HiDPI-crisp) ────────────────────────────────


class _CloseButton(QAbstractButton):
    """A 16×16 close button that draws its own × with antialiased
    strokes. Scales perfectly on HiDPI where Qt's default close-tab
    pixmap looks blurry."""

    _ICON_SIZE = 16

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFixedSize(self._ICON_SIZE, self._ICON_SIZE)
        self.setToolTip("Close tab")
        self.setFocusPolicy(Qt.NoFocus)

    def sizeHint(self) -> QSize:
        return QSize(self._ICON_SIZE, self._ICON_SIZE)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # Rounded background on hover.
        if self.underMouse():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(Palette.bg_surface_2))
            p.drawRoundedRect(self.rect(), 3, 3)
            x_color = QColor(Palette.text_primary)
        else:
            x_color = QColor(Palette.text_muted)

        pen = QPen(x_color, 1.5, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)

        pad = 5
        r = QRect(pad, pad,
                  self.width() - pad * 2, self.height() - pad * 2)
        p.drawLine(r.topLeft(), r.bottomRight())
        p.drawLine(r.topRight(), r.bottomLeft())
        p.end()

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)


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


class _CodeView(QWidget):
    """Composite widget: find bar on top, code editor below.

    Find bar appears on Ctrl+F (Cmd+F on mac), hides on Esc. Search
    uses Qt's native ``QTextDocument.find`` so case-insensitive /
    wrap-around behaviour is handled natively.

    Holds a reference to the owning ``StudioState`` so the editor can
    resolve jump-to-definition lookups against the global symbol
    index without threading state through every call.
    """

    def __init__(self, state: StudioState,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._editor = _PlainCodeEditor(self)
        self._editor.jumpRequested.connect(self._resolve_and_jump)
        self._find   = _FindBar(self._editor, self)
        self._find.setVisible(False)

        layout.addWidget(self._find)
        layout.addWidget(self._editor, 1)

        # Cross-platform standard shortcut (Ctrl+F / Cmd+F).
        sc_find = QShortcut(QKeySequence.StandardKey.Find, self)
        sc_find.setContext(Qt.WidgetWithChildrenShortcut)
        sc_find.activated.connect(self._find.show_and_focus)

        sc_next = QShortcut(QKeySequence.StandardKey.FindNext, self)
        sc_next.setContext(Qt.WidgetWithChildrenShortcut)
        sc_next.activated.connect(self._find.find_next)

        sc_prev = QShortcut(QKeySequence.StandardKey.FindPrevious, self)
        sc_prev.setContext(Qt.WidgetWithChildrenShortcut)
        sc_prev.activated.connect(self._find.find_prev)

        # F12 — jump to definition of the word under the cursor.
        sc_def = QShortcut(QKeySequence("F12"), self)
        sc_def.setContext(Qt.WidgetWithChildrenShortcut)
        sc_def.activated.connect(self._jump_to_cursor_word)

    # ── jump-to-definition ────────────────────────────────────────

    def _jump_to_cursor_word(self) -> None:
        cur = self._editor.textCursor()
        cur.select(QTextCursor.WordUnderCursor)
        word = cur.selectedText().strip()
        if word:
            self._resolve_and_jump(word)

    def _resolve_and_jump(self, word: str) -> None:
        """Resolve ``word`` against the global symbol index. Prefers an
        exact class-name match, then a unique method/field match; if
        the word is ambiguous (same method name on many classes) we
        open the palette pre-filled with it so the user can pick."""
        if self._state.active_resource() is None or not word:
            return
        symbols = actions.build_symbol_index(self._state)
        # Class hits first — exact short name or exact full name.
        for s in symbols:
            if s.kind == "class" and (
                s.class_short_name == word or s.class_full_name == word
            ):
                self._state.jump_to(s.class_full_name)
                return
        # Member hits.
        member_hits = [
            s for s in symbols
            if s.kind != "class" and s.member == word
        ]
        if len(member_hits) == 1:
            s = member_hits[0]
            self._state.jump_to(s.class_full_name, member=s.member)
            return
        if member_hits:
            # Ambiguous — open the palette pre-filled so the user chooses.
            from .palette import SymbolPalette
            dlg = SymbolPalette(self._state, self.window())
            dlg._input.setText(word)
            geo = self.window().geometry()
            dlg.move(
                geo.x() + (geo.width() - dlg.width()) // 2,
                geo.y() + 120,
            )
            dlg.exec()

    # ── API expected by the editor container ──────────────────────

    def toPlainText(self) -> str:
        return self._editor.toPlainText()

    def set_text(self, text: str) -> None:
        self._editor.setPlainText(text)
        self._editor.verticalScrollBar().setValue(0)

    def scroll_to_line(self, line: int) -> None:
        """Centre the editor on the given 1-based line number."""
        block = self._editor.document().findBlockByLineNumber(
            max(0, line - 1),
        )
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        self._editor.setTextCursor(cursor)
        self._editor.centerCursor()
        self._editor.setFocus()

    def scroll_to_member(self, member: str) -> None:
        """Find ``function member(`` or ``function get/set member(`` or
        ``var member`` / ``const member`` in the current source and
        scroll to it. Falls back to a plain-text ``member`` search if
        none of the definition forms match."""
        if not member:
            return
        text = self._editor.toPlainText()
        patterns = [
            rf"\bfunction\s+(?:get|set)\s+{re.escape(member)}\b",
            rf"\bfunction\s+{re.escape(member)}\b",
            rf"\b(?:var|const)\s+{re.escape(member)}\b",
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                line = text.count("\n", 0, m.start()) + 1
                self.scroll_to_line(line)
                return
        # Fallback — plain find.
        idx = text.find(member)
        if idx >= 0:
            line = text.count("\n", 0, idx) + 1
            self.scroll_to_line(line)


class _PlainCodeEditor(QPlainTextEdit):
    """Text pane with a left-side line-number gutter.

    The gutter is a sibling ``_LineNumberGutter`` widget positioned by
    ``resizeEvent`` and repainted whenever the editor scrolls or its
    block count changes. Keeping the gutter as a sibling (rather than
    a custom ``paintEvent`` on the editor itself) preserves
    ``QPlainTextEdit`` selection handling and HiDPI text rendering.
    """

    # Emitted when the user Ctrl+clicks a word; the payload is the
    # identifier under the cursor.
    jumpRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CodeEditor")
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setFont(code_font())
        self.setTabStopDistance(
            QFontMetrics(self.font()).horizontalAdvance(" ") * 4,
        )
        self._highlighter = As3Highlighter(self.document())

        self._gutter = _LineNumberGutter(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._on_update_request)
        self._update_gutter_width()

        self.setMouseTracking(True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (event.button() == Qt.LeftButton
                and event.modifiers() & Qt.ControlModifier):
            cursor = self.cursorForPosition(event.pos())
            cursor.select(QTextCursor.WordUnderCursor)
            word = cursor.selectedText().strip()
            if word:
                self.jumpRequested.emit(word)
                event.accept()
                return
        super().mousePressEvent(event)

    # ── gutter plumbing ─────────────────────────────────────────────

    def gutter_width(self) -> int:
        count = max(1, self.blockCount())
        digits = len(str(count))
        # Two chars of padding on either side of the number.
        char = QFontMetrics(self.font()).horizontalAdvance("9")
        return 12 + char * digits + 8

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _on_update_request(self, rect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(
            QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()),
        )

    def paint_gutter(self, event) -> None:
        from PySide6.QtGui import QPainter as _QPainter

        painter = _QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor(Palette.bg_app))

        block = self.firstVisibleBlock()
        block_num = block.blockNumber()
        top = int(self.blockBoundingGeometry(block)
                  .translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        current_block = self.textCursor().blockNumber()
        active_color = QColor(Palette.text_secondary)
        idle_color = QColor(Palette.text_disabled)
        painter.setFont(self.font())
        right_pad = 8

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(active_color if block_num == current_block
                               else idle_color)
                painter.drawText(
                    0, top,
                    self._gutter.width() - right_pad,
                    QFontMetrics(self.font()).height(),
                    Qt.AlignRight,
                    str(block_num + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_num += 1
        painter.end()


class _LineNumberGutter(QWidget):
    """Thin left-side widget that delegates its painting to the host
    ``_PlainCodeEditor`` — the editor is what knows the text block
    geometry."""

    def __init__(self, editor: "_PlainCodeEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_gutter(event)


class _FindBar(QFrame):
    """Slim search strip that floats above the code editor.

    Wire:
    - text change -> live incremental search from cursor forward
    - Enter        -> find next
    - Shift+Enter  -> find previous
    - Esc          -> close and return focus to editor
    """

    def __init__(
        self,
        editor: QPlainTextEdit,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._editor = editor
        self.setObjectName("FindBar")
        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 8, 6)
        layout.setSpacing(6)

        self._input = QLineEdit(self)
        self._input.setObjectName("FindInput")
        self._input.setPlaceholderText("Find")
        self._input.setFixedHeight(28)
        self._input.textChanged.connect(self._on_text_changed)
        self._input.returnPressed.connect(self.find_next)
        layout.addWidget(self._input, 1)

        # Status label sits inside the line-edit column (not beside it)
        # so it doesn't create a second coloured block when empty.
        self._status = QLabel("", self)
        self._status.setObjectName("FindStatus")
        self._status.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._status.setVisible(False)
        layout.addWidget(self._status)

        prev = QToolButton(self)
        prev.setObjectName("FindNav")
        prev.setText("▲")
        prev.setFixedSize(24, 28)
        prev.setCursor(QCursor(Qt.PointingHandCursor))
        prev.setToolTip("Previous (Shift+Enter)")
        prev.clicked.connect(self.find_prev)
        layout.addWidget(prev)

        nxt = QToolButton(self)
        nxt.setObjectName("FindNav")
        nxt.setText("▼")
        nxt.setFixedSize(24, 28)
        nxt.setCursor(QCursor(Qt.PointingHandCursor))
        nxt.setToolTip("Next (Enter)")
        nxt.clicked.connect(self.find_next)
        layout.addWidget(nxt)

        close = _CloseButton(self)
        close.setToolTip("Close Find (Esc)")
        close.clicked.connect(self.hide_and_refocus)
        layout.addWidget(close)

        # Esc closes when focus is inside the find bar.
        esc = QShortcut(QKeySequence("Esc"), self)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self.hide_and_refocus)

        # Scoped stylesheet — no inherited global surface / padding
        # confuses child widgets.
        self.setStyleSheet(
            f"""
            QFrame#FindBar {{
                background: {Palette.bg_surface};
                border-bottom: 1px solid {Palette.border};
            }}
            QFrame#FindBar QLineEdit#FindInput {{
                background: {Palette.bg_surface_2};
                color: {Palette.text_primary};
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 2px 8px;
                selection-background-color: {Palette.bg_selected};
            }}
            QFrame#FindBar QLineEdit#FindInput:focus {{
                border: 1px solid {Palette.accent_fg};
            }}
            QFrame#FindBar QLabel#FindStatus {{
                color: {Palette.text_muted};
                background: transparent;
                padding: 0 8px;
                font-size: 11px;
            }}
            QFrame#FindBar QToolButton#FindNav {{
                background: transparent;
                color: {Palette.text_muted};
                border: none;
                padding: 0;
                border-radius: 4px;
                font-size: 11px;
            }}
            QFrame#FindBar QToolButton#FindNav:hover {{
                background: {Palette.bg_surface_2};
                color: {Palette.text_primary};
            }}
            """,
        )

    # ── public slots ──────────────────────────────────────────────

    def show_and_focus(self) -> None:
        self.setVisible(True)
        self._input.setFocus(Qt.ShortcutFocusReason)
        self._input.selectAll()
        # If there's residual text in the query box, re-paint matches
        # so the user sees them immediately.
        if self._input.text():
            self._repaint_matches()
            self._refresh_count(self._input.text())

    def hide_and_refocus(self) -> None:
        self.setVisible(False)
        # Drop all match tints when the bar closes so the code view
        # returns to a clean state.
        self._editor.setExtraSelections([])
        self._editor.setFocus(Qt.OtherFocusReason)

    def find_next(self) -> None:
        self._find(forward=True, from_cursor=True)

    def find_prev(self) -> None:
        self._find(forward=False, from_cursor=True)

    # ── internals ────────────────────────────────────────────────

    def _on_text_changed(self, _text: str) -> None:
        # Re-paint all match highlights and jump to the first one.
        self._repaint_matches()
        cursor = self._editor.textCursor()
        cursor.setPosition(cursor.selectionStart())
        self._editor.setTextCursor(cursor)
        self._find(forward=True)

    def _find(self, *, forward: bool) -> None:
        needle = self._input.text()
        if not needle:
            self._set_status("")
            return

        flags = QTextDocument.FindFlag(0)
        if not forward:
            flags |= QTextDocument.FindBackward

        found = self._editor.find(needle, flags)
        if not found:
            # Wrap around.
            cursor = self._editor.textCursor()
            cursor.movePosition(
                QTextCursor.End if not forward else QTextCursor.Start,
            )
            self._editor.setTextCursor(cursor)
            found = self._editor.find(needle, flags)

        self._refresh_count(needle)

    def _repaint_matches(self) -> None:
        """Walk the whole document and mark every occurrence of the
        query with a tinted background via ``setExtraSelections``. This
        is what makes matches *visible* as the user scrolls — ``find()``
        alone only moves the cursor."""
        needle = self._input.text()
        if not needle:
            self._editor.setExtraSelections([])
            return

        match_fmt = QTextCharFormat()
        match_fmt.setBackground(QColor(Palette.accent_fg))
        # Darken the text so the accent-fg background stays readable.
        match_fmt.setForeground(QColor(Palette.bg_app))

        selections: list[QTextEdit.ExtraSelection] = []
        doc = self._editor.document()
        cursor = QTextCursor(doc)
        while True:
            cursor = doc.find(needle, cursor)
            if cursor.isNull() or not cursor.hasSelection():
                break
            sel = QTextEdit.ExtraSelection()
            sel.format = match_fmt
            sel.cursor = cursor
            selections.append(sel)

        self._editor.setExtraSelections(selections)
        self._match_count = len(selections)

    def _refresh_count(self, needle: str) -> None:
        if not needle:
            self._set_status("")
            return
        total = getattr(self, "_match_count", 0)
        if total == 0:
            self._set_status("No results")
            return
        # Figure out which match the cursor is currently sitting on.
        pos = self._editor.textCursor().selectionStart()
        doc = self._editor.document()
        nth = 0
        cursor = QTextCursor(doc)
        while True:
            cursor = doc.find(needle, cursor)
            if cursor.isNull() or not cursor.hasSelection():
                break
            nth += 1
            if cursor.selectionStart() >= pos:
                break
        self._set_status(f"{nth} of {total}")

    def _set_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))


# ── breadcrumb ───────────────────────────────────────────────────────────


class _Breadcrumb(QFrame):
    """Thin strip above the tab area showing ``package > ClassName``.

    A dedicated row so the current class identity is always visible
    even when tabs are scrolled off-screen on a wide workspace.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Breadcrumb")
        self.setFixedHeight(24)
        self.setStyleSheet(
            f"""
            QFrame#Breadcrumb {{
                background: {Palette.bg_surface};
                border-bottom: 1px solid {Palette.border};
            }}
            QFrame#Breadcrumb QLabel {{
                color: {Palette.text_muted};
                font-size: 11px;
                padding: 0 10px;
                background: transparent;
            }}
            QFrame#Breadcrumb QLabel#BreadcrumbName {{
                color: {Palette.text_primary};
                font-weight: 600;
            }}
            """,
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._label = QLabel("", self)
        layout.addWidget(self._label)
        layout.addStretch(1)

    def set_for(self, cls: ClassEntry | None, package: str = "") -> None:
        if cls is None:
            self._label.setText("")
            return
        pkg = package or cls.package or "(default)"
        self._label.setText(
            f"{pkg}  ›  <span style='color:{Palette.text_primary};"
            f"font-weight:600;'>{cls.name}</span>",
        )
        self._label.setTextFormat(Qt.RichText)


# ── outline pane ─────────────────────────────────────────────────────────


class _Outline(QFrame):
    """Right-side list of fields + methods for the active class.

    Updated whenever ``tabs_changed`` or ``active_resource_changed``
    fires. Clicking a row jumps the code view to the member.
    """

    _KIND_GLYPH = {
        "field": "⬥", "method": "ƒ", "getter": "›", "setter": "‹",
    }

    def __init__(self, state: StudioState,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.setObjectName("Outline")
        self.setMinimumWidth(180)
        self.setStyleSheet(
            f"""
            QFrame#Outline {{
                background: {Palette.bg_surface};
                border-left: 1px solid {Palette.border};
            }}
            QLabel#OutlineCaption {{
                color: {Palette.text_muted};
                font-size: 10px;
                font-weight: 600;
                letter-spacing: 1px;
                padding: 8px 10px 4px 10px;
                background: transparent;
            }}
            QListWidget#OutlineList {{
                background: transparent;
                color: {Palette.text_secondary};
                border: none;
                padding: 2px 4px;
                outline: 0;
                selection-background-color: {Palette.bg_selected};
                selection-color: {Palette.text_primary};
            }}
            QListWidget#OutlineList::item {{
                padding: 3px 6px;
                border-radius: 3px;
            }}
            QListWidget#OutlineList::item:hover {{
                background: {Palette.bg_surface_2};
            }}
            QListWidget#OutlineList::item:selected {{
                background: {Palette.bg_selected};
                color: {Palette.text_primary};
            }}
            """,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        caption = QLabel("OUTLINE", self)
        caption.setObjectName("OutlineCaption")
        layout.addWidget(caption)
        self._list = QListWidget(self)
        self._list.setObjectName("OutlineList")
        self._list.setUniformItemSizes(True)
        self._list.itemActivated.connect(self._on_activate)
        self._list.itemClicked.connect(self._on_activate)
        layout.addWidget(self._list, 1)

    def set_for(self, resource, full_name: str | None) -> None:
        self._list.clear()
        if resource is None or not full_name:
            return
        self._full_name = full_name
        members = actions.list_members(resource.resource, full_name)
        for m in members:
            glyph = self._KIND_GLYPH.get(m.kind, "•")
            static = " static" if m.is_static else ""
            label = f"{glyph}  {m.name}  : {m.type_name}{static}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, m.name)
            self._list.addItem(item)

    def _on_activate(self, item: QListWidgetItem) -> None:
        name = item.data(Qt.UserRole)
        if not name or not hasattr(self, "_full_name"):
            return
        self._state.jump_requested.emit(self._full_name, str(name), -1)


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
