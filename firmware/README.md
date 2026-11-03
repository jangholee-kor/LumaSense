# ESP32-S3 센서 펌웨어

SuperMini의 VL53L1X·BH1750·Wi-Fi 구성은 [SuperMini·ToF 안내](../docs/supermini-tof.md)를 따른다.<br>
아래 배선·16MB 메모리·LD2412 명령은 DevKit 프로필에 해당한다.

ESP-IDF 5.5.x로 BH1750 조도, LD2412 인체 감지와 USB Serial/JTAG JSON Lines 통신을 구현한다.<br>
사용자가 실물 모듈 표기를 MCN16R8로 확인했으며 기본 플래시는 16MB로 설정한다.<br>
PSRAM을 사용하지 않는 기본 빌드와 octal PSRAM 활성화 빌드를 구분한다.<br>
GPIO19/20은 USB Serial/JTAG용으로 예약한다.<br>
센서가 응답하지 않거나 레이더 데이터가 오래되면 값은 null, 정상 여부는 false로 전송한다.

| 기능 | 예시 GPIO/설정 |
|---|---|
| BH1750 SDA / SCL | GPIO8 / GPIO9, 100kHz |
| BH1750 주소 | 0x23, ADDR 배선에 따라 0x5C |
| ESP RX ← LD2412 TX | GPIO16 |
| ESP TX → LD2412 RX | GPIO17 |
| LD2412 UART | 115200, 8N1 |
| 내장 D10 RGB LED | GPIO38, SK6812MINI-HS, 기본 채널 밝기 4/255 |

위 핀은 배선이 확정되기 전의 예시이며 menuconfig의 Smart Monitor Controller 항목에서 변경한다.<br>
USB Serial/JTAG, 플래시·PSRAM, 부팅 스트랩 핀과 중복되는 설정은 펌웨어가 센서 초기화 전에 거부한다.<br>
제공 회로도의 J1 ESP USB를 데이터 통신과 플래시에 사용한다.<br>
J3는 CP2102에 연결되며 이 펌웨어의 센서 JSON 스트림은 출력하지 않는다.

펌웨어 0.2.2는 메인 작업 스택을 8192바이트 이상으로 설정한다.<br>
기존 빌드 설정이 더 작으면 컴파일 단계에서 중단하므로 menuconfig의 ESP System Settings에서 Main task stack size를 8192 이상으로 저장한다.<br>
USB 명령 수신 버퍼는 정적 메모리에 두며 `main_stack_min_free_bytes`로 부팅 이후 메인 스택의 최소 여유량을 보고한다.<br>
USB JSON 스트림에 일반 로그가 섞이지 않도록 보조 콘솔은 None으로 설정한다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_firmware.ps1
powershell -ExecutionPolicy Bypass -File scripts\build_firmware.ps1
powershell -ExecutionPolicy Bypass -File scripts\test_firmware.ps1
# GPIO 설정 변경
powershell -ExecutionPolicy Bypass -File scripts\build_firmware.ps1 -Menuconfig
# PSRAM 활성화 프로필은 별도 빌드 디렉터리를 사용한다.
powershell -ExecutionPolicy Bypass -File scripts\build_firmware.ps1 -EnablePsram
```

기본 결과물은 `.local/firmware-build/smart_monitor_s3.bin`과 부트로더·파티션 바이너리이다.<br>
기본 빌드에서는 센서 통신에 필요하지 않은 PSRAM을 비활성화해 초기 기동을 단순하게 한다.<br>
`-EnablePsram`은 MCN16R8의 octal PSRAM 초기화와 메모리 검사를 포함하며 실제 기동 확인이 필요하다.<br>
파서 테스트는 ESP-IDF 펌웨어와 같은 C 소스를 PC의 GCC로 컴파일해 실행한다.<br>
실제 센서 전원·신호 레벨은 [하드웨어 문서](../docs/hardware.md), USB 통신은 [프로토콜 문서](../docs/protocol.md)를 참고한다.<br>
플래시·리셋·10분 센서 로그와 명령 실행은 [펌웨어 시험 안내](../docs/firmware-testing.md)에 정리한다.

## 내장 RGB 센서 상태 표시

펌웨어 0.2.1부터 회로도 D10의 SK6812MINI-HS를 GPIO38에서 RMT로 제어한다.<br>
색상은 MCU에서 읽은 센서 상태를 나타내며 Windows 자동 제어의 활성화나 실제 모니터 전원 상태를 뜻하지 않는다.

| 표시 | 의미 |
|---|---|
| 파랑 | 부팅 후 최대 3초 동안 센서 초기화·첫 데이터 대기 |
| 초록 | BH1750·LD2412 데이터 정상, 움직임 또는 정지 인체 감지 |
| 노랑 | BH1750·LD2412 데이터 정상, 레이더가 미감지를 보고함 |
| 빨강 점멸 | 초기 대기 이후 센서 오류·만료·보정 상태 또는 잘못된 GPIO 설정 |

정상 데이터가 도착하면 3초를 기다리지 않고 초록 또는 노랑으로 바뀐다.<br>
센서 오류는 정상 미감지보다 우선하며 빨강은 약 0.5초 켜짐·0.5초 꺼짐으로 반복한다.<br>
부팅 전·펌웨어 실행 중단·LED 자체 고장까지 색상으로 진단할 수 있는 것은 아니다.

`build_firmware.ps1 -Menuconfig`의 Smart Monitor Controller에서 LED 사용 여부·GPIO·채널 밝기를 설정한다.<br>
설정을 저장한 뒤 `build_firmware.ps1`로 다시 빌드한다.<br>
기본 밝기는 4/255, 설정 범위는 0~32이며 0은 검정 데이터를 보내 LED를 끈다.<br>
사용 여부를 해제하면 LED 드라이버를 만들지 않고 해당 GPIO도 예약하지 않는다.<br>
이전 펌웨어가 켜 둔 색이 남아 있으면 전원을 다시 연결하거나 밝기 0 설정으로 끈다.<br>
LED가 활성화된 동안 센서 핀과 LED 핀이 겹치면 센서 초기화를 차단하고 충돌 핀의 LED도 구동하지 않는다.

RMT 초기화·전송 오류는 USB의 `status_led`에 기록하고 정상 센서 수집은 계속한다.<br>
LED 제어 오류만으로 `sensor_ok`를 false로 바꾸지 않는다.<br>
단색은 색상이 달라질 때만 전송하며 전송 완료 대기는 최대 20ms로 제한한다.<br>
전송 실패 후에는 오류를 유지하고 재시도하거나 전송 버퍼를 덮어쓰지 않는다.

BH1750을 옆으로 배치할 때 수광면을 케이스 밖의 방 쪽으로 향하게 하고 내장 RGB LED 빛이 직접 닿지 않게 분리·차광한다.<br>
낮은 LED 밝기만으로 광간섭이 없어졌다고 가정하지 말고 [실물 시험](../docs/firmware-testing.md)의 LED 켜짐·꺼짐 비교를 수행한다.
