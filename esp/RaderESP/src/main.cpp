 #include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include "config.h"
#include "env.h"
#include "shell.h"
#include "network.h"
#include "tfmini.h"
#include "vl53.h"

static Env  g_env;
static SensorMode g_sensor = SENSOR_NONE;  // 3-state: TFMINI / VL53 / NONE
static bool g_useLAN       = false;        // INTERFACE_SEL: false=WiFi, true=LAN8720
static unsigned long lastPublishMs = 0;

// ─────────────────────────────────────────────────────
static void setStatusLed(bool ok) {
    digitalWrite(PIN_STATUS_LED, ok ? HIGH : LOW);
}

static void errorHalt(const char *msg) {
    Serial.printf("[MAIN] ERROR: %s\n", msg);
    while (true) {
        digitalWrite(PIN_STATUS_LED, HIGH); delay(150);
        digitalWrite(PIN_STATUS_LED, LOW);  delay(150);
    }
}

// ─────────────────────────────────────────────────────
// hw_init: shell 진입 전 모든 IO 초기화
// ─────────────────────────────────────────────────────
static void hw_init() {
    // ── Status LED ───────────────────────────────────
    pinMode(PIN_STATUS_LED, OUTPUT);
    digitalWrite(PIN_STATUS_LED, LOW);

    // ── External LEDs ────────────────────────────────
    pinMode(PIN_M_LED_1, OUTPUT);
    pinMode(PIN_M_LED_2, OUTPUT);
    digitalWrite(PIN_M_LED_1, LOW);
    digitalWrite(PIN_M_LED_2, LOW);

    // ── INTERFACE_SEL (입력전용, 외부 10kΩ Pull-down 필수) ──
    pinMode(PIN_INTERFACE_SEL, INPUT);
    g_useLAN = (digitalRead(PIN_INTERFACE_SEL) == HIGH);
    Serial.printf("[HW] Interface : %s\n", g_useLAN ? "LAN8720" : "WiFi");

    // ── VL53 INT (입력전용, 현재 미사용) ─────────────
    pinMode(PIN_VL53_INT, INPUT);

    // ── I2C 기본 초기화 (50kHz, VL53L5CX 기본값) ─────
    Wire.begin(PIN_VL53_SDA, PIN_VL53_SCL);
    Wire.setClock(50000);
    Serial.printf("[HW] I2C ready : SDA=GPIO%d  SCL=GPIO%d  50kHz\n",
                  PIN_VL53_SDA, PIN_VL53_SCL);
}

// ─────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(200);

    // 모든 IO 초기화 (shell 진입 전)
    hw_init();

    // NVS 에서 환경변수 로드
    env_load(g_env);

    // ── 센서 자동 감지 (shell 진입 전) ─────────────────
    // 1) TFMini: UART2(GPIO16) 에서 500ms 유효 프레임 대기
    // 2) VL53  : I2C 0x29 ACK 확인
    // 3) NONE  : 둘 다 미응답
    if (tfmini_detect()) {
        g_sensor = SENSOR_TFMINI;
        Serial.println("[MAIN] Sensor: TFMini Plus (UART2)");
    } else {
        Wire.beginTransmission(0x29);
        uint8_t i2c_err = Wire.endTransmission();
        if (i2c_err == 0) {
            g_sensor = SENSOR_VL53;
            Serial.println("[MAIN] Sensor: VL53L5CX (I2C 0x29 ACK)");
        } else {
            g_sensor = SENSOR_NONE;
            Serial.printf("[MAIN] Sensor: NONE (TFmini no-frame, I2C err=%d)\n", i2c_err);
        }
    }

    // Minishell (3초 타임아웃) — 감지 결과를 인수로 전달
    shell_run(g_env, g_useLAN, g_sensor);

    // 네트워크 연결 (INTERFACE_SEL 기반)
    if (!g_useLAN) {
        // WiFi 모드
        if (!net_connect(g_env)) {
            Serial.println("[MAIN] WARNING: WiFi connection failed. Continuing...");
        }
        if (!net_mqtt_connect(g_env)) {
            Serial.println("[MAIN] WARNING: MQTT connection failed. Will retry in loop.");
        }
    } else {
        // LAN8720 모드
        Serial.println("[MAIN] LAN8720 mode — ETH main connect: TODO");
        // TODO: net_eth_connect(g_env);
    }

    setStatusLed(true);
    Serial.println("[MAIN] System ready. Publishing to topic: " MQTT_TOPIC);

    // vl53_begin() 은 센서 모드 확정 후
    if (g_sensor == SENSOR_VL53) {
        vl53_begin();
    }
}

void loop() {
    // WiFi 재연결
    if (WiFi.status() != WL_CONNECTED) {
        setStatusLed(false);
        Serial.println("[MAIN] WiFi lost. Reconnecting...");
        net_connect(g_env);
    }

    // MQTT 재연결
    if (!net_mqtt_connected()) {
        setStatusLed(false);
        net_mqtt_reconnect(g_env);
    } else {
        setStatusLed(true);
    }

    net_mqtt_loop();

    // ── 센서 버퍼 폴링 (매 loop) ──────────────────
    if (g_sensor == SENSOR_TFMINI) {
        tfmini_update();
    } else if (g_sensor == SENSOR_VL53) {
        vl53_update();
    }

    // ── 발행 주기마다 UDP 송출 ─────────────────────
    unsigned long now = millis();
    if (now - lastPublishMs >= PUBLISH_INTERVAL_MS) {
        lastPublishMs = now;

        if (g_sensor == SENSOR_TFMINI) {
            TFFrame frame;
            if (tfmini_read(frame)) {
                // RFP 3-2: {"mac":"AA:BB:CC:DD:EE:FF","ts":<ms>,"s1":[<dist_cm>]}
                uint8_t mac[6];
                WiFi.macAddress(mac);
                char macStr[18];
                snprintf(macStr, sizeof(macStr), "%02X:%02X:%02X:%02X:%02X:%02X",
                         mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

                char payload[128];
                snprintf(payload, sizeof(payload),
                         "{\"mac\":\"%s\",\"ts\":%lu,\"s1\":[%u]}",
                         macStr, now, frame.dist);
                Serial.printf("[TFMini] dist=%ucm -> MQTT topic=%s\n",
                              frame.dist, MQTT_TOPIC);
                net_mqtt_publish(payload);
            }
        } else if (g_sensor == SENSOR_VL53) {
            VL53Frame frame;
            if (vl53_read(frame)) {
                // RFP 3-2: {"mac":"..","ts":<ms>,"s2":[{"d":[...],"st":[...],"nb":[...]}]}
                uint8_t mac[6];
                WiFi.macAddress(mac);
                char macStr[18];
                snprintf(macStr, sizeof(macStr), "%02X:%02X:%02X:%02X:%02X:%02X",
                         mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

                // d[], st[], nb[] 배열 직렬화
                // 최대: d[]=383, st[]=255, nb[]=255, 구조=~60 → 약 953 bytes
                char payload[1024];
                int pos = 0;
                pos += snprintf(payload + pos, sizeof(payload) - pos,
                                "{\"mac\":\"%s\",\"ts\":%lu,\"s2\":[{\"d\":[",
                                macStr, now);
                for (int i = 0; i < VL53_RESOLUTION; i++) {
                    pos += snprintf(payload + pos, sizeof(payload) - pos,
                                    "%u%s", frame.dist_mm[i],
                                    i < VL53_RESOLUTION - 1 ? "," : "");
                }
                pos += snprintf(payload + pos, sizeof(payload) - pos, "],\"st\":[");
                for (int i = 0; i < VL53_RESOLUTION; i++) {
                    pos += snprintf(payload + pos, sizeof(payload) - pos,
                                    "%u%s", frame.target_status[i],
                                    i < VL53_RESOLUTION - 1 ? "," : "");
                }
                pos += snprintf(payload + pos, sizeof(payload) - pos, "],\"nb\":[");
                for (int i = 0; i < VL53_RESOLUTION; i++) {
                    pos += snprintf(payload + pos, sizeof(payload) - pos,
                                    "%u%s", frame.nb_target[i],
                                    i < VL53_RESOLUTION - 1 ? "," : "");
                }
                pos += snprintf(payload + pos, sizeof(payload) - pos, "]}]}");
                Serial.printf("[VL53] 8x8 frame -> MQTT topic=%s (%d bytes)\n",
                              MQTT_TOPIC, pos);
                net_mqtt_publish(payload);
            }
        }
    }
}