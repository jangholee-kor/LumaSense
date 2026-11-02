# Smart Monitor Controller

Windows 11에서 Twinkle Tray와 Windows API로 모니터를 제어하는 Python 3.12 / PySide6 프로그램이다.

## 설치와 테스트

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
powershell -ExecutionPolicy Bypass -File scripts\test.ps1
```

Twinkle Tray는 별도 설치하고 실행한다.
실행 경로는 기본 설치 폴더, Microsoft Store 실행 별칭, PATH, 사용자가 지정한 경로에서 검색한다.

## 구성

- `windows/core`: 밝기 백엔드, 설정, 진단, Windows 전원 API
- `windows/ui`: GUI와 시스템 트레이
- `windows/tests`: 실제 장치를 제어하지 않는 자동 테스트
- `scripts`: 설치, 실행, 테스트와 실기 시험
- `docs`: 사용법, 개발 기록과 Phase별 검증 결과
- `firmware`: Phase 2 진입 전 하드웨어 검토 자료
