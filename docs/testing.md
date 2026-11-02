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

### GUI에서 처음 시험하는 순서

1. 수정 전 프로그램이 실행 중이면 창 또는 트레이 메뉴의 종료를 누르고 `scripts/run_windows.ps1`로 다시 실행한다.
2. 창의 `03 화면 절전 · 복귀 시험`에서 1차 복귀 방식을 `SC_MONITORPOWER (-1)`, 절전 후 복귀를 5초, 추가 복귀 간격을 30초로 설정한다.
3. 마우스 이동 복귀 허용은 해제한 상태로 둔다.
4. 표시된 예정 시점이 1차 약 5초, 첫 추가 요청 약 35초인지 확인한다.
5. `5초 후 화면 절전 시험`을 누르고 카운트다운 중 취소 버튼을 눌러 화면이 꺼지지 않는지 확인한다.
6. 다시 시험 버튼을 누르고 두 화면이 꺼지는지 관찰한다.
7. 화면이 꺼지자마자 별도 시계로 측정을 시작하고 마우스·키보드를 조작하지 않은 채 각 화면이 켜지는 시점을 기록한다.
8. 약 35초의 추가 요청 전에 켜졌다면 해당 시험의 선택 API로 복귀한 것을 뒷받침한다.
9. 시험 버튼이 다시 활성화되면 화면 결과와 모니터별 복귀 시간, 입력 여부를 메모하고 관찰 결과 기록을 누른다.
10. 1차 복귀 방식을 `SetThreadExecutionState (일회성)`으로 바꿔 같은 설정으로 시험한다.

이 설정에서 시험 버튼은 처음 누른 시점에서 약 55초 후 다시 활성화된다.
추가 복귀 간격은 1차 API의 요청이 끝난 뒤 다음 API 요청까지 기다리는 시간이며 5~60초 범위에서 설정한다.
기본값은 30초이고 이전 설정 파일에 이 항목이 없으면 나머지 설정을 유지하면서 30초를 사용한다.
1차 복귀 5초와 추가 간격 30초의 조합에서는 절전 요청 직전 기준으로 약 5초와 약 35초에 각 API를 호출한다.
실제 화면이 꺼지고 켜지는 시각에는 모니터 자체 지연이 포함되므로 화면의 계획 시각은 근삿값이다.
추가 요청 이후에만 켜졌다면 먼저 보낸 API의 지연 효과와 추가 API의 효과를 해당 시험 하나로 확정하지 않는다.
첫 시험과 두 번째 시험에서 각각 어느 화면이 꺼졌고 몇 초쯤 다시 켜졌는지 기록한다.
카운트다운 취소는 화면 절전 명령 전까지만 가능하다.
이 설정에서 화면이 약 45초 후에도 돌아오지 않으면 실제 마우스나 키보드를 사용해 복귀하고 자동 복귀 실패와 수동 입력 여부를 기록한다.
모니터 선택 콤보는 밝기 제어의 대상이며 절전 시험은 선택값과 관계없이 두 화면 전체에 적용된다.

### 복귀 방식과 추가 요청

화면 절전은 전체 화면에 적용되며 PC의 프로그램은 계속 실행된다.
화면 절전 버튼을 누르면 5초 동안 카운트다운 취소 버튼을 사용할 수 있다.
트레이에서 시험을 시작하면 시험 창을 표시한다.
절전 명령 전에 별도 복귀 프로세스의 준비 응답을 확인하며 준비에 실패하면 절전을 요청하지 않는다.
복귀 프로세스는 GUI가 종료되더라도 남아서 복귀를 시도한다.

| 선택 방식 | 1차 요청 | 추가 요청 | 확인 항목 |
|---|---|---|---|
| `monitor_power` | SC_MONITORPOWER의 -1 | 설정한 간격 후 execution_state | 추가 요청 전에 켜지는지 |
| `execution_state` | ES_DISPLAY_REQUIRED 일회성 호출 | 설정한 간격 후 monitor_power | 추가 요청 전에 켜지는지 |
| `mouse_move` | SendInput 상대 +1/-1 이동 | 설정한 간격마다 monitor_power, execution_state | 입력 이동 허용 여부와 실제 복귀 |

마우스 이동을 허용하면 다른 방식의 마지막 추가 요청에도 마우스 이동을 사용한다.
클릭이나 키 입력은 생성하지 않지만 포인터 이동은 실행 중인 프로그램에 영향을 줄 수 있다.
마우스 방식은 GUI 체크박스나 CLI의 `--allow-mouse`로 허용한다.

```powershell
# 각 명령을 하나씩 실행하고 실제 꺼짐과 켜짐 시점을 확인한다.
powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1 --sleep-test --method monitor_power --seconds 5 --fallback-seconds 30
powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1 --sleep-test --method execution_state --seconds 5 --fallback-seconds 30
powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1 --sleep-test --method mouse_move --allow-mouse --seconds 5 --fallback-seconds 30
# 절전 없이 해당 복귀 API만 호출
powershell -ExecutionPolicy Bypass -File scripts\diagnose.ps1 --wake-only --method monitor_power
```

CLI 카운트다운은 Ctrl+C로 취소한다.
1차·추가 요청은 로그에서 `stage=primary`, `stage=fallback`으로 구분한다.
`wake_request_started`는 API를 호출하기 직전, `wake_attempt`는 반환 결과를 기록한다.
`watchdog_ready`와 `recovery_armed`는 1차 지연·추가 간격과 첫 추가 요청 예정 시점을 기록한다.
자동으로 실제 화면 상태를 판정할 수 없으므로 추가 요청은 1차 성공 여부와 무관하게 실행된다.
시험 중 다른 입력이 발생하면 화면이 먼저 깨어날 수 있으므로 입력 여부도 관찰 기록에 남긴다.

채팅 질문·메시지·앱 알림도 화면 복귀에 영향을 줄 수 있으므로 관찰 구간에는 보내지 않는다.<br>
질문으로 결과를 받을 때는 첫 복귀 요청 후 충분히 기다리고, 질문 알림이 나타나기 전에 화면이 켜졌는지 구분해서 기록한다.<br>
알림 전에 꺼져 있었고 알림 뒤 켜졌다면 선택한 복귀 API의 성공으로 처리하지 않는다.

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

## 실물 검증 상태

`phase1-validation.json`의 대상 모니터 관찰 항목을 채우고 `scripts/check_phase1.ps1`을 실행한다.
밝기 세 단계와 절전 성공, 한 가지 이상의 복귀 성공, 관찰자와 관찰 시각을 모두 요구한다.
실패한 복귀 방식은 실패로 남긴다.
기본 명령은 대기 항목을 보고하고 종료 코드 0을 반환해 후속 구현을 차단하지 않는다.
`--require-physical` 옵션을 추가하면 미충족 항목이 있을 때 종료 코드 1을 반환한다.
펌웨어와 후속 프로그램 구현·빌드·자동 테스트는 실물 검증 전에 수행할 수 있다.
