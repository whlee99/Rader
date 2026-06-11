"""
viewmodel/monitor_viewmodel.py
Model(MqttModel) 로부터 raw payload 를 받아 View 에 표시할 데이터로 변환.

변환 내용:
  - s1[0], s1[1] (cm) → tilt_deg (atan 계산)
  - s2[i].d (64 uint16, mm) → 8열 최솟값 리스트
  - 기울기/장애물 상태 → StatusInfo
"""

import math
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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
    config_loaded       = Signal(bool, str)  # (success, message)

    # Calibration 기본값 (config 로드 시 교체)
    _SENSOR_GAP_CM   = 50.0
    _BASELINE_OFFSET = 0.0
    _TILT_LIMIT_DEG  = 15.0
    _THRESHOLD_MM    = 300

    # 하위호환성: 기존 코드가 클래스 상수를 참조할 수 있도록
    SENSOR_GAP_CM   = property(lambda self: self._SENSOR_GAP_CM)
    BASELINE_OFFSET = property(lambda self: self._BASELINE_OFFSET)
    TILT_LIMIT_DEG  = property(lambda self: self._TILT_LIMIT_DEG)
    THRESHOLD_MM    = property(lambda self: self._THRESHOLD_MM)

    # config 파일: 프로젝트 루트 / config / rader_config.json
    # __file__ = .../src/monitor/viewmodel/monitor_viewmodel.py → .parent×4 = 프로젝트 루트
    CONFIG_PATH = (Path(__file__).resolve().parent.parent.parent.parent
                   / "config" / "rader_config.json")

    def __init__(self, model: MqttModel, parent=None):
        super().__init__(parent)
        self._model = model
        # Calibration 값 (인스턴스 변수로 관리)
        self._SENSOR_GAP_CM   = 50.0
        self._BASELINE_OFFSET = 0.0
        self._TILT_LIMIT_DEG  = 15.0
        self._THRESHOLD_MM    = 300
        # MAC → 역할("L"/"R") 매핑 테이블 (config 로드 시 교체)
        self._mac_to_role: dict[str, str] = {}
        # L/R 최신값 저장 버퍼
        self._s1_buf: dict[str, int] = {}   # {"L": cm, "R": cm}
        # MAC → S2 디스플레이 슬롯 (config 로드 시 세팅, 없으면 도착 순서 자동 배정)
        self._mac_to_s2_slot: dict[str, int] = {}

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

    # ── Config 로드 ──────────────────────────────────────────────────
    def load_config(self, path: Path = None) -> tuple[bool, str]:
        """config JSON 로드 → MAC 매핑 + Calibration 값 적용."""
        p = path or self.CONFIG_PATH
        if not p.exists():
            msg = f"config 파일이 없습니다: {p}\n"\
                  "Setup 프로그램에서 설정 후 저장하세요."
            self.config_loaded.emit(False, msg)
            return False, msg

        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            msg = f"config 파일 읽기 실패: {e}"
            self.config_loaded.emit(False, msg)
            return False, msg

        # Calibration 상수 적용
        self._SENSOR_GAP_CM   = float(cfg.get("sensor_gap_cm",  50.0))
        self._BASELINE_OFFSET = float(cfg.get("baseline_offset", 0.0))
        self._TILT_LIMIT_DEG  = float(cfg.get("tilt_limit_deg", 15.0))
        self._THRESHOLD_MM    = int(cfg.get("threshold_mm", 300))

        # MAC → 역할 매핑 구성
        self._mac_to_role.clear()
        self._mac_to_s2_slot.clear()
        s2_slot = 0
        for dev in cfg.get("devices", []):
            if dev.get("type") == "S1":
                role = dev.get("s1", "")
                if role in ("L", "R"):
                    self._mac_to_role[dev["mac"]] = role
            elif dev.get("type") == "S2":
                self._mac_to_s2_slot[dev["mac"]] = s2_slot
                s2_slot += 1

        self._s1_buf.clear()   # 이전 버퍼 융기화
        s1_mapped = ", ".join(f"{m}→{r}" for m, r in self._mac_to_role.items()) or "(매핑 없음)"
        s2_mapped = ", ".join(f"{m}→슬롯{i}" for m, i in self._mac_to_s2_slot.items()) or "(매핑 없음)"
        msg = (f"config 로드 성공: {p}\n"
               f"  S1 매핑: {s1_mapped}\n"
               f"  S2 매핑: {s2_mapped}\n"
               f"  gap={self._SENSOR_GAP_CM}cm  "
               f"baseline={self._BASELINE_OFFSET}°  "
               f"tilt_limit={self._TILT_LIMIT_DEG}°  "
               f"threshold={self._THRESHOLD_MM}mm")
        self.config_loaded.emit(True, msg)
        return True, msg

    # ── Payload 처리 ──────────────────────────────────────────────────────────
    @Slot(dict)
    def _on_payload(self, data: dict):
        s1  = data.get("s1", [])
        s2  = data.get("s2", [])
        mac = data.get("mac", "?")

        # ── S1: MAC 매핑 L/R 버퍼 갱신 → 기울기 계산 ─────────────────────
        if s1:
            role = self._mac_to_role.get(mac, "")
            if role in ("L", "R"):
                self._s1_buf[role] = s1[0]   # ESP32 1대 = TFmini 1개 → s1[0] 만 사용

        left_cm  = self._s1_buf.get("L", 0)
        right_cm = self._s1_buf.get("R", 0)

        if self.SENSOR_GAP_CM > 0 and (left_cm or right_cm):
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

        # ── S2: MAC → 슬롯 매핑으로 업데이트 ──────────────────────────────
        # ESP32 1대 = VL53 1개: s2 배열의 첫 번째(index 0)만 사용
        if s2:
            # 슬롯 결정: config 매핑 우선, 없으면 도착 순서로 자동 배정
            slot = self._mac_to_s2_slot.get(mac)
            if slot is None:
                slot = len(self._mac_to_s2_slot)
                self._mac_to_s2_slot[mac] = slot

            d64  = s2[0].get("d", [4000] * 64)
            cols = self._d64_to_cols(d64)
            self.s2_updated.emit(slot, cols)
            all_min = [min(cols)]
        else:
            all_min = []

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
