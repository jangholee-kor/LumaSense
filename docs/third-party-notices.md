# 배포 파일의 외부 구성요소

LumaSense의 Windows 배포 폴더에는 Python 3.12, PySide6·Qt 6.11.0, shiboken6, pyserial 3.5와 PyInstaller 부트로더가 포함된다.<br>
Twinkle Tray와 ESP-IDF는 Windows ZIP에 포함하지 않고 별도로 설치한다.<br>
설치된 Python 패키지의 라이선스 파일은 ZIP의 `licenses` 폴더에 복사한다.<br>
Qt DLL은 `_internal` 아래의 별도 파일로 포함하며 폴더 전체를 함께 보관한다.<br>
외부 구성요소의 원문·소스·배포 조건은 각 프로젝트에서 확인한다.

| 구성요소 | 원문과 소스 |
|---|---|
| Python | [라이선스](https://docs.python.org/3/license.html), [소스](https://github.com/python/cpython) |
| PySide6·shiboken6 | [라이선스 안내](https://doc.qt.io/qtforpython-6/licenses.html), [소스](https://code.qt.io/pyside/pyside-setup.git) |
| Qt | [라이선스 안내](https://doc.qt.io/qt-6/licensing.html), [소스](https://code.qt.io/qt/) |
| pyserial | [BSD 라이선스와 소스](https://github.com/pyserial/pyserial) |
| PyInstaller | [부트로더 예외를 포함한 라이선스](https://pyinstaller.org/en/stable/license.html), [소스](https://github.com/pyinstaller/pyinstaller) |
