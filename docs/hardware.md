# 하드웨어 자료

원본 보드 회로도는 [HG-ESP32-S3-DevkitC-1-USB-C.pdf](reference/HG-ESP32-S3-DevkitC-1-USB-C.pdf)이며 센서 연결 전의 개발보드 회로이다.
개발 요구사항 원문은 [개발 계획서 v1](reference/development-plan-v1.md)에 보관한다.

회로도 1쪽의 U3 표기는 ESP32-S3-WROOM-1-N16R2이며 계획서의 N16R8과 다르다.
Phase 2에서 실물 모듈 인쇄와 플래시·PSRAM 구성을 확인하고 ESP-IDF 설정을 정한다.
2쪽의 J1 ESP USB는 GPIO19/20에 연결되며 J3 USB는 CP2102에 연결된다.
USB Serial/JTAG용 GPIO19/20에는 센서를 배정하지 않는다.
회로도에 BH1750과 LD2412의 센서 배선은 포함되어 있지 않다.
센서 전원, UART 신호 전압, LD2412 핀 순서와 프로토콜은 제조사 자료 확인 후 확정한다.

초기 회사 시험 모니터는 27B2H2이며 사용자가 주 모니터로 확인했다.
집의 최종 대상 모니터는 Philips 32M2N8900 OLED이다.
두 모니터의 밝기 제어와 화면 복귀 결과는 각각 기록한다.
