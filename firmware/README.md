# ESP32-S3 센서 펌웨어

ESP-IDF 5.5.x로 BH1750 조도, LD2412 인체 감지와 USB Serial/JTAG JSON Lines 통신을 구현한다.
사용자가 실물 모듈 표기를 MCN16R8로 확인했으며 기본 플래시는 16MB로 설정한다.
PSRAM을 사용하지 않는 기본 빌드와 octal PSRAM 활성화 빌드를 구분한다.
GPIO19/20은 USB Serial/JTAG용으로 예약한다.
센서가 응답하지 않거나 레이더 데이터가 오래되면 값은 null, 정상 여부는 false로 전송한다.

| 기능 | 예시 GPIO/설정 |
|---|---|
| BH1750 SDA / SCL | GPIO8 / GPIO9, 100kHz |
| BH1750 주소 | 0x23, ADDR 배선에 따라 0x5C |
| ESP RX ← LD2412 TX | GPIO16 |
| ESP TX → LD2412 RX | GPIO17 |
| LD2412 UART | 115200, 8N1 |

위 핀은 배선이 확정되기 전의 예시이며 menuconfig의 Smart Monitor Controller 항목에서 변경한다.
USB Serial/JTAG, 플래시·PSRAM, 부팅 스트랩 핀과 중복되는 설정은 펌웨어가 센서 초기화 전에 거부한다.
제공 회로도의 J1 ESP USB를 데이터 통신과 플래시에 사용한다.
J3는 CP2102에 연결되며 이 펌웨어의 센서 JSON 스트림은 출력하지 않는다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_firmware.ps1
powershell -ExecutionPolicy Bypass -File scripts\build_firmware.ps1
powershell -ExecutionPolicy Bypass -File scripts\test_firmware.ps1
# GPIO 설정 변경
powershell -ExecutionPolicy Bypass -File scripts\build_firmware.ps1 -Menuconfig
# PSRAM 활성화 프로필은 별도 빌드 디렉터리를 사용한다.
powershell -ExecutionPolicy Bypass -File scripts\build_firmware.ps1 -EnablePsram
```

기본 결과물은 `.local/firmware-build/smart_monitor_s3.bin`과 부트로더·파티션 바이너리이다.
기본 빌드에서는 센서 통신에 필요하지 않은 PSRAM을 비활성화해 초기 기동을 단순하게 한다.
`-EnablePsram`은 MCN16R8의 octal PSRAM 초기화와 메모리 검사를 포함하며 실제 기동 확인이 필요하다.
파서 테스트는 ESP-IDF 펌웨어와 같은 C 소스를 PC의 GCC로 컴파일해 실행한다.
실제 센서 전원·신호 레벨은 [하드웨어 문서](../docs/hardware.md), USB 통신은 [프로토콜 문서](../docs/protocol.md)를 참고한다.
