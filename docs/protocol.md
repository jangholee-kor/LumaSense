# USB 센서 프로토콜 v1

ESP32-S3는 J1 ESP USB의 USB Serial/JTAG CDC로 UTF-8 JSON Lines를 전송한다.<br>
각 JSON 객체는 LF 한 바이트로 끝나며 기본 주기는 200ms이다.<br>
통신 도구는 115200 baud로 포트를 열지만 네이티브 USB 전송 속도가 UART baud와 같다는 뜻은 아니다.<br>
센서 UART는 별도로 LD2412 기본 115200 8N1을 사용한다.

## 센서 데이터

```json
{"ver":1,"type":"telemetry","device":"smart-monitor-s3","firmware":"0.2.2","seq":1234,"uptime_ms":258000,"lux":125.5,"light_ok":true,"radar_ok":true,"sensor_ok":true,"presence":true,"moving":false,"stationary":true,"distance_cm":67,"radar_state":2,"moving_distance_cm":0,"stationary_distance_cm":67,"moving_energy":0,"stationary_energy":59,"engineering":false,"errors":[]}
```

`seq`는 부팅 후 전송마다 증가하며 재부팅 시 다시 0부터 시작한다.<br>
`light_ok`와 `radar_ok`는 각 센서의 유효성을 나타내고 `sensor_ok`는 둘 다 정상일 때 true이다.<br>
조도 읽기 실패나 오래된 값은 `lux: null`, `light_ok: false`로 표시한다.<br>
레이더 데이터가 기본 2초 동안 오지 않거나 보정 상태이면 `presence`, `moving`, `stationary`, `distance_cm`은 null이고 `radar_ok`는 false이다.<br>
정상 레이더가 무인 상태를 보고했을 때만 `presence: false`가 된다.<br>
`distance_cm`은 현재 감지 상태에 해당하는 유효한 거리 중 가까운 값이며 제공할 거리가 없으면 null이다.<br>
원시 움직임·정지 거리와 에너지는 별도 필드로 보존한다.<br>
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

`radar_config`의 `engineering`은 boolean이며 전원 재투입 시 레이더의 기본 모드로 돌아간다.<br>
기본 감지 설정은 `min_gate`, `max_gate`, `absence_seconds` 세 항목을 함께 지정한다.<br>
거리문은 원시 프로토콜 인덱스 0~13이고 최소 인덱스는 최대 인덱스 이하여야 한다.<br>
`absence_seconds`는 제조사 문서에 따라 5~65535 정수로 제한한다.<br>
거리문의 실제 길이는 레이더에 저장된 해상도 설정에 따라 달라지므로 이 펌웨어는 임의의 미터 값을 원시 인덱스로 변환하지 않는다.<br>
`moving_thresholds`와 `stationary_thresholds`는 각각 0~100 정수 14개의 배열이다.<br>
모듈의 기본 감지 범위·유지 시간·문별 민감도는 비휘발 설정이므로 명시적인 호스트 명령으로만 변경한다.<br>
여러 항목은 순서대로 적용되며 중간 실패 시 이미 적용된 항목이 있을 수 있다.<br>
실패 응답의 `configuration_may_be_partial`을 확인하고 제조사 도구로 설정을 다시 읽어 검증한다.<br>
부팅 시 자동으로 범위·민감도를 덮어쓰지 않는다.

## LD2412 내부 프레임 검증

[제조사 V1.06 프로토콜](https://r0.hlktech.com/download/HLK-LD2412-24G/1/LD2412%20%E4%B8%B2%E5%8F%A3%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE%20V1.06%20241105.pdf)에 따라 리틀 엔디언 길이, 보고 헤더 F4 F3 F2 F1, 꼬리 F8 F7 F6 F5와 내부 AA/55 표식을 검사한다.<br>
설정 ACK는 FD FC FB FA와 04 03 02 01 표식, 명령 번호 및 ACK 상태로 확인한다.<br>
이 프로토콜에는 체크섬 필드가 정의되어 있지 않아 별도의 CRC 검사를 수행한다고 주장하지 않는다.<br>
마커와 길이가 유효한 채 데이터 비트만 바뀐 경우까지 검출할 수 있다는 보장은 없다.<br>
보고 상태 4~6은 보정 상태로 처리해 인체 부재로 변환하지 않는다.<br>
과도한 길이나 손상된 프레임은 버리고 다음 헤더를 검색하며 버퍼는 256바이트로 제한한다.<br>
UART 및 설정 ACK의 실제 타이밍은 센서를 연결해 검증한다.
