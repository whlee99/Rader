#include "shell.h"
#include "config.h"
#include "network.h"
#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <ETH.h>
#include <ESP32Ping.h>

// ─────────────────────────────────────────────────────
// 히스토리 (최대 10개)
// ─────────────────────────────────────────────────────
#define HISTORY_MAX 10
static String s_history[HISTORY_MAX];
static int    s_histCount = 0;  // 저장된 항목 수
static int    s_histHead  = 0;  // 가장 최근 항목 인덱스 (ring buffer)

static void history_push(const String &cmd) {
    if (cmd.length() == 0) return;
    // 직전과 동일한 명령어는 중복 저장 안 함
    if (s_histCount > 0) {
        int last = (s_histHead + HISTORY_MAX - 1) % HISTORY_MAX;
        if (s_history[last] == cmd) return;
    }
    s_history[s_histHead] = cmd;
    s_histHead = (s_histHead + 1) % HISTORY_MAX;
    if (s_histCount < HISTORY_MAX) s_histCount++;
}

// idx: 0 = 가장 최근, 1 = 두 번째 최근 ...
static String history_get(int idx) {
    if (idx < 0 || idx >= s_histCount) return "";
    int pos = (s_histHead - 1 - idx + HISTORY_MAX * 2) % HISTORY_MAX;
    return s_history[pos];
}

// ─────────────────────────────────────────────────────
// 내부 헬퍼
// ─────────────────────────────────────────────────────
static void printPrompt() {
    Serial.print("RADER> ");
}

// 현재 라인을 지우고 새 내용으로 교체 (VT100)
static void replaceCurrentLine(const String &newLine, String &line) {
    // 기존 문자 수만큼 \b \b 로 지우기
    for (int i = 0; i < (int)line.length(); i++) Serial.print("\b \b");
    line = newLine;
    Serial.print(line);
}

static String readLine() {
    String line = "";
    int histIdx = -1;  // -1: 현재 입력 중, 0~: 히스토리 탐색 중
    String savedLine = "";  // ↑ 누르기 전 입력 중이던 내용 보존
    unsigned long startMs = millis();  // 잔류 개행 필터용

    while (true) {
        if (!Serial.available()) continue;

        char c = (char)Serial.read();

        // ESC 시퀀스 감지 (VT100: ESC [ A = ↑, ESC [ B = ↓)
        if (c == 0x1B) {
            delay(10);
            if (!Serial.available()) continue;
            if ((char)Serial.read() != '[') continue;
            if (!Serial.available()) { delay(10); }
            char arrow = (char)Serial.read();

            if (arrow == 'A') {  // ↑ (이전 명령)
                int next = histIdx + 1;
                if (next < s_histCount) {
                    if (histIdx == -1) savedLine = line;  // 현재 입력 보존
                    histIdx = next;
                    replaceCurrentLine(history_get(histIdx), line);
                }
            } else if (arrow == 'B') {  // ↓ (다음 명령)
                if (histIdx > 0) {
                    histIdx--;
                    replaceCurrentLine(history_get(histIdx), line);
                } else if (histIdx == 0) {
                    histIdx = -1;
                    replaceCurrentLine(savedLine, line);
                }
            }
            continue;
        }

        if (c == '\r' || c == '\n') {
            // 이전 명령의 \r\n 잔류 개행은 50ms 이내 빈 줄로 들어옴 → 무시
            if (line.length() == 0 && (millis() - startMs < 50)) continue;
            Serial.print("\r\n");
            break;
        } else if (c == '\b' || c == 127) {   // 백스페이스
            if (line.length() > 0) {
                line.remove(line.length() - 1);
                Serial.print("\b \b");
            }
        } else {
            line += c;
            Serial.print(c);
        }
    }
    return line;
}

static void printHelp() {
    Serial.println();
    Serial.println("  printenv          print all env variables");
    Serial.println("  test network      send env via UDP multicast/unicast");
    Serial.println("  test i2c          scan VL53L5CX I2C addr (0x29/0x52), incl. SDA/SCL swap");
    Serial.println("  test lan8720      LAN8720 PHY ID (MDIO) + link check + GW ping");
    Serial.println("  test led          toggle M_LED_1/2/3 x3, then 1->2->3 sequential");
    Serial.println("  test dipsw        show current DIP SW value (0~3, SW0=LSB)");
    Serial.println("  probe             show current IO / mode status");
    Serial.println("  run               exit shell -> start main");
    Serial.println("  reboot            restart ESP32");
    Serial.println("  help              show this help");
}

// ─────────────────────────────────────────────────────
// Minishell 진입
// ─────────────────────────────────────────────────────
void shell_run(Env &e, int netMode, SensorMode sensorMode) {
    Serial.println("\n================================");
    Serial.println("   RADER Minishell  v1.0");
    Serial.println("================================");
    Serial.printf("Press any key within %d sec...\n", SHELL_TIMEOUT_MS / 1000);

    // 3초 타임아웃 (대기 중 M_LED_1 / M_LED_2 / M_LED_3 교대 점멸, active-LOW)
    unsigned long deadline    = millis() + SHELL_TIMEOUT_MS;
    unsigned long ledToggleMs = millis();
    bool ledState = false;   // false: LED1=ON, LED2/3=OFF
    digitalWrite(PIN_M_LED_1, LOW);   // LED1 ON
    digitalWrite(PIN_M_LED_2, HIGH);  // LED2 OFF
    digitalWrite(PIN_M_LED_3, HIGH);  // LED3 OFF

    bool entered = false;
    while (millis() < deadline) {
        if (Serial.available()) {
            Serial.read();   // 키 소비
            entered = true;
            break;
        }
        if (millis() - ledToggleMs >= 250) {
            ledToggleMs = millis();
            ledState = !ledState;
            // active-LOW: LOW=ON, HIGH=OFF
            // LED1 vs LED2+LED3 교대
            digitalWrite(PIN_M_LED_1, ledState ? HIGH : LOW);
            digitalWrite(PIN_M_LED_2, ledState ? LOW  : HIGH);
            digitalWrite(PIN_M_LED_3, ledState ? LOW  : HIGH);
        }
    }

    // Shell 종료 시 LED1/2 ON, LED3는 ErrorCode 제어로 넘김 (OFF 상태 유지)
    digitalWrite(PIN_M_LED_1, LOW);
    digitalWrite(PIN_M_LED_2, LOW);
    // LED3: setup()의 evalError() 및 loop()에서 제어

    if (!entered) {
        Serial.println("[SHELL] Timeout → starting main.\n");
        return;
    }

    Serial.println("\nEntered shell. Type 'help' for commands.");
    printHelp();

    // 네트워크는 shell 진입 전 setup() 에서 이미 초기화됨 — 상태만 표시
    if (netMode < 2) {
        Serial.printf("[NET] WiFi mode %d — SSID: %s  Broker: %s  Status: %s\n",
                      netMode, e.ssid.c_str(), e.brokerip.c_str(),
                      (WiFi.status() == WL_CONNECTED) ? "Connected" : "Not connected");
    } else {
        Serial.printf("[NET] LAN8720 mode — IP: %s\n",
                      ETH.localIP().toString().c_str());
    }

    // ── 명령 루프
    while (true) {
        printPrompt();
        String cmd = readLine();
        cmd.trim();
        history_push(cmd);

        if (cmd == "help") {
            printHelp();

        } else if (cmd == "printenv") {
            env_print(e);
            int sw0 = digitalRead(PIN_DIP_SW0);
            int sw1 = digitalRead(PIN_DIP_SW1);
            const char* modeNames[] = {
                "WiFi        (SSID=TRDR,  Broker=192.168.0.203)",
                "WiFi-Dev    (SSID=spdio, Broker=192.168.0.20)",
                "LAN8720 RSV (10 -> same as 11)",
                "LAN8720 UTP"
            };
            Serial.println("─────────────────────────────────");
            Serial.printf("  dipsw    : SW1(VN)=%d  SW0(VP)=%d  ->  Mode %d%d: %s\n",
                          sw1, sw0, sw1, sw0, modeNames[netMode]);
            Serial.println("─────────────────────────────────");

        } else if (cmd == "probe") {
            // ── Section 1: IO 핀 현재 상태 ──────────────────────────
            int sw0  = digitalRead(PIN_DIP_SW0);
            int sw1  = digitalRead(PIN_DIP_SW1);
            int led1 = digitalRead(PIN_M_LED_1);   // active-LOW: LOW=ON
            int led2 = digitalRead(PIN_M_LED_2);
            int led3 = digitalRead(PIN_M_LED_3);
            int stat = digitalRead(PIN_STATUS_LED);
            int vint = digitalRead(PIN_VL53_INT);
            int vrst = digitalRead(PIN_VL53_RST);
            #define LEDSTR(v) ((v)==LOW ? "ON " : "OFF")
            Serial.println("[PROBE] ── IO Pin Status ──────────────────────────────────");
            Serial.printf("[PROBE] DIP SW   : SW1(VN/IO39)=%d  SW0(VP/IO36)=%d\n", sw1, sw0);
            Serial.printf("[PROBE] LED      : LED1(IO13)=%s  LED2(IO33)=%s  LED3(IO14)=%s\n",
                          LEDSTR(led1), LEDSTR(led2), LEDSTR(led3));
            Serial.printf("[PROBE] StatusLED: IO2=%s\n", stat ? "ON" : "OFF");
            Serial.printf("[PROBE] VL53 INT : IO34=%d\n", vint);
            Serial.printf("[PROBE] VL53 RST : IO16=%d  (shared with TFMini RX)\n", vrst);
            Serial.printf("[PROBE] I2C      : SDA=IO%d  SCL=IO%d  50kHz\n",
                          PIN_VL53_SDA, PIN_VL53_SCL);

            // ── Section 2: Mode config info
            const char* modeStr;
            const char* brokerStr;
            switch (netMode) {
                case NET_WIFI:     modeStr = "WiFi        (SSID=TRDR)";  brokerStr = NET00_BROKER; break;
                case NET_WIFI_DEV: modeStr = "WiFi-Dev    (SSID=spdio)"; brokerStr = NET01_BROKER; break;
                case NET_LAN_RSV:  modeStr = "LAN8720 RSV (10)";          brokerStr = NET00_BROKER; break;
                case NET_LAN:      modeStr = "LAN8720     (11)";          brokerStr = NET00_BROKER; break;
                default:           modeStr = "UNKNOWN"; brokerStr = "-"; break;
            }
            Serial.println("[PROBE] ── Mode Config Info ─────────────────────────────");
            Serial.printf("[PROBE] Net Mode : %d%d = %s\n", sw1, sw0, modeStr);

            if (netMode < 2) {
                // WiFi mode
                bool wifiOk = (WiFi.status() == WL_CONNECTED);
                Serial.printf("[PROBE] WiFi     : %s",  wifiOk ? "CONNECTED" : "DISCONNECTED");
                if (wifiOk) {
                    Serial.printf("  |  SSID=%s  |  IP=%s  |  RSSI=%ddBm",
                                  WiFi.SSID().c_str(),
                                  WiFi.localIP().toString().c_str(),
                                  WiFi.RSSI());
                }
                Serial.println();
            } else {
                // LAN mode
                bool ethOk = ETH.linkUp();
                Serial.printf("[PROBE] ETH      : %s", ethOk ? "LINK UP" : "LINK DOWN");
                if (ethOk) {
                    Serial.printf("  |  IP=%s", ETH.localIP().toString().c_str());
                }
                Serial.println();
            }
            Serial.printf("[PROBE] MQTT     : (shell phase - not started yet)  Broker=%s:%d\n",
                          brokerStr, MQTT_PORT);

            // Shell phase check: DHCP assigned + broker ping
            IPAddress localIp = (netMode < 2) ? WiFi.localIP() : ETH.localIP();
            bool dhcpOk = (localIp != IPAddress(0, 0, 0, 0));
            Serial.printf("[PROBE] DHCP     : %s  |  IP=%s\n",
                          dhcpOk ? "OK" : "FAIL (no IP)",
                          localIp.toString().c_str());

            if (dhcpOk) {
                IPAddress broker;
                broker.fromString(brokerStr);
                Serial.printf("[PROBE] Broker   : ping %s ... ", brokerStr);
                bool pingOk = Ping.ping(broker, 1);
                if (pingOk)
                    Serial.printf("OK  (%.1f ms)\n", Ping.averageTime());
                else
                    Serial.println("FAIL (unreachable)");
            } else {
                Serial.printf("[PROBE] Broker   : skip (DHCP failed)\n");
            }
            // TFmini: boot-time detection result (UART2 frame probe is boot-time only)
            bool tfDetected = (sensorMode == SENSOR_TFMINI);

            // VL53L5CX: live I2C probe at 0x29
            Wire.beginTransmission(0x29);
            bool vl53Detected = (Wire.endTransmission() == 0);

            Serial.printf("[PROBE] TFmini   : %s\n",
                          tfDetected   ? "DETECTED    (UART2 IO16)         <- active"
                                       : "not detected (boot-time UART2 probe)");
            Serial.printf("[PROBE] VL53L5CX : %s\n",
                          vl53Detected ? (tfDetected
                                       ? "DETECTED    (I2C 0x29)            <- standby (TFmini priority)"
                                       : "DETECTED    (I2C 0x29)            <- active")
                                       : "not detected (I2C 0x29 NACK)");
            Serial.println("[PROBE] ────────────────────────────────────────────────────");


        } else if (cmd == "test led") {
            // ── Phase 1: 3개 동시 ON/OFF 토글 3회 (active-LOW) ──────
            Serial.println("[LED] Phase1: M_LED_1/2/3 simultaneous toggle x3...");
            for (int i = 0; i < 3; i++) {
                digitalWrite(PIN_M_LED_1, LOW);
                digitalWrite(PIN_M_LED_2, LOW);
                digitalWrite(PIN_M_LED_3, LOW);
                Serial.printf("  [%d] ON\n", i + 1);
                delay(500);
                digitalWrite(PIN_M_LED_1, HIGH);
                digitalWrite(PIN_M_LED_2, HIGH);
                digitalWrite(PIN_M_LED_3, HIGH);
                Serial.printf("  [%d] OFF\n", i + 1);
                delay(500);
            }
            // ── Phase 2: 1→2→3 순서로 1초 간격 ON/OFF ─────────────
            Serial.println("[LED] Phase2: 1->2->3 sequential...");
            const int seqPins[] = {PIN_M_LED_1, PIN_M_LED_2, PIN_M_LED_3};
            for (int i = 0; i < 3; i++) {
                Serial.printf("  LED%d ON\n", i + 1);
                digitalWrite(seqPins[i], LOW);
                delay(1000);
                digitalWrite(seqPins[i], HIGH);
                Serial.printf("  LED%d OFF\n", i + 1);
            }
            Serial.println("[LED] Done.");

        } else if (cmd == "test i2c") {
            const uint8_t targets[]  = {0x29, 0x52};
            const int     nTargets   = 2;
            const int     sdaPins[]  = {PIN_VL53_SDA, PIN_VL53_SCL};
            const int     sclPins[]  = {PIN_VL53_SCL, PIN_VL53_SDA};
            const char   *labels[]   = {"normal", "swapped"};
            const uint32_t clocks[]  = {100000, 50000, 10000};
            const int      nClocks   = 3;

            bool anyFound = false;
            for (int combo = 0; combo < 2 && !anyFound; combo++) {
                for (int ci = 0; ci < nClocks && !anyFound; ci++) {
                    Wire.end();
                    delay(20);
                    pinMode(sdaPins[combo], INPUT_PULLUP);
                    pinMode(sclPins[combo], INPUT_PULLUP);
                    Wire.begin(sdaPins[combo], sclPins[combo]);
                    Wire.setClock(clocks[ci]);
                    delay(50);

                    Serial.printf("[I2C] %s %lukHz: SDA=GPIO%d SCL=GPIO%d\n",
                                  labels[combo], clocks[ci]/1000,
                                  sdaPins[combo], sclPins[combo]);

                    for (int i = 0; i < nTargets; i++) {
                        Wire.beginTransmission(targets[i]);
                        uint8_t err = Wire.endTransmission();
                        if (err == 0) {
                            Serial.printf("[I2C]   \u2192 Found 0x%02X!  \u2190 VL53L5CX detected!\n", targets[i]);
                            anyFound = true;
                        } else {
                            Serial.printf("[I2C]   \u2192 0x%02X err=%d\n", targets[i], err);
                        }
                    }
                }
            }
            Wire.end();
            // I2C 기본값 복구 (hw_init 상태로 복원)
            Wire.begin(PIN_VL53_SDA, PIN_VL53_SCL);
            Wire.setClock(50000);
            if (!anyFound) {
                Serial.println("[I2C] Not found at any speed or pin combo.");
                Serial.println("[I2C] Check: VIN=5V, VDD=3.3V, SDA/SCL wiring, LPN=3.3V");
            }

        } else if (cmd == "test network") {
            net_test_multicast(e);

        } else if (cmd == "test lan8720") {
            net_eth_test(e);

        } else if (cmd == "test dipsw") {
            int sw0 = digitalRead(PIN_DIP_SW0);
            int sw1 = digitalRead(PIN_DIP_SW1);
            int val = (sw1 << 1) | sw0;
            Serial.printf("[DIPSW] SW1(VN)=%d  SW0(VP)=%d  ->  Value=%d\n",
                          sw1, sw0, val);

        } else if (cmd == "run") {
            Serial.println("[SHELL] Exiting → starting main.\n");
            break;

        } else if (cmd == "reboot") {
            Serial.println("[SHELL] Rebooting...");
            delay(300);
            ESP.restart();

        } else if (cmd.length() > 0) {
            Serial.printf("  Unknown command: '%s'  (type 'help')\n", cmd.c_str());
        }
    }
}
