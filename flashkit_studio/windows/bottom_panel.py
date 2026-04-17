"""Bottom tabbed panel for References / Hierarchy / Bookmarks / Assets.

Hidden by default so it doesn't waste screen space on a fresh session.
Panels call ``show_tab(name)`` to pop the panel open on a specific
tab; the close button (X on the right) hides the whole strip.

The panel lives inside the editor's vertical layout (between the
view-bar and the window's bottom edge). It's a ``QFrame`` rather than
a QDockWidget so it tracks the main editor splitter naturally and
doesn't introduce floatable chrome we don't want.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QSizePolicy, QTabWidget, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import actions
from ..state import StudioState
from ..theme import Palette


class BottomPanel(QFrame):
    """Tab container. Each tab is a ``QWidget`` subclass in this file."""

    closed = Signal()

    def __init__(self, state: StudioState,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.setObjectName("BottomPanel")
        self.setMinimumHeight(160)
        self.setStyleSheet(
            f"""
            QFrame#BottomPanel {{
                background: {Palette.bg_surface};
                border-top: 1px solid {Palette.border};
            }}
            QFrame#BottomPanel QTabBar {{
                background: {Palette.bg_surface};
                border: none;
            }}
            QFrame#BottomPanel QTabBar::tab {{
                background: transparent;
                color: {Palette.text_muted};
                padding: 6px 12px;
                border: none;
            }}
            QFrame#BottomPanel QTabBar::tab:selected {{
                color: {Palette.text_primary};
                border-bottom: 2px solid {Palette.accent_fg};
            }}
            QFrame#BottomPanel QTabBar::tab:hover {{
                color: {Palette.text_secondary};
            }}
            QFrame#BottomPanel QTreeWidget,
            QFrame#BottomPanel QListWidget {{
                background: {Palette.bg_app};
                color: {Palette.text_primary};
                border: none;
                outline: 0;
            }}
            QFrame#BottomPanel QTreeWidget::item,
            QFrame#BottomPanel QListWidget::item {{
                padding: 3px 6px;
            }}
            QFrame#BottomPanel QTreeWidget::item:selected,
            QFrame#BottomPanel QListWidget::item:selected {{
                background: {Palette.bg_selected};
            }}
            QFrame#BottomPanel QLineEdit {{
                background: {Palette.bg_surface_2};
                color: {Palette.text_primary};
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 3px 8px;
            }}
            QFrame#BottomPanel QLineEdit:focus {{
                border: 1px solid {Palette.accent_fg};
            }}
            """,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header row with tabs + close button.
        header = QHBoxLayout()
        header.setContentsMargins(4, 2, 4, 0)
        header.setSpacing(2)
        self._tabs = QTabWidget(self)
        self._tabs.setDocumentMode(True)
        header.addWidget(self._tabs, 1)

        close = QToolButton(self)
        close.setText("×")
        close.setFixedSize(24, 24)
        close.setCursor(QCursor(Qt.PointingHandCursor))
        close.setStyleSheet(
            f"""
            QToolButton {{
                background: transparent;
                color: {Palette.text_muted};
                border: none;
                font-size: 16px;
            }}
            QToolButton:hover {{
                background: {Palette.bg_surface_2};
                color: {Palette.text_primary};
                border-radius: 3px;
            }}
            """,
        )
        close.clicked.connect(self._hide_self)
        header.addWidget(close, 0)
        layout.addLayout(header)

        # Tab pages.
        self.refs_tab = _ReferencesTab(state)
        self.hier_tab = _HierarchyTab(state)
        self.book_tab = _BookmarksTab(state)
        self.asset_tab = _AssetsTab(state)
        self._tabs.addTab(self.refs_tab, "References")
        self._tabs.addTab(self.hier_tab, "Hierarchy")
        self._tabs.addTab(self.book_tab, "Bookmarks")
        self._tabs.addTab(self.asset_tab, "Assets")

    # ── public API ────────────────────────────────────────────────

    def show_tab(self, name: str) -> None:
        idx = {"references": 0, "hierarchy": 1,
               "bookmarks": 2, "assets": 3}.get(name, 0)
        self._tabs.setCurrentIndex(idx)
        self.setVisible(True)

    def _hide_self(self) -> None:
        self.setVisible(False)
        self.closed.emit()


# ── References tab ─────────────────────────────────────────────────


class _ReferencesTab(QWidget):
    """Grouped by source-class, expandable. Double-click to jump."""

    def __init__(self, state: StudioState) -> None:
        super().__init__()
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._header = QLabel("Right-click a field or method in the outline "
                              "and pick Find References.")
        self._header.setStyleSheet(
            f"color: {Palette.text_muted}; font-size: 11px; padding: 2px;"
        )
        layout.addWidget(self._header)

        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(["Source", "Kind"])
        self._tree.setColumnWidth(0, 420)
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.itemActivated.connect(self._on_activate)
        self._tree.itemDoubleClicked.connect(self._on_activate)
        layout.addWidget(self._tree, 1)

    def set_results(self, title: str,
                    rows: list[actions.RefRow]) -> None:
        self._header.setText(title)
        self._tree.clear()
        if not rows:
            placeholder = QTreeWidgetItem(self._tree)
            placeholder.setText(0, "(no references)")
            placeholder.setDisabled(True)
            return
        by_class: dict[str, list[actions.RefRow]] = {}
        for row in rows:
            by_class.setdefault(row.source_class, []).append(row)
        for cls in sorted(by_class):
            group = QTreeWidgetItem(self._tree)
            group.setText(0, cls)
            group.setText(1, f"{len(by_class[cls])}")
            group.setExpanded(True)
            group.setData(0, Qt.UserRole, ("class", cls, -1))
            for row in by_class[cls]:
                child = QTreeWidgetItem(group)
                child.setText(0, f"    {row.source_member}")
                child.setText(1, row.ref_kind)
                child.setData(0, Qt.UserRole,
                              ("member", cls, row.source_member))

    def _on_activate(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, cls, member = data
        if kind == "member" and member:
            self.state.jump_to(cls, member=str(member))
        else:
            self.state.jump_to(cls)


# ── Hierarchy tab ──────────────────────────────────────────────────


class _HierarchyTab(QWidget):
    """Tree: root → … → current → subclasses. Indent depth shows the
    relation. Double-click to jump."""

    def __init__(self, state: StudioState) -> None:
        super().__init__()
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._header = QLabel("Select a class to see its hierarchy.")
        self._header.setStyleSheet(
            f"color: {Palette.text_muted}; font-size: 11px;"
        )
        layout.addWidget(self._header)

        self._list = QListWidget(self)
        self._list.itemActivated.connect(self._on_activate)
        self._list.itemDoubleClicked.connect(self._on_activate)
        layout.addWidget(self._list, 1)

    def set_results(self, class_full_name: str,
                    rows: list[actions.HierarchyRow]) -> None:
        self._header.setText(f"Hierarchy for {class_full_name}")
        self._list.clear()
        if not rows:
            item = QListWidgetItem("(no hierarchy info)")
            item.setFlags(Qt.NoItemFlags)
            self._list.addItem(item)
            return
        for row in rows:
            indent = "    " * (abs(row.depth))
            if row.relation == "self":
                text = f"{indent}◆ {row.class_full_name}"
                fg_role = Palette.text_primary
            elif row.relation == "super":
                text = f"{indent}↑ {row.class_full_name}"
                fg_role = Palette.text_secondary
            else:
                text = f"{indent}↓ {row.class_full_name}"
                fg_role = Palette.text_secondary
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, row.class_full_name)
            from PySide6.QtGui import QBrush, QColor
            item.setForeground(QBrush(QColor(fg_role)))
            self._list.addItem(item)

    def _on_activate(self, item: QListWidgetItem) -> None:
        name = item.data(Qt.UserRole)
        if not name:
            return
        self.state.jump_to(str(name))


# ── Bookmarks tab ──────────────────────────────────────────────────


class _BookmarksTab(QWidget):
    """All bookmarks in the active SWF, grouped by class. Persisted on
    ``LoadedResource.bookmarks`` — cleared when the SWF closes."""

    def __init__(self, state: StudioState) -> None:
        super().__init__()
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        hint = QLabel("Press Ctrl+B in the code view to toggle a bookmark "
                      "on the current line.")
        hint.setStyleSheet(f"color: {Palette.text_muted}; font-size: 11px;")
        layout.addWidget(hint)

        self._tree = QTreeWidget(self)
        self._tree.setHeaderLabels(["Location", "Line"])
        self._tree.setColumnWidth(0, 420)
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.itemActivated.connect(self._on_activate)
        self._tree.itemDoubleClicked.connect(self._on_activate)
        layout.addWidget(self._tree, 1)

        state.tabs_changed.connect(self.refresh)
        state.active_resource_changed.connect(self.refresh)

    def refresh(self) -> None:
        self._tree.clear()
        r = self.state.active_resource()
        if r is None or not r.bookmarks:
            placeholder = QTreeWidgetItem(self._tree)
            placeholder.setText(0, "(no bookmarks)")
            placeholder.setDisabled(True)
            return
        for full_name in sorted(r.bookmarks):
            lines = r.bookmarks[full_name]
            if not lines:
                continue
            short = full_name.rpartition(".")[2]
            parent = QTreeWidgetItem(self._tree)
            parent.setText(0, f"{short}  ({full_name})")
            parent.setText(1, f"{len(lines)}")
            parent.setExpanded(True)
            parent.setData(0, Qt.UserRole, ("class", full_name, -1))
            for ln in sorted(lines):
                child = QTreeWidgetItem(parent)
                child.setText(0, f"    line {ln}")
                child.setData(0, Qt.UserRole, ("line", full_name, ln))

    def _on_activate(self, item: QTreeWidgetItem, _col: int = 0) -> None:
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, cls, line = data
        if kind == "line":
            self.state.jump_to(cls, line=int(line))
        else:
            self.state.jump_to(cls)


# ── Assets tab ────────────────────────────────────────────────────


class _AssetsTab(QWidget):
    """Every embedded bitmap / sound / font / binary-data tag in the
    SWF. Right-click → Export to dump the raw payload to disk."""

    def __init__(self, state: StudioState) -> None:
        super().__init__()
        self.state = state
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self._header = QLabel("")
        self._header.setStyleSheet(
            f"color: {Palette.text_muted}; font-size: 11px;"
        )
        layout.addWidget(self._header)

        self._list = QListWidget(self)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._ctx_menu)
        layout.addWidget(self._list, 1)

        state.active_resource_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self._list.clear()
        assets = actions.list_assets(self.state)
        if not assets:
            self._header.setText("No exportable assets in this SWF.")
            return
        self._header.setText(f"{len(assets)} exportable assets")
        for a in assets:
            item = QListWidgetItem(
                f"[{a.kind}]  {a.name}  ·  {a.size_bytes:,} bytes",
            )
            item.setData(Qt.UserRole, a)
            self._list.addItem(item)

    def _ctx_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        act_export = menu.addAction("Export…")
        chosen = menu.exec(self._list.mapToGlobal(pos))
        if chosen is act_export:
            entry: actions.AssetEntry = item.data(Qt.UserRole)
            suffix = {"bitmap": ".jpg", "sound": ".bin",
                      "font": ".bin", "binary": ".bin"}.get(entry.kind, ".bin")
            path, _ = QFileDialog.getSaveFileName(
                self, "Export asset",
                f"{entry.name}{suffix}",
                "All Files (*)",
            )
            if path:
                ok = actions.export_asset(self.state, entry, Path(path))
                if ok:
                    self.state.set_status(f"Exported {entry.name} to {path}")
                else:
                    self.state.set_status("Export failed", error=True)
