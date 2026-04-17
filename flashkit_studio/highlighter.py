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
        # P-Code-specific formats: offset is the same number colour, the
        # mnemonic steals the keyword colour, raw bytes dim like comments.
        self._pc_offset = _fmt(p.syn_number)
        self._pc_bytes  = _fmt(p.syn_comment)
        self._pc_mnem   = _fmt(p.syn_keyword, bold=True)

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

        # P-Code line shape — both the hex-dump variant ("  0000  d0 30 …
        # mnemonic …") and the plain variant ("  0000  mnemonic …") the
        # disasm renderer used before hex bytes were added.
        self._pc_line = QRegularExpression(
            r"^\s+([0-9A-F]{4,})\s+"                   # 1: offset
            r"(?:((?:[0-9a-f]{2}\s?)+(?:…)?)\s+)?"     # 2: optional hex
            r"([a-z_][a-z0-9_]*)"                      # 3: mnemonic
        )

    def highlightBlock(self, text: str) -> None:
        # If this line looks like a P-Code row, apply the disasm
        # format and skip the AS3 rules (those would try to match
        # things like "returnvoid" as keywords which is fine, but
        # also mis-colour hex bytes as identifiers).
        pc = self._pc_line.match(text)
        if pc.hasMatch():
            self.setFormat(pc.capturedStart(1), pc.capturedLength(1),
                           self._pc_offset)
            if pc.capturedStart(2) >= 0:
                self.setFormat(pc.capturedStart(2), pc.capturedLength(2),
                               self._pc_bytes)
            self.setFormat(pc.capturedStart(3), pc.capturedLength(3),
                           self._pc_mnem)
            # Operands tail can still use AS3 rules (strings, numbers).
            tail_start = pc.capturedEnd(3)
            tail = text[tail_start:]
            for regex, fmt in self._rules[:4]:  # strings + builtins only
                it = regex.globalMatch(tail)
                while it.hasNext():
                    m = it.next()
                    self.setFormat(tail_start + m.capturedStart(),
                                   m.capturedLength(), fmt)
            return

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
