@echo off

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
set "PYTHON_ARGS="
if exist "%PYTHON_EXE%" exit /b 0

where py >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3"
  exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_EXE=python"
  set "PYTHON_ARGS="
  exit /b 0
)

echo [ERROR] Python was not found.
echo Install Python 3.11 or newer, then run:
echo py -3 -m venv .venv
echo .\.venv\Scripts\python.exe -m pip install -r requirements.txt
exit /b 1
