"""Global QSS (Qt Style Sheet) applied to the QApplication.

One sheet for the whole app so styling is consistent across widgets.
Named colours and spacings live in the class-level ``Palette`` and
``Scale`` so each tweak is a one-line change.

Fonts are loaded from ``flashkit_studio/assets/fonts`` (bundled with
the imgui studio — we share the same asset folder so neither has to
duplicate).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QFontDatabase, QFont, QColor


# ── palette ──────────────────────────────────────────────────────────────


class Palette:
    bg_app       = "#0e0f11"
    bg_surface   = "#14161a"     # sidebar / tab strip / status
    bg_surface_2 = "#1b1e23"     # inputs / hover
    bg_selected  = "#252b33"     # active row / active tab

    border       = "#22262b"

    text_primary   = "#e4e6ea"
    text_secondary = "#a7abb3"
    text_muted     = "#6d727b"
    text_disabled  = "#4a4e56"

    accent_fg   = "#5e9ce6"
    accent_wash = "rgba(94, 156, 230, 18)"   # 7% alpha

    error   = "#ef6c6c"

    # Syntax tokens used by the highlighter.
    syn_keyword  = "#e07c9a"    # soft pink
    syn_type     = "#9cdcb8"    # mint
    syn_string   = "#e3c98f"    # sand
    syn_number   = "#c59bdf"    # lavender
    syn_comment  = "#5b6068"    # dim grey
    syn_function = "#82b7ef"    # cyan-blue
    syn_builtin  = "#e09f65"    # amber


class Scale:
    XS, SM, S, M, L, XL = 4, 6, 8, 12, 16, 24
    RADIUS = 6
    SIDEBAR_MIN = 240


# ── font loading ─────────────────────────────────────────────────────────


_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "fonts"

# Discovered font families (populated by load_fonts()).
UI_FAMILY: str = "Inter"
CODE_FAMILY: str = "JetBrains Mono"

UI_SIZE = 10      # pt (Qt uses points)
CODE_SIZE = 10    # matches modern editor defaults


def load_fonts() -> None:
    """Register our bundled Inter and JetBrains Mono with Qt so the
    stylesheet can reference them by family name."""
    global UI_FAMILY, CODE_FAMILY

    for path, expect in [
        (_ASSET_DIR / "Inter-Regular.ttf",         "Inter"),
        (_ASSET_DIR / "JetBrainsMono-Regular.ttf", "JetBrains Mono"),
        (_ASSET_DIR / "JetBrainsMono-Medium.ttf",  "JetBrains Mono"),
    ]:
        if not path.exists():
            continue
        fid = QFontDatabase.addApplicationFont(str(path))
        if fid == -1:
            continue
        fams = QFontDatabase.applicationFontFamilies(fid)
        if fams:
            if expect == "Inter":
                UI_FAMILY = fams[0]
            elif expect == "JetBrains Mono":
                CODE_FAMILY = fams[0]


def ui_font() -> QFont:
    f = QFont(UI_FAMILY, UI_SIZE)
    f.setHintingPreference(QFont.PreferFullHinting)
    return f


def code_font() -> QFont:
    f = QFont(CODE_FAMILY, CODE_SIZE)
    f.setFixedPitch(True)
    f.setHintingPreference(QFont.PreferFullHinting)
    return f


# ── global stylesheet ────────────────────────────────────────────────────


def stylesheet() -> str:
    p = Palette
    s = Scale
    return f"""
    QWidget {{
        background-color: {p.bg_app};
        color: {p.text_primary};
        font-family: "{UI_FAMILY}", "Segoe UI", sans-serif;
    }}

    /* Main window chrome ------------------------------------------------ */
    QMainWindow, QMainWindow::separator {{
        background-color: {p.bg_app};
    }}
    QMainWindow::separator {{
        background-color: {p.border};
        width: 1px;
        height: 1px;
    }}

    /* Menus ------------------------------------------------------------- */
    QMenuBar {{
        background-color: {p.bg_surface};
        color: {p.text_secondary};
        border-bottom: 1px solid {p.border};
        padding: 2px 6px;
        font-size: 13px;
    }}
    QMenuBar::item {{
        padding: 6px 12px;
        background: transparent;
        border-radius: {s.RADIUS}px;
    }}
    QMenuBar::item:selected, QMenuBar::item:pressed {{
        background-color: {p.bg_surface_2};
        color: {p.text_primary};
    }}
    QMenu {{
        background-color: {p.bg_surface};
        color: {p.text_primary};
        border: 1px solid {p.border};
        border-radius: {s.RADIUS}px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: {s.RADIUS - 2}px;
    }}
    QMenu::item:selected {{
        background-color: {p.bg_surface_2};
    }}
    QMenu::separator {{
        height: 1px;
        background: {p.border};
        margin: 4px 6px;
    }}

    /* Status bar -------------------------------------------------------- */
    QStatusBar {{
        background-color: {p.bg_surface};
        color: {p.text_secondary};
        border-top: 1px solid {p.border};
        padding: 0 12px;
        font-size: 12px;
        min-height: 24px;
    }}
    QStatusBar::item {{ border: none; }}
    QStatusBar QLabel {{ background: transparent; }}

    /* Splitter handle --------------------------------------------------- */
    QSplitter::handle {{
        background: {p.border};
    }}
    QSplitter::handle:horizontal {{
        width: 1px;
    }}
    QSplitter::handle:hover {{
        background: {p.accent_fg};
    }}

    /* Sidebar container + inner widgets --------------------------------- */
    QWidget#Sidebar {{
        background-color: {p.bg_surface};
    }}
    QLabel.caption {{
        color: {p.text_muted};
        font-size: 10px;
        font-weight: 600;
        letter-spacing: 1px;
        padding: 4px 10px 2px 10px;
        background: transparent;
    }}

    /* Combo, line edit -------------------------------------------------- */
    QComboBox, QLineEdit {{
        background-color: {p.bg_surface_2};
        color: {p.text_primary};
        border: 1px solid transparent;
        border-radius: {s.RADIUS}px;
        padding: 6px 10px;
        selection-background-color: {p.bg_selected};
    }}
    QComboBox:hover, QLineEdit:hover {{
        border: 1px solid {p.border};
    }}
    QComboBox:focus, QLineEdit:focus {{
        border: 1px solid {p.accent_fg};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        width: 20px;
        border: none;
    }}
    QComboBox::down-arrow {{
        width: 10px; height: 10px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {p.bg_surface};
        color: {p.text_primary};
        border: 1px solid {p.border};
        border-radius: {s.RADIUS}px;
        padding: 4px;
        selection-background-color: {p.bg_selected};
        outline: 0;
    }}
    QLineEdit[placeholder] {{
        color: {p.text_disabled};
    }}

    /* Tree view -------------------------------------------------------- */
    QTreeView {{
        background-color: {p.bg_surface};
        color: {p.text_secondary};
        border: none;
        padding: 2px 6px;
        outline: 0;
        selection-background-color: {p.bg_selected};
        selection-color: {p.text_primary};
    }}
    QTreeView::item {{
        padding: 4px 6px;
        border-radius: {s.RADIUS - 2}px;
    }}
    QTreeView::item:hover {{
        background-color: {p.bg_surface_2};
    }}
    QTreeView::item:selected {{
        background-color: {p.bg_selected};
        color: {p.text_primary};
    }}
    QTreeView::branch {{
        background: transparent;
    }}

    /* Tabs (class tabs) ----------------------------------------------- */
    QTabWidget::pane {{
        border: none;
        background: {p.bg_app};
    }}
    QTabBar {{
        background: {p.bg_surface};
        border-bottom: 1px solid {p.border};
    }}
    QTabBar::tab {{
        background: {p.bg_surface};
        color: {p.text_muted};
        padding: 8px 14px;
        margin-right: 2px;
        border: none;
        border-top-left-radius: {s.RADIUS}px;
        border-top-right-radius: {s.RADIUS}px;
        min-width: 80px;
    }}
    QTabBar::tab:hover {{
        background: {p.bg_surface_2};
        color: {p.text_secondary};
    }}
    QTabBar::tab:selected {{
        background: {p.bg_app};
        color: {p.text_primary};
    }}
    /* Close button inside each tab.  We draw our own × because Qt's
       built-in closeTabButton glyph is a small raster pixmap that
       doesn't scale cleanly on HiDPI. */
    QTabBar::close-button {{
        subcontrol-origin: padding;
        subcontrol-position: right;
        width: 16px; height: 16px;
        margin: 4px 6px 4px 2px;
        border-radius: 3px;
        background: transparent;
    }}
    QTabBar::close-button:hover {{
        background: {p.bg_surface_2};
    }}

    /* Bottom view switcher (QToolButton row) -------------------------- */
    QFrame#ViewBar {{
        background-color: {p.bg_surface};
        border-top: 1px solid {p.border};
    }}
    QToolButton.viewpill {{
        background: transparent;
        color: {p.text_muted};
        border: none;
        padding: 6px 12px;
        border-radius: {s.RADIUS}px;
        font-size: 12px;
    }}
    QToolButton.viewpill:hover {{
        background-color: {p.bg_surface_2};
        color: {p.text_secondary};
    }}
    QToolButton.viewpill:checked {{
        background-color: {p.bg_selected};
        color: {p.text_primary};
    }}

    /* Code editor ----------------------------------------------------- */
    QPlainTextEdit#CodeEditor {{
        background-color: {p.bg_app};
        color: {p.text_primary};
        border: none;
        selection-background-color: {p.bg_selected};
        font-family: "{CODE_FAMILY}", "Consolas", monospace;
        font-size: {CODE_SIZE}pt;
    }}

    /* Scrollbars ------------------------------------------------------ */
    QScrollBar:vertical {{
        background: transparent;
        width: 12px;
        margin: 0;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {p.border};
        min-height: 24px;
        border-radius: 6px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {p.text_muted};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0; background: transparent;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 12px;
        margin: 0;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background: {p.border};
        min-width: 24px;
        border-radius: 6px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: {p.text_muted};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0; background: transparent;
    }}

    /* Tooltip --------------------------------------------------------- */
    QToolTip {{
        background-color: {p.bg_surface};
        color: {p.text_primary};
        border: 1px solid {p.border};
        padding: 6px 8px;
        border-radius: {s.RADIUS}px;
    }}
    """
