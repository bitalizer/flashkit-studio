"""Sidebar: workspace picker + class tree.

Structure:

    WORKSPACE                  (caption)
    [pressor2.swf         v]   (combo)
    CLASSES                    (caption)
    [🔍 Search classes…   ]    (line edit)
    ▸ default
        Main
        SaveData
        …
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox, QLabel, QLineEdit, QTreeView, QVBoxLayout, QWidget,
)

from .. import icons
from ..state import StudioState, ClassEntry
from ..theme import Palette, Scale


def _pkg_icon(expanded: bool):
    """Chevron that rotates with package expansion state. Cached via
    ``icons.icon`` so building the sidebar on a large SWF doesn't
    re-rasterise the same two glyphs 300 times."""
    name = "chevron_down" if expanded else "chevron_right"
    return icons.icon(name, size=14, color=Palette.text_muted)


def _class_icon():
    return icons.icon(
        "class", size=14,
        color=Palette.accent_fg,
        bg=Palette.bg_surface_2,
    )


class Sidebar(QWidget):
    """Left (or right) panel of the main window."""

    classClicked = Signal(object)  # ClassEntry

    def __init__(self, state: StudioState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.setObjectName("Sidebar")
        self.setMinimumWidth(Scale.SIDEBAR_MIN)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Scale.S, Scale.S, Scale.S, Scale.S)
        layout.setSpacing(Scale.XS)

        # WORKSPACE section.
        workspace_caption = QLabel("WORKSPACE")
        workspace_caption.setProperty("class", "caption")
        layout.addWidget(workspace_caption)

        self.swf_combo = QComboBox()
        self.swf_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.swf_combo.setMinimumContentsLength(1)
        self.swf_combo.currentIndexChanged.connect(self._on_swf_changed)
        layout.addWidget(self.swf_combo)

        layout.addSpacing(Scale.S)

        # CLASSES section.
        classes_caption = QLabel("CLASSES")
        classes_caption.setProperty("class", "caption")
        layout.addWidget(classes_caption)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Search classes…")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self.filter)

        # Tree.
        self.tree = QTreeView()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        # The default Qt branch indicator renders as a tiny raster pixmap
        # that looks fuzzy on HiDPI, so we paint the chevron ourselves
        # inside the package row label instead. Turn off the built-in
        # decoration to avoid a double-indicator gutter.
        self.tree.setRootIsDecorated(False)
        self.tree.setAnimated(False)
        self.tree.setEditTriggers(QTreeView.NoEditTriggers)
        self.tree.setIndentation(12)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.activated.connect(self._on_tree_activated)
        self.tree.clicked.connect(self._on_tree_activated)
        self.tree.expanded.connect(self._sync_pkg_chevron)
        self.tree.collapsed.connect(self._sync_pkg_chevron)
        layout.addWidget(self.tree, 1)

        self.model = QStandardItemModel(self.tree)
        self.tree.setModel(self.model)

        self._all_classes: list[ClassEntry] = []
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(80)
        self._filter_timer.timeout.connect(self._rebuild_tree)

        # React to state changes.
        state.resources_changed.connect(self._refresh_resources)
        state.active_resource_changed.connect(self._refresh_resources)
        state.tabs_changed.connect(self._refresh_row_decor)

        self._refresh_resources()

    # ── resources combo ────────────────────────────────────────────

    def _refresh_resources(self) -> None:
        self.swf_combo.blockSignals(True)
        self.swf_combo.clear()
        for r in self.state.resources:
            self.swf_combo.addItem(r.display_name)
        if self.state.active_resource_index is not None:
            self.swf_combo.setCurrentIndex(self.state.active_resource_index)
        self.swf_combo.blockSignals(False)

        r = self.state.active_resource()
        self._all_classes = list(r.classes) if r else []
        self._rebuild_tree()

    def _on_swf_changed(self, index: int) -> None:
        if index < 0:
            return
        self.state.set_active_resource(index)

    # ── tree ──────────────────────────────────────────────────────

    def _apply_filter(self, _text: str) -> None:
        self._filter_timer.start()

    def _rebuild_tree(self) -> None:
        self.model.clear()
        self.model.setColumnCount(1)

        filter_lower = self.filter.text().lower()
        # Filter matches the class's qualified name or any of its
        # fields/methods — lets a user locate "SomeClass" by typing
        # "onTick" if that's the method they remember. Member names
        # come from the workspace ``ClassInfo`` which is already
        # resolved at load time.
        filtered = []
        if not filter_lower:
            filtered = list(self._all_classes)
        else:
            r = self.state.active_resource()
            ci_by_full = {
                ci.qualified_name: ci for ci in r.resource.classes
            } if r else {}
            for c in self._all_classes:
                if filter_lower in c.full_name.lower():
                    filtered.append(c)
                    continue
                ci = ci_by_full.get(c.full_name)
                if ci is None:
                    continue
                if any(filter_lower in f.name.lower() for f in ci.all_fields):
                    filtered.append(c)
                    continue
                if any(filter_lower in m.name.lower() for m in ci.all_methods):
                    filtered.append(c)

        by_pkg: dict[str, list[ClassEntry]] = {}
        for c in filtered:
            by_pkg.setdefault(c.package or "(default)", []).append(c)

        root = self.model.invisibleRootItem()
        class_icon = _class_icon()
        collapsed_icon = _pkg_icon(expanded=False)
        for pkg in sorted(by_pkg):
            # Start collapsed; _sync_pkg_chevron flips the icon on expand.
            pkg_item = QStandardItem(collapsed_icon, pkg)
            pkg_item.setSelectable(False)
            pkg_item.setData(("pkg", pkg), Qt.UserRole)
            for c in by_pkg[pkg]:
                item = QStandardItem(class_icon, c.name)
                item.setEditable(False)
                item.setToolTip(c.full_name)
                item.setData(("class", c), Qt.UserRole)
                pkg_item.appendRow(item)
            root.appendRow(pkg_item)

        # Expand all when filtering so matches are visible.
        if filter_lower:
            self.tree.expandAll()
        else:
            # Expand packages by default on first load; otherwise leave
            # user's collapse state alone.
            for i in range(root.rowCount()):
                self.tree.expand(self.model.index(i, 0))

        # Programmatic expand calls above don't always emit the
        # ``expanded`` signal, so ensure every visible package row has
        # the right chevron before the first paint.
        for i in range(root.rowCount()):
            self._sync_pkg_chevron(self.model.index(i, 0))

        self._refresh_row_decor()

    def _sync_pkg_chevron(self, index) -> None:
        """Rotate the chevron icon on the package row when Qt fires
        expanded or collapsed. ``index`` is always a top-level
        (package) index because class rows have no children."""
        item = self.model.itemFromIndex(index)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data or data[0] != "pkg":
            return
        item.setIcon(_pkg_icon(self.tree.isExpanded(index)))

    def _refresh_row_decor(self) -> None:
        """Style class rows by open-tab state (open = brighter than
        closed; focused = selected-row highlight).

        Implemented by setting the item's foreground color on the fly.
        """
        from PySide6.QtGui import QBrush, QColor
        from ..theme import Palette

        r = self.state.active_resource()
        if r is None:
            return
        open_set = set(r.open_class_tabs)
        focused = r.active_class_full_name

        root = self.model.invisibleRootItem()
        for i in range(root.rowCount()):
            pkg = root.child(i)
            # Package node: dim label, mono weight.
            pkg.setForeground(QBrush(QColor(Palette.text_muted)))
            for j in range(pkg.rowCount()):
                ci = pkg.child(j)
                data = ci.data(Qt.UserRole)
                if not data or data[0] != "class":
                    continue
                cls: ClassEntry = data[1]
                if cls.full_name == focused:
                    ci.setForeground(QBrush(QColor(Palette.text_primary)))
                elif cls.full_name in open_set:
                    ci.setForeground(QBrush(QColor(Palette.text_secondary)))
                else:
                    ci.setForeground(QBrush(QColor(Palette.text_muted)))

    def _on_tree_activated(self, index) -> None:
        item = self.model.itemFromIndex(index)
        if item is None:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        kind, payload = data
        if kind == "class":
            self.classClicked.emit(payload)
        elif kind == "pkg":
            # Toggle expansion.
            if self.tree.isExpanded(index):
                self.tree.collapse(index)
            else:
                self.tree.expand(index)
