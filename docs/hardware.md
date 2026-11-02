# 하드웨어 자료

원본 보드 회로도는 [HG-ESP32-S3-DevkitC-1-USB-C.pdf](reference/HG-ESP32-S3-DevkitC-1-USB-C.pdf)이며 센서 연결 전의 개발보드 회로이다.
개발 요구사항 원문은 [개발 계획서 v1](reference/development-plan-v1.md)에 보관한다.

회로도 1쪽의 U3 표기는 ESP32-S3-WROOM-1-N16R2이며 사용자가 실물 표기를 MCN16R8로 확인했다.
펌웨어는 16MB 플래시로 빌드하며 PSRAM 비활성 기본 프로필과 octal PSRAM 활성 프로필을 제공한다.
2쪽의 J1 ESP USB는 GPIO19/20에 연결되며 J3 USB는 CP2102에 연결된다.
USB Serial/JTAG용 GPIO19/20에는 센서를 배정하지 않는다.
회로도에 BH1750과 LD2412의 센서 배선은 포함되어 있지 않다.
아래 배선 예시는 GPIO를 menuconfig에서 변경할 수 있는 펌웨어 기본값이다.

| ESP32-S3 | 센서 연결 |
|---|---|
| GPIO8 | BH1750 SDA |
| GPIO9 | BH1750 SCL |
| 3V3 / GND | BH1750 전원과 접지 |
| GPIO16 RX | LD2412 TX |
| GPIO17 TX | LD2412 RX |
| 보드 5V / GND | LD2412의 +5V / GND |

실물 센서 모듈의 핀 이름을 기준으로 연결하며 커넥터의 물리적 핀 순서를 위 표에서 추정하지 않는다.
BH1750FVI IC의 동작 전원은 2.4~3.6V이므로 예시는 3.3V로 공급하고 I²C 풀업도 3.3V에 연결한다.
브레이크아웃 보드의 VIN 허용 범위와 풀업 배선은 해당 실물을 확인한다.
LD2412 제조사 V1.06 자료는 5V 또는 3.3V 전원 입력과 200mA 초과 공급 능력, 3.3V IO를 명시한다.
위 예시는 +5V 입력 하나를 사용하며 3V3 전원 입력과 동시에 연결하지 않는다.
BH1750의 ADDR에 따라 I²C 주소를 0x23 또는 0x5C로 설정한다.
USB용 GPIO19/20, 플래시·PSRAM용 GPIO26~37, 부팅 스트랩 GPIO0/3/45/46과 센서 핀 중복은 펌웨어가 거부한다.

참고 자료는 [HI-LINK LD2412 통신 프로토콜 V1.06](https://r0.hlktech.com/download/HLK-LD2412-24G/1/LD2412%20%E4%B8%B2%E5%8F%A3%E9%80%9A%E4%BF%A1%E5%8D%8F%E8%AE%AE%20V1.06%20241105.pdf) 4~5쪽과 [ROHM BH1750FVI Rev.D](https://core-electronics.com.au/attachments/uploads/BH1750FVI-datasheet.pdf)이다.

회사 주 모니터는 Q27U2G5R4-이며 보조 모니터는 27B2H2이다.
사용자가 처음 알려 준 주 모니터 정보를 이후 Q27U2G5R4-로 정정했다.
초기 자동 CLI 밝기 시험은 27B2H2에서 수행했다.
집의 최종 대상 모니터는 Philips 32M2N8900 OLED이다.
두 모니터의 밝기 제어와 화면 복귀 결과는 각각 기록한다.
