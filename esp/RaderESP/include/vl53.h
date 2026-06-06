#pragma once
#include <stdint.h>

// ─────────────────────────────────────────────────────
// VL53L5CX 드라이버 (I2C, 8x8 = 64 zones)
//
// 핀 배정 (config.h):
//   SDA  = GPIO5   SCL  = GPIO4
//   LPN  = GPIO0   (주의: ESP32 dev 보드 BOOT 버튼과 공유)
//   RST  = GPIO16  (TFMini 미사용 시 Serial2.end() 후 재사용)
//   INT  = GPIO34  (현재 미사용 — 폴링 방식)
//
// 데이터 형식:
//   dist_mm[0..63] — 8x8 그리드, 좌상단→우하단 순서, 단위 mm
//   0xFFFF = 유효하지 않은 측정값 (범위 초과 등)
// ─────────────────────────────────────────────────────

#define VL53_RESOLUTION 64  // 8x8

struct VL53Frame {
    uint16_t dist_mm[VL53_RESOLUTION];  // 거리 (mm)
};

// I2C 초기화 + 센서 설정 + 측정 시작
void vl53_begin();

// loop() 매회 호출 — 새 데이터 폴링 + 최신값 캐싱 (Lossy)
void vl53_update();

// 발행 시점에 캐시된 최신값 반환 — 새 데이터 있으면 true
bool vl53_read(VL53Frame &out);
