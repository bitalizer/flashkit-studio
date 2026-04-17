"""Persistent preferences — window geometry, sidebar width, recent SWFs.

Thin wrapper around ``QSettings`` so call sites don't juggle string
keys. Settings are grouped under the application name set in
``app.py``; on Windows they live in the registry, on mac in
``~/Library/Preferences``, on Linux in ``~/.config/flashkit``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QByteArray, QSettings


_MAX_RECENT = 10


def _s() -> QSettings:
    # Application and organization names are set in app.py before any
    # window is constructed, so unqualified QSettings() picks them up.
    return QSettings()


# ── window / splitter geometry ────────────────────────────────────────────


def save_window_state(geometry: QByteArray, state: QByteArray,
                      splitter: QByteArray) -> None:
    s = _s()
    s.setValue("window/geometry", geometry)
    s.setValue("window/state", state)
    s.setValue("window/splitter", splitter)


def load_window_state() -> tuple[QByteArray, QByteArray, QByteArray]:
    s = _s()
    return (
        s.value("window/geometry", QByteArray()),
        s.value("window/state", QByteArray()),
        s.value("window/splitter", QByteArray()),
    )


def save_sidebar_side(side: str) -> None:
    _s().setValue("window/sidebar_side", side)


def load_sidebar_side(default: str = "left") -> str:
    return str(_s().value("window/sidebar_side", default))


# ── recent SWFs ──────────────────────────────────────────────────────────


def recent_swfs() -> list[Path]:
    s = _s()
    raw = s.value("recent/swfs", []) or []
    if isinstance(raw, str):
        raw = [raw]
    out: list[Path] = []
    for entry in raw:
        try:
            p = Path(entry)
        except Exception:  # noqa: BLE001
            continue
        if p not in out:
            out.append(p)
    return out


def push_recent_swf(path: Path) -> None:
    """Record ``path`` as the most-recently-opened SWF. Moves existing
    entries to the front; trims to ``_MAX_RECENT``."""
    p = Path(path).resolve()
    existing = [x for x in recent_swfs() if x != p]
    existing.insert(0, p)
    del existing[_MAX_RECENT:]
    _s().setValue("recent/swfs", [str(x) for x in existing])


def clear_recent_swfs() -> None:
    _s().setValue("recent/swfs", [])
