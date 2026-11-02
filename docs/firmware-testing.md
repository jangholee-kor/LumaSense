# ESP32-S3 펌웨어 실행과 실물 시험

## 빌드 환경

Windows 11과 ESP-IDF 5.5.x, Python 3.12를 사용한다.<br>
검증에 사용한 SDK는 ESP-IDF 5.5.4이며 커밋은 `735507283d5b2f9fb363a1901172dbd9e847945d`이다.<br>
다른 설치 경로를 사용할 때는 `IDF_PATH`와 필요하면 `IDF_TOOLS_PATH`를 지정한다.<br>
환경 스크립트는 해당 SDK의 export.ps1을 사용하고 5.5.x 버전인지 검사한다.

```powershell
# Windows 도구 의존성 설치
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# ESP-IDF 설치 후 ESP32-S3 도구 준비
powershell -ExecutionPolicy Bypass -File scripts\setup_firmware.ps1
# 펌웨어 빌드와 같은 파서의 PC 테스트
powershell -ExecutionPolicy Bypass -File scripts\build_firmware.ps1
powershell -ExecutionPolicy Bypass -File scripts\test_firmware.ps1
# 개별 바이너리와 통합 바이너리, SHA-256 목록을 ZIP으로 묶기
powershell -ExecutionPolicy Bypass -File scripts\package_firmware.ps1
```

기본 패키지는 `.local/firmware-release/default.zip`, PSRAM 프로필은 `.local/firmware-release/psram.zip`이다.<br>
PSRAM 프로필을 사용할 때는 build, package, flash 스크립트 모두에 `-EnablePsram`을 지정한다.<br>
PSRAM 활성화 빌드의 성공은 실물 메모리 초기화 성공을 증명하지 않는다.

## 배선과 첫 플래시

[하드웨어 문서](hardware.md)의 예시 배선을 실제 센서의 핀 이름과 대조한다.<br>
다르게 배선했으면 `build_firmware.ps1 -Menuconfig`에서 GPIO를 바꾸고 다시 빌드한다.<br>
보드의 J1 ESP USB를 PC에 연결하고 아래 목록에서 해당 장치의 COM 포트를 확인한다.<br>
J3 CP2102는 이 펌웨어의 JSON 스트림 출력 포트가 아니다.

```powershell
.venv\Scripts\python.exe -m tools.sensor_cli ports
# COM번호를 확인한 값으로 바꾼다.
powershell -ExecutionPolicy Bypass -File scripts\flash_firmware.ps1 -Port COM번호
.venv\Scripts\python.exe -m tools.sensor_cli status --port COM번호
```

COM 포트를 생략하면 VID 303A / PID 1001인 USB Serial/JTAG 장치가 한 개일 때만 자동 선택한다.<br>
이 VID/PID만으로 ESP32-S3 모델을 확정할 수 없으므로 물리 연결과 포트를 대조한다.<br>
플래시는 생성된 ESP-IDF 인자와 `chip=esp32s3` 검사로 실행하며 칩 종류가 다르면 쓰기 전에 실패해야 한다.<br>
이미 사용 중인 COM 포트는 다른 도구에서 닫고 진행한다.<br>
이 펌웨어의 첫 플래시는 부트로더·파티션·앱 영역을 해당 빌드 구성으로 기록한다.<br>
처음 연결에서 다운로드 모드로 진입하지 못하면 BOOT를 누른 채 RESET을 한 번 누른 뒤 BOOT를 놓고 다시 실행한다.<br>
보드와 센서의 실제 플래시·기동은 별도 검증이며 빌드 결과만으로 성공 처리하지 않는다.

## 상태·명령 확인

상태 도구는 포트를 연 뒤 `smart-monitor-s3`의 유효한 telemetry를 확인하고 나서 명령을 전송한다.<br>
`get_status` 응답에서 펌웨어 버전, 전송 주기와 실제 GPIO 설정을 확인한다.<br>
센서가 아직 없으면 상태 명령은 동작할 수 있지만 sensor_ok는 false이고 센서값은 null이어야 한다.

```powershell
.venv\Scripts\python.exe -m tools.sensor_cli status --port COM번호
.venv\Scripts\python.exe -m tools.sensor_cli command --port COM번호 --request-file config\firmware\reporting-200ms.json
.venv\Scripts\python.exe -m tools.sensor_cli command --port COM번호 --request-file config\firmware\engineering-on.json
# 리셋은 COM 포트를 닫은 뒤 실행한다.
powershell -ExecutionPolicy Bypass -File scripts\reset_firmware.ps1 -Port COM번호
```

JSON 명령 파일은 UTF-8이며 PowerShell의 인용부호 전달 차이를 피할 수 있다.<br>
공학 모드를 켜면 원시 거리문별 에너지 배열을 확인할 수 있다.<br>
범위·민감도 변경은 [프로토콜 문서](protocol.md)에 따라 별도 명령 파일로 지정한다.<br>
레이더 설정 중 ACK를 기다리므로 USB 전송이 잠시 늦어질 수 있고 부분 적용 오류가 나면 설정을 다시 확인한다.

## 10분 센서 데이터 검증

```powershell
powershell -ExecutionPolicy Bypass -File scripts\monitor_firmware.ps1 -Port COM번호 -Duration 600
```

수신 로그는 `.local/sensor-capture/실행시각/sensor.jsonl`에 PC 수신 UTC 시각과 원본 패킷을 함께 기록한다.<br>
`summary.json`에는 정상·센서 오류·손상 패킷 수, 누락 순번, 재시작, 전송 오류와 경과 시간을 기록한다.<br>
`sensor_stream_pass`는 요청한 구간의 유효한 스트림 검사 결과이고 `ten_minute_stream_pass`는 정상 수신을 실제 600초 이상 수행했을 때만 true이다.<br>
짧은 시험 결과로 10분 기준을 충족했다고 표시하지 않는다.<br>
데이터가 끊기면 오류로 끝나며 이미 받은 로그와 실패 요약은 남는다.<br>
오류가 있는 구간은 임의의 조도 0 또는 presence false로 대체하지 않는다.

다음 상황을 각각 시험하고 새로운 로그 디렉터리에 결과를 보관한다.

1. 센서 두 개를 연결한 상태로 10분 정상 수신한다.
2. 조명을 바꿔 lux가 반응하는지 확인한다.
3. 움직임과 정지 상태에서 presence·에너지를 비교한다.
4. 레이더 통신이 중단되면 2초 후 radar_ok=false와 presence=null이 되는지 확인한다.
5. 조도센서 통신이 실패하면 lux=null이 되는지 확인하고 연결 복구 후 다시 정상 측정되는지 확인한다.
6. USB 재연결 후 상태와 새 순번을 확인하고 새 수집 명령을 실행한다.

수집 CLI는 진단용으로 오류를 기록하고 종료한다.<br>
Windows GUI는 같은 프로토콜을 사용하며 백그라운드 연결·재연결과 자동 밝기·인체 제어를 제공한다.

## 내장 RGB LED 실물 확인

펌웨어 0.2.1의 기본 LED 설정은 GPIO38, 채널 밝기 4/255이다.<br>
아래 시험은 자동 밝기·절전을 끈 상태에서 센서 원본값과 LED 표시를 비교한다.

1. 전원 투입 후 첫 데이터 대기 중 파랑이 나타나는지 확인한다.
2. 두 센서가 정상이고 사람이 감지되면 초록, 레이더가 미감지를 보고하면 노랑인지 확인한다.
3. BH1750 오류 또는 레이더 데이터 만료·보정 상태에서 빨강이 약 0.5초 간격으로 켜지고 꺼지는지 확인한다.
4. 센서를 다시 정상화한 뒤 초록·노랑 표시로 돌아오는지 확인한다.
5. `.venv\Scripts\python.exe -m tools.sensor_cli status --port COM번호`의 `status_led`를 실제 색상과 비교한다.
6. 방 조명·모니터 밝기·센서 위치를 고정하고 초록·노랑·빨강 점멸 구간의 Lux를 기록한다.
7. menuconfig에서 LED 밝기를 0으로 바꾸고 다시 빌드·플래시한 뒤 같은 조건의 Lux와 비교한다.
8. LED 색이나 점멸에 따라 조도가 반복적으로 변하면 칸막이·위치·밝기를 조정하고 다시 비교한다.

센서 배선을 변경할 때는 USB와 외부 전원을 먼저 분리한다.<br>
초록·노랑 색상이 뒤바뀌거나 일부 색이 켜지지 않으면 실물 LED 종류·GPIO·전원과 요청값을 확인한다.<br>
센서가 이미 데이터를 보고하면 파랑 구간은 짧을 수 있으며, 3초 내내 파랑으로 유지하는 동작은 아니다.<br>
LED의 정상 표시만으로 Windows 연결이나 실제 모니터 제어 성공을 판정하지 않는다.
