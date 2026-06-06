#include "tfmini.h"
#include "config.h"
#include <Arduino.h>

// ─────────────────────────────────────────────────────
// UART2 로 TFMini Plus 수신 (논블로킹 상태 머신)
//
// Lossy cache 패턴:
//   tfmini_update() 을 loop() 매회 호출 → UART 버퍼를 지속 소진하면서
//   유효한 프레임을 s_latest 에 덮어쓰기(최신값 유지)
//   tfmini_read() 는 발행 시점에만 최신값 코피해감
// ─────────────────────────────────────────────────────

#define FRAME_LEN 9

static uint8_t s_buf[FRAME_LEN];
static uint8_t s_idx    = 0;
static TFFrame s_latest = {0, 0, 0.0f};
static bool    s_hasFrame = false;

// 내부 펄스 파서 (공통 로직)
static void parse_byte(uint8_t b) {
    if (s_idx == 0 && b != 0x59) return;
    if (s_idx == 1 && b != 0x59) { s_idx = 0; return; }

    s_buf[s_idx++] = b;

    if (s_idx == FRAME_LEN) {
        s_idx = 0;
        uint8_t chk = 0;
        for (int i = 0; i < FRAME_LEN - 1; i++) chk += s_buf[i];
        if (chk != s_buf[FRAME_LEN - 1]) return;  // 캐시 유지, 불량 프레임 무시

        s_latest.dist     = (uint16_t)(s_buf[2] | (s_buf[3] << 8));
        s_latest.strength = (uint16_t)(s_buf[4] | (s_buf[5] << 8));
        s_latest.temp     = (float)((uint16_t)(s_buf[6] | (s_buf[7] << 8))) / 8.0f - 256.0f;
        s_hasFrame = true;
    }
}

// 부팅 시 자동 감지: UART2 열고 TFMINI_DETECT_MS 동안 유효 프레임 수신 시도
// 유효 프레임 받으면: Serial2 열린 상태로 true 반환
// 미감지:  Serial2.end() 후 GPIO16 해제하고 false 반환
bool tfmini_detect() {
    Serial2.begin(TFMINI_BAUD, SERIAL_8N1, TFMINI_RX_PIN, TFMINI_TX_PIN);
    Serial.printf("[TFMini] Auto-detect: UART2 RX=GPIO%d, %d baud, %dms...\n",
                  TFMINI_RX_PIN, TFMINI_BAUD, TFMINI_DETECT_MS);

    s_idx = 0;
    s_hasFrame = false;
    unsigned long deadline = millis() + TFMINI_DETECT_MS;

    while (millis() < deadline) {
        while (Serial2.available()) {
            parse_byte((uint8_t)Serial2.read());
        }
        if (s_hasFrame) {
            Serial.printf("[TFMini] Detected! dist=%ucm, strength=%u\n",
                          s_latest.dist, s_latest.strength);
            return true;
        }
    }

    Serial.println("[TFMini] Not detected → releasing UART2 (GPIO16 free for VL53).");
    Serial2.end();
    // Serial2.end() 후 GPIO16 을 즉시 HIGH 출력으로 고정
    // → VL53L5CX RST(XSHUT) 가 floating 으로 shutdown 상태에 빠지지 않도록 방지
    pinMode(TFMINI_RX_PIN, OUTPUT);
    digitalWrite(TFMINI_RX_PIN, HIGH);
    return false;
}

// loop() 매회 호출 — UART 버퍼를 최대한 비우며 언제나 최신 프레임을 캐싱
void tfmini_update() {
    while (Serial2.available()) {
        parse_byte((uint8_t)Serial2.read());
    }
}

// 발행 시점에 캐시된 최신 프레임을 반환 (Lossy: 받은 후 플래그 리셋)
bool tfmini_read(TFFrame &out) {
    if (!s_hasFrame) return false;
    out = s_latest;
    s_hasFrame = false;
    return true;
}
