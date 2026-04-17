"""Quick-open palette.

Ctrl+P brings up a narrow modal dialog with an input field and a
filtered list of every class, method, and field in the active SWF.
Typing fuzzy-matches; Enter jumps to the selected entry.

The fuzzy matcher here is a simple subsequence score with bonuses for
consecutive matches and word boundaries — good enough for the sizes we
deal with (tens of thousands of symbols at most) and predictable
enough that users can learn which abbreviations work. An external
fuzzy library would be heavier for no real benefit at this scale.
"""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog, QFrame, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import actions
from ..state import StudioState
from ..theme import Palette


_MAX_RESULTS = 200


class SymbolPalette(QDialog):
    """Centered modal. Fixed width, variable height up to a cap."""

    def __init__(self, state: StudioState,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Go to Symbol")
        self.setModal(True)
        self.setWindowFlags(
            Qt.Dialog | Qt.FramelessWindowHint,
        )
        self.setFixedWidth(640)

        self.setObjectName("Palette")
        self.setStyleSheet(
            f"""
            QDialog#Palette {{
                background: {Palette.bg_surface};
                border: 1px solid {Palette.border};
                border-radius: 8px;
            }}
            QDialog#Palette QLineEdit#PaletteInput {{
                background: {Palette.bg_surface_2};
                color: {Palette.text_primary};
                border: 1px solid {Palette.border};
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                selection-background-color: {Palette.bg_selected};
            }}
            QDialog#Palette QLineEdit#PaletteInput:focus {{
                border: 1px solid {Palette.accent_fg};
            }}
            QDialog#Palette QLabel#PaletteHint {{
                color: {Palette.text_muted};
                font-size: 11px;
                padding: 2px 4px;
            }}
            QDialog#Palette QListWidget {{
                background: transparent;
                color: {Palette.text_primary};
                border: none;
                outline: 0;
            }}
            QDialog#Palette QListWidget::item {{
                padding: 6px 10px;
                border-radius: 4px;
            }}
            QDialog#Palette QListWidget::item:hover {{
                background: {Palette.bg_surface_2};
            }}
            QDialog#Palette QListWidget::item:selected {{
                background: {Palette.bg_selected};
                color: {Palette.text_primary};
            }}
            """,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        layout.setSpacing(8)

        self._input = QLineEdit(self)
        self._input.setObjectName("PaletteInput")
        self._input.setPlaceholderText("Go to class, method, or field…")
        self._input.textChanged.connect(self._refresh)
        self._input.returnPressed.connect(self._accept_current)
        layout.addWidget(self._input)

        self._hint = QLabel(self)
        self._hint.setObjectName("PaletteHint")
        layout.addWidget(self._hint)

        self._list = QListWidget(self)
        self._list.setUniformItemSizes(True)
        self._list.itemActivated.connect(lambda _it: self._accept_current())
        layout.addWidget(self._list, 1)

        # Build the index once per open — SWFs aren't mutated under us.
        self._symbols = actions.build_symbol_index(state)
        self._hint.setText(
            f"{len(self._symbols)} symbols  ·  ↑↓ select  ·  Enter open  ·  Esc close"
        )
        self._refresh("")

        # Re-route up/down presses in the input into the list so the
        # user can drive both with the keyboard.
        self._input.installEventFilter(self)

    # ── filtering ──────────────────────────────────────────────────

    def _refresh(self, _text: str = "") -> None:
        query = self._input.text().strip()
        self._list.clear()
        if not self._symbols:
            return

        if not query:
            # No query — show the first N classes as a reasonable default.
            ranked: list[tuple[int, actions.Symbol]] = []
            for sym in self._symbols:
                if sym.kind == "class":
                    ranked.append((0, sym))
                if len(ranked) >= _MAX_RESULTS:
                    break
        else:
            ranked = _rank(self._symbols, query)[:_MAX_RESULTS]

        for _score, sym in ranked:
            item = QListWidgetItem(_format_row(sym))
            item.setData(Qt.UserRole, sym)
            item.setSizeHint(QSize(0, 26))
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)

    def _accept_current(self) -> None:
        item = self._list.currentItem()
        if item is None:
            self.reject()
            return
        sym: actions.Symbol = item.data(Qt.UserRole)
        self.state.jump_to(
            sym.class_full_name,
            member=sym.member or "",
        )
        self.accept()

    # ── keyboard routing ──────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        if obj is self._input and event.type() == event.Type.KeyPress:
            ke: QKeyEvent = event
            if ke.key() in (Qt.Key_Up, Qt.Key_Down):
                row = self._list.currentRow()
                delta = -1 if ke.key() == Qt.Key_Up else 1
                new_row = max(0, min(self._list.count() - 1, row + delta))
                self._list.setCurrentRow(new_row)
                return True
        return super().eventFilter(obj, event)


# ── fuzzy ranking ──────────────────────────────────────────────────


def _rank(symbols: Iterable[actions.Symbol],
          query: str) -> list[tuple[int, actions.Symbol]]:
    """Score every symbol against ``query`` and return the hits
    sorted best-first. A ``None`` score means no match."""
    q = query.lower()
    out: list[tuple[int, actions.Symbol]] = []
    for sym in symbols:
        score = _score(sym.label.lower(), q)
        if score is None:
            continue
        # Classes rank above members when scores tie — users most
        # often want the class itself.
        kind_bonus = 20 if sym.kind == "class" else 0
        out.append((score + kind_bonus, sym))
    out.sort(key=lambda t: -t[0])
    return out


def _score(haystack: str, needle: str) -> int | None:
    """Subsequence match score: every needle char must appear in order
    in haystack. More points for adjacent matches and for matches at
    word boundaries (dots, underscores, capitals). ``None`` = no match."""
    if not needle:
        return 0
    h_i = 0
    score = 0
    streak = 0
    prev_boundary = True
    for ch in needle:
        while h_i < len(haystack) and haystack[h_i] != ch:
            prev_boundary = haystack[h_i] in "._" or haystack[h_i].isupper()
            h_i += 1
            streak = 0
        if h_i >= len(haystack):
            return None
        # Match
        if streak > 0:
            score += 4
        if prev_boundary:
            score += 6
        score += 1
        streak += 1
        h_i += 1
        prev_boundary = False
    # Shorter hay = better match relative to query length.
    return score - len(haystack) // 32


def _format_row(sym: actions.Symbol) -> str:
    glyph = {"class": "▣", "method": "ƒ", "field": "◆"}.get(sym.kind, "•")
    if sym.kind == "class":
        pkg = sym.package or "(default)"
        return f"{glyph}  {sym.class_short_name}    {pkg}"
    return f"{glyph}  {sym.class_short_name}.{sym.member}    {sym.package or '(default)'}"
