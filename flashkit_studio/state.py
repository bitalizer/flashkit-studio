"""Application state — the single source of truth, shared by every
view.

Views connect to ``StudioState``'s Qt signals so they refresh when
something changes (SWF opened, class opened as a tab, active view
switched…). Actions mutate the state and emit; nothing else.

This is deliberately the same mental model as the imgui studio but
re-expressed as a ``QObject`` with signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal

from flashkit.abc.types import AbcFile
from flashkit.workspace.resource import Resource
from flashkit.workspace.workspace import Workspace


# ── plain-data types ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ClassEntry:
    """A single row in the sidebar tree."""
    abc_index: int
    class_index: int
    name: str
    package: str
    full_name: str
    is_interface: bool
    trait_count: int


@dataclass
class LoadedResource:
    """One open SWF and the editor state belonging to it."""
    path: Path
    resource: Resource
    workspace: Workspace
    classes: list[ClassEntry] = field(default_factory=list)

    open_class_tabs: list[str] = field(default_factory=list)
    active_class_full_name: Optional[str] = None
    bookmarks: dict[str, list[int]] = field(default_factory=dict)

    def toggle_bookmark(self, full_name: str, line: int) -> bool:
        """Toggle a bookmark on ``(class, line)``. Returns the new state."""
        lines = self.bookmarks.setdefault(full_name, [])
        if line in lines:
            lines.remove(line)
            if not lines:
                del self.bookmarks[full_name]
            return False
        lines.append(line)
        lines.sort()
        return True

    @property
    def display_name(self) -> str:
        return self.path.name

    def open_tab(self, cls: ClassEntry) -> None:
        if cls.full_name not in self.open_class_tabs:
            self.open_class_tabs.append(cls.full_name)
        self.active_class_full_name = cls.full_name

    def close_tab(self, full_name: str) -> None:
        if full_name not in self.open_class_tabs:
            return
        idx = self.open_class_tabs.index(full_name)
        del self.open_class_tabs[idx]
        if self.active_class_full_name == full_name:
            if self.open_class_tabs:
                self.active_class_full_name = self.open_class_tabs[max(0, idx - 1)]
            else:
                self.active_class_full_name = None

    def close_tabs_except(self, full_name: str) -> None:
        if full_name in self.open_class_tabs:
            self.open_class_tabs = [full_name]
            self.active_class_full_name = full_name

    def close_all_tabs(self) -> None:
        self.open_class_tabs = []
        self.active_class_full_name = None

    def active_class(self) -> Optional[ClassEntry]:
        if self.active_class_full_name is None:
            return None
        for c in self.classes:
            if c.full_name == self.active_class_full_name:
                return c
        return None


# ── studio state ─────────────────────────────────────────────────────────


class StudioState(QObject):
    """Global UI state with change-notification signals."""

    # Emitted when the set of loaded SWFs changes.
    resources_changed = Signal()
    # Emitted when the user picks a different SWF.
    active_resource_changed = Signal()
    # Emitted when open-class-tabs list changes or active tab changes.
    tabs_changed = Signal()
    # Emitted when active view (Source/P-Code/…) changes.
    view_changed = Signal(str)
    # Status bar message.
    status_changed = Signal(str, bool, bool)  # text, busy, error
    # Persistent recent-SWFs list changed (a new path was pushed).
    recent_changed = Signal()
    # Strings/multinames filter changed.
    pool_filter_changed = Signal()
    # Request to navigate somewhere after a tab is focused.
    # Args: class_full_name, member_name_or_empty, line_number_or_minus1.
    # The editor panel is the sole consumer — it scrolls the code view
    # to the first line containing the given member identifier or, if
    # a line is supplied instead, directly to that line.
    jump_requested = Signal(str, str, int)

    def __init__(self) -> None:
        super().__init__()
        self.resources: list[LoadedResource] = []
        self.active_resource_index: Optional[int] = None
        self.active_view: str = "source"
        # Filter text for the Strings and Multinames views. Persisted
        # across view switches but not across SWF opens.
        self.pool_filter: str = ""

    # ── resources ──────────────────────────────────────────────────

    def add_resource(self, r: LoadedResource) -> None:
        self.resources.append(r)
        self.active_resource_index = len(self.resources) - 1
        self.resources_changed.emit()
        self.active_resource_changed.emit()

    def close_resource(self, index: int) -> None:
        if not (0 <= index < len(self.resources)):
            return
        del self.resources[index]
        if self.active_resource_index == index:
            self.active_resource_index = (len(self.resources) - 1) if self.resources else None
            self.active_resource_changed.emit()
        elif self.active_resource_index is not None and self.active_resource_index > index:
            self.active_resource_index -= 1
            self.active_resource_changed.emit()
        self.resources_changed.emit()

    def set_active_resource(self, index: int) -> None:
        if 0 <= index < len(self.resources) and index != self.active_resource_index:
            self.active_resource_index = index
            self.active_resource_changed.emit()

    def active_resource(self) -> Optional[LoadedResource]:
        if self.active_resource_index is None:
            return None
        if not (0 <= self.active_resource_index < len(self.resources)):
            return None
        return self.resources[self.active_resource_index]

    def active_class(self) -> Optional[ClassEntry]:
        r = self.active_resource()
        return r.active_class() if r else None

    def active_abc(self) -> Optional[AbcFile]:
        r = self.active_resource()
        c = r.active_class() if r else None
        if r is None or c is None:
            return None
        if 0 <= c.abc_index < len(r.resource.abc_blocks):
            return r.resource.abc_blocks[c.abc_index]
        return None

    # ── tabs ───────────────────────────────────────────────────────

    def open_class(self, cls: ClassEntry) -> None:
        r = self.active_resource()
        if r is None:
            return
        r.open_tab(cls)
        self.tabs_changed.emit()

    def close_class_tab(self, full_name: str) -> None:
        r = self.active_resource()
        if r is None:
            return
        r.close_tab(full_name)
        self.tabs_changed.emit()

    def close_other_class_tabs(self, keep: str) -> None:
        r = self.active_resource()
        if r is None:
            return
        r.close_tabs_except(keep)
        self.tabs_changed.emit()

    def close_all_class_tabs(self) -> None:
        r = self.active_resource()
        if r is None:
            return
        r.close_all_tabs()
        self.tabs_changed.emit()

    def focus_class_tab(self, full_name: str) -> None:
        r = self.active_resource()
        if r is None:
            return
        if full_name in r.open_class_tabs and r.active_class_full_name != full_name:
            r.active_class_full_name = full_name
            self.tabs_changed.emit()

    # ── view + status ──────────────────────────────────────────────

    def set_active_view(self, key: str) -> None:
        if key != self.active_view:
            self.active_view = key
            self.view_changed.emit(key)

    def set_pool_filter(self, text: str) -> None:
        if text != self.pool_filter:
            self.pool_filter = text
            self.pool_filter_changed.emit()

    def set_status(self, text: str, *, busy: bool = False, error: bool = False) -> None:
        self.status_changed.emit(text, busy, error)

    # ── navigation ─────────────────────────────────────────────────

    def jump_to(self, full_name: str, *,
                member: str = "", line: int = -1) -> None:
        """Open ``full_name`` (creating the tab if needed), focus it,
        then emit ``jump_requested`` so the editor can scroll to the
        given member or line. Used by the symbol palette, the
        find-in-all-files panel, and jump-to-definition."""
        r = self.active_resource()
        if r is None:
            return
        cls = next((c for c in r.classes if c.full_name == full_name), None)
        if cls is None:
            return
        self.open_class(cls)
        self.jump_requested.emit(full_name, member, line)
