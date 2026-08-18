"""
src/setup/viewmodel/setup_viewmodel.py
Setup UI 의 ViewModel.

- MQTT 수신 → 장치 자동 감지 → 시그널로 View 갱신
- Calibration 계산 (tilt_deg)
- Config 빌드 / 저장 / JSON 미리보기
- SSH Push (paramiko)
"""

import math
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from ..model.config_model import RaderConfig, DeviceConfig

from src.monitor.model.mqtt_model import MqttModel

# config 로컬 저장 경로
# config 파일: 프로젝트 루트(src 의 부모) / config / rader_config.json
# __file__ = .../src/setup/viewmodel/setup_viewmodel.py → .parent×4 = 프로젝트 루트
_PROJECT_ROOT   = Path(__file__).resolve().parent.parent.parent.parent
LOCAL_CONFIG_PATH = _PROJECT_ROOT / "config" / "rader_config.json"


# ── 수신 장치 스냅샷 ──────────────────────────────────────────────────────────
@dataclass
class DeviceSnapshot:
    mac:         str
    dtype:       str         # "S1" | "S2"
    last_seen:   str         # HH:MM:SS
    s1_values:   list[int]   # cm  (S1 장치)
    s2_values:   list[int]   # mm, 64 zone 최솟값 (S2 장치)
    s2_raw64:    list[int]   = None   # mm, 64존 원시값 (S2 장치)


# ── ViewModel ─────────────────────────────────────────────────────────────────
class SetupViewModel(QObject):
    """
    View 가 바인딩할 시그널:
        device_list_updated(list[DeviceSnapshot])  — 감지된 장치 목록 갱신
        tilt_preview_updated(float, int, int)      — (tilt_deg, left_cm, right_cm)
        log_signal(str)
        mqtt_connected()
        mqtt_disconnected()
        publish_result(bool, str)                  — (성공, 메시지)
        config_preview_updated(str)                — JSON 미리보기 텍스트
    """

    device_list_updated   = Signal(list)     # list[DeviceSnapshot]
    tilt_preview_updated  = Signal(float, int, int)
    log_signal            = Signal(str)
    mqtt_connected        = Signal()
    mqtt_disconnected     = Signal()
    publish_result        = Signal(bool, str)   # (success, message)
    config_preview_updated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model  = MqttModel(client_id="rader_setup")
        self._config = RaderConfig()
        self._devices: dict[str, DeviceSnapshot] = {}   # mac → snapshot

        # 최신 S1 raw 값 (calibration 용)
        self._latest_s1: dict[str, list[int]] = {}   # mac → [cm, ...]

        self._model.payload_received.connect(self._on_payload)
        self._model.log_signal.connect(self.log_signal)
        self._model.connected.connect(self.mqtt_connected)
        self._model.disconnected.connect(self.mqtt_disconnected)

        # 로컬 config 자동 로드 (있으면)
        if LOCAL_CONFIG_PATH.exists():
            try:
                self._config = RaderConfig.load(LOCAL_CONFIG_PATH)
                self._log(f"로컬 config 로드: {LOCAL_CONFIG_PATH}")
            except Exception as e:
                self._log(f"config 로드 실패: {e}")

    # ── MQTT 제어 ─────────────────────────────────────────────────────────────
    def connect_broker(self, broker: str, port: int):
        self._model.connect_broker(broker, port)

    def disconnect_broker(self):
        self._model.disconnect_broker()

    def cleanup(self):
        self._model.cleanup()

    # ── Payload 수신 ──────────────────────────────────────────────────────────
    @Slot(dict)
    def _on_payload(self, data: dict):
        mac = data.get("mac", "")
        if not mac:
            return

        ts    = datetime.now().strftime("%H:%M:%S")
        dtype = "S1" if "s1" in data else "S2"

        if dtype == "S1":
            s1_raw = data.get("s1", [0])
            snap   = DeviceSnapshot(
                mac=mac, dtype="S1", last_seen=ts,
                s1_values=s1_raw, s2_values=[],
            )
            self._latest_s1[mac] = s1_raw
            # Calibration 미리보기 갱신 (매핑된 S1이 있을 때)
            self._emit_tilt_preview()
        else:
            s2_raw = data.get("s2", [{}])
            zone_d = s2_raw[0].get("d", []) if s2_raw else []
            raw64  = (zone_d + [4000] * 64)[:64]
            min_d  = min(zone_d) if zone_d else 0
            snap   = DeviceSnapshot(
                mac=mac, dtype="S2", last_seen=ts,
                s1_values=[], s2_values=[min_d],
                s2_raw64=raw64,
            )

        self._devices[mac] = snap
        self.device_list_updated.emit(list(self._devices.values()))

    def clear_devices(self):
        """감지된 장치 목록을 초기화한다."""
        self._devices.clear()
        self._latest_s1.clear()
        self.device_list_updated.emit([])

    # ── Calibration 미리보기 ──────────────────────────────────────────────────
    def _emit_tilt_preview(self):
        """현재 config 매핑 기준으로 tilt_deg 계산 후 시그널 발행.
        매핑이 없으면 수신된 S1 MAC 순서로 첫 번째=L, 두 번째=R 폴백 적용."""
        left_cm = right_cm = 0

        # ── 1순위: config 매핑 기반 ──────────────────────────────────────────
        for dev in self._config.devices:
            if dev.type != "S1":
                continue
            s1v = self._latest_s1.get(dev.mac, [])
            if not s1v:
                continue
            dist = s1v[0]
            if dev.s1 == "L":
                left_cm = dist
            elif dev.s1 == "R":
                right_cm = dist

        # ── 2순위: 매핑 미설정 시 수신 순서 폴백 (미리보기용) ───────────────
        if left_cm == 0 and right_cm == 0 and self._latest_s1:
            macs = sorted(self._latest_s1.keys())   # MAC 알파벳 순 정렬
            if len(macs) >= 1:
                left_cm  = self._latest_s1[macs[0]][0]
            if len(macs) >= 2:
                right_cm = self._latest_s1[macs[1]][0]

        gap = self._config.sensor_gap_cm
        if gap > 0:
            diff     = left_cm - right_cm
            tilt_deg = round(math.degrees(math.atan(diff / gap))
                             - self._config.baseline_offset, 2)
        else:
            tilt_deg = 0.0

        self.tilt_preview_updated.emit(tilt_deg, left_cm, right_cm)

    def capture_baseline(self):
        """현재 측정 각도를 baseline 으로 저장"""
        left_cm = right_cm = 0
        for dev in self._config.devices:
            if dev.type != "S1":
                continue
            s1v = self._latest_s1.get(dev.mac, [])
            if not s1v:
                continue
            dist = s1v[0]
            if dev.s1 == "L":
                left_cm = dist
            elif dev.s1 == "R":
                right_cm = dist

        gap = self._config.sensor_gap_cm
        if gap > 0:
            raw_angle = math.degrees(math.atan((left_cm - right_cm) / gap))
        else:
            raw_angle = 0.0
        self._config.baseline_offset = round(raw_angle, 3)
        self._log(f"Baseline 저장: {self._config.baseline_offset}°")
        self._emit_tilt_preview()

    # ── Config 접근/수정 ──────────────────────────────────────────────────────
    def get_config(self) -> RaderConfig:
        return self._config

    def update_device_mapping(self, mac: str, dtype: str,
                               s1_role: str = "",
                               s2_labels: list[str] = None,
                               active_s2: int = 1):
        dev = DeviceConfig(
            mac       = mac,
            type      = dtype,
            s1        = s1_role,           # "L" or "R"
            s2        = s2_labels or [""],
            active_s2 = active_s2,
        )
        self._config.upsert_device(dev)
        self._update_config_preview()

    def update_calib_params(self, sensor_gap_cm: float,
                             tilt_limit_deg: float,
                             threshold_mm: int):
        self._config.sensor_gap_cm  = sensor_gap_cm
        self._config.tilt_limit_deg = tilt_limit_deg
        self._config.threshold_mm   = threshold_mm
        self._update_config_preview()
        self._emit_tilt_preview()

    def _update_config_preview(self):
        self.config_preview_updated.emit(self._config.to_json())

    # ── 로컬 저장 ─────────────────────────────────────────────────────────────
    def save_config_local(self):
        try:
            self._config.save(LOCAL_CONFIG_PATH)
            self._log(f"로컬 저장 완료: {LOCAL_CONFIG_PATH}")
        except Exception as e:
            self._log(f"저장 실패: {e}")

    def save_config_to_path(self, path: str) -> tuple[bool, str]:
        """지정 경로에 저장 (한글 경로 지원). 성공 여부와 메시지를 반환."""
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(self._config.to_json(), encoding="utf-8")
            msg = f"저장 완료: {p}"
            self._log(msg)
            return True, msg
        except Exception as e:
            msg = f"저장 실패: {e}"
            self._log(msg)
            return False, msg

    # ── MQTT Publish Config ───────────────────────────────────────────────────
    def mqtt_publish_config(self):
        """RDR/config 토픽에 retain=True, QoS=1 로 config JSON publish.
        브로커에 연결된 상태에서만 동작."""
        ok = self._model.publish_config(self._config.to_json())
        if ok:
            msg = "config publish 성공 → RPi4 Monitor가 수신하면 자동 저장됩니다"
        else:
            msg = "브로커에 미접속 — 탭①에서 브로커에 먼저 접속하세요"
        self.publish_result.emit(ok, msg)
        self._log(msg)

    # ── 내부 로그 ─────────────────────────────────────────────────────────────
    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_signal.emit(f"[{ts}] {msg}")
