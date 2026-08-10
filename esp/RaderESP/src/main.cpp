 #include <Arduino.h>
#include <WiFi.h>
#include <ETH.h>
#include <Wire.h>
#include "config.h"
#include "env.h"
#include "shell.h"
#include "network.h"
#include "tfmini.h"
#include "vl53.h"

static Env  g_env;
static SensorMode g_sensor  = SENSOR_NONE;  // 3-state: TFMINI / VL53 / NONE
static int        g_netMode = NET_WIFI;     // NetworkMode: DIP SW 기반
static ErrorCode  g_error   = ERR_NONE;    // 현재 오류 코드
static unsigned long lastPublishMs = 0;

// 오류 코드 실시간 평가 — loop()와 probe 양쪽에서 사용
static ErrorCode evalError(SensorMode sensor, int netMode) {
    if (netMode < 2) {
        if (WiFi.status() != WL_CONNECTED)           return ERR_WIFI_LOST;
        if (WiFi.localIP() == IPAddress(0, 0, 0, 0)) return ERR_DHCP_FAIL;
        if (!net_mqtt_connected())                   return ERR_MQTT_FAIL;
    } else {
        if (!ETH.linkUp())                           return ERR_ETH_DOWN;
        if (ETH.localIP() == IPAddress(0, 0, 0, 0)) return ERR_DHCP_FAIL;
        if (!net_mqtt_connected())                   return ERR_MQTT_FAIL;
    }
    if (sensor == SENSOR_NONE) return ERR_SENSOR_NONE;
    return ERR_NONE;
}

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
    pinMode(PIN_M_LED_3, OUTPUT);
    digitalWrite(PIN_M_LED_1, HIGH);  // active-LOW: HIGH=OFF
    digitalWrite(PIN_M_LED_2, HIGH);
    digitalWrite(PIN_M_LED_3, HIGH);

    // ── DIP Switch (입력전용) ─────────────────────────
    pinMode(PIN_DIP_SW0, INPUT);
    pinMode(PIN_DIP_SW1, INPUT);
    g_netMode = (digitalRead(PIN_DIP_SW1) << 1) | digitalRead(PIN_DIP_SW0);
    const char* modeNames[] = {"WiFi(00)", "WiFi-Dev(01)", "LAN8720-RSV(10)", "LAN8720(11)"};
    Serial.printf("[HW] Network Mode: %d = %s\n", g_netMode, modeNames[g_netMode]);

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

    // DIP SW 모드에 따라 네트워크 파라미터 덜어쓰기 (NVS 무시)
    g_env.ipmode = 1;  // 전체 DHCP
    switch (g_netMode) {
        case NET_WIFI:
            g_env.ssid = NET00_SSID; g_env.pwd = NET00_PWD; g_env.brokerip = NET00_BROKER;
            break;
        case NET_WIFI_DEV:
            g_env.ssid = NET01_SSID; g_env.pwd = NET01_PWD; g_env.brokerip = NET01_BROKER;
            break;
        default:  // NET_LAN_RSV / NET_LAN
            g_env.brokerip = NET00_BROKER;  // 192.168.0.203
            break;
    }

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

    // 부팅 시 네트워크 초기화 — shell 진입 전
    if (g_netMode < 2) {
        if (!net_connect(g_env)) {
            Serial.println("[MAIN] WARNING: WiFi connection failed.");
        }
    } else {
        if (!net_eth_connect(g_env)) {
            Serial.println("[MAIN] WARNING: LAN8720 init failed.");
        }
    }

    // Minishell (3초 타임아웃) — 감지 결과를 인수로 전달
    shell_run(g_env, g_netMode, g_sensor);

    // MQTT 연결 (전체 모드 공통)
    if (!net_mqtt_connect(g_env)) {
        Serial.println("[MAIN] WARNING: MQTT connection failed. Will retry in loop.");
    }

    setStatusLed(true);
    Serial.println("[MAIN] System ready. Publishing to topic: " MQTT_TOPIC);

    // LED3 초기 상태 설정
    g_error = evalError(g_sensor, g_netMode);
    if (g_error == ERR_NONE) digitalWrite(PIN_M_LED_3, LOW);  // ON

    // vl53_begin() 은 센서 모드 확정 후
    if (g_sensor == SENSOR_VL53) {
        vl53_begin();
    }
}

void loop() {
    // WiFi 재연결 (WiFi 모드에서만)
    if (g_netMode < 2) {
        if (WiFi.status() != WL_CONNECTED) {
            setStatusLed(false);
            Serial.println("[MAIN] WiFi lost. Reconnecting...");
            net_connect(g_env);
        }
    }

    // MQTT 재연결 (전체 모드 공통 — WiFi 모드는 연결된 경우에만)
    bool netReady = (g_netMode < 2) ? (WiFi.status() == WL_CONNECTED) : true;
    if (netReady) {
        if (!net_mqtt_connected()) {
            setStatusLed(false);
            net_mqtt_reconnect(g_env);
        } else {
            setStatusLed(true);
        }
    }

    net_mqtt_loop();

    // ── LED3 오류 표시 (비블로킹, millis 기반) ─────────────
    {
        static unsigned long led3Ms    = 0;
        static bool          led3State = false;

        ErrorCode curErr = evalError(g_sensor, g_netMode);
        g_error = curErr;

        if (curErr == ERR_NONE) {
            digitalWrite(PIN_M_LED_3, LOW);  // active-LOW: ON
        } else {
            unsigned long interval = errBlinkMs(curErr);
            unsigned long now2 = millis();
            if (now2 - led3Ms >= interval) {
                led3Ms   = now2;
                led3State = !led3State;
                digitalWrite(PIN_M_LED_3, led3State ? LOW : HIGH);
            }
        }
    }

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