"""AS3 syntax highlighter for the code editor.

Lightweight — recognises keywords, builtin types, strings, numbers,
line and block comments, and call-style function names. Colours
come from :mod:`~flashkit_studio.theme.Palette`.
"""

from __future__ import annotations

import re

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import (
    QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument,
)

from .theme import Palette


_KEYWORDS = (
    r"\b(?:package|class|interface|extends|implements|public|private|"
    r"protected|internal|static|final|override|native|dynamic|function|"
    r"const|var|return|if|else|for|each|while|do|switch|case|default|"
    r"break|continue|try|catch|finally|throw|new|delete|typeof|is|as|in|"
    r"import|include|use|namespace|null|undefined|true|false|this|super|"
    r"void)\b"
)

_BUILTINS = (
    r"\b(?:int|uint|Number|String|Boolean|Object|Array|Vector|Function|"
    r"Error|Date|RegExp|XML|XMLList|Math|JSON|trace)\b"
)

_NUMBER = r"\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b"

# Identifier immediately followed by '(' — call site.
_CALL = r"[A-Za-z_][A-Za-z0-9_]*(?=\s*\()"

# String: double-quoted, single-quoted. Allow escapes.
_DQSTR = r"\"(?:\\.|[^\"\\])*\""
_SQSTR = r"'(?:\\.|[^'\\])*'"

# Line comment.
_LINE_COMMENT = r"//[^\n]*"


def _fmt(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.DemiBold)
    if italic:
        fmt.setFontItalic(True)
    return fmt


class As3Highlighter(QSyntaxHighlighter):
    """Single-pass tokenizer with block-comment state tracking."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)

        p = Palette
        self._kw      = _fmt(p.syn_keyword, bold=True)
        self._type    = _fmt(p.syn_type)
        self._number  = _fmt(p.syn_number)
        self._string  = _fmt(p.syn_string)
        self._call    = _fmt(p.syn_function)
        self._builtin = _fmt(p.syn_builtin)
        self._comment = _fmt(p.syn_comment, italic=True)

        # Order matters: comments first so strings inside them aren't
        # highlighted.
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = [
            (QRegularExpression(_LINE_COMMENT), self._comment),
            (QRegularExpression(_DQSTR),        self._string),
            (QRegularExpression(_SQSTR),        self._string),
            (QRegularExpression(_BUILTINS),     self._builtin),
            (QRegularExpression(_KEYWORDS),     self._kw),
            (QRegularExpression(_NUMBER),       self._number),
            (QRegularExpression(_CALL),         self._call),
        ]

        self._block_start = QRegularExpression(r"/\*")
        self._block_end   = QRegularExpression(r"\*/")

    def highlightBlock(self, text: str) -> None:
        # Apply single-line rules.
        for regex, fmt in self._rules:
            it = regex.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        # Multi-line /* … */ comments.
        self.setCurrentBlockState(0)
        start = 0
        if self.previousBlockState() != 1:
            m = self._block_start.match(text)
            start = m.capturedStart() if m.hasMatch() else -1
        else:
            start = 0

        while start >= 0:
            end_match = self._block_end.match(text, start)
            if not end_match.hasMatch():
                self.setCurrentBlockState(1)
                length = len(text) - start
            else:
                length = end_match.capturedEnd() - start
            self.setFormat(start, length, self._comment)
            nxt = self._block_start.match(text, start + length)
            start = nxt.capturedStart() if nxt.hasMatch() else -1
