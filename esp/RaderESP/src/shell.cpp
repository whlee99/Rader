#include "shell.h"
#include "config.h"
#include "network.h"
#include <Arduino.h>
#include <Wire.h>

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

static String prompt_input(const char *label) {
    Serial.printf("  %s : ", label);
    return readLine();
}

static void printHelp() {
    Serial.println();
    Serial.println("  printenv          env 전체 출력");
    Serial.println("  set mac           MAC 주소 설정 (재부팅 후 적용)");
    Serial.println("  set ip            Static IP 설정");
    Serial.println("  set gw            게이트웨이 설정");
    Serial.println("  set mask          서브넷 마스크 설정");
    Serial.println("  set ipmode        IP 모드 (0=Static, 1=DHCP)");
    Serial.println("  set ssid          WiFi SSID 설정");
    Serial.println("  set pwd           WiFi 패스워드 설정");
    Serial.println("  set brockerip     MQTT 브로커 IP 설정");
    Serial.println("  test network      UDP Multicast 로 env 송출");
  Serial.println("  test i2c          VL53L5CX I2C 주소(0x29/0x52) 감지, SDA/SCL 교체 포함");
  Serial.println("  test lan8720      LAN8720 PHY ID(MDIO) + 링크 확인 + GW ping");
  Serial.println("  test led          M_LED_1/2 동시 ON/OFF 토글 (3회)");
    Serial.println("  run               Shell 종료 → main 실행");
    Serial.println("  reboot            ESP32 재시작");
    Serial.println("  help              이 도움말");
}

// ─────────────────────────────────────────────────────
// Minishell 진입
// ─────────────────────────────────────────────────────
void shell_run(Env &e) {
    Serial.println("\n================================");
    Serial.println("   RADER Minishell  v1.0");
    Serial.println("================================");
    Serial.printf("Press any key within %d sec...\n", SHELL_TIMEOUT_MS / 1000);

    // 3초 타임아웃 (대기 중 M_LED_1 / M_LED_2 교대 점멸)
    unsigned long deadline    = millis() + SHELL_TIMEOUT_MS;
    unsigned long ledToggleMs = millis();
    bool ledState = false;   // false: LED1=ON, LED2=OFF
    digitalWrite(PIN_M_LED_1, HIGH);
    digitalWrite(PIN_M_LED_2, LOW);

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
            digitalWrite(PIN_M_LED_1, ledState ? LOW  : HIGH);
            digitalWrite(PIN_M_LED_2, ledState ? HIGH : LOW);
        }
    }

    // Shell 종료 시 두 LED 모두 ON
    digitalWrite(PIN_M_LED_1, HIGH);
    digitalWrite(PIN_M_LED_2, HIGH);

    if (!entered) {
        Serial.println("[SHELL] Timeout → starting main.\n");
        return;
    }

    Serial.println("\nEntered shell. Type 'help' for commands.");
    printHelp();

    // Shell 진입 시 WiFi 연결
    Serial.println("[NET] Connecting WiFi...");
    if (net_connect(e)) {
        Serial.println("[NET] WiFi connected.");
    } else {
        Serial.println("[NET] WiFi failed. Check ssid/pwd/ip settings.");
    }

    // ── 헬퍼: 키워드 뒤 인라인 값 추출, 없으면 프롬프트로 입력 받기
    auto getValue = [&](const String &cmd, const char *key, const char *label) -> String {
        String prefix = String(key) + " ";
        if (cmd.startsWith(prefix)) {
            String v = cmd.substring(prefix.length());
            v.trim();
            return v;
        }
        return prompt_input(label);
    };

    // 명령 루프
    while (true) {
        printPrompt();
        String cmd = readLine();
        cmd.trim();
        history_push(cmd);

        if (cmd == "help") {
            printHelp();

        } else if (cmd == "printenv") {
            env_print(e);

        } else if (cmd == "set mac" || cmd.startsWith("set mac ")) {
            String v = getValue(cmd, "set mac", "MAC (XX:XX:XX:XX:XX:XX)");
            if (v.length() > 0) {
                e.mac = v;
                env_save(e);
                Serial.println("  Saved. Reboot required for MAC to take effect.");
            }

        } else if (cmd == "set ip" || cmd.startsWith("set ip ")) {
            String v = getValue(cmd, "set ip", "Static IP");
            if (v.length() > 0) { e.ip = v; env_save(e); Serial.println("  Saved."); }

        } else if (cmd == "set gw" || cmd.startsWith("set gw ")) {
            String v = getValue(cmd, "set gw", "Gateway");
            if (v.length() > 0) { e.gw = v; env_save(e); Serial.println("  Saved."); }

        } else if (cmd == "set mask" || cmd.startsWith("set mask ")) {
            String v = getValue(cmd, "set mask", "Subnet Mask");
            if (v.length() > 0) { e.mask = v; env_save(e); Serial.println("  Saved."); }

        } else if (cmd == "set ipmode" || cmd.startsWith("set ipmode ")) {
            String v = getValue(cmd, "set ipmode", "IP Mode (0=Static, 1=DHCP)");
            if (v.length() > 0) {
                int mode = v.toInt();
                if (mode == 0 || mode == 1) {
                    e.ipmode = mode;
                    env_save(e);
                    Serial.printf("  Saved. Mode: %s\n", mode == 0 ? "Static" : "DHCP");
                } else {
                    Serial.println("  Invalid value. Use 0 or 1.");
                }
            }

        } else if (cmd == "set ssid" || cmd.startsWith("set ssid ")) {
            String v = getValue(cmd, "set ssid", "SSID");
            if (v.length() > 0) { e.ssid = v; env_save(e); Serial.println("  Saved."); }

        } else if (cmd == "set pwd" || cmd.startsWith("set pwd ")) {
            String v = getValue(cmd, "set pwd", "Password");
            if (v.length() > 0) { e.pwd = v; env_save(e); Serial.println("  Saved."); }

        } else if (cmd == "set brockerip" || cmd.startsWith("set brockerip ")) {
            String v = getValue(cmd, "set brockerip", "Broker IP");
            if (v.length() > 0) { e.brokerip = v; env_save(e); Serial.println("  Saved."); }

        } else if (cmd == "test led") {
            Serial.println("[LED] Blinking M_LED_1 (IO14) & M_LED_2 (IO13) x3...");
            for (int i = 0; i < 3; i++) {
                digitalWrite(PIN_M_LED_1, HIGH);
                digitalWrite(PIN_M_LED_2, HIGH);
                Serial.println("  ON");
                delay(500);
                digitalWrite(PIN_M_LED_1, LOW);
                digitalWrite(PIN_M_LED_2, LOW);
                Serial.println("  OFF");
                delay(500);
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
            if (!anyFound) {
                Serial.println("[I2C] Not found at any speed or pin combo.");
                Serial.println("[I2C] Check: VIN=5V, VDD=3.3V, SDA/SCL wiring, LPN=3.3V");
            }

        } else if (cmd == "test network") {
            net_test_multicast(e);

        } else if (cmd == "test lan8720") {
            net_eth_test(e);

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
