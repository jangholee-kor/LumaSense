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

## Wi-Fi 연결

SuperMini 펌웨어 0.3.1과 Windows 앱 0.4.0은 공유기를 통한 TCP 연결을 제공한다.<br>
S3는 2.4GHz 공유기에 접속하고 PC 앱이 센서의 IPv4 주소와 TCP 포트 47653으로 접속한다.<br>
PC는 같은 LAN에 유선으로 연결해도 되며 인터넷이나 별도 중계 서버는 필요하지 않다.<br>
게스트 네트워크의 장치 간 격리가 켜져 있으면 PC와 센서가 통신할 수 없으므로 서로 접근 가능한 LAN을 사용한다.

1. USB로 SuperMini에 연결한다.
2. 시스템 / 센서 탭에서 공유기 이름과 비밀번호를 입력하고 USB로 Wi-Fi 설정 저장을 누른다.
3. 잠시 기다린 뒤 장치 IP / 연결 상태 조회를 누른다.
4. IP가 표시되면 대시보드에서 연결 방식을 Wi-Fi · TCP로 선택하고 연결을 누른다.
5. 센서 유효성이 정상이고 연결 안정화가 끝나는지 확인한 뒤 자동 제어를 켠다.

공유기 이름은 UTF-8 1~32바이트, 비밀번호는 8~63바이트이며 WPA2 이상인 개인 네트워크를 사용한다.<br>
설정 저장 ACK는 보드 NVS 저장·적용 요청의 성공이며 공유기 접속 성공을 뜻하지 않는다.<br>
IP 조회의 공유기 연결 상태와 PC의 실제 센서 수신을 각각 확인한다.<br>
공유기에서 센서에 같은 IP를 배정하도록 DHCP 예약을 설정하면 재부팅 후에도 같은 주소로 연결하기 쉽다.<br>
IP 자동 검색은 제공하지 않으며 주소가 바뀌면 USB로 다시 조회하거나 공유기에서 확인한다.

공유기 비밀번호는 보드 NVS에 저장하며 앱 설정·로그·배포 파일에는 기록하지 않는다.<br>
앱은 처음 설정할 때 무작위 장치 키를 만들고 보드와 PC의 로컬 설정에 저장한다.<br>
TCP 연결은 이 키를 확인한 뒤 telemetry와 명령을 허용하며, Wi-Fi 접속 정보 변경은 USB에서만 허용한다.<br>
설정 내보내기는 장치 키를 제외하고, 가져오기는 현재 PC에 저장된 키를 유지한다.<br>
키가 없는 다른 PC에서는 USB 설정 절차로 새 키를 등록한다.<br>
PC의 `settings.json`과 보드 NVS에는 장치 키가 있으므로 이 파일과 플래시 내용을 공유하지 않는다.<br>
TCP 자체는 TLS로 암호화하지 않으므로 신뢰하는 로컬 네트워크에서 사용하고 포트를 인터넷에 공개하지 않는다.

센서 수집과 네트워크 송수신은 별도 작업에서 실행한다.<br>
전송 대기열은 최신 telemetry 한 건만 유지하며 오래된 데이터를 누적하지 않는다.<br>
PC는 인증 응답의 부팅 식별자·uptime과 수신 시각을 대조해 지연된 데이터를 거부하고 연결을 다시 시도한다.<br>
공유기·TCP 연결이 끊기면 기존 센서 오류 처리로 카운트다운을 취소하고, 재접속 후 안정화를 다시 시작한다.<br>
ACK를 받지 못한 설정·재시작 명령은 자동 재전송하지 않는다.

PC와 앱은 실행 중이어야 하며 화면만 절전된 상태에서 재감지 복귀를 처리한다.<br>
PC 절전·최대 절전·종료 상태에서 센서 패킷으로 PC를 깨우는 기능은 제공하지 않는다.

## 센서 방향과 판정

모듈을 세로로 회전해도 광학 창이 몸통을 향하면 사용할 수 있다.<br>
초기 ROI는 중앙의 8×8 정사각형이며 센서의 기본 16×16 영역보다 좁다.<br>
실제 착석·기대기·빈 의자에서 유효한 거리값이 구분되는지 확인한 뒤 범위를 조정한다.<br>
모니터·책상 모서리가 광학 경로를 가리거나 BH1750에 내장 LED 빛이 들어가지 않도록 배치한다.

내장 LED는 센서 수집 상태와 펌웨어의 150cm 이내 물체 여부를 표시한다.<br>
PC의 착석 최소·최대 거리 설정과 독립적이며 실제 모니터 상태를 뜻하지 않는다.

펌웨어는 50ms 측정 시간과 100ms 측정 간격을 사용하고 기본 200ms마다 데이터를 전송한다.<br>
VL53L1X 원시 상태 9에 해당하는 정상 측정만 거리값으로 사용하며 거리는 40~4000mm 범위로 제한한다.<br>
측정 실패·범위 초과·500ms 이상 오래된 측정은 `tof_ok=false`, `distance_mm=null`이다.<br>
유효한 배경 거리가 착석 범위 밖이면 부재로 판정한다.<br>
앱 0.6.3은 VL53L1X 자체의 I²C 통신과 500ms 미만의 측정 갱신이 정상일 때 거리 측정 실패를 부재로 판정한다.<br>
이 상태에서는 뒤쪽 배경 거리가 측정되지 않아도 입력한 시간 뒤에 카운트다운을 시작한다.<br>
통신 오류·측정 만료·명시적 하드웨어·설정 오류와 알 수 없는 상태는 계속 자동 절전을 보류하며 거리 측정 실패와 구분한다.<br>
원본 거리 유효성과 제어 판정은 [통신 프로토콜](protocol.md)에 설명한 조건으로 분리한다.

PC는 정상 데이터가 기본 5초간 이어진 뒤 자동 절전을 허용한다.<br>
센서 오류나 수신 중단이 발생하면 부재 시간과 5초 카운트다운을 취소한다.<br>
앱이 화면을 꺼 둔 상태에서 센서 오류가 발생하면 기존 독립 복귀 감시와 복귀 요청을 사용한다.<br>
API 접수 성공과 실제 화면 켜짐·꺼짐은 별도로 확인한다.

## 진단과 시험

기록 해시 검증이 끝났는데도 USB 센서 응답이 없으면 BOOT 버튼을 놓았는지와 현재 COM 포트를 확인한다.<br>
칩이 ROM 기록 모드에 남아 있는 경우 앱에서 포트를 해제한 뒤 아래 명령으로 watchdog reset을 요청할 수 있다.<br>
이 명령은 MAC을 조회하고 재시작하며 플래시를 백업하거나 다시 기록하지 않는다.

```powershell
. .\scripts\idf_environment.ps1
python -m esptool --chip esp32s3 --port COM번호 --before no_reset --after watchdog_reset --no-stub read_mac
```

재시작 뒤 USB 상태 조회와 새 센서 데이터 수신을 확인한다.

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
