# Smart Monitor Controller

Windows 11에서 ESP32-S3의 BH1750 조도와 LD2412 감지 또는 VL53L1X 거리 데이터를 받아 밝기와 자리 비움에 따른 화면 절전을 제어하는 Python 3.12 / PySide6 프로그램이다.<br>
Twinkle Tray와 Windows API로 모니터를 제어하고 USB·Wi-Fi 연결, 자동 제어·수동 진단·시뮬레이션을 제공한다.

## 설치와 테스트

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1
```

Twinkle Tray는 별도 설치하고 실행한다.<br>
실행 경로는 기본 설치 폴더, Microsoft Store 실행 별칭, PATH, 사용자가 지정한 경로에서 검색한다.<br>
설치 프로그램은 [공식 Twinkle Tray 저장소](https://github.com/xanderfrangos/twinkle-tray)에서 받는다.

## 실행과 진단

창에서 대상 모니터를 선택하고 밝기 시험 버튼을 누른다.<br>
창 닫기는 트레이로 숨기며 트레이 메뉴 또는 창의 종료 버튼으로 프로그램을 종료한다.<br>
트레이를 사용할 수 없는 환경에서는 창을 닫으면 종료한다.<br>
밝기 명령은 선택한 모니터에 적용되고 Windows 절전 명령은 연결된 화면 전체에 적용된다.

```powershell
# 실행 파일과 모니터 목록 조회
powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1
# 지정 모니터의 20/50/80% 시험 후 기존 보고 밝기로 복원
powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1 --brightness-sweep --monitor-name 27B2H2
# 5초 카운트다운 후 절전, 약 5초에 1차 요청, 약 35초에 추가 요청
powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1 --sleep-test --method monitor_power --seconds 5 --fallback-seconds 30
```

설정과 실행 로그는 `%LOCALAPPDATA%\SmartMonitorController`에 저장된다.<br>
`SMC_DATA_DIR` 환경 변수로 별도 경로를 지정할 수 있다.<br>
자세한 시험·복귀 절차는 [testing.md](docs/testing.md), 확인된 결과는 [개발 기록](docs/development-log.md)을 참고한다.<br>
센서 연결·밝기 곡선·자동 절전·레이더 설정·로그인 실행은 [사용 안내](docs/user-guide.md)를 따른다.

`사용자 프로필 · lux 구간별 밝기`에서 조도 기준마다 밝기를 지정하고 이름별로 저장·선택할 수 있다.<br>
계단형 그래프의 점을 드래그하거나 표를 편집하고 `밝기 설정 적용`으로 저장한다.

## 시뮬레이션과 배포

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_simulation.ps1
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
powershell -ExecutionPolicy Bypass -File scripts\check_exe.ps1
```

시뮬레이션은 가상 센서와 출력 백엔드로 동작하며 실제 USB·밝기·전원을 제어하지 않는다.<br>
EXE 폴더·ZIP 생성과 가속 모델·실제 시간 GUI 자원 검사는 [배포와 검증 안내](docs/release-testing.md)를 참고한다.

## 개발 단계

Phase 1 구현과 대상 모니터의 실기 검증은 [검증 상태](docs/phase1-validation.json)로 추적한다.<br>
아래 명령으로 실기 검증 대기 항목을 확인한다.<br>
실물 검증 대기 상태에서도 후속 펌웨어와 프로그램을 구현할 수 있다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_phase1.ps1
```

실물 검증을 필수 검사로 사용할 때만 `--require-physical` 옵션을 추가한다.<br>
Phase 2의 ESP-IDF 펌웨어 배선과 메모리 설정은 [하드웨어 확인 항목](docs/hardware.md)을 참고한다.<br>
USB 통신·자동 밝기·인체 상태 제어는 독립 모듈로 구성한다.<br>
구현·자동 검사와 실물 단계별 판정은 [검증 기록](docs/validation/implementation-2026-11-02.json)으로 구분한다.

## ESP32-S3 펌웨어

SuperMini와 VL53L1X의 확정 배선·빌드·거리 판정은 [SuperMini·ToF 안내](docs/supermini-tof.md)를 따른다.

SuperMini는 USB에서 공유기 접속 정보를 저장한 뒤 Wi-Fi TCP로 연결할 수 있다.<br>
앱의 시스템 / 센서 탭에서 Wi-Fi 설정과 장치 IP를 확인하고 대시보드에서 연결 방식을 선택한다.

[펌웨어 프로젝트](firmware/README.md)는 BH1750·LD2412 센서 수집과 양방향 USB 통신을 제공한다.<br>
MCN16R8 기준으로 기본·PSRAM 프로필을 빌드하고 [펌웨어 시험 안내](docs/firmware-testing.md)에 따라 플래시·센서 로그를 확인한다.<br>
GPIO 기본값은 배선 예시이며 실제 연결에 맞춰 변경한다.

## 구성

- `windows/core`: 밝기 백엔드, 설정, 진단, Windows 전원 API
- `windows/ui`: GUI와 시스템 트레이
- `windows/tests`: 실제 장치를 제어하지 않는 자동 테스트
- `scripts`: 설치, 실행, 테스트와 실기 시험
- `docs`: 사용법, 개발 기록과 Phase별 검증 결과
- `firmware`: ESP32-S3 센서 펌웨어와 native 파서 테스트
