"""
src/setup/main.py
rader_setup 앱 진입점.

실행:
    cd D:\\git.whlee2\\Rader
    .venv\\Scripts\\python -m src.setup.main
"""

import sys
import signal

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from .viewmodel.setup_viewmodel import SetupViewModel
from .view.setup_window import SetupWindow, STYLESHEET


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    sigint_timer = QTimer()
    sigint_timer.setInterval(100)
    sigint_timer.timeout.connect(lambda: None)
    sigint_timer.start()

    vm  = SetupViewModel()
    win = SetupWindow(vm)
    win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
