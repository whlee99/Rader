"""
model/mqtt_model.py
MQTT Broker 구독 모델.
QThread 안에서 동작하며 수신된 JSON payload 를 파싱해 시그널로 전달.
"""

import json
import time

from PySide6.QtCore import QObject, QThread, Signal, Slot

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

TOPIC = "RDR"


# ── Worker (QThread 내부 실행) ─────────────────────────────────────────────────
class _MqttWorker(QObject):
    payload_received = Signal(dict)   # 파싱된 payload dict
    log_signal       = Signal(str)    # 로그 메시지
    connected        = Signal()
    disconnected     = Signal()
    finished         = Signal()

    def __init__(self, broker: str, port: int):
        super().__init__()
        self.broker   = broker
        self.port     = port
        self._client  = None
        self._running = False

    def _log(self, msg: str):
        self.log_signal.emit(msg)

    def _make_client(self):
        try:
            return mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id="rader_monitor",
                clean_session=True,
            )
        except AttributeError:
            return mqtt.Client(client_id="rader_monitor", clean_session=True)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(TOPIC, qos=1)
            self._log(f"브로커 접속 성공  ({self.broker}:{self.port})  →  구독: {TOPIC}")
            self.connected.emit()
        else:
            self._log(f"브로커 접속 거부  rc={rc}")
            self._running = False

    def _on_disconnect(self, client, userdata, rc):
        self._log(f"브로커 연결 해제  rc={rc}")
        self.disconnected.emit()

    def _on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            self.payload_received.emit(data)
        except Exception as exc:
            self._log(f"payload 파싱 오류: {exc}")

    @Slot()
    def run(self):
        if not MQTT_AVAILABLE:
            self._log("ERROR: paho-mqtt 미설치  →  pip install paho-mqtt")
            self.finished.emit()
            return

        self._client = self._make_client()
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message

        self._log(f"브로커 접속 시도  →  {self.broker}:{self.port}")
        try:
            self._client.connect(self.broker, self.port, keepalive=60)
        except Exception as exc:
            self._log(f"접속 실패: {exc}")
            self.finished.emit()
            return

        self._running = True
        self._client.loop_start()

        # 접속 대기 (최대 5초)
        deadline = time.time() + 5.0
        while not self._client.is_connected() and time.time() < deadline:
            time.sleep(0.05)

        if not self._client.is_connected():
            self._log("접속 타임아웃 (5s)")
            self._client.loop_stop()
            self.finished.emit()
            return

        # 메시지 수신은 loop_start 가 처리하므로 여기서는 stop 신호 대기
        while self._running:
            time.sleep(0.1)

        self._client.loop_stop()
        self._client.disconnect()
        self._log("구독 종료  브로커 접속 해제")
        self.finished.emit()

    def stop(self):
        self._running = False


# ── 퍼블릭 Model 클래스 ───────────────────────────────────────────────────────
class MqttModel(QObject):
    """
    외부에서 사용하는 MQTT 구독 모델.
    connect_broker() / disconnect_broker() 로 제어.
    수신 데이터는 payload_received 시그널로 전달.
    """

    payload_received = Signal(dict)
    log_signal       = Signal(str)
    connected        = Signal()
    disconnected     = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _MqttWorker | None = None
        self._thread: QThread     | None = None

    def connect_broker(self, broker: str, port: int):
        if self._thread and self._thread.isRunning():
            return

        self._worker = _MqttWorker(broker, port)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.payload_received.connect(self.payload_received)
        self._worker.log_signal.connect(self.log_signal)
        self._worker.connected.connect(self.connected)
        self._worker.disconnected.connect(self.disconnected)
        self._worker.finished.connect(self._on_finished)

        self._thread.start()

    def disconnect_broker(self):
        if self._worker:
            self._worker.stop()

    def _on_finished(self):
        if self._thread:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None

    def cleanup(self):
        self.disconnect_broker()
        if self._thread:
            self._thread.quit()
            self._thread.wait()
