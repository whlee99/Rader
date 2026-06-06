#include "network.h"
#include "config.h"
#include <WiFi.h>
#include <WiFiUdp.h>
#include <PubSubClient.h>
#include <esp_wifi.h>

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
