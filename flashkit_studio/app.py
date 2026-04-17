"""Entry point — create the QApplication and launch the main window."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication

from . import theme
from .state import StudioState
from .windows.main import MainWindow


def _apply_dark_palette(app: QApplication) -> None:
    """Baseline dark palette so the default Qt styling (which peeks
    through the stylesheet in a few spots) is already dark. The QSS
    sheet layered on top covers the rest.
    """
    p = QPalette()
    p.setColor(QPalette.Window,          QColor(theme.Palette.bg_app))
    p.setColor(QPalette.WindowText,      QColor(theme.Palette.text_primary))
    p.setColor(QPalette.Base,            QColor(theme.Palette.bg_surface_2))
    p.setColor(QPalette.AlternateBase,   QColor(theme.Palette.bg_surface))
    p.setColor(QPalette.Text,            QColor(theme.Palette.text_primary))
    p.setColor(QPalette.Button,          QColor(theme.Palette.bg_surface_2))
    p.setColor(QPalette.ButtonText,      QColor(theme.Palette.text_primary))
    p.setColor(QPalette.ToolTipBase,     QColor(theme.Palette.bg_surface))
    p.setColor(QPalette.ToolTipText,     QColor(theme.Palette.text_primary))
    p.setColor(QPalette.Highlight,       QColor(theme.Palette.bg_selected))
    p.setColor(QPalette.HighlightedText, QColor(theme.Palette.text_primary))
    p.setColor(QPalette.Disabled, QPalette.Text,
               QColor(theme.Palette.text_disabled))
    p.setColor(QPalette.Disabled, QPalette.ButtonText,
               QColor(theme.Palette.text_disabled))
    app.setPalette(p)


def run(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(argv)
    app.setApplicationName("FlashKit Studio")
    app.setOrganizationName("flashkit")

    # Neutral style so our QSS owns the look.
    app.setStyle("Fusion")

    # Fonts must be loaded before stylesheet (so {UI_FAMILY} resolves).
    theme.load_fonts()
    app.setFont(theme.ui_font())

    _apply_dark_palette(app)
    app.setStyleSheet(theme.stylesheet())

    state = StudioState()
    window = MainWindow(state)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
