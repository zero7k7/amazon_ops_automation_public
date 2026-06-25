@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"
call scripts\windows_python.bat
if errorlevel 1 (
  pause
  exit /b 1
)

echo Amazon Ops Automation
echo Starting window-scoped daily report session...
"%PYTHON_EXE%" %PYTHON_ARGS% scripts\run_report_window.py --workflow daily
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo.
  echo [ERROR] daily report session failed with exit code %EXIT_CODE%.
  pause
)
exit /b %EXIT_CODE%
