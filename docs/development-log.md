# 개발 기록

## 2026-11-02 · Phase 1 구현과 회사 초기 시험

Windows 11 Pro 빌드 26200, Python 3.12.2, PySide6 6.11.0에서 구현·시험했다.
프로젝트 구조와 밝기 백엔드는 `c506fac`, GUI·트레이와 전원 시험 기능은 `bdb7b63`으로 커밋하고 각 작업 직후 푸시했다.
재현 스크립트와 검증 기록을 마지막 작업 단위로 정리했다.

### 구현

- PySide6 GUI, 시스템 트레이, 중복 실행 방지와 JSON 설정 저장
- Twinkle Tray 경로·모니터 자동 탐색, 전체 ID 선택과 20/50/80% 수동 밝기 요청
- Windows 화면 절전, 5초 카운트다운과 취소
- SC_MONITORPOWER, SetThreadExecutionState, 선택적 SendInput 복귀
- 독립 프로세스의 예약 복귀와 추가 복귀 요청
- API 결과와 실제 화면 관찰을 분리한 시험 ID별 JSON Lines 로그
- 고정 의존성 설치, GUI 실행, 자동 테스트, 실제 장치 시험과 다음 단계 확인 스크립트

### 자동 검증

자동 테스트 24건이 통과했다.
CLI 오류·시간 초과, 모니터 목록 파싱, 대상 ID 검증, 밝기 복원, 설정 검증, 카운트다운 취소, 안전장치 준비 실패 시 절전 차단, 중복 명령 차단과 GUI 스레드 분리를 확인했다.
주 실행 프로세스를 즉시 종료해도 별도 프로세스가 모의 복귀 요청을 수행하는 통합 테스트도 통과했다.
GUI smoke 실행과 한글 렌더링을 확인했다.
GUI 작업 객체가 일찍 해제되어 완료 신호가 누락되던 오류를 수정하고 해당 동작을 테스트로 검증했다.
PowerShell 진단 출력의 한글 인코딩을 UTF-8로 지정했다.

### 실제 API 시험

사용자가 회사 주 모니터를 27B2H2, 집의 모니터를 Philips 32M2N8900으로 확인했다.
회사에서는 Q27U2G5R4-와 27B2H2 두 대가 검색됐다.
아래 시각은 한국 시간이며 원본 이벤트의 시각은 UTC이다.

| 시험 | 결과 | 물리 동작 판정 |
|---|---|---|
| 27B2H2 밝기 20/50/80% | CLI OK, Twinkle Tray 보고값 20/50/80% 일치 | 관찰 대기 |
| 기존 밝기 복원 | 24% 요청 후 보고값 24% 확인 | 관찰 대기 |
| 12:03:02 전체 화면 절전 요청 | SC_MONITORPOWER(2) 접수 | 실제 꺼짐 관찰 대기 |
| 12:03:12 monitor_power 1차 복귀 | API 접수, 12:03:17 execution_state 추가 요청 | 개별 복귀 성공 관찰 대기 |
| 12:03:47 전체 화면 절전 요청 | SC_MONITORPOWER(2) 접수 | 실제 꺼짐 관찰 대기 |
| 12:03:57 execution_state 1차 복귀 | API 접수, 12:04:02 monitor_power 추가 요청 | 개별 복귀 성공 관찰 대기 |
| 마우스 이동 복귀 | 구현 및 모의 테스트 | 실제 장치 시험 미수행 |
| Philips 32M2N8900, HDR/SDR 비교 | 집에서 별도 시험 필요 | 미검증 |

밝기 시험 ID는 `8da1fd2e14664f63a2dc0c860e59c842`이다.
monitor_power 1차 복귀 시험 ID는 `35c86cc8923d46079d4bc889dd097843`, execution_state 1차 복귀 시험 ID는 `7936ccb1ea2142659d2826f84498946a`이다.
원본 실행 로그는 `%LOCALAPPDATA%\SmartMonitorController`에 있고 필요한 시험 이벤트를 [회사 시험 기록](validation/office-2026-11-02.json)에 보관했다.
API 접수와 Twinkle Tray 보고값만으로 실제 화면의 밝기·절전·복귀가 성공했다고 판정하지 않았다.

### 단계 판정

Phase 1의 프로그램 구현과 자동 테스트를 마쳤으며 실제 화면 관찰 결과를 기다린다.
최종 대상 Philips의 실기 기준은 `phase1-validation.json`에 미검증 상태로 남겼다.
`scripts/check_phase1.ps1`은 현재 종료 코드 1과 미충족 항목을 출력한다.
Phase 2 펌웨어와 GPIO 배정, ESP-IDF 빌드·플래시는 수행하지 않았다.

### 구현 참고 자료

- [Twinkle Tray 공식 CLI 설명](https://github.com/xanderfrangos/twinkle-tray#command-line-arguments)
- [Twinkle Tray CLI 출력 구현](https://github.com/xanderfrangos/twinkle-tray/blob/master/src/Utils.js)
- [Microsoft WM_SYSCOMMAND](https://learn.microsoft.com/en-us/windows/win32/menurc/wm-syscommand)
- [Microsoft SetThreadExecutionState](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate)
- [Microsoft SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)

2026-11-02 확인 시점의 공식 CLI 동작을 참고했다.
Twinkle Tray 버전에 따라 출력 형식이 달라지면 원본 로그를 기준으로 파서를 검토한다.
