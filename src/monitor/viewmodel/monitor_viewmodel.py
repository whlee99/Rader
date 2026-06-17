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

from PySide6.QtCore import QObject, Signal, Slot, QTimer

from ..model.mqtt_model import MqttModel


# ── 상태 정보 데이터클래스 ────────────────────────────────────────────────────
@dataclass
class StatusInfo:
    level:   str   # "OK" | "FAIL"
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

    # config 파일: 프로젝트 루트 / config / rader_config.json
    CONFIG_PATH = (Path(__file__).resolve().parent.parent.parent.parent
                   / "config" / "rader_config.json")

    def __init__(self, model: MqttModel, parent=None):
        super().__init__(parent)
        self._model = model

        # 로드된 config dict (전체) — 프로그램 시작 시 읽고, MQTT 수신 시 갱신
        self._config: dict = {
            "sensor_gap_cm":   50.0,
            "baseline_offset": 0.0,
            "tilt_limit_deg":  15.0,
            "threshold_mm":    300,
            "devices":         [],
        }

        # config에서 파생된 빠른 조회용 캐시
        self._mac_to_role: dict[str, str] = {}      # mac → "L" | "R"
        self._mac_to_s2_slot: dict[str, int] = {}   # mac → slot index

        # L/R 최신값 저장 버퍼
        self._s1_buf: dict[str, int] = {}   # {"L": cm, "R": cm}
        # S2 슬롯별 현재 최솟값 (mm)
        self._s2_min_dist: dict[int, int] = {}

        # ── 최신값 버퍼 (lossy coalescing) ────────────────────────────────────
        # MQTT 네트워크 스레드가 빠르게 쌓아도 GUI는 항상 최신값만 처리
        # 동일 MAC의 중간 패킷은 덮어써서 버림
        self._pending: dict[str, dict] = {}   # mac → 최신 payload
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(50)     # 50ms마다 드레인 (최대 20fps)
        self._drain_timer.timeout.connect(self._drain_pending)
        self._drain_timer.start()

        # Model 시그널 연결
        self._model.payload_received.connect(self._on_payload)
        self._model.config_received.connect(self._on_config_received)
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

        # config dict 전체를 저장 (runtime 에서 직접 참조)
        self._config = cfg

        # 빠른 조회용 캐시 재구성
        self._mac_to_role.clear()
        self._mac_to_s2_slot.clear()
        s2_auto = 0   # label 파싱 실패 시 폴백용 카운터
        for dev in cfg.get("devices", []):
            if dev.get("type") == "S1":
                role = dev.get("s1", "")
                if role in ("L", "R"):
                    self._mac_to_role[dev["mac"]] = role
            elif dev.get("type") == "S2":
                # "pos1"~"pos10" → 0-based slot (pos1=0, pos2=1, ...)
                label = (dev.get("s2") or [""])[0]
                try:
                    slot = int(label.replace("pos", "")) - 1
                    if slot < 0:
                        raise ValueError
                except (ValueError, AttributeError):
                    slot = s2_auto   # 파싱 불가 시 등장 순서 사용
                self._mac_to_s2_slot[dev["mac"]] = slot
                s2_auto += 1

        self._s1_buf.clear()       # 이전 버퍼 초기화
        self._s2_min_dist.clear()   # S2 누적 상태 초기화
        s1_mapped = ", ".join(f"{m}→{r}" for m, r in self._mac_to_role.items()) or "(매핑 없음)"
        s2_mapped = ", ".join(f"{m}→슬롯{i}" for m, i in self._mac_to_s2_slot.items()) or "(매핑 없음)"
        msg = (f"config 로드 성공: {p}\n"
               f"  S1 매핑: {s1_mapped}\n"
               f"  S2 매핑: {s2_mapped}\n"
               f"  gap={self._config.get('sensor_gap_cm', 50.0)}cm  "
               f"baseline={self._config.get('baseline_offset', 0.0)}°  "
               f"tilt_limit={self._config.get('tilt_limit_deg', 15.0)}°  "
               f"threshold={self._config.get('threshold_mm', 300)}mm")
        self.config_loaded.emit(True, msg)
        return True, msg

    # ── MQTT 수신 config (RDR/config retained) ──────────────────────────
    @Slot(str)
    def _on_config_received(self, json_text: str):
        """Setup PC로부터 RDR/config 토픽으로 수신한 config JSON을
        로컬 파일로 저장하고 즉시 적용.
        기존 파일과 내용이 동일하면 저장/로드를 건너뜀 (재접속 반복 방지)."""
        # 기존 파일과 동일한 내용이면 무시
        if self.CONFIG_PATH.exists():
            try:
                existing = self.CONFIG_PATH.read_text(encoding="utf-8")
                if existing.strip() == json_text.strip():
                    return   # 변경 없음 — 조용히 무시
            except Exception:
                pass

        try:
            self.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            self.CONFIG_PATH.write_text(json_text, encoding="utf-8")
            self.log_signal.emit("[config] MQTT로 config 수신 → 로컬 저장 완료")
        except Exception as e:
            self.log_signal.emit(f"[config] 로컬 저장 실패: {e}")
            return
        self.load_config()

    # ── Payload 수신: 버퍼에 최신값 덮어쓰기 (coalescing) ───────────────────
    @Slot(dict)
    def _on_payload(self, data: dict):
        mac = data.get("mac", "?")
        self._pending[mac] = data   # 동일 MAC의 이전 미처리 패킷은 폐기

    # ── 50ms 타이머: 버퍼 드레인 → MAC당 최신 1개만 처리 ────────────────────
    @Slot()
    def _drain_pending(self):
        if not self._pending:
            return
        # 현재 버퍼 스냅샷을 가져오고 버퍼 초기화 (이후 도착분은 다음 주기)
        snapshot, self._pending = self._pending, {}
        for data in snapshot.values():
            self._process(data)

    def _process(self, data: dict):
        s1  = data.get("s1", [])
        s2  = data.get("s2", [])
        mac = data.get("mac", "?")

        # ── S1: MAC 매핑 L/R 버퍼 갱신 → 기울기 계산 ─────────────────────
        if s1:
            role = self._mac_to_role.get(mac, "")
            if role in ("L", "R"):
                self._s1_buf[role] = s1[0]

        left_cm  = self._s1_buf.get("L", 0)
        right_cm = self._s1_buf.get("R", 0)

        gap_cm       = float(self._config.get("sensor_gap_cm",   50.0))
        baseline     = float(self._config.get("baseline_offset",  0.0))
        tilt_limit   = float(self._config.get("tilt_limit_deg",  15.0))
        threshold_mm =   int(self._config.get("threshold_mm",     300))

        if gap_cm > 0 and (left_cm or right_cm):
            diff_cm  = right_cm - left_cm
            tilt_deg = math.degrees(math.atan(diff_cm / gap_cm)) - baseline
        else:
            tilt_deg = 0.0

        self.tilt_updated.emit(round(tilt_deg, 2))
        self.s1_labels_updated.emit(
            f"S1-L: {left_cm} cm  ({left_cm * 10} mm)",
            f"S1-R: {right_cm} cm  ({right_cm * 10} mm)",
        )

        # ── S2: MAC → 슬롯 매핑으로 업데이트 ──────────────────────────────
        if s2:
            slot = self._mac_to_s2_slot.get(mac)
            if slot is not None:   # config 매핑된 슬롯만 처리
                d64 = s2[0].get("d", [4000] * 64)
                self.s2_updated.emit(slot, d64)
                self._s2_min_dist[slot] = min(d64)

        # ── 전체 상태: 모든 S2 슬롯 + 기울기 종합 판단 ────────────────────────
        overall_min = min(self._s2_min_dist.values()) if self._s2_min_dist else 9999

        has_obstacle = overall_min < threshold_mm
        has_tilt     = abs(tilt_deg) > tilt_limit

        if has_obstacle or has_tilt:
            reasons = []
            if has_obstacle:
                reasons.append(f"OBSTACLE {overall_min}mm")
            if has_tilt:
                reasons.append(f"TILT {tilt_deg:.1f}°")
            status = StatusInfo("FAIL", "FAIL: " + " | ".join(reasons), tilt_deg, overall_min)
        else:
            status = StatusInfo("OK", "SYSTEM OK", tilt_deg, overall_min)

        self.status_updated.emit(status)

        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_signal.emit(
            f"[{ts}]  MAC={mac}  tilt={tilt_deg:.1f}°  "
            f"min_d={overall_min}mm  S2×{len(s2)}"
        )

    @staticmethod
    def _d64_to_cols(d64: list) -> list:
        """64값(8×8) → 8열 최솟값 (열별 8개 row 중 min)"""
        result = []
        for col in range(8):
            col_vals = [d64[row * 8 + col] for row in range(8) if row * 8 + col < len(d64)]
            result.append(min(col_vals) if col_vals else 4000)
        return result
