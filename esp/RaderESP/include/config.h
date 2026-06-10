#pragma once

// ── 기본값 (NVS 가 비어있을 때 사용) ─────────────────
#define DEFAULT_MAC      ""
#define DEFAULT_IP       "192.168.0.199"
#define DEFAULT_GW       "192.168.0.1"
#define DEFAULT_MASK     "255.255.255.0"
#define DEFAULT_IPMODE   1               // 0=Static, 1=DHCP
#define DEFAULT_SSID     "spdio"
#define DEFAULT_PWD      "dosadosa"
#define DEFAULT_BROKER   "192.168.0.100" // RPI4 IP 로 변경

// ── MQTT ─────────────────────────────────────────────
#define MQTT_PORT           1883
#define MQTT_CLIENT_ID      "srader_esp32"
#define MQTT_TOPIC          "RDR"
#define MQTT_BUFFER_SIZE    512

// ── UDP (test network) ──────────────────────────────────
#define UDP_MCAST_ADDR   "239.255.3.4"
#define UDP_MCAST_PORT   8096
#define UDP_UCAST_ADDR   "192.168.0.20"
#define UDP_UCAST_PORT   8096

// ── Minishell ─────────────────────────────────────────
#define SHELL_TIMEOUT_MS    3000

// ── 발행 주기 ─────────────────────────────────────────
#define PUBLISH_INTERVAL_MS 200   // 초당 5회

// ── GPIO ──────────────────────────────────────────────
#define PIN_STATUS_LED   2   // 내장 LED: 정상=점등, 오류=점멸
#define PIN_M_LED_1     14   // 외부 LED 1
#define PIN_M_LED_2     13   // 외부 LED 2

// ── TFMini Plus (UART2) ───────────────────────────────
#define TFMINI_BAUD     115200
#define TFMINI_RX_PIN   16   // UART2 RX  ※ VL53L5CX 사용 시 I2C_RST 로 전환
#define TFMINI_TX_PIN   -1   // 미사용 — GPIO17 은 LAN8720 CLK 출력에 할당
#define TFMINI_UDP_PORT 8096
#define TFMINI_DETECT_MS 500 // 부팅 시 TFMini 감지 대기 시간

// ── VL53L5CX (I2C) ────────────────────────────────────
// GPIO16: TFMini 미감지 시 Serial2.end() 후 I2C_RST 출력으로 재사용
// GPIO0 : ESP32 dev 보드 BOOT 버튼과 공유 (LPN) — 실제 보드 확인 필요
#define PIN_VL53_SDA     5   // I2C SDA
#define PIN_VL53_SCL     4   // I2C SCL
#define PIN_VL53_LPN     0   // LPN — 하드웨어에서 3.3V 고정, CPU 비연결 (코드 미사용)
#define PIN_VL53_INT    34   // CX_INT (현재 미사용, 폴링 방식)
#define PIN_VL53_RST    16   // I2C_RST (TFMini RX 핀과 공유)
#define VL53_UDP_PORT   8096

// ── LAN8720 (RMII Ethernet) ──────────────────────────
// RMII 고정 핀: TXD0=IO19, TXD1=IO22, TX_EN=IO21
//              RXD0=IO25, RXD1=IO26, CRS_DV=IO27 (모두 10K Pull-up)
#define ETH_MDC_PIN     23   // MDC  → LAN8720 MDC
#define ETH_MDIO_PIN    18   // MDIO → LAN8720 MDIO  (10K Pull-up)
#define ETH_CLK_PIN     17   // 50MHz CLK 출력 → LAN8720 XTAL1/CLKIN
#define ETH_NRST_PIN    32   // nRST → LAN8720 nRST (active-LOW, GPIO 제어 필수)
#define ETH_PHY_ADDR     1   // PHYAD0=VCC or floating → 주소 1 (Reg18 PHYAD=1 확인)
