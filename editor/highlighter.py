import json
import re
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

class CodeHighlighter(QSyntaxHighlighter):
    def __init__(self, document, language, theme_file=None, languages_file=None):
        super().__init__(document)
        self.theme = self._load(theme_file)
        self.languages = self._load(languages_file).get("languages", {})
        self.language = language
        self._build_formats()
        self._compile()

    @staticmethod
    def _load(path):
        if not path:
            return {}
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _fmt(self, name, fallback="#FFFFFF", bold=False, italic=False):
        f = QTextCharFormat()
        f.setForeground(QColor(self.theme.get("syntax", {}).get(name, fallback)))
        if bold:
            f.setFontWeight(QFont.Weight.Bold)
        if italic:
            f.setFontItalic(True)
        return f

    def _build_formats(self):
        self.fmts = {
            "keyword": self._fmt("keyword", bold=True),
            "builtin": self._fmt("builtin"),
            "string": self._fmt("string"),
            "comment": self._fmt("comment", italic=True),
            "function": self._fmt("function"),
            "class": self._fmt("class", bold=True),
            "number": self._fmt("number"),
            "operator": self._fmt("operator"),
            "preprocessor": self._fmt("preprocessor"),
            "constant": self._fmt("keyword", bold=True),
        }

    def _compile(self):
        c = self.languages.get(self.language, {})
        self.config = c
        self.keywords = set(c.get("keywords", []))
        self.builtins = set(c.get("builtins", []))
        self.constants = set(c.get("constants", []))
        self.ident_re = re.compile(c.get("identifier", r"[A-Za-z_][A-Za-z0-9_]*"))
        self.num_re = re.compile(c["number"]) if c.get("number") else None
        self.ops = sorted(c.get("operators", []), key=len, reverse=True)
        self.line_comments = sorted(c.get("line_comments", []), key=len, reverse=True)
        self.block_comments = sorted(c.get("block_comments", []), key=lambda x: len(x["start"]), reverse=True)
        self.strings = sorted(c.get("strings", []), key=lambda x: max(map(len, x.get("quotes", [""]))), reverse=True)
        fn = c.get("function", {})
        cl = c.get("class", {})
        self.fn_defs = set(fn.get("definition_keywords", []))
        self.class_defs = set(cl.get("definition_keywords", []))
        self.fn_calls = fn.get("highlight_calls", False)
        self.preprocessor = c.get("preprocessor", [])

    def set_language(self, language):
        if language not in self.languages:
            return
        self.language = language
        self._compile()
        self.rehighlight()

    def _set(self, start, length, name):
        if length:
            self.setFormat(start, length, self.fmts[name])

    def _op(self, text, pos):
        return next((x for x in self.ops if text.startswith(x, pos)), None)

    def _string(self, text, pos):
        for s in self.strings:
            for prefix in sorted(s.get("prefixes", [""]), key=len, reverse=True):
                if prefix and not text[pos:].lower().startswith(prefix.lower()):
                    continue
                qpos = pos + len(prefix)
                for quote in s.get("quotes", ['"']):
                    if not text.startswith(quote, qpos):
                        continue
                    i = qpos + len(quote)
                    esc = s.get("escape", "\\")
                    while i < len(text):
                        if esc and text[i] == esc:
                            i += 2
                        elif text.startswith(quote, i):
                            return i + len(quote), len(quote) > 1
                        else:
                            i += 1
                    return len(text), len(quote) > 1
        return None

    def _prev_word(self, text, pos):
        m = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*$", text[:pos])
        return m.group(1) if m else None

    def highlightBlock(self, text):
        i, n = 0, len(text)
        state = self.previousBlockState()

        if state >= 1000:
            idx = state - 1000
            spec = self.block_comments[idx] if idx < len(self.block_comments) else None
            if spec:
                end = text.find(spec["end"])
                if end < 0:
                    self._set(0, n, "comment")
                    self.setCurrentBlockState(state)
                    return
                end += len(spec["end"])
                self._set(0, end, "comment")
                i = end

        elif state >= 1:
            idx = state - 1
            if idx < len(self.strings):
                closed = False
                for q in self.strings[idx].get("quotes", []):
                    end = text.find(q)
                    if end >= 0:
                        end += len(q)
                        self._set(0, end, "string")
                        i, closed = end, True
                        break
                if not closed:
                    self._set(0, n, "string")
                    self.setCurrentBlockState(state)
                    return

        self.setCurrentBlockState(0)

        while i < n:
            if any(text.startswith(x, i) for x in self.line_comments):
                self._set(i, n - i, "comment")
                return

            block = next((x for x in self.block_comments if text.startswith(x["start"], i)), None)
            if block:
                idx = self.block_comments.index(block)
                end = text.find(block["end"], i + len(block["start"]))
                if end < 0:
                    self._set(i, n - i, "comment")
                    self.setCurrentBlockState(1000 + idx)
                    return
                end += len(block["end"])
                self._set(i, end - i, "comment")
                i = end
                continue

            s = self._string(text, i)
            if s:
                end, multi = s
                self._set(i, end - i, "string")
                if multi:
                    idx = next(
                        (j for j, x in enumerate(self.strings)
                         if any(text.startswith(p + q, i)
                                for p in x.get("prefixes", [""])
                                for q in x.get("quotes", []))
                        ),
                        None,
                    )
                    if idx is not None:
                        self.setCurrentBlockState(1 + idx)
                    return
                i = end
                continue

            if self.preprocessor and not text[:i].strip() and any(text.startswith(x, i) for x in self.preprocessor):
                self._set(i, n - i, "preprocessor")
                return

            if self.num_re:
                m = self.num_re.match(text, i)
                if m:
                    self._set(i, m.end() - i, "number")
                    i = m.end()
                    continue

            m = self.ident_re.match(text, i)
            if m:
                word, end = m.group(), m.end()
                prev = self._prev_word(text, i)

                if word in self.keywords:
                    self._set(i, end - i, "keyword")
                elif word in self.builtins:
                    self._set(i, end - i, "builtin")
                elif word in self.constants:
                    self._set(i, end - i, "constant")
                elif prev in self.fn_defs:
                    self._set(i, end - i, "function")
                elif prev in self.class_defs:
                    self._set(i, end - i, "class")
                elif self.fn_calls and text[end:].lstrip().startswith("("):
                    self._set(i, end - i, "function")

                i = end
                continue

            op = self._op(text, i)
            if op:
                self._set(i, len(op), "operator")
                i += len(op)
                continue

            i += 1