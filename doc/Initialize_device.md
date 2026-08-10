# Device Initialization Sequence

ESP32 부팅 후 `setup()` 에서 수행되는 초기화 절차를 순서대로 정리한다.

---

## 전체 흐름

```
Power-ON / Reset
      │
      ▼
[1] Serial 시작 (115200 baud)
      │
      ▼
[2] hw_init() — GPIO / I2C 초기화
      │
      ▼
[3] env_load() — NVS 환경변수 로드
      │
      ▼
[4] 센서 자동 감지
      ├─ TFMini Plus (UART2)  →  SENSOR_TFMINI
      ├─ VL53L5CX   (I2C)     →  SENSOR_VL53
      └─ 미감지                →  SENSOR_NONE
      │
      ▼
[5] Minishell (3 초 타임아웃)
      │  'run' 입력 또는 타임아웃 경과 시 종료
      ▼
[6] 네트워크 연결
      ├─ WiFi 모드  →  net_connect() → net_mqtt_connect()
      └─ LAN8720 모드 →  (TODO: net_eth_connect)
      │
      ▼
[7] Status LED 점등 (정상 준비)
      │
      ▼
[8] VL53L5CX 초기화 (SENSOR_VL53 인 경우만)
      │
      ▼
loop() 진입
```

---

## 단계별 상세

### [1] Serial 초기화
| 항목 | 값 |
|---|---|
| Baud rate | 115200 |
| 대기 | 200 ms (안정화) |

---

### [2] `hw_init()` — 하드웨어 GPIO / I2C 초기화

| 대상 | 핀 | 동작 |
|---|---|---|
| Status LED | GPIO 2 | OUTPUT, LOW |
| External LED 1 | GPIO 14 | OUTPUT, LOW |
| External LED 2 | GPIO 13 | OUTPUT, LOW |
| INTERFACE_SEL | GPIO 35 | INPUT (외부 10 kΩ Pull-down 필수) |
| VL53 INT | GPIO 34 | INPUT (현재 미사용) |
| I2C (SDA/SCL) | GPIO 5 / GPIO 4 | `Wire.begin()`, 50 kHz |

**INTERFACE_SEL 판독**

| 핀 상태 | 네트워크 모드 |
|---|---|
| LOW (Open) | WiFi |
| HIGH (점퍼 → 3.3 V) | LAN8720 |

---

### [3] `env_load()` — NVS 환경변수 로드

NVS(Non-Volatile Storage)에서 아래 값을 읽는다. NVS가 비어있으면 `config.h` 기본값 사용.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `ssid` | `TRDR` | WiFi SSID |
| `pwd` | `dosadosa` | WiFi 패스워드 |
| `brokerip` | `192.168.0.203` | MQTT 브로커 IP |
| `ip` | `192.168.0.199` | 정적 IP |
| `gw` | `192.168.0.1` | 게이트웨이 |
| `mask` | `255.255.255.0` | 서브넷 마스크 |
| `ipmode` | `1` | 0=Static, 1=DHCP |

---

### [4] 센서 자동 감지

두 센서를 순서대로 시도하며 먼저 응답하는 쪽을 채택한다.

```
① TFMini Plus 감지
   └─ UART2 (RX=GPIO16) 를 115200 baud 로 열기
   └─ 500 ms 동안 유효 9-byte 프레임(헤더 0x59 0x59) 수신 대기
      ├─ 성공 → SENSOR_TFMINI, Serial2 유지
      └─ 실패 → Serial2.end(), GPIO16 해제

② VL53L5CX 감지 (TFMini 미감지 시)
   └─ I2C 주소 0x29 에 ACK 확인
      ├─ ACK  → SENSOR_VL53
      └─ NACK → SENSOR_NONE
```

| 결과 | 상수 | 값 |
|---|---|---|
| TFMini Plus 감지 | `SENSOR_TFMINI` | 0 |
| VL53L5CX 감지 | `SENSOR_VL53` | 1 |
| 미감지 | `SENSOR_NONE` | 2 |

---

### [5] Minishell — `shell_run()`

- Serial 콘솔을 통해 파라미터 확인 및 변경 가능
- **타임아웃**: 3000 ms (`SHELL_TIMEOUT_MS`)
- 3 초 내 입력 없거나 `run` 명령 입력 시 자동 종료 → 다음 단계 진행
- `↑` / `↓` 키로 히스토리 탐색 지원 (최대 10 개)

---

### [6] 네트워크 연결

**WiFi 모드** (`INTERFACE_SEL` = LOW)

`net_connect()` 내부 절차:

```
① WiFi.disconnect(true)  — 이전 연결 초기화
② WiFi.mode(WIFI_STA)    — Station 모드 설정
③ MAC 지정 (env.mac 가 설정된 경우)
   └─ esp_wifi_set_mac() 으로 MAC 덮어쓰기
④ IP 모드 분기
   ├─ Static (ipmode=0): WiFi.config(ip, gw, mask) 적용
   └─ DHCP   (ipmode=1): 별도 설정 없음
⑤ WiFi.begin(ssid, pwd) 호출
⑥ 500 ms 간격으로 최대 20 회 (10 초) 연결 대기
   ├─ 성공 → IP 출력 후 true 반환
   └─ 실패 → 경고 출력 후 false 반환, loop() 에서 재시도
```

| 항목 | 기본값 | NVS 키 |
|---|---|---|
| SSID | `TRDR` | `ssid` |
| 패스워드 | `dosadosa` | `pwd` |
| IP 모드 | `1` (DHCP) | `ipmode` |
| 정적 IP | `192.168.0.199` | `ip` |
| 게이트웨이 | `192.168.0.1` | `gw` |
| 서브넷 마스크 | `255.255.255.0` | `mask` |
| MAC 오버라이드 | (없음) | `mac` |

**MQTT 연결** — WiFi 성공 후 `net_mqtt_connect()` 호출

| 항목 | 값 |
|---|---|
| 브로커 IP | `192.168.0.203` (NVS: `brokerip`) |
| 포트 | 1883 |
| Topic | `RDR` |
| Client ID | `srader_<MAC 12자리>` (런타임 생성) |
| 버퍼 크기 | 1024 bytes |

> **loop() 재연결 조건**: WiFi가 연결된 경우에만 MQTT 재연결 시도  
> (WiFi 끊김 상태에서 MQTT 재연결 시도 → `errno 118` 방지)

**LAN8720 모드** (`INTERFACE_SEL` = HIGH)

- 현재 TODO — `net_eth_connect()` 미구현

---

### [7] Status LED 점등

- GPIO 2 → HIGH
- 정상 준비 완료 표시

---

### [8] VL53L5CX 초기화 (`SENSOR_VL53` 인 경우)

- `vl53_begin()` 호출
- I2C (SDA=GPIO5, SCL=GPIO4, 50 kHz) 상에서 8×8 해상도 설정

---

## loop() 주요 동작

| 동작 | 주기 |
|---|---|
| WiFi 재연결 (끊김 감지 시) | 매 loop |
| MQTT 재연결 (연결 끊김 시) | 매 loop |
| 센서 버퍼 폴링 (`tfmini_update` / `vl53_update`) | 매 loop |
| MQTT 데이터 발행 | 200 ms (초당 5회, `PUBLISH_INTERVAL_MS`) |

### MQTT 페이로드 형식

**TFMini Plus**
```json
{"mac":"AA:BB:CC:DD:EE:FF", "ts":<ms>, "s1":[<dist_cm>]}
```

**VL53L5CX (8×8)**
```json
{"mac":"AA:BB:CC:DD:EE:FF", "ts":<ms>, "s2":[{"d":[...64개...],"st":[...64개...],"nb":[...64개...]}]}
```

---

## 오류 처리

| 상황 | 동작 |
|---|---|
| `errorHalt()` 호출 | Status LED 150 ms 주기 점멸 후 무한 루프 |
| WiFi 연결 실패 | 경고 로그, loop() 에서 재시도 |
| MQTT 연결 실패 | 경고 로그, loop() 에서 재시도, LED 소등 |
