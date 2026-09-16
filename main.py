import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from editor import CodeEditor

BASE_DIR = Path(__file__).resolve().parent

THEME_FILE = BASE_DIR / "config" / "theme.json"
LANGUAGES_FILE = BASE_DIR / "config" / "languages.json"

app = QApplication(sys.argv)

editor = CodeEditor(
    language="python",
    theme_file=THEME_FILE,
    languages_file=LANGUAGES_FILE,
)

editor.setPlainText('''print("Hello, World!")''')

editor.resize(1280, 720)
editor.show()

sys.exit(app.exec())