#pragma once
#include <stdint.h>

// ─────────────────────────────────────────────────────
// TFMini Plus 드라이버 (UART2, 9-byte frame, 115200 baud)
//
// 프레임 구조:
//   [0x59][0x59][DistL][DistH][StrL][StrH][TempL][TempH][Checksum]
//   Dist     : cm
//   Strength : 신호 강도 (0~65535, 권장 200~65000)
//   Temp     : °C = raw/8 - 256
// ─────────────────────────────────────────────────────

struct TFFrame {
    uint16_t dist;      // 거리 (cm)
    uint16_t strength;  // 신호 강도
    float    temp;      // 내부 온도 (°C)
};

// 부팅 시 자동 감지 (TFMINI_DETECT_MS 동안 UART2 가동)
// - 유효 프레임 수신 시 Serial2 열린 상태로 true 반환
// - 미감지 시 Serial2.end() 후 GPIO16 해제하고 false 반환
bool tfmini_detect();

// loop() 매회 호출 — UART 버퍼 소진 + 최신 프레임 케싱 (Lossy)
void tfmini_update();

// 발행 시점에 케싱된 최신값 반환 — 값이 있으면 true
bool tfmini_read(TFFrame &out);
