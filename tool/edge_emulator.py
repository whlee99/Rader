#!/usr/bin/env python3
"""
edge_emulator.py
ESP32 Edge 장치 에뮬레이터 - Telemetry 데이터 송신 도구

7대의 가상 ESP32를 생성하며, 각 장치는 고유 MAC으로 독립 송신.
  - Device 1-2  (MAC :01~:02) : S1 타입 — TFmini Plus 1개  (슬라이더: 0~1000 cm)
  - Device 3-7  (MAC :03~:07) : S2 타입 — VL53L5CX  1개  (슬라이더: 0~4000 mm, 64 zone 동일값)
  - 주기 : 500 ms

물리 배치 순서 (좌→우): 01 / 03 / 04 / 05 / 06 / 07 / 02

사용법:
    python tool/edge_emulator.py
"""

import sys
import json
import time
import threading
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton,
    QTextEdit, QGroupBox, QSlider,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject, Slot
from PySide6.QtGui import QFont

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

# ── 고정 설정 ─────────────────────────────────────────────────────────────────
TOPIC           = "RDR"
INTERVAL_MS     = 500
ZONE_COUNT      = 64            # 8x8
OUI             = "A4:CF:12"    # Espressif OUI
S1_DEVICE_COUNT = 2             # Device 1-2 : TFmini Plus
S2_DEVICE_COUNT = 5             # Device 3-7 : VL53L5CX
TOTAL_DEVICES   = S1_DEVICE_COUNT + S2_DEVICE_COUNT   # 7
LOG_MAX_LINES   = 5000

# 물리 배치 순서 (0-based index) : 01, 03, 04, 05, 06, 07, 02
DISPLAY_ORDER = [0, 2, 3, 4, 5, 6, 1]

# 슬라이더 범위
S1_MAX_CM  = 1000   # TFmini Plus 표시 최대 (cm)
S2_MAX_MM  = 4000   # VL53L5CX 최대 (mm)

# 슬라이더 기본값
S1_DEFAULT_CM = 500
S2_DEFAULT_MM = 2000


def _mac_for(index: int) -> str:
    """index 0-based → A4:CF:12:00:00:(index+1)"""
    return f"{OUI}:00:00:{(index + 1):02X}"


def _device_type(index: int) -> str:
    """index 0-based → 'S1' or 'S2'"""
    return "S1" if index < S1_DEVICE_COUNT else "S2"


# ── 페이로드 생성 (슬라이더 값 사용) ─────────────────────────────────────────
def generate_payload(mac: str, device_type: str, value: int) -> str:
    """
    value:
      S1 → 거리 cm
      S2 → 거리 mm (64 zone 전체 동일값, status=5(유효), nb=1)
    """
    payload: dict = {"mac": mac, "ts": int(time.time() * 1000)}
    if device_type == "S1":
        payload["s1"] = [value]
    else:
        payload["s2"] = [{
            "d":  [value] * ZONE_COUNT,
            "st": [5]     * ZONE_COUNT,
            "nb": [1]     * ZONE_COUNT,
        }]
    return json.dumps(payload, separators=(",", ":"))


# ── 장치 1대 Worker ───────────────────────────────────────────────────────────
class DeviceWorker(QObject):
    log_signal    = Signal(str)
    status_signal = Signal(str, bool)
    finished      = Signal(str)

    def __init__(self, mac: str, broker: str, port: int,
                 device_type: str, value_getter):
        super().__init__()
        self.mac           = mac
        self.broker        = broker
        self.port          = port
        self.device_type   = device_type
        self._value_getter = value_getter
        self._stop_evt     = threading.Event()
        self._client       = None

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_signal.emit(f"[{ts}]  [{self.mac}]  {msg}")

    def _make_client(self):
        cid = f"rader_emu_{self.mac.replace(':', '')}"
        try:
            return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1,
                               client_id=cid, clean_session=True)
        except AttributeError:
            return mqtt.Client(client_id=cid, clean_session=True)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._log("접속 성공")
            self.status_signal.emit(self.mac, True)
        else:
            self._log(f"접속 거부 rc={rc}")
            self.status_signal.emit(self.mac, False)
            self._stop_evt.set()

    def _on_disconnect(self, client, userdata, rc):
        self.status_signal.emit(self.mac, False)

    @Slot()
    def run(self):
        if not MQTT_AVAILABLE:
            self._log("ERROR: paho-mqtt 미설치")
            self.finished.emit(self.mac)
            return

        self._client = self._make_client()
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        try:
            self._client.connect(self.broker, self.port, keepalive=60)
        except Exception as exc:
            self._log(f"접속 실패: {exc}")
            self.finished.emit(self.mac)
            return

        self._client.loop_start()

        deadline = time.time() + 5.0
        while not self._client.is_connected() and time.time() < deadline:
            if self._stop_evt.wait(timeout=0.05):
                break

        if not self._client.is_connected():
            if not self._stop_evt.is_set():
                self._log("접속 타임아웃 (5s)")
            self._client.loop_stop()
            self.finished.emit(self.mac)
            return

        count = 0
        while not self._stop_evt.is_set():
            value   = self._value_getter()
            payload = generate_payload(self.mac, self.device_type, value)
            self._client.publish(TOPIC, payload, qos=1)
            count += 1
            unit = "cm" if self.device_type == "S1" else "mm"
            self._log(f"TX #{count:>5}  {value}{unit}  {len(payload):,}B")
            self._stop_evt.wait(timeout=INTERVAL_MS / 1000.0)

        self._client.loop_stop()
        self._client.disconnect()
        self._log("송신 중지")
        self.finished.emit(self.mac)

    def stop(self):
        self._stop_evt.set()


# ── 수직 슬라이더 컬럼 위젯 ──────────────────────────────────────────────────
class SensorSliderWidget(QWidget):
    """장치 1대의 수직 슬라이더 + 값 표시"""

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self._dtype = _device_type(index)
        dev_num     = index + 1

        if self._dtype == "S1":
            self._max     = S1_MAX_CM
            self._unit    = "cm"
            self._default = S1_DEFAULT_CM
            range_top     = f"{S1_MAX_CM // 100}m"
        else:
            self._max     = S2_MAX_MM
            self._unit    = "mm"
            self._default = S2_DEFAULT_MM
            range_top     = f"{S2_MAX_MM // 1000}m"

        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        layout.setContentsMargins(4, 4, 4, 4)

        dev_lbl = QLabel(f"{dev_num:02d}")
        dev_lbl.setAlignment(Qt.AlignCenter)
        dev_lbl.setStyleSheet(
            f"font-weight:bold; font-size:13px; "
            f"color:{'#ef9a9a' if self._dtype == 'S1' else '#90caf9'};"
        )
        layout.addWidget(dev_lbl)

        type_lbl = QLabel(self._dtype)
        type_lbl.setAlignment(Qt.AlignCenter)
        type_lbl.setStyleSheet("font-size:10px; color:#aaa;")
        layout.addWidget(type_lbl)

        top_lbl = QLabel(range_top)
        top_lbl.setAlignment(Qt.AlignCenter)
        top_lbl.setStyleSheet("font-size:10px; color:#777;")
        layout.addWidget(top_lbl)

        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(0, self._max)
        self.slider.setValue(self._default)
        self.slider.setTickInterval(self._max // 4)
        self.slider.setTickPosition(QSlider.TicksBothSides)
        self.slider.setMinimumHeight(180)
        layout.addWidget(self.slider, alignment=Qt.AlignHCenter)

        bot_lbl = QLabel("0m")
        bot_lbl.setAlignment(Qt.AlignCenter)
        bot_lbl.setStyleSheet("font-size:10px; color:#777;")
        layout.addWidget(bot_lbl)

        self.val_lbl = QLabel(f"{self._default} {self._unit}")
        self.val_lbl.setAlignment(Qt.AlignCenter)
        self.val_lbl.setStyleSheet("font-size:11px; font-weight:bold;")
        layout.addWidget(self.val_lbl)

        self.slider.valueChanged.connect(self._on_value_changed)

    @Slot(int)
    def _on_value_changed(self, v: int):
        self.val_lbl.setText(f"{v} {self._unit}")

    def value(self) -> int:
        return self.slider.value()


# ── 메인 윈도우 ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Rader Edge Emulator")
        self.resize(900, 640)
        self._devices: dict[str, tuple[QThread, DeviceWorker]] = {}
        self._device_labels: dict[str, QLabel] = {}
        self._sliders: dict[str, SensorSliderWidget] = {}
        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # ── 연결 설정 ────────────────────────────────────────────────────────
        conn_box = QGroupBox("브로커 연결 설정")
        conn_lay = QHBoxLayout(conn_box)

        conn_lay.addWidget(QLabel("Broker IP :"))
        self.broker_edit = QLineEdit("localhost")
        self.broker_edit.setFixedWidth(150)
        conn_lay.addWidget(self.broker_edit)

        conn_lay.addWidget(QLabel("Port :"))
        self.port_edit = QLineEdit("1883")
        self.port_edit.setFixedWidth(55)
        conn_lay.addWidget(self.port_edit)

        conn_lay.addSpacing(20)
        self.start_btn = QPushButton("▶  Start")
        self.start_btn.setFixedWidth(110)
        self.start_btn.setStyleSheet(
            "QPushButton{background:#2e7d32;color:white;font-weight:bold;padding:4px 8px;}"
            "QPushButton:disabled{background:#aaa;}")
        self.start_btn.clicked.connect(self._on_start)
        conn_lay.addWidget(self.start_btn)

        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setFixedWidth(110)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            "QPushButton{background:#c62828;color:white;font-weight:bold;padding:4px 8px;}"
            "QPushButton:disabled{background:#aaa;}")
        self.stop_btn.clicked.connect(self._on_stop)
        conn_lay.addWidget(self.stop_btn)
        conn_lay.addStretch()
        root.addWidget(conn_box)

        # ── 센서 슬라이더 ────────────────────────────────────────────────────
        slider_box = QGroupBox("센서 값 조정  (물리 배치 순서: 좌→우,  빨강=S1/TFmini,  파랑=S2/VL53)")
        slider_lay = QHBoxLayout(slider_box)
        slider_lay.setSpacing(8)
        slider_lay.addStretch()
        for idx in DISPLAY_ORDER:
            mac = _mac_for(idx)
            w   = SensorSliderWidget(idx)
            self._sliders[mac] = w
            slider_lay.addWidget(w)
        slider_lay.addStretch()
        root.addWidget(slider_box)

        # ── 장치 상태 표시 ───────────────────────────────────────────────────
        self.device_box = QGroupBox("가상 장치 연결 상태")
        self.device_lay = QHBoxLayout(self.device_box)
        root.addWidget(self.device_box)

        # ── 로그 ─────────────────────────────────────────────────────────────
        log_box = QGroupBox("로그")
        log_lay = QVBoxLayout(log_box)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(QFont("Consolas", 8))
        self.log_edit.setFixedHeight(120)
        log_lay.addWidget(self.log_edit)
        clr = QPushButton("로그 지우기")
        clr.setFixedWidth(100)
        clr.clicked.connect(self.log_edit.clear)
        log_lay.addWidget(clr, alignment=Qt.AlignRight)
        root.addWidget(log_box)

    def _rebuild_device_labels(self):
        while self.device_lay.count():
            item = self.device_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._device_labels.clear()

        for i in range(TOTAL_DEVICES):
            mac   = _mac_for(i)
            dtype = _device_type(i)
            lbl   = QLabel(f"[{dtype}] :{(i+1):02X}\n미접속")
            lbl.setStyleSheet("color:gray; font-family:Consolas; font-size:11px;"
                              "border:1px solid #555; border-radius:4px; padding:4px 6px;")
            lbl.setAlignment(Qt.AlignCenter)
            self._device_labels[mac] = lbl
            self.device_lay.addWidget(lbl)
        self.device_lay.addStretch()

    def _append_log(self, msg: str):
        if self.log_edit.document().blockCount() >= LOG_MAX_LINES:
            self.log_edit.clear()
        self.log_edit.append(msg)
        self.log_edit.verticalScrollBar().setValue(
            self.log_edit.verticalScrollBar().maximum())

    @Slot()
    def _on_start(self):
        broker = self.broker_edit.text().strip()
        try:
            port = int(self.port_edit.text().strip())
        except ValueError:
            self._append_log("ERROR: Port는 숫자여야 합니다.")
            return

        self._rebuild_device_labels()
        self.start_btn.setEnabled(False)
        self.broker_edit.setEnabled(False)
        self.port_edit.setEnabled(False)
        self.stop_btn.setEnabled(True)

        for i in range(TOTAL_DEVICES):
            mac   = _mac_for(i)
            dtype = _device_type(i)
            sw    = self._sliders[mac]
            worker = DeviceWorker(mac, broker, port, dtype,
                                  value_getter=sw.value)
            thread = QThread()
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.log_signal.connect(self._append_log)
            worker.status_signal.connect(self._on_device_status)
            worker.finished.connect(self._on_device_finished)
            self._devices[mac] = (thread, worker)
            thread.start()

    @Slot()
    def _on_stop(self):
        for _, (_, worker) in self._devices.items():
            worker.stop()
        self.stop_btn.setEnabled(False)

    @Slot(str, bool)
    def _on_device_status(self, mac: str, connected: bool):
        lbl = self._device_labels.get(mac)
        if not lbl:
            return
        try:
            idx   = int(mac.split(":")[-1], 16) - 1
            dtype = _device_type(idx)
            num   = idx + 1
        except Exception:
            dtype, num = "??", 0

        if connected:
            lbl.setText(f"[{dtype}] :{num:02X}\n송신 중")
            lbl.setStyleSheet("color:#4caf50; font-family:Consolas; font-size:11px;"
                              "border:1px solid #4caf50; border-radius:4px; padding:4px 6px;")
        else:
            lbl.setText(f"[{dtype}] :{num:02X}\n미접속")
            lbl.setStyleSheet("color:gray; font-family:Consolas; font-size:11px;"
                              "border:1px solid #555; border-radius:4px; padding:4px 6px;")

    @Slot(str)
    def _on_device_finished(self, mac: str):
        if mac in self._devices:
            thread, _ = self._devices.pop(mac)
            thread.quit()
            thread.wait()

        if not self._devices:
            self.start_btn.setEnabled(True)
            self.broker_edit.setEnabled(True)
            self.port_edit.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def closeEvent(self, event):
        for _, (thread, worker) in self._devices.items():
            worker.stop()
            thread.quit()
        for _, (thread, _) in self._devices.items():
            thread.wait(2000)
        event.accept()


# ── 진입점 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
