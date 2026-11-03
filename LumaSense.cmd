@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"

if not exist ".venv\Scripts\python.exe" (
    echo Python 가상환경이 없습니다.
    echo 먼저 다음 명령으로 설치하세요.
    echo powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m windows.main %*
set "LUMASENSE_EXIT_CODE=%ERRORLEVEL%"
if not "%LUMASENSE_EXIT_CODE%"=="0" (
    echo.
    echo LumaSense 실행이 종료됐습니다. 오류 코드: %LUMASENSE_EXIT_CODE%
    pause
)
exit /b %LUMASENSE_EXIT_CODE%
