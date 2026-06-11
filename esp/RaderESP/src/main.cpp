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
                // RFP 3-2: {"mac":"AA:BB:CC:DD:EE:FF","ts":<ms>,"s1":[<dist_cm>]}
                uint8_t mac[6];
                esp_wifi_get_mac(WIFI_IF_STA, mac);
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
        } else {
            VL53Frame frame;
            if (vl53_read(frame)) {
                // RFP 3-2: {"mac":"..","ts":<ms>,"s2":[{"d":[...],"st":[...],"nb":[...]}]}
                uint8_t mac[6];
                esp_wifi_get_mac(WIFI_IF_STA, mac);
                char macStr[18];
                snprintf(macStr, sizeof(macStr), "%02X:%02X:%02X:%02X:%02X:%02X",
                         mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);

                // d[], st[], nb[] 배열 직렬화 (최대 ~480 bytes)
                char payload[640];
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