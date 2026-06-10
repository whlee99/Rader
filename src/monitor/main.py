"""
src/monitor/main.py
rader_monitor 앱 진입점.

실행:
    cd D:\\git.whlee2\\Rader
    .venv\\Scripts\\python -m src.monitor.main
"""

import sys
import signal

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from .model.mqtt_model import MqttModel
from .viewmodel.monitor_viewmodel import MonitorViewModel
from .view.dashboard import SraderDashboard, STYLESHEET


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)

    # SIGINT (Ctrl+C) 처리
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    sigint_timer = QTimer()
    sigint_timer.setInterval(100)
    sigint_timer.timeout.connect(lambda: None)
    sigint_timer.start()

    model = MqttModel()
    vm    = MonitorViewModel(model)
    win   = SraderDashboard(vm)
    win.show()

    # Broker 는 항상 localhost:1883 (Mosquitto)
    vm.connect_broker("localhost", 1883)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
