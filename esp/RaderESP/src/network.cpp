#include "network.h"
#include "config.h"
#include <WiFi.h>
#include <WiFiUdp.h>
#include <PubSubClient.h>
#include <esp_wifi.h>
#include <ETH.h>
#include <ESP32Ping.h>

static WiFiClient   s_wifiClient;
static PubSubClient s_mqtt(s_wifiClient);
static WiFiUDP      s_udp;

// ─────────────────────────────────────────────────────
// WiFi 연결
// ─────────────────────────────────────────────────────
bool net_connect(const Env &e) {
    WiFi.disconnect(true);
    WiFi.mode(WIFI_STA);

    // MAC 주소 지정
    if (!e.mac.isEmpty()) {
        uint8_t mac[6];
        int n = sscanf(e.mac.c_str(), "%hhx:%hhx:%hhx:%hhx:%hhx:%hhx",
                       &mac[0], &mac[1], &mac[2], &mac[3], &mac[4], &mac[5]);
        if (n == 6) {
            esp_wifi_set_mac(WIFI_IF_STA, mac);
            Serial.printf("[WiFi] MAC set to %s\n", e.mac.c_str());
        }
    }

    // Static IP 설정
    if (e.ipmode == 0) {
        IPAddress ip, gw, mask;
        ip.fromString(e.ip);
        gw.fromString(e.gw);
        mask.fromString(e.mask);
        WiFi.config(ip, gw, mask);
        Serial.printf("[WiFi] Static IP: %s\n", e.ip.c_str());
    }

    WiFi.begin(e.ssid.c_str(), e.pwd.c_str());
    Serial.printf("[WiFi] Connecting to '%s'", e.ssid.c_str());

    int retry = 0;
    while (WiFi.status() != WL_CONNECTED && retry < 20) {
        delay(500);
        Serial.print(".");
        retry++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[WiFi] Connected. IP: %s\n",
                      WiFi.localIP().toString().c_str());
        return true;
    }

    Serial.println("\n[WiFi] Connection failed.");
    return false;
}

// ─────────────────────────────────────────────────────
// MQTT 연결
// ─────────────────────────────────────────────────────
bool net_mqtt_connect(const Env &e) {
    s_mqtt.setServer(e.brokerip.c_str(), MQTT_PORT);
    s_mqtt.setBufferSize(MQTT_BUFFER_SIZE);

    Serial.printf("[MQTT] Connecting to %s ...", e.brokerip.c_str());
    if (s_mqtt.connect(MQTT_CLIENT_ID)) {
        Serial.println(" connected.");
        return true;
    }
    Serial.printf(" failed (rc=%d)\n", s_mqtt.state());
    return false;
}

void net_mqtt_reconnect(const Env &e) {
    if (s_mqtt.connected()) return;
    Serial.printf("[MQTT] Reconnecting to %s ...", e.brokerip.c_str());
    if (s_mqtt.connect(MQTT_CLIENT_ID)) {
        Serial.println(" connected.");
    } else {
        Serial.printf(" failed (rc=%d)\n", s_mqtt.state());
    }
}

void net_mqtt_loop() {
    s_mqtt.loop();
}

bool net_mqtt_publish(const char *payload) {
    if (!s_mqtt.connected()) return false;
    return s_mqtt.publish(MQTT_TOPIC, payload);
}

bool net_mqtt_connected() {
    return s_mqtt.connected();
}

// ─────────────────────────────────────────────────────
// UDP Multicast: env 내용을 239.255.3.4:8096 으로 송출
// ─────────────────────────────────────────────────────
void net_test_multicast(const Env &e) {
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[NET] Not connected. Run 'test network' after WiFi.");
        return;
    }

    char buf[256];
    snprintf(buf, sizeof(buf),
             "mac=%s;ip=%s;gw=%s;mask=%s;ipmode=%d;ssid=%s;brokerip=%s",
             e.mac.c_str(), e.ip.c_str(), e.gw.c_str(), e.mask.c_str(),
             e.ipmode, e.ssid.c_str(), e.brokerip.c_str());

    // Multicast 송출
    IPAddress mcast;
    mcast.fromString(UDP_MCAST_ADDR);
    s_udp.beginPacket(mcast, UDP_MCAST_PORT);
    s_udp.print(buf);
    s_udp.endPacket();
    Serial.printf("[NET] Multicast → %s:%d\n", UDP_MCAST_ADDR, UDP_MCAST_PORT);

    // Unicast 송출
    IPAddress ucast;
    ucast.fromString(UDP_UCAST_ADDR);
    s_udp.beginPacket(ucast, UDP_UCAST_PORT);
    s_udp.print(buf);
    s_udp.endPacket();
    Serial.printf("[NET] Unicast   → %s:%d\n", UDP_UCAST_ADDR, UDP_UCAST_PORT);

    Serial.printf("[NET] Payload   : %s\n", buf);
}

// ─────────────────────────────────────────────────────
// UDP Unicast 단건 송출
// ─────────────────────────────────────────────────────
void net_udp_send(const char *host, uint16_t port, const char *payload) {
    IPAddress dest;
    dest.fromString(host);
    s_udp.beginPacket(dest, port);
    s_udp.print(payload);
    s_udp.endPacket();
}

// ─────────────────────────────────────────────────────
// MDIO bit-bang: PHY 레지스터 직접 읽기 (ETH.begin() 이전)
// IEEE 802.3 Clause 22, MDC ~500 kHz (마진 2.5 MHz 이내)
// ─────────────────────────────────────────────────────
static uint16_t mdio_read_reg(uint8_t phy_addr, uint8_t reg) {
    const int MDC  = ETH_MDC_PIN;   // GPIO23
    const int MDIO = ETH_MDIO_PIN;  // GPIO18

    pinMode(MDC,  OUTPUT);
    pinMode(MDIO, OUTPUT);
    digitalWrite(MDC, LOW);

    // MDC 1클록 + MDIO 비트 송주
    auto send_bit = [&](int b) {
        digitalWrite(MDIO, b ? HIGH : LOW);
        delayMicroseconds(1);
        digitalWrite(MDC, HIGH);
        delayMicroseconds(1);
        digitalWrite(MDC, LOW);
        delayMicroseconds(1);
    };

    for (int i = 0; i < 32; i++) send_bit(1);  // Preamble: 32 x '1'
    send_bit(0); send_bit(1);                   // ST: 01
    send_bit(1); send_bit(0);                   // OP: 10 (read)
    for (int i = 4; i >= 0; i--) send_bit((phy_addr >> i) & 1); // PHY addr
    for (int i = 4; i >= 0; i--) send_bit((reg      >> i) & 1); // REG addr

    // Turnaround: master releases, PHY drives 0 on 2nd TA clock
    pinMode(MDIO, INPUT_PULLUP);
    delayMicroseconds(1);
    digitalWrite(MDC, HIGH); delayMicroseconds(1);  // TA[1]: Z
    digitalWrite(MDC, LOW);  delayMicroseconds(1);
    digitalWrite(MDC, HIGH); delayMicroseconds(1);  // TA[0]: PHY drives 0
    digitalWrite(MDC, LOW);  delayMicroseconds(1);

    // DATA: PHY drives 16 bits (sample on rising edge)
    uint16_t data = 0;
    for (int i = 15; i >= 0; i--) {
        delayMicroseconds(1);
        digitalWrite(MDC, HIGH);
        delayMicroseconds(1);
        if (digitalRead(MDIO)) data |= (1u << i);
        digitalWrite(MDC, LOW);
        delayMicroseconds(1);
    }

    pinMode(MDIO, INPUT_PULLUP);  // idle
    return data;
}

// ─────────────────────────────────────────────────────
// MDIO bit-bang: PHY 레지스터 직접 쓰기
// ─────────────────────────────────────────────────────
static void mdio_write_reg(uint8_t phy_addr, uint8_t reg, uint16_t val) {
    const int MDC  = ETH_MDC_PIN;
    const int MDIO = ETH_MDIO_PIN;

    pinMode(MDC,  OUTPUT);
    pinMode(MDIO, OUTPUT);
    digitalWrite(MDC, LOW);

    auto send_bit = [&](int b) {
        digitalWrite(MDIO, b ? HIGH : LOW);
        delayMicroseconds(1);
        digitalWrite(MDC, HIGH);
        delayMicroseconds(1);
        digitalWrite(MDC, LOW);
        delayMicroseconds(1);
    };

    for (int i = 0; i < 32; i++) send_bit(1);   // Preamble
    send_bit(0); send_bit(1);                    // ST: 01
    send_bit(0); send_bit(1);                    // OP: 01 (write)
    for (int i = 4; i >= 0; i--) send_bit((phy_addr >> i) & 1);
    for (int i = 4; i >= 0; i--) send_bit((reg      >> i) & 1);
    send_bit(1); send_bit(0);                    // TA: 10
    for (int i = 15; i >= 0; i--) send_bit((val >> i) & 1);

    pinMode(MDIO, INPUT_PULLUP);  // idle
}

// ETH 이중 초기화 방지 (ETH.begin() 은 부팅당 1회만 허용)
static bool s_eth_initialized = false;

// ─────────────────────────────────────────────────────
// LAN8720 테스트: ETH 초기화 → MDIO PHY ID 검증 → 링크 → GW ping
//
// 실행 순서:
//   1) ETH.begin() — GPIO32 로 nRST 제어 + GPIO17 CLK 공급 후 리셋 해제
//   2) MDIO bit-bang — nRST 해제 후 PHY ID 읽기 (CLK 공급 후이므로 정상 응답)
//   3) 링크/IP 대기
//   4) GW ping
//
// ※ MDIO 를 ETH.begin() 이전에 실행하면 nRST 유지 중이라 0xFFFF 만 반환됨
// ─────────────────────────────────────────────────────
bool net_eth_test(const Env &e) {
    Serial.println("[ETH] ── LAN8720 Test ──────────────────────────────────────");

    // WiFi 를 일시 비활성화: ETH 없이 WiFi 를 통해 ping 이 나가는 것을 방지
    bool wifi_was_connected = (WiFi.status() == WL_CONNECTED);
    if (wifi_was_connected) {
        Serial.println("[ETH] WiFi disabled for ETH-only test.");
        WiFi.disconnect(true);
        delay(200);
    }

    // ── 1. ETH.begin: nRST 제어 + CLK 공급 + PHY 초기화 ────
    if (s_eth_initialized) {
        Serial.println("[ETH] Already initialized (ETH.begin skipped — reboot to retry).");
    } else {
        Serial.printf("[ETH] ETH.begin: phy_addr=%d  nRST=GPIO%d  CLK=GPIO17 OUT (50MHz)\n",
                      ETH_PHY_ADDR, ETH_NRST_PIN);
        if (!ETH.begin(ETH_PHY_ADDR, ETH_NRST_PIN, ETH_MDC_PIN, ETH_MDIO_PIN,
                       ETH_PHY_LAN8720, ETH_CLOCK_GPIO17_OUT)) {
            Serial.println("[ETH] ETH.begin() failed.");
            return false;
        }
        s_eth_initialized = true;
        delay(50);

        // ── PHY 소프트웨어 리셋 ─────────────────────────────────
        // 원인: ETH.begin() 내부 EMAC 드라이버가 CLK 테스트를 위해
        //       PHY Loopback(Reg0 bit14)=1 로 설정하고 해제하지 못하는 경우가 있음.
        //       Loopback 상태에서는 케이블 TX 가 비활성화 → DHCP/ping 불가.
        // 해결: PHY 소프트웨어 리셋(bit15=1) → 리셋 후 AN 활성화 재설정.
        //       RMII CLK 은 이미 EMAC 이 공급 중이므로 리셋 후 바로 동작 가능.
        uint16_t r0 = mdio_read_reg(ETH_PHY_ADDR, 0);
        Serial.printf("[ETH] PHY Reg0 after ETH.begin: 0x%04X  Loopback=%d\n",
                      r0, (r0 >> 14) & 1);

        // 소프트 리셋 (bit15): self-clearing, 완료까지 최대 0.5초
        Serial.print("[ETH] PHY soft-reset");
        mdio_write_reg(ETH_PHY_ADDR, 0, 0x8000);
        for (int i = 0; i < 20; i++) {
            delay(50);
            r0 = mdio_read_reg(ETH_PHY_ADDR, 0);
            Serial.print(".");
            if (!(r0 & 0x8000)) break;  // bit15 자동 클리어 대기
        }
        Serial.println();
        Serial.printf("[ETH] PHY Reg0 after reset: 0x%04X  Loopback=%d\n",
                      r0, (r0 >> 14) & 1);

        // AN 활성화 + 100M 광고 + Restart AN
        // bit13=1(100M), bit12=1(AN enable), bit9=1(Restart AN)
        mdio_write_reg(ETH_PHY_ADDR, 0, (1<<13)|(1<<12)|(1<<9));
        delay(20);
        r0 = mdio_read_reg(ETH_PHY_ADDR, 0);
        Serial.printf("[ETH] PHY Reg0 after AN setup: 0x%04X  Loopback=%d  AN=%d\n",
                      r0, (r0 >> 14) & 1, (r0 >> 12) & 1);
    }

    // ── 2. MDIO bit-bang: PHY ID 검증 + 주요 레지스터 덤프 ──
    // ETH.begin() 이 nRST 해제 + CLK 공급을 완료한 후이므로 정상 응답 가능
    Serial.printf("[ETH] MDIO verify: MDC=GPIO%d  MDIO=GPIO%d\n",
                  ETH_MDC_PIN, ETH_MDIO_PIN);
    bool phy_ok = false;
    for (uint8_t addr = 0; addr <= 1; addr++) {
        uint16_t id1 = mdio_read_reg(addr, 2);
        uint16_t id2 = mdio_read_reg(addr, 3);
        Serial.printf("[ETH]   Addr %d: ID1=0x%04X  ID2=0x%04X", addr, id1, id2);
        // LAN8720 / LAN8720A: Microchip OUI, 클론 포함
        if ((id1 == 0x0007 || id1 == 0x000F)
            && (id2 != 0xFFFF) && (id2 != 0x0000)) {
            Serial.printf("  -> LAN8720 family OK");
            phy_ok = true;
        }
        Serial.println();
    }
    if (!phy_ok) {
        Serial.println("[ETH]   WARN: PHY ID unrecognized. Continuing anyway.");
    }
    // 주요 레지스터 덤프 (PHY addr 0 기준)
    // Reg0: Basic Control, Reg1: Basic Status
    // Reg17: Mode Control/Status (LAN8720 specific)
    // Reg18: Special Modes
    uint16_t reg0  = mdio_read_reg(0, 0);   // Basic Control
    uint16_t reg1  = mdio_read_reg(0, 1);   // Basic Status
    uint16_t reg17 = mdio_read_reg(0, 17);  // Mode Control/Status
    uint16_t reg18 = mdio_read_reg(0, 18);  // Special Modes (PHYAD, MODE)
    Serial.printf("[ETH]   Reg0  (BasicCtrl)    = 0x%04X  AN=%d FD=%d SP=%d\n",
                  reg0, (reg0>>12)&1, (reg0>>8)&1, (reg0>>13)&1);
    Serial.printf("[ETH]   Reg1  (BasicStatus)  = 0x%04X  Link=%d AN_done=%d\n",
                  reg1, (reg1>>2)&1, (reg1>>5)&1);
    Serial.printf("[ETH]   Reg17 (ModeCtrl)     = 0x%04X\n", reg17);
    Serial.printf("[ETH]   Reg18 (SpecialModes) = 0x%04X  MODE=%d PHYAD=%d\n",
                  reg18, (reg18>>5)&7, reg18&0x1F);

    // ── 3. 링크 대기 (최대 5초) ─────────────────────────────
    Serial.print("[ETH] Waiting for link");
    unsigned long t = millis();
    while (millis() - t < 5000) {
        if (ETH.linkUp()) break;
        delay(500);
        Serial.print(".");
    }
    Serial.println();

    if (!ETH.linkUp()) {
        Serial.println("[ETH] Link timeout. Check cable / LAN8720 power.");
        return false;
    }
    Serial.printf("[ETH] Link: %uMbps %s  MAC: %s\n",
                  ETH.linkSpeed(),
                  ETH.fullDuplex() ? "Full-Duplex" : "Half-Duplex",
                  ETH.macAddress().c_str());

    // ── 4. IP 할당: DHCP 시도 후 실패 시 Static fallback ────
    // Static fallback: env.ip/gw/mask 를 ETH 에 임시 적용하여
    // RMII 데이터 경로 동작 여부를 DHCP 와 무관하게 확인
    Serial.print("[ETH] Waiting for DHCP");
    t = millis();
    while (millis() - t < 8000) {
        if (ETH.localIP() != IPAddress(0, 0, 0, 0)) break;
        delay(500);
        Serial.print(".");
    }
    Serial.println();

    if (ETH.localIP() == IPAddress(0, 0, 0, 0)) {
        Serial.println("[ETH] DHCP failed. Trying static IP fallback...");
        IPAddress sip, sgw, smask;
        if (!e.ip.isEmpty())   sip.fromString(e.ip.c_str());
        if (!e.gw.isEmpty())   sgw.fromString(e.gw.c_str());
        if (!e.mask.isEmpty()) smask.fromString(e.mask.c_str());

        if (sip != IPAddress(0,0,0,0)) {
            ETH.config(sip, sgw, smask);
            delay(200);
            Serial.printf("[ETH] Static IP applied: %s\n", ETH.localIP().toString().c_str());
        } else {
            Serial.println("[ETH] No static IP configured. Set ip/gw/mask via shell.");
        }
    }
    Serial.printf("[ETH] IP: %s\n", ETH.localIP().toString().c_str());

    // ── 4. GW ping ───────────────────────────────────────────
    IPAddress gw;
    if (!e.gw.isEmpty()) gw.fromString(e.gw.c_str());
    if (!gw || gw == IPAddress(0, 0, 0, 0)) gw = ETH.gatewayIP();

    Serial.printf("[ETH] Ping %s x3 ...\n", gw.toString().c_str());
    int success = 0;
    float totalMs = 0.0f;
    for (int i = 0; i < 3; i++) {
        if (Ping.ping(gw, 1)) {
            success++;
            totalMs += Ping.averageTime();
        }
        delay(200);
    }
    bool ok = (success > 0);
    if (ok) {
        Serial.printf("[ETH] Ping OK  success=%d/3  avg=%.1f ms\n",
                      success, totalMs / success);
    } else {
        Serial.printf("[ETH] Ping FAILED  success=0/3\n");
    }

    // WiFi 복원
    if (wifi_was_connected) {
        Serial.println("[ETH] Restoring WiFi...");
        net_connect(e);
    }
    return ok;
}
