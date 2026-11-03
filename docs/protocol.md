# 센서 통신 프로토콜

SuperMini의 VL53L1X 펌웨어는 아래 v2 거리 데이터를 사용하며 USB 명령·ACK는 v1 형식을 유지한다.<br>
배선과 판정 설정은 [SuperMini·ToF 안내](supermini-tof.md)를 따른다.

## VL53L1X 거리 데이터 v2

```json
{"ver":2,"type":"telemetry","device":"smart-monitor-s3","presence_sensor":"vl53l1x","firmware":"0.3.1","boot_id":"0123456789abcdef","seq":1,"uptime_ms":1000,"light_ok":true,"tof_ok":true,"sensor_ok":true,"lux":125.5,"distance_mm":600,"tof_raw_status":9,"tof_epoch":0,"tof_sample_age_ms":30,"tof_error":"ESP_OK","roi_size":8}
```

`boot_id`는 부팅마다 새로 생성한 16자리 16진수이며 PC는 값이 바뀌면 새 연결로 안정화한다.<br>
`tof_raw_status`는 센서 레지스터의 원시 상태이며 ST ULD에서 RangeValid로 변환하는 9만 유효한 거리값으로 사용한다.<br>
`tof_ok=true`이면 `distance_mm`은 40~4000 정수이고 `tof_sample_age_ms`는 0~499 정수이다.<br>
`tof_ok=false`이면 `distance_mm=null`이며 유효한 거리값을 만들지 않는다.<br>
`sensor_ok`는 `light_ok && tof_ok`이고 조도 무효 시 `lux=null`이다.<br>
이 데이터는 움직임·정지 인체 분류를 제공하지 않는다.<br>
0.3.1의 `tof_epoch`는 SHUT 재시작마다 증가하며 PC는 이 값이 바뀌면 측정 안정화를 다시 시작한다.<br>
PC가 거리 범위·전환 유지 시간·거리 여유를 적용해 착석 상태를 만들며 원본 거리와 유효성을 보존한다.

앱 0.6.3은 거리 측정 성공과 VL53L1X의 I²C 통신·측정 갱신을 따로 판정한다.<br>
`tof_error=ESP_OK`이고 측정 나이가 0~499ms이면 센서에서 새 측정을 읽고 인터럽트를 해제하는 I²C 작업이 정상 완료된 관측이다.<br>
PC 내부의 `tof_acquisition_ok`는 이 통신·갱신 상태를 나타내며 원본 패킷에 추가로 전송되는 필드는 아니다.

이 상태에서 `tof_ok=false`·`distance_mm=null`이고 아래 거리·품질 상태이면 거리 미측정으로 부재 관측을 생성한다.

| 원시 상태 | ST ULD 변환값 | 거리 미측정 사유 |
|---|---|---|
| 4 | 2 | 반사 신호 부족 |
| 5 | 4 | 측정 범위·위상 경계 초과 |
| 6 | 1 | 측정 편차 초과 |
| 7 | 7 | 거리 모호성·wraparound |
| 8 | 3 | 최소 감지 조건 미달 |
| 9 | 0 | 펌웨어 거리 허용 범위 40~4000mm 밖 |
| 12 | 9 | 반사 간섭 신호 검사 실패 |
| 19 | 6 | wrap 검사를 하지 않은 측정 |
| 22 | 11 | 합쳐진 반사 펄스 |
| 23 | 12 | 검출 신호 부족 |

거리 미측정은 착석 범위 밖의 유효한 거리와 같은 부재 유지 시간을 적용하고 정상 측정의 안정화 시간을 초기화하지 않는다.<br>
원본 `tof_ok`와 `sensor_ok`는 false로 보존하고 PC 내부의 `tof_no_target`과 제어 가능 여부를 구분한다.<br>
조도까지 정상일 때만 해당 관측으로 자동 꺼짐을 진행한다.<br>
I²C 응답이 있어도 명시적인 하드웨어 오류인 원시 상태 3, 설정·동기화·알 수 없는 상태는 부재로 바꾸지 않는다.<br>
통신 실패·누락된 `tof_error`·500ms 이상 오래된 측정·수신 중단도 계속 꺼짐을 보류한다.<br>
다른 I²C 장치의 응답으로 VL53L1X의 상태를 대신 판단하지 않는다.<br>
기존 펌웨어 0.3.1이 필요한 필드를 모두 전송하므로 재기록 없이 사용할 수 있다.

상태 정의는 [ST ULD 가이드의 Range status interpretation](https://www.st.com/resource/en/user_manual/um2510-a-guide-to-using-the-vl53l1x-ultra-lite-driver-stmicroelectronics.pdf)과 [ST 원시 상태 변환 코드](https://github.com/stm32duino/VL53L1X/blob/main/src/vl53l1x_class.cpp)를 따른다.<br>
거리 미측정은 반사율이나 측정 품질 때문에 발생할 수도 있으므로 실제 사람의 부재를 확정하는 분류값이 아닌 앱의 감지 기준이다.

## TCP 연결과 Wi-Fi 설정

SuperMini TCP 포트는 47653이며 JSON Lines 형식과 telemetry v2·명령/ACK v1을 사용한다.<br>
첫 명령은 `auth`이고 `ver=1`, 요청별 문자열 `id`, USB로 등록한 64자리 16진수 `token`을 포함한다.<br>
성공 응답은 `type=ack`, `cmd=auth`, 같은 `id`, `ok=true`, `boot_id`, `uptime_ms`를 담는다.<br>
인증 전 telemetry·센서 명령을 허용하지 않으며 인증 실패·3초 시간 초과·2048바이트 이상의 입력 줄은 연결을 종료한다.<br>
한 번에 PC 클라이언트 한 개를 연결한다.

USB 명령 `wifi_config`는 `ssid`, `password`, `token`을 NVS에 저장하고 공유기 연결을 요청한다.<br>
이 명령은 TCP에서 거부하며 ACK·상태 응답에 비밀번호와 키를 넣지 않는다.<br>
`network_status`와 `get_status` 응답의 `network`에는 `configured`, `connected`, `address`, `port`, `error`가 있다.<br>
저장 성공·공유기 접속·PC 센서 수신은 별도 상태이다.<br>
PC는 요청별 인증 ID와 부팅 식별자, uptime 진행을 대조해 이전 연결이나 지연된 패킷을 배제한다.

펌웨어 0.3.2부터 `network`에 다음 출력 진단 필드를 추가하며 기존 명령과 telemetry 형식은 유지한다.

| 필드 | 의미 |
|---|---|
| `tx_power_requested_dbm` | 빌드 설정에서 요청한 최대 출력이며 단위는 dBm이다.<br>출력 제한을 해제하면 `null`이다. |
| `tx_power_max_dbm` | 응답 시점에 `esp_wifi_get_max_tx_power()`로 읽은 드라이버의 최대 출력 설정이다.<br>조회 실패 시 `null`이며 방사 출력 측정값이 아니다. |
| `tx_power_read_error` | 출력 조회 API의 오류 이름이며 성공은 `ESP_OK`이다. |

출력 제한 적용·초기 조회가 실패하거나 초기 조회값이 요청 상한을 넘으면 네트워크 초기화를 중단하고 `network.error`에 오류를 남긴다.<br>
이 경우에도 USB 명령과 센서 수집은 계속되며 상태 조회 명령의 `ok=true`는 조회 응답 성공을 뜻한다.<br>
공유기 접속 성공은 `network.connected`와 IP 할당으로 별도 확인한다.

## LD2412 USB 전송

아래 v1 telemetry와 레이더 설정 명령은 LD2412 펌웨어에 해당한다.

ESP32-S3는 J1 ESP USB의 USB Serial/JTAG CDC로 UTF-8 JSON Lines를 전송한다.<br>
각 JSON 객체는 LF 한 바이트로 끝나며 기본 주기는 200ms이다.<br>
통신 도구는 115200 baud로 포트를 열지만 네이티브 USB 전송 속도가 UART baud와 같다는 뜻은 아니다.<br>
센서 UART는 별도로 LD2412 기본 115200 8N1을 사용한다.

## 센서 데이터

```json
{"ver":1,"type":"telemetry","device":"smart-monitor-s3","firmware":"0.2.3","seq":1234,"uptime_ms":258000,"lux":125.5,"light_ok":true,"radar_ok":true,"sensor_ok":true,"presence":true,"moving":false,"stationary":true,"distance_cm":67,"radar_state":2,"radar_reserved":248,"moving_distance_cm":0,"stationary_distance_cm":67,"moving_energy":0,"stationary_energy":59,"engineering":false,"errors":[]}
```

`seq`는 부팅 후 전송마다 증가하며 재부팅 시 다시 0부터 시작한다.<br>
`light_ok`와 `radar_ok`는 각 센서의 유효성을 나타내고 `sensor_ok`는 둘 다 정상일 때 true이다.<br>
조도 읽기 실패나 오래된 값은 `lux: null`, `light_ok: false`로 표시한다.<br>
레이더 데이터가 기본 2초 동안 오지 않거나 보정 상태이면 `presence`, `moving`, `stationary`, `distance_cm`은 null이고 `radar_ok`는 false이다.<br>
정상 레이더가 무인 상태를 보고했을 때만 `presence: false`가 된다.<br>
`distance_cm`은 현재 감지 상태에 해당하는 유효한 거리 중 가까운 값이며 제공할 거리가 없으면 null이다.<br>
원시 움직임·정지 거리와 에너지는 별도 필드로 보존한다.<br>
0.2.3부터 `radar_reserved`는 제조사 표 11의 마지막 예약 바이트를 원시 값으로 보존하며 물리적 의미를 해석하지 않는다.<br>
공학 모드에서는 `moving_gate_energy`, `stationary_gate_energy` 배열에 실제 프레임이 제공한 거리문 수만큼 기록한다.<br>
추가 진단 필드는 `radar_rejected_frames`, `usb_dropped_lines`, `light_error`, `radar_init_error`, `free_heap`이다.<br>
0.2.2부터 `main_stack_min_free_bytes`는 메인 작업이 부팅 이후 기록한 최소 스택 여유량을 바이트로 나타낸다.<br>
구현체는 알 수 없는 추가 필드를 허용하고 버전과 알려진 필드의 형식을 검사한다.

펌웨어 0.2.1은 telemetry와 `get_status` ACK에 다음 `status_led` 진단 객체를 추가한다.

```json
{"status_led":{"enabled":true,"gpio":38,"brightness":4,"driver_ok":true,"error":"ESP_OK","state":"present","updates":2,"requested_rgb":[0,4,0]}}
```

`state`는 `disabled`, `starting`, `present`, `absent`, `sensor_error` 중 하나이다.<br>
`brightness`는 채널별 최대 요청값이며 광학적 휘도나 조도 측정값이 아니다.<br>
`requested_rgb`는 빨강·초록·파랑 순서의 요청값이고, 오류 점멸의 꺼짐 구간에는 `[0,0,0]`이다.<br>
`updates`는 전송 완료가 확인된 프레임 수이며, `driver_ok`와 `error`는 RMT 드라이버의 결과이다.<br>
전송 완료는 실제 LED 점등이나 색상 검증을 의미하지 않는다.<br>
LED만 고장 난 경우 센서의 `sensor_ok`와 `errors`에는 영향을 주지 않고 `status_led`에서 별도로 확인한다.<br>
이 필드는 PC가 보고한 자동 제어·모니터 상태가 아니라 MCU의 센서 유효성과 레이더 감지 상태를 나타낸다.

## PC 명령과 응답

명령은 `ver: 1`, 응답을 연결할 `id`, `cmd`를 포함한 한 줄이다.<br>
ACK는 같은 id와 cmd, 성공 여부 `ok`, ESP-IDF 오류 이름 `error`를 반환한다.

```json
{"ver":1,"id":"request-1","cmd":"ping"}
{"ver":1,"type":"ack","id":"request-1","cmd":"ping","ok":true,"error":"ESP_OK"}
```

| cmd | 입력 | 동작 |
|---|---|---|
| `ping` | 없음 | 연결 응답 |
| `get_status` | 없음 | 장치·펌웨어 버전, 전송 주기, 실제 GPIO 설정 반환 |
| `set_reporting` | `interval_ms`: 100~5000 정수 | RAM의 전송 주기 변경, 재부팅하면 빌드 기본값 |
| `radar_config` | 아래 항목 중 하나 이상 | 제조사 ACK를 기다리며 설정 적용 |
| `radar_get_config` | 없음 | 저장된 거리 해상도·범위·부재 유지 시간·OUT 극성·두 감도 배열 조회 |
| `radar_calibrate_background` | `empty_confirmed: true` 필수 | 빈 환경을 확인한 뒤 동적 배경 보정 시작 |
| `radar_calibration_status` | 없음 | 제조사 보정 진행 상태 `active`와 펌웨어 대기 상태 `calibration_pending` 조회 |

`radar_config`의 `engineering`은 boolean이며 전원 재투입 시 레이더의 기본 모드로 돌아간다.<br>
기본 감지 설정은 `min_gate`, `max_gate`, `absence_seconds` 세 항목을 함께 지정한다.<br>
기본 설정 쓰기의 `min_gate`, `max_gate` 입력은 현재 0~13이며 최소 값은 최대 값 이하여야 한다.<br>
에너지 배열은 인덱스 0~13의 14개 값이며, 기본 설정의 최대 거리문 값과 배열의 마지막 인덱스를 같은 값으로 해석하지 않는다.<br>
ESPHome의 LD2412 구현은 기본 설정의 `max_gate`를 배열 인덱스보다 1 크게 송신한다.<br>
따라서 해상도 20cm와 원시 `max_gate=8`은 마지막 배열 인덱스 7까지의 약 1.6m 구간으로 해석하되, 경계의 실제 감지는 설치 후 확인한다.<br>
`absence_seconds`는 제조사 문서에 따라 5~65535 정수로 제한한다.<br>
거리문의 실제 길이는 레이더에 저장된 해상도 설정에 따라 달라지므로 이 펌웨어는 임의의 미터 값을 원시 인덱스로 변환하지 않는다.<br>
0.2.4부터 `resolution_cm`에 20·50·75 중 하나를 지정할 수 있으며 다른 설정 항목과 함께 보내면 거부한다.<br>
거리 해상도 변경은 레이더 재시작을 동반하며 기존 범위·유지 시간·감도가 바뀔 수 있다.<br>
해상도 변경 후 약 3초 동안 새 보고를 기다리고, 범위·감도 설정을 별도 명령으로 적용한 뒤 `radar_get_config`로 저장값을 대조한다.<br>
재시작 직전의 감지값은 무효 처리하며 새 보고가 들어오기 전에는 정상 감지로 사용하지 않는다.<br>
`moving_thresholds`와 `stationary_thresholds`는 각각 0~100 정수 14개의 배열이다.<br>
모듈의 기본 감지 범위·유지 시간·문별 민감도는 비휘발 설정이므로 명시적인 호스트 명령으로만 변경한다.<br>
여러 항목은 순서대로 적용되며 중간 실패 시 이미 적용된 항목이 있을 수 있다.<br>
실패 응답의 `configuration_may_be_partial`을 확인하고 `radar_get_config`로 설정을 다시 읽어 검증한다.<br>
부팅 시 자동으로 범위·민감도를 덮어쓰지 않는다.

조회 응답의 `radar` 객체는 `resolution_code`, `gate_width_cm`, `min_gate`, `max_gate`, `absence_seconds`, `out_polarity`, `moving_thresholds`, `stationary_thresholds`, `complete`를 담는다.<br>
조회는 비휘발 설정을 변경하지 않으며 `ok=true`와 `complete=true`를 모두 확인한다.<br>
공학 모드는 별도 설정이며 조회 결과에 포함하지 않는다.<br>
조회 도중 실패하면 일부 필드만 포함될 수 있으므로 이를 완전한 설정으로 저장하지 않는다.<br>
감도 배열의 임계값이 높을수록 감지가 둔해지며 100은 해당 구간을 비활성화하는 값이다.<br>
거리 설정은 측정 구간을 제한하며 사람과 물건의 구분이나 감지 경계의 정확도를 보장하지 않는다.

거리문 번호 변환과 재시작 순서는 [ESPHome LD2412 구현](https://github.com/esphome/esphome/blob/dev/esphome/components/ld2412/ld2412.cpp)을 함께 참고한다.

배경 보정은 센서·의자·책상을 실제 사용할 위치에 고정하고 감지 범위에 사람이 없을 때 시작한다.<br>
제조사 프로토콜의 명령 0x000B는 접수 후 약 10초 뒤 보정을 시작하고 결과를 모듈에 저장한다.<br>
시작 ACK는 보정 완료를 뜻하지 않는다.<br>
호스트는 0x001B에 해당하는 `radar_calibration_status`를 주기적으로 조회해 `active=true` 이후 `active=false` 전환을 확인한다.<br>
펌웨어는 이 전환을 확인할 때까지 `radar_calibration_pending=true`로 유지하고 감지값을 무효 처리한다.<br>
보정 중 설정 변경·중복 시작은 거부하며, 보정 종료 직전 보고도 무효 처리해 새 보고를 기다린다.<br>
시작 명령의 ACK가 유실돼도 보정이 시작됐을 수 있으므로 대기 상태를 유지한다.<br>
시작·종료 전환을 확인하지 못한 경우 완료로 처리하지 않고 상태 조회와 원본 로그로 원인을 확인한다.<br>
배경 보정 후 저장 설정과 실제 빈자리·착석 감지를 다시 확인한다.

## LD2412 내부 프레임 검증

[제조사 V1.06 프로토콜](https://r0.hlktech.com/download/HLK-LD2412-24G/1/LD2412%20%E4%B8%B2%E5%8F%A3%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE%20V1.06%20241105.pdf)에 따라 리틀 엔디언 길이, 보고 헤더 F4 F3 F2 F1, 꼬리 F8 F7 F6 F5와 내부 AA/55 표식을 검사한다.<br>
설정 ACK는 FD FC FB FA와 04 03 02 01 표식, 명령 번호 및 ACK 상태로 확인한다.<br>
보고 데이터의 마지막 예약 바이트는 값이 고정돼 있지 않으므로 0만 허용하는 검사를 하지 않는다.<br>
이 프로토콜에는 체크섬 필드가 정의되어 있지 않아 별도의 CRC 검사를 수행한다고 주장하지 않는다.<br>
마커와 길이가 유효한 채 데이터 비트만 바뀐 경우까지 검출할 수 있다는 보장은 없다.<br>
보고 상태 4~6은 보정 상태로 처리해 인체 부재로 변환하지 않는다.<br>
과도한 길이나 손상된 프레임은 버리고 다음 헤더를 검색하며 버퍼는 256바이트로 제한한다.<br>
UART 및 설정 ACK의 실제 타이밍은 센서를 연결해 검증한다.
