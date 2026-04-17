"""Find-in-files dialog.

Ctrl+Shift+F opens a modeless window that decompiles every class in
the active SWF (using the source cache when warm) and shows line
matches. Double-click a result to jump to it.

Search runs in the Qt event loop rather than a worker thread — the
decompile cache means repeat queries are cheap, and even a cold search
across 1000 classes finishes in a couple of seconds. We yield to the
event loop periodically via ``QApplication.processEvents`` so the UI
stays responsive.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from .. import actions
from ..state import StudioState
from ..theme import Palette


class FindInFilesDialog(QDialog):
    """Modeless — users often want to keep this open while navigating
    to matches."""

    def __init__(self, state: StudioState,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Find in Files")
        self.setModal(False)
        self.resize(720, 520)

        self.setStyleSheet(
            f"""
            QDialog {{
                background: {Palette.bg_surface};
            }}
            QLineEdit {{
                background: {Palette.bg_surface_2};
                color: {Palette.text_primary};
                border: 1px solid {Palette.border};
                border-radius: 4px;
                padding: 4px 8px;
            }}
            QLineEdit:focus {{
                border: 1px solid {Palette.accent_fg};
            }}
            QTreeWidget {{
                background: {Palette.bg_app};
                color: {Palette.text_primary};
                border: 1px solid {Palette.border};
                border-radius: 4px;
            }}
            QTreeWidget::item {{
                padding: 3px 4px;
            }}
            QTreeWidget::item:selected {{
                background: {Palette.bg_selected};
            }}
            QPushButton {{
                background: {Palette.bg_surface_2};
                color: {Palette.text_primary};
                border: 1px solid {Palette.border};
                border-radius: 4px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background: {Palette.bg_selected};
            }}
            """,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Search row.
        row = QHBoxLayout()
        row.setSpacing(8)
        self._input = QLineEdit(self)
        self._input.setPlaceholderText("Text to find across all classes")
        self._input.returnPressed.connect(self._run_search)
        row.addWidget(self._input, 1)

        self._case = QCheckBox("Case sensitive")
        row.addWidget(self._case)

        btn = QPushButton("Search")
        btn.setDefault(True)
        btn.clicked.connect(self._run_search)
        row.addWidget(btn)
        layout.addLayout(row)

        # Progress bar.
        self._progress = QProgressBar(self)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # Results tree — grouped by class.
        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(["Location", "Match"])
        self._tree.setColumnWidth(0, 260)
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.itemActivated.connect(self._on_activate)
        self._tree.itemDoubleClicked.connect(self._on_activate)
        layout.addWidget(self._tree, 1)

        # Status line.
        self._status = QLabel("")
        self._status.setStyleSheet(
            f"color: {Palette.text_muted}; font-size: 11px;"
        )
        layout.addWidget(self._status)

        esc = QShortcut(QKeySequence("Esc"), self)
        esc.activated.connect(self.close)

        self._input.setFocus()

    # ── search ─────────────────────────────────────────────────────

    def _run_search(self) -> None:
        needle = self._input.text().strip()
        self._tree.clear()
        if not needle:
            self._status.setText("")
            return

        self._progress.setRange(0, 0)  # busy indicator until first callback
        self._progress.setVisible(True)
        self._status.setText("Searching…")
        QApplication.processEvents()

        def on_progress(done: int, total: int) -> None:
            self._progress.setRange(0, total)
            self._progress.setValue(done)
            QApplication.processEvents()

        hits = actions.find_in_all(
            self.state, needle,
            case_sensitive=self._case.isChecked(),
            progress_cb=on_progress,
        )

        self._progress.setVisible(False)

        if not hits:
            self._status.setText("No results")
            return

        # Group by class.
        by_class: dict[str, list[actions.FindHit]] = {}
        for h in hits:
            by_class.setdefault(h.class_full_name, []).append(h)

        for full_name, group in sorted(by_class.items()):
            short = group[0].class_short_name
            parent = QTreeWidgetItem(self._tree)
            parent.setText(0, f"{short}  ({full_name})")
            parent.setText(1, f"{len(group)} matches")
            parent.setExpanded(True)
            parent.setData(0, Qt.UserRole, ("class", full_name, -1))
            for h in group:
                child = QTreeWidgetItem(parent)
                child.setText(0, f"  line {h.line_number}")
                child.setText(1, h.line_text.strip())
                child.setData(0, Qt.UserRole,
                              ("line", full_name, h.line_number))

        self._status.setText(
            f"{len(hits)} matches in {len(by_class)} classes",
        )

    def _on_activate(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, full_name, line = data
        if kind == "line":
            self.state.jump_to(full_name, line=int(line))
        else:
            self.state.jump_to(full_name)
