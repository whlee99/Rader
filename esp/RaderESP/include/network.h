#pragma once
#include "env.h"

// WiFi 연결 (Static/DHCP, MAC 적용)
bool net_connect(const Env &e);

// MQTT 브로커 연결
bool net_mqtt_connect(const Env &e);

// MQTT 재연결 시도 (loop 에서 호출)
void net_mqtt_reconnect(const Env &e);

// MQTT loop (내부 keepalive 처리)
void net_mqtt_loop();

// MQTT 메시지 발행
bool net_mqtt_publish(const char *payload);

// 연결 상태 확인
bool net_mqtt_connected();

// UDP Multicast 로 env 내용 송출 (test network)
void net_test_multicast(const Env &e);

// UDP unicast 단건 송출
void net_udp_send(const char *host, uint16_t port, const char *payload);
