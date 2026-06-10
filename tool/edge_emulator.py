#!/usr/bin/env python3
"""
edge_emulator.py
ESP32 Edge 장치 에뮬레이터 - Telemetry 데이터 송신 도구

장치 수만큼 가상 ESP32를 생성하며, 각 장치는 고유 MAC으로 독립 송신.
  - S1(TFmini Plus) × 2  per device
  - S2(VL53L5CX)   × 5  per device
  - 주기 : 500 ms

사용법:
    python tool/edge_emulator.py
"""

import sys
import json
import time
import random
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton,
    QTextEdit, QGroupBox, QSpinBox,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject, Slot
from PySide6.QtGui import QFont

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

# ── 고정 설정 ─────────────────────────────────────────────────────────────────
TOPIC        = "RDR"
INTERVAL_MS  = 500
S1_COUNT     = 2
S2_COUNT     = 5
ZONE_COUNT   = 64   # 8x8
OUI          = "A4:CF:12"   # Espressif OUI


def _mac_for(index: int) -> str:
    """index 0-based → A4:CF:12:00:00:(index+1)"""
    return f"{OUI}:00:00:{(index + 1):02X}"


# ── 페이로드 생성 ─────────────────────────────────────────────────────────────
def _make_s1() -> list:
    return [random.randint(50, 300) for _ in range(S1_COUNT)]


def _make_s2() -> list:
    result = []
    for _ in range(S2_COUNT):
        result.append({
            "d":  [random.randint(200, 2500) for _ in range(ZONE_COUNT)],
            "st": [random.choice([5, 6, 9, 10]) for _ in range(ZONE_COUNT)],
            "nb": [random.randint(0, 1)         for _ in range(ZONE_COUNT)],
        })
    return result


def generate_payload(mac: str) -> str:
    return json.dumps({
        "mac": mac,
        "ts":  int(time.time() * 1000),
        "s1":  _make_s1(),
        "s2":  _make_s2(),
    }, separators=(",", ":"))


# ── 장치 1대 Worker ───────────────────────────────────────────────────────────
class DeviceWorker(QObject):
    log_signal    = Signal(str)
    status_signal = Signal(str, bool)   # (mac, connected)
    finished      = Signal(str)         # mac

    def __init__(self, mac: str, broker: str, port: int):
        super().__init__()
        self.mac      = mac
        self.broker   = broker
        self.port     = port
        self._running = False
        self._client  = None

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
            self._running = False

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
        self._running = True

        deadline = time.time() + 5.0
        while not self._client.is_connected() and time.time() < deadline:
            time.sleep(0.05)

        if not self._client.is_connected():
            self._log("접속 타임아웃 (5s)")
            self._client.loop_stop()
            self.finished.emit(self.mac)
            return

        count = 0
        while self._running:
            payload = generate_payload(self.mac)
            self._client.publish(TOPIC, payload, qos=1)
            count += 1
            self._log(f"TX #{count:>5}  {len(payload):,}B")
            time.sleep(INTERVAL_MS / 1000.0)

        self._client.loop_stop()
        self._client.disconnect()
        self._log("송신 중지")
        self.finished.emit(self.mac)

    def stop(self):
        self._running = False


# ── 메인 윈도우 ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Rader Edge Emulator")
        self.resize(820, 580)
        self._devices: dict[str, tuple[QThread, DeviceWorker]] = {}  # mac → (thread, worker)
        self._device_labels: dict[str, QLabel] = {}
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
        conn_lay.addWidget(QLabel("가상 장치 수 :"))
        self.device_spin = QSpinBox()
        self.device_spin.setRange(1, 8)
        self.device_spin.setValue(2)
        self.device_spin.setFixedWidth(55)
        conn_lay.addWidget(self.device_spin)

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

        # ── 장치 상태 표시 ───────────────────────────────────────────────────
        self.device_box = QGroupBox("가상 장치 상태")
        self.device_lay = QHBoxLayout(self.device_box)
        root.addWidget(self.device_box)

        # ── 고정 정보 ────────────────────────────────────────────────────────
        info_box = QGroupBox("에뮬레이터 정보")
        info_lay = QHBoxLayout(info_box)
        for text in [
            f"OUI : {OUI}:xx:xx:xx",
            f"TOPIC : {TOPIC}",
            f"S1 × {S1_COUNT}  |  S2 × {S2_COUNT}  (8×8)",
            f"주기 : {INTERVAL_MS} ms",
        ]:
            lbl = QLabel(text)
            lbl.setStyleSheet("color:#555;")
            info_lay.addWidget(lbl)
            info_lay.addSpacing(12)
        info_lay.addStretch()
        root.addWidget(info_box)

        # ── 로그 ─────────────────────────────────────────────────────────────
        log_box = QGroupBox("로그")
        log_lay = QVBoxLayout(log_box)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(QFont("Consolas", 8))
        log_lay.addWidget(self.log_edit)
        clr = QPushButton("로그 지우기")
        clr.setFixedWidth(100)
        clr.clicked.connect(self.log_edit.clear)
        log_lay.addWidget(clr, alignment=Qt.AlignRight)
        root.addWidget(log_box, stretch=1)

    # ── 장치 상태 위젯 갱신 ───────────────────────────────────────────────────
    def _rebuild_device_labels(self, count: int):
        # 기존 위젯 제거
        while self.device_lay.count():
            item = self.device_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._device_labels.clear()

        for i in range(count):
            mac = _mac_for(i)
            lbl = QLabel(f"●  {mac}\n미접속")
            lbl.setStyleSheet("color:gray; font-family:Consolas; font-size:11px;"
                              "border:1px solid #ccc; border-radius:4px; padding:4px 8px;")
            lbl.setAlignment(Qt.AlignCenter)
            self._device_labels[mac] = lbl
            self.device_lay.addWidget(lbl)
        self.device_lay.addStretch()

    # ── 슬롯 ──────────────────────────────────────────────────────────────────
    def _append_log(self, msg: str):
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

        count = self.device_spin.value()
        self._rebuild_device_labels(count)

        self.start_btn.setEnabled(False)
        self.broker_edit.setEnabled(False)
        self.port_edit.setEnabled(False)
        self.device_spin.setEnabled(False)
        self.stop_btn.setEnabled(True)

        for i in range(count):
            mac = _mac_for(i)
            worker = DeviceWorker(mac, broker, port)
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
        if connected:
            lbl.setText(f"●  {mac}\n송신 중")
            lbl.setStyleSheet("color:#2e7d32; font-family:Consolas; font-size:11px;"
                              "border:1px solid #4caf50; border-radius:4px; padding:4px 8px;")
        else:
            lbl.setText(f"●  {mac}\n미접속")
            lbl.setStyleSheet("color:gray; font-family:Consolas; font-size:11px;"
                              "border:1px solid #ccc; border-radius:4px; padding:4px 8px;")

    @Slot(str)
    def _on_device_finished(self, mac: str):
        if mac in self._devices:
            thread, _ = self._devices.pop(mac)
            thread.quit()
            thread.wait()

        if not self._devices:   # 모든 장치 종료
            self.start_btn.setEnabled(True)
            self.broker_edit.setEnabled(True)
            self.port_edit.setEnabled(True)
            self.device_spin.setEnabled(True)
            self.stop_btn.setEnabled(False)

    def closeEvent(self, event):
        for _, (thread, worker) in self._devices.items():
            worker.stop()
            thread.quit()
            thread.wait()
        event.accept()


# ── 진입점 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


import sys
import json
import time
import random
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton,
    QTextEdit, QGroupBox,
)
from PySide6.QtCore import Qt, QThread, Signal, QObject, Slot
from PySide6.QtGui import QFont

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

# ── 에뮬레이터 고정 설정 ──────────────────────────────────────────────────────
FAKE_MAC    = "A4:CF:12:00:00:01"   # Espressif OUI 기반 에뮬레이터 전용 MAC
TOPIC       = "RDR"
INTERVAL_MS = 500
S1_COUNT    = 2
S2_COUNT    = 5
ZONE_COUNT  = 64   # 8x8


# ── 페이로드 생성 ─────────────────────────────────────────────────────────────
def _make_s1() -> list:
    """TFmini Plus 거리값 2개 (cm, 50~300)"""
    return [random.randint(50, 300) for _ in range(S1_COUNT)]


def _make_s2() -> list:
    """VL53L5CX 8x8 데이터 5개"""
    result = []
    for _ in range(S2_COUNT):
        result.append({
            "d":  [random.randint(200, 2500) for _ in range(ZONE_COUNT)],
            "st": [random.choice([5, 6, 9, 10]) for _ in range(ZONE_COUNT)],
            "nb": [random.randint(0, 1)         for _ in range(ZONE_COUNT)],
        })
    return result


def generate_payload() -> str:
    payload = {
        "mac": FAKE_MAC,
        "ts":  int(time.time() * 1000),
        "s1":  _make_s1(),
        "s2":  _make_s2(),
    }
    return json.dumps(payload, separators=(",", ":"))


# ── MQTT Worker (QThread 내부에서 실행) ───────────────────────────────────────
class MqttWorker(QObject):
    log_signal    = Signal(str)   # 로그 메시지
    status_signal = Signal(bool)  # True=접속중·송신중, False=미접속
    finished      = Signal()

    def __init__(self, broker: str, port: int):
        super().__init__()
        self.broker   = broker
        self.port     = port
        self._running = False
        self._client  = None

    # ── 내부 유틸 ──────────────────────────────────────────────────────────────
    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_signal.emit(f"[{ts}]  {msg}")

    def _make_client(self):
        """paho-mqtt v1 / v2 모두 대응"""
        try:
            return mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id="rader_emulator",
                clean_session=True,
            )
        except AttributeError:
            return mqtt.Client(client_id="rader_emulator", clean_session=True)

    # ── MQTT 콜백 ─────────────────────────────────────────────────────────────
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._log(f"브로커 접속 성공  ({self.broker}:{self.port})")
            self.status_signal.emit(True)
        else:
            self._log(f"브로커 접속 거부  rc={rc}")
            self.status_signal.emit(False)
            self._running = False

    def _on_disconnect(self, client, userdata, rc):
        if rc != 0:
            self._log(f"브로커 연결 끊김  rc={rc}")
        self.status_signal.emit(False)

    # ── 메인 루프 ─────────────────────────────────────────────────────────────
    @Slot()
    def run(self):
        if not MQTT_AVAILABLE:
            self._log("ERROR: paho-mqtt 미설치  →  pip install paho-mqtt")
            self.finished.emit()
            return

        self._client = self._make_client()
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect

        self._log(f"브로커 접속 시도  →  {self.broker}:{self.port}")
        try:
            self._client.connect(self.broker, self.port, keepalive=60)
        except Exception as exc:
            self._log(f"접속 실패:  {exc}")
            self.status_signal.emit(False)
            self.finished.emit()
            return

        self._client.loop_start()
        self._running = True

        # 접속 확인 대기 (최대 5초)
        deadline = time.time() + 5.0
        while not self._client.is_connected() and time.time() < deadline:
            time.sleep(0.05)

        if not self._client.is_connected():
            self._log("접속 타임아웃 (5s)")
            self._client.loop_stop()
            self.status_signal.emit(False)
            self.finished.emit()
            return

        # 송신 루프
        count = 0
        while self._running:
            payload = generate_payload()
            self._client.publish(TOPIC, payload, qos=1)
            count += 1
            self._log(
                f"TX #{count:>5}  topic={TOPIC}  "
                f"S1×{S1_COUNT}  S2×{S2_COUNT}  "
                f"{len(payload):,}B"
            )
            time.sleep(INTERVAL_MS / 1000.0)

        # 종료
        self._client.loop_stop()
        self._client.disconnect()
        self._log("송신 중지  브로커 접속 해제")
        self.status_signal.emit(False)
        self.finished.emit()

    def stop(self):
        self._running = False


# ── 메인 윈도우 ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Rader Edge Emulator")
        self.resize(760, 540)
        self._thread: QThread | None = None
        self._worker: MqttWorker | None = None
        self._build_ui()

    # ── UI 구성 ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # 연결 설정
        conn_box = QGroupBox("브로커 연결 설정")
        conn_lay = QHBoxLayout(conn_box)

        conn_lay.addWidget(QLabel("Broker IP :"))
        self.broker_edit = QLineEdit("192.168.0.203")
        self.broker_edit.setFixedWidth(160)
        conn_lay.addWidget(self.broker_edit)

        conn_lay.addWidget(QLabel("Port :"))
        self.port_edit = QLineEdit("1883")
        self.port_edit.setFixedWidth(60)
        conn_lay.addWidget(self.port_edit)

        conn_lay.addSpacing(24)

        self.start_btn = QPushButton("▶  Start")
        self.start_btn.setFixedWidth(110)
        self.start_btn.setStyleSheet(
            "QPushButton{background:#2e7d32;color:white;font-weight:bold;padding:4px 8px;}"
            "QPushButton:disabled{background:#aaa;}"
        )
        self.start_btn.clicked.connect(self._on_start)
        conn_lay.addWidget(self.start_btn)

        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setFixedWidth(110)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet(
            "QPushButton{background:#c62828;color:white;font-weight:bold;padding:4px 8px;}"
            "QPushButton:disabled{background:#aaa;}"
        )
        self.stop_btn.clicked.connect(self._on_stop)
        conn_lay.addWidget(self.stop_btn)

        conn_lay.addStretch()
        root.addWidget(conn_box)

        # 에뮬레이터 정보
        info_box = QGroupBox("에뮬레이터 정보")
        info_lay = QHBoxLayout(info_box)
        for text in [
            f"MAC : {FAKE_MAC}",
            f"TOPIC : {TOPIC}",
            f"S1 × {S1_COUNT}  |  S2 × {S2_COUNT}  (8×8)",
            f"주기 : {INTERVAL_MS} ms",
        ]:
            lbl = QLabel(text)
            lbl.setStyleSheet("color:#444;")
            info_lay.addWidget(lbl)
            info_lay.addSpacing(16)

        info_lay.addStretch()

        self.status_lbl = QLabel("●  미접속")
        self.status_lbl.setStyleSheet("color:gray;font-weight:bold;font-size:13px;")
        info_lay.addWidget(self.status_lbl)
        root.addWidget(info_box)

        # 로그
        log_box = QGroupBox("로그")
        log_lay = QVBoxLayout(log_box)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setFont(QFont("Consolas", 9))
        log_lay.addWidget(self.log_edit)

        clear_btn = QPushButton("로그 지우기")
        clear_btn.setFixedWidth(100)
        clear_btn.clicked.connect(self.log_edit.clear)
        log_lay.addWidget(clear_btn, alignment=Qt.AlignRight)
        root.addWidget(log_box, stretch=1)

        if not MQTT_AVAILABLE:
            self._append_log("⚠  paho-mqtt 미설치 — 실행 전  pip install paho-mqtt  필요")

    # ── 슬롯 ──────────────────────────────────────────────────────────────────
    def _append_log(self, msg: str):
        self.log_edit.append(msg)
        sb = self.log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    @Slot()
    def _on_start(self):
        broker = self.broker_edit.text().strip()
        try:
            port = int(self.port_edit.text().strip())
        except ValueError:
            self._append_log("ERROR: Port 는 숫자여야 합니다.")
            return
        if not broker:
            self._append_log("ERROR: Broker IP 를 입력하세요.")
            return

        self.start_btn.setEnabled(False)
        self.broker_edit.setEnabled(False)
        self.port_edit.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self._worker = MqttWorker(broker, port)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log_signal.connect(self._append_log)
        self._worker.status_signal.connect(self._on_status)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    @Slot()
    def _on_stop(self):
        if self._worker:
            self._worker.stop()
        self.stop_btn.setEnabled(False)

    @Slot(bool)
    def _on_status(self, connected: bool):
        if connected:
            self.status_lbl.setText("●  송신 중")
            self.status_lbl.setStyleSheet("color:#2e7d32;font-weight:bold;font-size:13px;")
        else:
            self.status_lbl.setText("●  미접속")
            self.status_lbl.setStyleSheet("color:gray;font-weight:bold;font-size:13px;")

    @Slot()
    def _on_finished(self):
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self.start_btn.setEnabled(True)
        self.broker_edit.setEnabled(True)
        self.port_edit.setEnabled(True)
        self.stop_btn.setEnabled(False)

    def closeEvent(self, event):
        if self._worker:
            self._worker.stop()
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        event.accept()


# ── 진입점 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
