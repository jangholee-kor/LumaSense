# Windows 제어 시험

## 실행 환경

Windows 11, Python 3.12 이상, 실행 중인 Twinkle Tray를 사용한다.
`scripts/setup.ps1`은 저장소의 `.venv`에 고정된 패키지 버전을 설치한다.
경로에 공백이 있어도 PowerShell 스크립트는 자신의 위치를 기준으로 실행한다.
PowerShell에서 실행 정책 때문에 차단되면 README의 `-ExecutionPolicy Bypass -File` 형식으로 실행한다.

## 자동 테스트와 UI 렌더링

```powershell
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
$env:SMC_DATA_DIR = "$PWD\.local\smoke"
$env:QT_QPA_PLATFORM = 'offscreen'
powershell -ExecutionPolicy Bypass -File scripts\run_windows.ps1 --smoke-test --screenshot "$PWD\.local\ui.png"
Remove-Item Env:\QT_QPA_PLATFORM
Remove-Item Env:\SMC_DATA_DIR
```

자동 테스트는 CLI 오류·시간 초과, 잘못된 모니터 목록, 밝기 복원, 카운트다운 취소, 중복 절전 방지, GUI 스레드 분리와 설정 검증을 확인한다.
독립 복귀 프로세스 테스트는 모의 전원 API를 사용해 실행 주체가 종료된 후에도 복귀 작업이 수행되는지 확인한다.
자동 테스트와 smoke 실행은 실제 밝기·절전 명령을 보내지 않는다.

## 밝기 시험

1. Twinkle Tray를 실행하고 GUI의 자동 탐색 버튼으로 모니터를 검색한다.
2. 모니터 이름과 전체 ID를 확인하고 대상 한 대를 선택한다.
3. 20%, 50%, 80%를 각각 적용하고 실제 밝기 변화와 Twinkle Tray의 상태를 비교한다.
4. 각 시험이 끝나면 관찰 결과와 HDR/SDR 상태를 입력하고 기록 버튼을 누른다.
5. 시험 전 밝기로 복원한다.

CLI의 `--brightness-sweep`은 각 단계에서 2초 기다리고 `finally`에서 기존 보고값으로 복원을 시도한다.
장치 분리나 프로그램 강제 종료 때문에 복원이 실패하면 Twinkle Tray에서 수동으로 복원한다.
Twinkle Tray의 밝기 보고값에는 내부 캐시나 보정 설정이 반영될 수 있으므로 물리 휘도 측정으로 취급하지 않는다.
GUI에서 경로를 바꾼 뒤에는 목록을 다시 검색해 새 실행 파일을 적용한다.
Store 별칭이 응답하지 않으면 실행 파일을 직접 지정하고 원본 CLI 로그를 확인한다.

## 절전과 복귀 방식 비교

화면 절전은 전체 화면에 적용되며 PC의 프로그램은 계속 실행된다.
화면 절전 버튼을 누르면 5초 동안 카운트다운 취소 버튼을 사용할 수 있다.
트레이에서 시험을 시작하면 시험 창을 표시한다.
절전 명령 전에 별도 복귀 프로세스의 준비 응답을 확인하며 준비에 실패하면 절전을 요청하지 않는다.
복귀 프로세스는 GUI가 종료되더라도 남아서 복귀를 시도한다.

| 선택 방식 | 1차 요청 | 추가 요청 | 확인 항목 |
|---|---|---|---|
| `monitor_power` | SC_MONITORPOWER의 -1 | 5초 후 execution_state | 1차 요청 시점에 켜지는지 |
| `execution_state` | ES_DISPLAY_REQUIRED 일회성 호출 | 5초 후 monitor_power | 추가 요청 전에 켜지는지 |
| `mouse_move` | SendInput 상대 +1/-1 이동 | 5초 간격으로 monitor_power, execution_state | 입력 이동 허용 여부와 실제 복귀 |

마우스 이동을 허용하면 다른 방식의 마지막 추가 요청에도 마우스 이동을 사용한다.
클릭이나 키 입력은 생성하지 않지만 포인터 이동은 실행 중인 프로그램에 영향을 줄 수 있다.
마우스 방식은 GUI 체크박스나 CLI의 `--allow-mouse`로 허용한다.

```powershell
# 각 명령을 하나씩 실행하고 실제 꺼짐과 켜짐 시점을 확인한다.
powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1 --sleep-test --method monitor_power
powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1 --sleep-test --method execution_state
powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1 --sleep-test --method mouse_move --allow-mouse
# 절전 없이 해당 복귀 API만 호출
powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1 --wake-only --method monitor_power
```

CLI 카운트다운은 Ctrl+C로 취소한다.
1차·추가 요청은 로그에서 `stage=primary`, `stage=fallback`으로 구분한다.
자동으로 실제 화면 상태를 판정할 수 없으므로 추가 요청은 1차 성공 여부와 무관하게 실행된다.
시험 중 다른 입력이 발생하면 화면이 먼저 깨어날 수 있으므로 입력 여부도 관찰 기록에 남긴다.
자동 복귀가 되지 않으면 실제 마우스나 키보드를 사용해 복귀하고 실패로 기록한다.
로그 시각과 눈으로 본 켜짐 시각을 비교할 수 없으면 개별 방식의 성공으로 판정하지 않는다.

## 결과 기록과 오류 진단

일반 진단은 `app.log`와 보관본 3개, 구조화된 이벤트는 UTC 날짜별 `events-YYYY-MM-DD.jsonl`에 저장한다.
GUI의 로그 폴더 열기 버튼으로 파일 위치를 확인한다.
CLI 원문 stdout·stderr, 종료 코드, 예외, 시험 ID, 복귀 방식과 사용자 관찰 결과를 저장한다.
실제 화면 관찰 전에는 `physical_result=unverified`로 기록한다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1 --record pass --test-id '실행 시 출력된 ID' --notes '27B2H2 SDR, 밝기 변화 확인'
```

API가 오류 없이 반환해도 모니터·그래픽 드라이버·연결 방식에 따라 실제 복귀가 실패할 수 있다.
HDR와 SDR, Windows 잠금 상태, 모니터 재연결은 별도 환경으로 기록한다.
연결 오류가 나면 목록을 새로고침하고 전체 ID를 다시 선택한다.
화면을 제어하는 다른 프로그램이 같은 설정을 변경하는지도 확인한다.

## Phase 2 진입

`phase1-validation.json`의 대상 모니터 관찰 항목을 채우고 `scripts/check_phase1.ps1`을 실행한다.
밝기 세 단계와 절전 성공, 한 가지 이상의 복귀 성공, 관찰자와 관찰 시각을 모두 요구한다.
실패한 복귀 방식은 실패로 남긴다.
센서나 ESP-IDF 펌웨어는 이 단계 이후에 구현한다.
