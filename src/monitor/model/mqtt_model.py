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

TOPIC        = "RDR"
TOPIC_CONFIG = "RDR/config"


# ── Worker (QThread 내부 실행) ─────────────────────────────────────────────────
class _MqttWorker(QObject):
    payload_received = Signal(dict)   # 파싱된 payload dict
    config_received  = Signal(str)    # Provisioning config JSON 문자열
    log_signal       = Signal(str)    # 로그 메시지
    connected        = Signal()
    disconnected     = Signal()
    finished         = Signal()

    def __init__(self, broker: str, port: int, client_id: str = "rader_monitor"):
        super().__init__()
        self.broker    = broker
        self.port      = port
        self._client_id = client_id
        self._client   = None
        self._running  = False

    def _log(self, msg: str):
        self.log_signal.emit(msg)

    def _make_client(self):
        try:
            return mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION1,
                client_id=self._client_id,
                clean_session=True,
            )
        except AttributeError:
            return mqtt.Client(client_id=self._client_id, clean_session=True)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(TOPIC,        qos=1)
            client.subscribe(TOPIC_CONFIG, qos=1)
            self._log(f"브로커 접속 성공  ({self.broker}:{self.port})  →  구독: {TOPIC}, {TOPIC_CONFIG}")
            self.connected.emit()
        else:
            self._log(f"브로커 접속 거부  rc={rc}")
            self._running = False

    def _on_disconnect(self, client, userdata, rc):
        self._log(f"브로커 연결 해제  rc={rc}")
        self.disconnected.emit()

    def _on_message(self, client, userdata, msg):
        try:
            raw = msg.payload.decode()
            if msg.topic == TOPIC_CONFIG:
                self.config_received.emit(raw)
            else:
                self.payload_received.emit(json.loads(raw))
        except Exception as exc:
            self._log(f"payload 파싱 오류: {exc}")

    def publish(self, topic: str, payload: str,
                retain: bool = False, qos: int = 1) -> bool:
        """브로커에 메시지 발행. 접속 중일 때만 동작. True=성공."""
        if self._client and self._client.is_connected():
            self._client.publish(topic, payload, qos=qos, retain=retain)
            return True
        return False

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
    외부에서 사용하는 MQTT 구독/발행 모델.
    connect_broker() / disconnect_broker() 로 제어.
    수신 데이터는 payload_received 시그널로,
    RDR/config 수신은 config_received 시그널로 전달.
    """

    payload_received = Signal(dict)
    config_received  = Signal(str)   # Provisioning config JSON 문자열
    log_signal       = Signal(str)
    connected        = Signal()
    disconnected     = Signal()

    def __init__(self, parent=None, client_id: str = "rader_monitor"):
        super().__init__(parent)
        self._client_id  = client_id
        self._worker: _MqttWorker | None = None
        self._thread: QThread     | None = None

    def connect_broker(self, broker: str, port: int):
        if self._thread and self._thread.isRunning():
            return

        self._worker = _MqttWorker(broker, port, client_id=self._client_id)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.payload_received.connect(self.payload_received)
        self._worker.config_received.connect(self.config_received)
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

    def publish_config(self, json_text: str) -> bool:
        """RDR/config 토픽에 retain=True 로 config JSON 발행.
        브로커에 연결되어 있을 때만 동작. True=성공."""
        if self._worker:
            return self._worker.publish(TOPIC_CONFIG, json_text,
                                        retain=True, qos=1)
        return False

    def cleanup(self):
        self.disconnect_broker()
        if self._thread:
            self._thread.quit()
            self._thread.wait()
