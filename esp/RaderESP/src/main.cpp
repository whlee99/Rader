 #include <Arduino.h>
#include <WiFi.h>
#include "config.h"
#include "env.h"
#include "shell.h"
#include "network.h"
#include "tfmini.h"
#include "vl53.h"

static Env  g_env;
static bool g_useTFMini    = false;
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
void setup() {
    Serial.begin(115200);
    delay(200);

    pinMode(PIN_STATUS_LED, OUTPUT);
    setStatusLed(false);

    pinMode(PIN_M_LED_1, OUTPUT);
    pinMode(PIN_M_LED_2, OUTPUT);
    digitalWrite(PIN_M_LED_1, LOW);
    digitalWrite(PIN_M_LED_2, LOW);

    // NVS 에서 환경변수 로드
    env_load(g_env);

    // Minishell (3초 타임아웃)
    shell_run(g_env);

    // WiFi 연결
    if (!net_connect(g_env)) {
        Serial.println("[MAIN] WARNING: WiFi connection failed. Continuing...");
    }

    // MQTT 연결
    if (!net_mqtt_connect(g_env)) {
        Serial.println("[MAIN] WARNING: MQTT connection failed. Will retry in loop.");
    }

    setStatusLed(true);
    Serial.println("[MAIN] System ready. Publishing to topic: " MQTT_TOPIC);

    // ── 센서 자동 감지 ──────────────────────────────
    // UART2(GPIO16)에서 TFMini 프레임 수신 시 → TFMini 모드
    // 미수신 시 → Serial2.end() 후 GPIO16을 VL53L5CX I2C_RST 로 전환
    g_useTFMini = tfmini_detect();
    if (g_useTFMini) {
        Serial.println("[MAIN] Sensor mode: TFMini Plus (UART2)");
    } else {
        Serial.println("[MAIN] Sensor mode: VL53L5CX (I2C)");
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
    if (g_useTFMini) {
        tfmini_update();
    } else {
        vl53_update();
    }

    // ── 발행 주기마다 UDP 송출 ─────────────────────
    unsigned long now = millis();
    if (now - lastPublishMs >= PUBLISH_INTERVAL_MS) {
        lastPublishMs = now;

        if (g_useTFMini) {
            TFFrame frame;
            if (tfmini_read(frame)) {
                char payload[64];
                snprintf(payload, sizeof(payload),
                         "{\"dist\":%u,\"str\":%u,\"temp\":%.1f}",
                         frame.dist, frame.strength, frame.temp);
                Serial.printf("[TFMini] dist=%ucm  strength=%u  temp=%.1fC  -> UDP %s:%d\n",
                              frame.dist, frame.strength, frame.temp,
                              UDP_UCAST_ADDR, TFMINI_UDP_PORT);
                net_udp_send(UDP_UCAST_ADDR, TFMINI_UDP_PORT, payload);
            }
        } else {
            VL53Frame frame;
            if (vl53_read(frame)) {
                // {"m":"cx","d":[d0,d1,...,d63]}  — 최대 ~410 bytes
                char payload[512];
                int pos = 0;
                pos += snprintf(payload + pos, sizeof(payload) - pos, "{\"m\":\"cx\",\"d\":[");
                for (int i = 0; i < VL53_RESOLUTION; i++) {
                    pos += snprintf(payload + pos, sizeof(payload) - pos,
                                    "%u%s", frame.dist_mm[i],
                                    i < VL53_RESOLUTION - 1 ? "," : "");
                }
                pos += snprintf(payload + pos, sizeof(payload) - pos, "]}");
                Serial.printf("[VL53] 8x8 frame -> UDP %s:%d\n", UDP_UCAST_ADDR, VL53_UDP_PORT);
                net_udp_send(UDP_UCAST_ADDR, VL53_UDP_PORT, payload);
            }
        }
    }
}