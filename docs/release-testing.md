# 배포와 검증 안내

## 설치·자동 검사

저장소 루트에서 PowerShell 명령을 실행한다.<br>
Python 3.12 이상이 설치된 Windows 11에서 고정 버전 의존성을 설치한다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
powershell -ExecutionPolicy Bypass -File scripts\smoke_test.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_simulation.ps1
```

pytest와 smoke는 실제 모니터·USB를 제어하지 않는다.<br>
시뮬레이션에서는 Lux·감지 상태·센서 오류를 조작하고 밝기 요청·상태·카운트다운을 확인한다.<br>
펌웨어의 C 파서는 `scripts\test_firmware.ps1`, 기본·PSRAM 빌드는 `scripts\build_firmware.ps1`로 검사한다.<br>
배선·플래시·10분 수신은 [펌웨어 시험 안내](firmware-testing.md)를 따른다.

## EXE 생성과 검사

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1
powershell -ExecutionPolicy Bypass -File scripts\check_exe.ps1
```

배포 결과는 `.local\windows-dist\LumaSense` 폴더에 생성된다.<br>
빌드 중에는 Windows System32를 PATH 앞에 두어 다른 개발 도구의 ICU DLL이 수집되는 것을 방지한다.<br>
검사 도구는 EXE의 화면 생성·PNG 저장·정상 종료와 독립 복귀 도우미 두 개를 시뮬레이션으로 실행한다.<br>
실제 전원 API와 모니터 밝기는 변경하지 않는다.<br>
성공 보고서에는 EXE SHA-256과 검사항목이 기록된다.

검사 출력에 표시된 report.json 경로를 다음 명령에 넣는다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\package_windows.ps1 -CheckReport '.local\exe-check\실행별폴더\report.json'
```

패키지 도구는 검사한 EXE와 현재 EXE의 해시가 같은지 확인한다.<br>
실행 폴더·가이드·외부 구성요소 고지·검사 결과·파일별 해시를 고유 배포 폴더와 ZIP으로 만든다.<br>
ZIP 무결성과 모든 manifest 파일의 SHA-256을 다시 확인한다.<br>
파일을 수정한 뒤에는 빌드·검사·패키지를 다시 생성한다.<br>
서명·설치 프로그램을 사용하지 않는 폴더 실행 방식이다.

## 장시간 모델 검사

```powershell
powershell -ExecutionPolicy Bypass -File scripts\soak_test.ps1 -Hours 24 -Step .2
```

이 검사는 24시간 분량의 가상 시각을 빠르게 진행하는 제어 모델 시험이다.<br>
조도 변화·정지 착석·부재·센서 오류·수동 밝기를 반복하고 요청 조건·복귀 횟수·Python 할당량을 검사한다.<br>
실제 Qt 프로그램이 24시간 실행되거나 실물 센서가 동작했다는 뜻은 아니다.

## 실제 시간의 GUI 자원 검사

```powershell
# EXE를 60초 동안 실행하고 CPU·메모리를 기록한다.
powershell -ExecutionPolicy Bypass -File scripts\profile_windows.ps1 --seconds 60
# 같은 시뮬레이션 GUI를 실제 24시간 실행한다.
powershell -ExecutionPolicy Bypass -File scripts\profile_windows.ps1 --seconds 86400
```

도구는 별도 설정으로 EXE를 실행하고 자동 밝기·자동 절전을 활성화한 가상 정지 착석 데이터를 공급한다.<br>
Windows API로 해당 EXE 프로세스의 CPU 시간과 작업 집합 메모리를 1초마다 읽는다.<br>
평균 CPU는 코어 하나의 100%를 기준으로 계산하며 전체 시스템 CPU 비율과 구분한다.<br>
요청한 시간이 지나면 프로그램이 정상 종료하며 조기 종료·예외·실제 Twinkle 호출을 실패로 처리한다.<br>
결과는 `.local\resource-check` 아래 고유 폴더의 report.json·resources.jsonl·실행 로그에 저장된다.<br>
24시간 시뮬레이션은 장시간 GUI 실행 검사이며 실물 운용 시험과 구분한다.

## 실물 통합 시험 순서

1. 자동 제어를 끈 상태에서 펌웨어를 기록하고 정상 센서 데이터를 10분 이상 수신한다.
2. GUI를 연결해 조도와 움직임·정지 착석·거리 표시가 실제 상황과 맞는지 확인한다.
3. USB 분리·재연결 후 같은 프로그램에서 복구되는지 확인한다.
4. 수동 밝기와 두 API의 개별 절전·복귀 시험 결과를 기록한다.
5. 자동 밝기만 활성화하고 낮·저녁·어두운 환경에서 반응 시간·명령 간격·흔들림을 확인한다.
6. 수동 밝기 조절 후 자동 밝기가 중단되고 재개되는지 확인한다.
7. 자동 절전을 활성화하고 30분 정지 착석 중 화면이 꺼지지 않는지 확인한다.
8. 최근 입력 보호 시간이 지난 뒤 자리 이탈·5초 취소·재감지 복귀를 확인한다.
9. 화면이 꺼진 상태의 USB 분리와 프로그램 종료 시 복귀 시도를 확인한다.
10. Windows 잠금·로그온, HDR/SDR과 집 Philips 32M2N8900에서 같은 조건을 확인한다.
11. 실제 센서·모니터를 연결한 상태로 24시간 실행하고 로그·CPU·메모리와 화면 관찰을 기록한다.

관찰 기록에는 모니터·HDR/SDR·시작 시각·요청 방식·실제 화면 켜짐 시점·사용자 입력 개입을 포함한다.<br>
API 성공 반환과 화면의 실제 동작을 별도로 판정한다.<br>
구현 검사와 실물 관찰 결과는 [개발 기록](development-log.md)과 `docs/validation`에 보관한다.
