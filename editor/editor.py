from pathlib import Path
import json

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QFont, QPainter, QTextCursor, QTextFormat, QKeyEvent
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit

from .line_number_area import LineNumberArea
from .highlighter import CodeHighlighter


class CodeEditor(QPlainTextEdit):
    def __init__(self, parent=None, language="python", theme_file=None, languages_file=None):
        super().__init__(parent)
        self.theme = self._load(theme_file)
        self.languages = self._load(languages_file).get("languages", {})
        self.language = language
        self.config = self.languages.get(language, {})
        self.indent_size = self.config.get("indent_size", 4)
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self._cursor_changed)
        self._setup()
        self.highlighter = CodeHighlighter(self.document(), language, theme_file, languages_file)
        self.update_line_number_area_width(0)
        self._cursor_changed()

    @staticmethod
    def _load(path):
        if not path:
            return {}
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _color(self, name, fallback):
        return QColor(self.theme.get("editor", {}).get(name, fallback))

    def _setup(self):
        font = QFont(self.theme.get("editor", {}).get("font", "Cascadia Code"), self.theme.get("editor", {}).get("font_size", 11))
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * self.indent_size)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFrameStyle(QPlainTextEdit.Shape.NoFrame)
        self.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {self._color("background", "#1E1E1E").name()};
                color: {self._color("foreground", "#D4D4D4").name()};
                selection-background-color: {self._color("selection_background", "#264F78").name()};
                selection-color: {self._color("selection_foreground", "#FFFFFF").name()};
                border: none;
            }}
        """)
        
    def set_language(self, language):
        if language not in self.languages:
            return
        self.language = language
        self.config = self.languages[language]
        self.indent_size = self.config.get("indent_size", 4)
        self.highlighter.set_language(language)

    def line_number_area_width(self):
        digits = len(str(max(1, self.blockCount())))
        return 20 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), self.line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        r = self.contentsRect()
        self.line_number_area.setGeometry(QRect(r.left(), r.top(), self.line_number_area_width(), r.height()))

    def line_number_area_paint_event(self, event):
        p = QPainter(self.line_number_area)
        p.fillRect(event.rect(), self._color("line_number_background", "#1E1E1E"))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                active = number == self.textCursor().blockNumber()
                p.setPen(self._color(
                    "line_number_active" if active else "line_number",
                    "#C6C6C6" if active else "#858585"
                ))
                p.drawText(0, top, self.line_number_area.width() - 8, self.fontMetrics().height(),
                           Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    def _cursor_changed(self):
        self._highlight_line()
        self._highlight_bracket()

    def _highlight_line(self):
        s = QTextEdit.ExtraSelection()
        s.format.setBackground(self._color("current_line", "#252526"))
        s.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        s.cursor = self.textCursor()
        s.cursor.clearSelection()
        self.setExtraSelections([s])

    def _highlight_bracket(self):
        pass

    def _indent(self, text):
        return text[:len(text) - len(text.lstrip())]

    def _increase_indent(self, text):
        rules = self.config.get("indent", {})
        stripped = text.strip()

        if stripped.endswith(tuple(rules.get("after", []))):
            return True

        for prefix in rules.get("prefixes", []):
            if stripped.startswith(prefix):
                return True

        return False

    def _decrease_indent(self, text):
        rules = self.config.get("indent", {})
        stripped = text.strip()
        return any(stripped.startswith(x) for x in rules.get("before", []))

    def _smart_enter(self):
        c = self.textCursor()
        line = c.block().text()
        level = len(self._indent(line)) // self.indent_size

        if self._increase_indent(line):
            level += 1

        if self._decrease_indent(line):
            level = max(0, level - 1)

        c.insertText("\n" + " " * (level * self.indent_size))

    def _smart_backspace(self):
        c = self.textCursor()

        if c.hasSelection():
            c.removeSelectedText()
            return

        pos = c.positionInBlock()
        line = c.block().text()

        if pos == 0 or line[:pos].strip():
            super().keyPressEvent(QKeyEvent(
                QKeyEvent.Type.KeyPress,
                Qt.Key.Key_Backspace,
                Qt.KeyboardModifier.NoModifier
            ))
            return

        remove = pos % self.indent_size or self.indent_size
        c.setPosition(c.position() - remove, QTextCursor.MoveMode.KeepAnchor)
        c.removeSelectedText()

    def _pairs(self):
        return self.config.get("pairs", {
            "(": ")",
            "[": "]",
            "{": "}",
            '"': '"',
            "'": "'"
        })

    def _insert_pair(self, char):
        c = self.textCursor()
        c.insertText(char + self._pairs()[char])
        c.movePosition(QTextCursor.MoveOperation.Left)
        self.setTextCursor(c)

    def _skip_pair(self, char):
        c = self.textCursor()
        pos = c.positionInBlock()
        line = c.block().text()
        if pos < len(line) and line[pos] == char:
            c.movePosition(QTextCursor.MoveOperation.Right)
            self.setTextCursor(c)
            return True
        return False

    def toggle_comment(self):
        marker = self.config.get("comment", "#")
        c = self.textCursor()
        start, end = c.selectionStart(), c.selectionEnd()
        c.setPosition(start)
        first = c.block().blockNumber()
        c.setPosition(end)
        last = c.block().blockNumber()

        c.beginEditBlock()
        for n in range(first, last + 1):
            block = self.document().findBlockByNumber(n)
            text = block.text()
            lead = len(text) - len(text.lstrip())
            c.setPosition(block.position() + lead)

            if text[lead:].startswith(marker):
                c.setPosition(c.position() + len(marker))
                if c.positionInBlock() < len(text) and text[c.positionInBlock()] == " ":
                    c.deleteChar()
            else:
                c.insertText(marker + " ")
        c.endEditBlock()

    def indent_selection(self, increase=True):
        c = self.textCursor()
        start, end = c.selectionStart(), c.selectionEnd()
        c.setPosition(start)
        first = c.block().blockNumber()
        c.setPosition(end)
        last = c.block().blockNumber()

        c.beginEditBlock()
        for n in range(first, last + 1):
            block = self.document().findBlockByNumber(n)
            c.setPosition(block.position())

            if increase:
                c.insertText(" " * self.indent_size)
            else:
                remove = min(self.indent_size, len(block.text()) - len(block.text().lstrip()))
                if remove:
                    c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, remove)
                    c.removeSelectedText()
        c.endEditBlock()

    def keyPressEvent(self, event):
        key = event.key()
        mod = event.modifiers()
        text = event.text()

        if key == Qt.Key.Key_Slash and mod & Qt.KeyboardModifier.ControlModifier:
            self.toggle_comment()
            return

        if key == Qt.Key.Key_Tab:
            self.indent_selection(not (mod & Qt.KeyboardModifier.ShiftModifier))
            return

        if key == Qt.Key.Key_Backtab:
            self.indent_selection(False)
            return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._smart_enter()
            return

        if key == Qt.Key.Key_Backspace:
            self._smart_backspace()
            return

        pairs = self._pairs()

        if text in pairs:
            self._insert_pair(text)
            return

        if text in pairs.values() and self._skip_pair(text):
            return

        if mod & Qt.KeyboardModifier.ControlModifier:
            if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                self.zoomIn(1)
                return
            if key == Qt.Key.Key_Minus:
                self.zoomOut(1)
                return

        super().keyPressEvent(event)

    def load_file(self, path):
        self.setPlainText(Path(path).read_text(encoding="utf-8"))

    def save_file(self, path):
        Path(path).write_text(self.toPlainText(), encoding="utf-8")

    def goto_line(self, line):
        block = self.document().findBlockByNumber(max(0, line - 1))
        c = self.textCursor()
        c.setPosition(block.position())
        self.setTextCursor(c)
        self.centerCursor()