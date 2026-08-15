"""
src/setup/model/config_model.py
Setup 설정 데이터 모델 — config.json 읽기/쓰기 및 인메모리 상태 관리.

config.json 구조 (RFP 3-3-2 기반):
{
  "devices": [
    {
      "mac"       : "A4:CF:12:00:00:01",
      "type"      : "S1",
      "s1"        : ["L", "R"],      // S1 전용: index 0, 1 위치 레이블
      "s2"        : ["위치A"],       // S2 전용: index 0 위치 레이블
      "active_s2" : 1                // S2 전용: 활성 zone 수 (1~10)
    }, ...
  ],
  "sensor_gap_cm"   : 50.0,
  "baseline_offset" : 0.0,
  "tilt_limit_deg"  : 15.0,
  "threshold_mm"    : 300
}
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── 장치 1대 설정 ─────────────────────────────────────────────────────────────
@dataclass
class DeviceConfig:
    mac:       str
    type:      str        # "S1" | "S2"
    s1:        str        = ""    # S1 전용: "L" 또는 "R" (장치 자체의 역할)
    s2:        list[str]  = field(default_factory=lambda: [""])   # S2 전용
    active_s2: int        = 64                                    # S2 전용 (max: 64 zone)


# ── 전체 Config ───────────────────────────────────────────────────────────────
@dataclass
class RaderConfig:
    devices:          list[DeviceConfig] = field(default_factory=list)
    sensor_gap_cm:    float = 1000.0
    baseline_offset:  float = 0.0
    tilt_limit_deg:   float = 15.0
    threshold_mm:     int   = 1000

    # ── 직렬화 ────────────────────────────────────────────────────────────────
    def to_dict(self) -> dict:
        devs = []
        for d in self.devices:
            entry: dict = {"mac": d.mac, "type": d.type}
            if d.type == "S1":
                entry["s1"] = d.s1     # "L" or "R"
            else:
                entry["s2"]        = d.s2
                entry["active_s2"] = d.active_s2
            devs.append(entry)
        return {
            "devices":         devs,
            "sensor_gap_cm":   self.sensor_gap_cm,
            "baseline_offset": self.baseline_offset,
            "tilt_limit_deg":  self.tilt_limit_deg,
            "threshold_mm":    self.threshold_mm,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    # ── 역직렬화 ──────────────────────────────────────────────────────────────
    @classmethod
    def from_dict(cls, d: dict) -> "RaderConfig":
        devs = []
        for dev in d.get("devices", []):
            dtype = dev.get("type", "S1")
            devs.append(DeviceConfig(
                mac       = dev.get("mac", ""),
                type      = dtype,
                s1        = dev.get("s1", "") if dtype == "S1" else "",
                s2        = dev.get("s2", [""]) if dtype == "S2" else [""],
                active_s2 = dev.get("active_s2", 64),
            ))
        return cls(
            devices         = devs,
            sensor_gap_cm   = float(d.get("sensor_gap_cm",   50.0)),
            baseline_offset = float(d.get("baseline_offset",  0.0)),
            tilt_limit_deg  = float(d.get("tilt_limit_deg",  15.0)),
            threshold_mm    = int(d.get("threshold_mm",       300)),
        )

    @classmethod
    def from_json(cls, text: str) -> "RaderConfig":
        return cls.from_dict(json.loads(text))

    # ── 파일 I/O ──────────────────────────────────────────────────────────────
    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "RaderConfig":
        return cls.from_json(path.read_text(encoding="utf-8"))

    # ── 헬퍼 ──────────────────────────────────────────────────────────────────
    def get_device(self, mac: str) -> Optional[DeviceConfig]:
        for d in self.devices:
            if d.mac == mac:
                return d
        return None

    def upsert_device(self, dev: DeviceConfig):
        """MAC 으로 찾아 갱신, 없으면 추가"""
        for i, d in enumerate(self.devices):
            if d.mac == dev.mac:
                self.devices[i] = dev
                return
        self.devices.append(dev)

    def remove_device(self, mac: str):
        self.devices = [d for d in self.devices if d.mac != mac]
