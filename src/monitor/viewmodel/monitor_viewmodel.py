"""
viewmodel/monitor_viewmodel.py
Model(MqttModel) 로부터 raw payload 를 받아 View 에 표시할 데이터로 변환.

변환 내용:
  - s1[0], s1[1] (cm) → tilt_deg (atan 계산)
  - s2[i].d (64 uint16, mm) → 8열 최솟값 리스트
  - 기울기/장애물 상태 → StatusInfo
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from ..model.mqtt_model import MqttModel


# ── 상태 정보 데이터클래스 ────────────────────────────────────────────────────
@dataclass
class StatusInfo:
    level:   str   # "OK" | "TILT" | "OBSTACLE"
    message: str
    tilt_deg: float
    min_dist_mm: int


# ── ViewModel ─────────────────────────────────────────────────────────────────
class MonitorViewModel(QObject):
    """
    View 가 바인딩할 시그널:
        tilt_updated(float)          — 기울기 각도 (도)
        s1_labels_updated(str, str)  — S1-L / S1-R 텍스트
        s2_updated(int, list)        — (센서_index, 8열 mm 리스트)
        status_updated(StatusInfo)   — 전체 상태
        log_signal(str)              — 로그 메시지
        mqtt_connected()
        mqtt_disconnected()
    """

    tilt_updated        = Signal(float)
    s1_labels_updated   = Signal(str, str)
    s2_updated          = Signal(int, list)
    status_updated      = Signal(object)   # StatusInfo
    log_signal          = Signal(str)
    mqtt_connected      = Signal()
    mqtt_disconnected   = Signal()

    # Calibration 기본값 (Setup 후 config 로 교체 예정)
    SENSOR_GAP_CM    = 50.0
    BASELINE_OFFSET  = 0.0
    TILT_LIMIT_DEG   = 15.0
    THRESHOLD_MM     = 300

    def __init__(self, model: MqttModel, parent=None):
        super().__init__(parent)
        self._model = model

        # Model 시그널 연결
        self._model.payload_received.connect(self._on_payload)
        self._model.log_signal.connect(self.log_signal)
        self._model.connected.connect(self.mqtt_connected)
        self._model.disconnected.connect(self.mqtt_disconnected)

    # ── 브로커 제어 (View 가 직접 호출) ──────────────────────────────────────
    def connect_broker(self, broker: str, port: int):
        self._model.connect_broker(broker, port)

    def disconnect_broker(self):
        self._model.disconnect_broker()

    def cleanup(self):
        self._model.cleanup()

    # ── Payload 처리 ──────────────────────────────────────────────────────────
    @Slot(dict)
    def _on_payload(self, data: dict):
        s1 = data.get("s1", [0, 0])
        s2 = data.get("s2", [])
        mac = data.get("mac", "?")

        # ── S1: 기울기 계산 ──────────────────────────────────────────────────
        left_cm  = s1[0] if len(s1) > 0 else 0
        right_cm = s1[1] if len(s1) > 1 else 0

        if self.SENSOR_GAP_CM > 0:
            diff_cm  = left_cm - right_cm
            tilt_deg = math.degrees(math.atan(diff_cm / self.SENSOR_GAP_CM)) \
                       - self.BASELINE_OFFSET
        else:
            tilt_deg = 0.0

        self.tilt_updated.emit(round(tilt_deg, 2))
        self.s1_labels_updated.emit(
            f"S1-L: {left_cm} cm  ({left_cm * 10} mm)",
            f"S1-R: {right_cm} cm  ({right_cm * 10} mm)",
        )

        # ── S2: 8열 최솟값 추출 ──────────────────────────────────────────────
        all_min = []
        for idx, sensor in enumerate(s2):
            d64 = sensor.get("d", [4000] * 64)
            cols = self._d64_to_cols(d64)
            self.s2_updated.emit(idx, cols)
            all_min.append(min(cols))

        min_dist = min(all_min) if all_min else 9999

        # ── 전체 상태 ─────────────────────────────────────────────────────────
        if min_dist < self.THRESHOLD_MM:
            status = StatusInfo("OBSTACLE", "!!! OBSTACLE DETECTED !!!", tilt_deg, min_dist)
        elif abs(tilt_deg) > self.TILT_LIMIT_DEG:
            status = StatusInfo("TILT", "TILT WARNING", tilt_deg, min_dist)
        else:
            status = StatusInfo("OK", "SYSTEM OK", tilt_deg, min_dist)

        self.status_updated.emit(status)

        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_signal.emit(
            f"[{ts}]  MAC={mac}  tilt={tilt_deg:.1f}°  "
            f"min_d={min_dist}mm  S2×{len(s2)}"
        )

    @staticmethod
    def _d64_to_cols(d64: list) -> list:
        """64값(8×8) → 8열 최솟값 (열별 8개 row 중 min)"""
        result = []
        for col in range(8):
            col_vals = [d64[row * 8 + col] for row in range(8) if row * 8 + col < len(d64)]
            result.append(min(col_vals) if col_vals else 4000)
        return result
