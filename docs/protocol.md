# 다음 단계의 통신 경계

센서 통신은 Phase 3에서 SerialManager와 SensorManager에 구현한다.
펌웨어는 개행으로 구분한 JSON Lines를 전송하며 프로토콜 버전과 순번을 포함한다.
계획서의 필드는 제조사 LD2412 프로토콜에서 실제로 제공하는 데이터와 대조한 뒤 확정한다.
Phase 1의 GUI와 밝기 백엔드는 센서 연결 없이 동작한다.
자동 밝기와 인체 감지는 별도 제어 모듈에서 BrightnessBackend와 DisplayController를 호출하도록 연결한다.
센서 연결 오류를 인체 부재로 취급하지 않는다.
