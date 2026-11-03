# SuperMini와 VL53L1X

ESP32-S3 SuperMini에서 BH1750 조도와 VL53L1X 거리를 읽고 Windows 앱으로 전달한다.<br>
VL53L1X의 유효한 거리가 설정한 착석 범위에 드는지 판단하며, 사람과 의자·물건을 구분하지 않는다.

## 배선과 전원

다음 GPIO는 2026-11-03 사용자가 연결했다고 알려 준 실제 배선이다.

| SuperMini | VL53L1X | BH1750 |
|---|---|---|
| GPIO12 | SDA / DATA | SDA |
| GPIO13 | SCL / CLK | SCL |
| GPIO4 | SHUT / XSHUT | 연결하지 않음 |
| GND | GND | GND |

두 센서는 하나의 100kHz I²C 버스를 공유한다.<br>
7비트 주소는 VL53L1X가 0x29, BH1750이 기본 0x23이며 ADDR 배선에 따라 0x5C를 사용한다.<br>
VL53L1X INT는 연결하지 않고 I²C로 측정 완료 여부를 확인한다.<br>
SHUT는 GPIO4의 오픈드레인 출력으로 LOW 또는 해제 상태만 만들며 모듈의 센서 전원으로 연결된 풀업 저항이 필요하다.<br>
SHUT를 5V에 연결하지 않는다.

센서 전원은 각 모듈의 VIN 규격을 따른다.<br>
사용자가 제시한 TOF400C 판매 자료는 VIN 3~5V를 표시하지만, 센서 칩의 전원과 신호 전압을 뜻하지 않는다.<br>
모듈의 레귤레이터·레벨 변환·풀업 연결을 확인하고 ESP32 쪽 SDA·SCL에 5V가 걸리지 않게 한다.<br>
모니터 USB를 전원으로 사용하면 화면 대기 중에도 해당 포트가 전원을 유지하도록 설정한다.<br>
모니터 대기 전원 유지와 Wi-Fi 송신 중 재부팅 여부는 실제 사용할 포트·케이블·센서를 함께 연결해 확인한다.

## 빌드와 USB 연결

SuperMini 프로필은 사진에서 확인한 ESP32-S3FH4R2에 맞춰 4MB 플래시와 PSRAM 비활성 설정을 사용한다.<br>
내장 RGB LED GPIO는 48이며 센서 핀과 중복되면 초기화를 차단한다.<br>
GPIO·ROI·LED는 `menuconfig`의 Smart Monitor Controller에서 변경할 수 있다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_firmware.ps1 -Board SuperMini
# GPIO·ROI 변경
powershell -ExecutionPolicy Bypass -File scripts\build_firmware.ps1 -Board SuperMini -Menuconfig
# 앱에서 센서 연결을 해제한 뒤 기록한다.
powershell -ExecutionPolicy Bypass -File scripts\flash_firmware.ps1 -Board SuperMini -Port COM번호
powershell -ExecutionPolicy Bypass -File scripts\package_firmware.ps1 -Board SuperMini
```

빌드 폴더는 `.local/firmware-build-supermini`, 패키지는 `.local/firmware-release/supermini.zip`이다.<br>
기록 스크립트는 기존 플래시를 백업하지 않는다.<br>
`-Board DevKit`은 기존 LD2412·16MB 설정을 사용하며 두 프로필의 빌드 폴더를 공유하지 않는다.

Windows 앱에서 해당 COM 포트로 연결하고 현재 거리와 센서 유효성을 확인한다.<br>
자동 제어 설정에서 ToF 착석 최소·최대 거리, 착석 유지 거리 여유, 상태 전환 유지 시간을 설정한다.<br>
기본값은 20~150cm, 거리 여유 5cm, 전환 유지 1초이다.<br>
거리 여유는 착석 상태에서 벗어나는 경계에 적용하며 다시 착석할 때는 원래 범위로 들어와야 한다.<br>
LD2412용 PC 감지 범위·거리문·공학 모드 설정은 ToF 판정에 사용하지 않는다.

## 센서 방향과 판정

모듈을 세로로 회전해도 광학 창이 몸통을 향하면 사용할 수 있다.<br>
초기 ROI는 중앙의 8×8 정사각형이며 센서의 기본 16×16 영역보다 좁다.<br>
실제 착석·기대기·빈 의자에서 유효한 거리값이 구분되는지 확인한 뒤 범위를 조정한다.<br>
모니터·책상 모서리가 광학 경로를 가리거나 BH1750에 내장 LED 빛이 들어가지 않도록 배치한다.

펌웨어는 50ms 측정 시간과 100ms 측정 간격을 사용하고 기본 200ms마다 데이터를 전송한다.<br>
VL53L1X 원시 상태 9에 해당하는 정상 측정만 사용하며 거리는 40~4000mm 범위로 제한한다.<br>
측정 실패·범위 초과·500ms 이상 오래된 측정은 `tof_ok=false`, `distance_mm=null`이다.<br>
빈자리에서도 센서가 측정할 수 있는 범위 안에 벽·의자 등의 배경이 있어야 유효한 거리로 부재를 판정할 수 있다.<br>
반사 신호 부족이나 측정 범위 초과를 부재로 바꾸지 않으므로 이 조건에서는 자동 절전을 보류한다.

PC는 정상 데이터가 기본 5초간 이어진 뒤 자동 절전을 허용한다.<br>
센서 오류나 수신 중단이 발생하면 부재 시간과 5초 카운트다운을 취소한다.<br>
앱이 화면을 꺼 둔 상태에서 센서 오류가 발생하면 기존 독립 복귀 감시와 복귀 요청을 사용한다.<br>
API 접수 성공과 실제 화면 켜짐·꺼짐은 별도로 확인한다.

## 진단과 시험

USB 명령 `get_status`로 `presence_sensor`, `sda_gpio`, `scl_gpio`, `shut_gpio`, `roi_size`를 읽는다.<br>
`tof_reset`은 SHUT를 LOW로 내렸다 해제한 뒤 센서를 다시 초기화하며 새로운 유효 측정이 올 때까지 기존 거리를 사용하지 않는다.<br>
레이더 설정 명령은 ToF 펌웨어에서 지원하지 않는다.

```powershell
.venv\Scripts\python.exe -m tools.sensor_cli status --port COM번호
.venv\Scripts\python.exe -m tools.sensor_cli command --port COM번호 --json '{"cmd":"tof_reset"}'
powershell -ExecutionPolicy Bypass -File scripts\test_firmware.ps1
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
```

센서 없는 자동 테스트와 실제 전원·배선·착석·화면 관찰은 검증 범위가 다르다.<br>
정지 착석·빈 의자·옷 색상·자리 이탈·재감지·센서 오류·모니터 대기 전원을 실제 설치 위치에서 각각 확인한다.

## 자료와 드라이버

드라이버는 [ST의 stm32duino/VL53L1X](https://github.com/stm32duino/VL53L1X/tree/5aa46e743913186c448aaf86dd0f12071fddc0a2)의 ULD 초기 설정과 레지스터 순서를 ESP-IDF I²C에 맞게 적용한다.<br>
초기화 대기와 I²C 호출에 시간 제한을 두고 첫 오류를 보존한다.<br>
라이선스는 `firmware/components/smc_sensors/LICENSE.vl53l1x`에 있으며 배포 ZIP에도 포함한다.<br>
전압·SHUT 조건은 [VL53L1X 데이터시트](https://www.st.com/resource/en/datasheet/vl53l1x.pdf), ROI는 [ST AN5191](https://www.st.com/resource/en/application_note/an5191-using-the-programmable-region-of-interest-roi-with-the-vl53l1x-stmicroelectronics.pdf)을 따른다.
