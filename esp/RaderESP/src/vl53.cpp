#include "vl53.h"
#include "config.h"
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_VL53L5CX.h>

// ─────────────────────────────────────────────────────
// VL53L5CX 드라이버 (Adafruit 라이브러리)
//
// GPIO16(I2C_RST): Serial2.end() 후 디지털 출력으로 재사용
// GPIO0 (LPN)    : HIGH = 정상동작 (주의: BOOT 버튼과 공유)
// ─────────────────────────────────────────────────────

static Adafruit_VL53L5CX      s_sensor;
static VL53L5CX_ResultsData   s_results;
static VL53Frame  s_latest;
static bool       s_hasFrame = false;
static bool       s_ready    = false;

void vl53_begin() {
    // RST 는 하드웨어에서 3.3V 고정 → CPU 제어 불필요
    // LPN 은 하드웨어에서 3.3V 고정 → CPU 제어 불필요

    // I2C 초기화: 내부 풀업 활성화 + 낮은 클럭으로 안정성 확보
    pinMode(PIN_VL53_SDA, INPUT_PULLUP);
    pinMode(PIN_VL53_SCL, INPUT_PULLUP);
    Wire.begin(PIN_VL53_SDA, PIN_VL53_SCL);
    Wire.setClock(400000);  // 400kHz (Fast mode)

    delay(50);  // Wire 안정화 대기

    // ── I2C 버스 스캔 ──────────────────────────────────
    Serial.printf("[I2C] Scanning bus (SDA=GPIO%d, SCL=GPIO%d, 50kHz)...\n",
                  PIN_VL53_SDA, PIN_VL53_SCL);
    int found = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        uint8_t err = Wire.endTransmission();
        if (err == 0) {
            Serial.printf("[I2C]   Found device at 0x%02X\n", addr);
            found++;
        }
    }
    if (found == 0) {
        Serial.println("[I2C]   No devices found.");
        // SDA/SCL 교체 후 재시도
        Serial.printf("[I2C]   Retrying with SDA=GPIO%d, SCL=GPIO%d (swapped)...\n",
                      PIN_VL53_SCL, PIN_VL53_SDA);
        Wire.end();
        delay(50);
        pinMode(PIN_VL53_SCL, INPUT_PULLUP);
        pinMode(PIN_VL53_SDA, INPUT_PULLUP);
        Wire.begin(PIN_VL53_SCL, PIN_VL53_SDA);  // 교체
        Wire.setClock(50000);
        delay(50);
        for (uint8_t addr = 1; addr < 127; addr++) {
            Wire.beginTransmission(addr);
            uint8_t err = Wire.endTransmission();
            if (err == 0) {
                Serial.printf("[I2C]   Swapped: Found device at 0x%02X  <- SDA/SCL were swapped!\n", addr);
                found++;
            }
        }
        if (found == 0) {
            Serial.println("[I2C]   Still nothing.");
            Serial.println("[I2C]   Checklist:");
            Serial.println("[I2C]     1. Verify VIN=5V with multimeter");
            Serial.println("[I2C]     2. Check SDA(GPIO5)/SCL(GPIO4) physical wiring");
            Serial.println("[I2C]     3. Connect RST(GPIO16) directly to 3.3V and retry");
            Serial.println("[I2C]     4. Possible breakout board defect");
            return;
        }
    }
    Serial.printf("[I2C]   Scan done. %d device(s) found.\n", found);
    // ───────────────────────────────────────────────────

    Serial.println("[VL53] Initializing VL53L5CX...");

    if (!s_sensor.begin(0x29, &Wire)) {
        Serial.println("[VL53] ERROR: Sensor not found! Check SDA/SCL/LPN wiring.");
        return;
    }

    s_sensor.setResolution(VL53L5CX_RESOLUTION_8X8);
    s_sensor.setRangingFrequency(15);  // 8x8 최대 15Hz (~67ms/frame)
    s_sensor.startRanging();
    s_ready = true;
    Serial.printf("[VL53] Ready — 8x8 mode 15Hz, SDA=GPIO%d, SCL=GPIO%d\n",
                  PIN_VL53_SDA, PIN_VL53_SCL);
}

void vl53_update() {
    if (!s_ready) return;

    if (!s_sensor.isDataReady()) return;

    if (!s_sensor.getRangingData(&s_results)) return;

    // 캐시 덮어쓰기 — 최신 64개 거리값 + 유효성 + 타겟수 유지
    for (int i = 0; i < VL53_RESOLUTION; i++) {
        s_latest.dist_mm[i]       = (uint16_t)s_results.distance_mm[i];
        s_latest.target_status[i] = s_results.target_status[i];
        s_latest.nb_target[i]     = s_results.nb_target_detected[i];
    }
    s_hasFrame = true;
}

bool vl53_read(VL53Frame &out) {
    if (!s_hasFrame) return false;
    out = s_latest;
    s_hasFrame = false;
    return true;
}
