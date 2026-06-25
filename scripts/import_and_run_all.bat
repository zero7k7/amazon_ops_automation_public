@echo off
setlocal
chcp 65001 >nul

set "PROJECT_DIR=%~dp0.."
pushd "%PROJECT_DIR%"

set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=%PROJECT_DIR%\.venv_mac\bin\python"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=C:\Users\Admin\venvs\amazon_ops_automation\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo ==========================================
echo Inbox Import + ALL Report Runner
echo Project: %PROJECT_DIR%
echo Python : %PYTHON_EXE%
echo ==========================================
echo.

echo [1/1] Running daily update with inbox import, ALL reports, and no-browser frontend cache checks...
"%PYTHON_EXE%" "scripts\run_daily_update.py"
if errorlevel 1 (
  echo.
  echo [ERROR] run_daily_update.py failed.
  popd
  pause
  exit /b 1
)

echo.
echo 报告已生成：
echo.
echo 1. 总览 Dashboard：
echo file:///%PROJECT_DIR:\=/%/data/output/dashboard.html
echo.
echo 2. 详细 HTML 报告：
echo file:///%PROJECT_DIR:\=/%/data/output/latest_recommendations.html
echo.
echo 3. Excel 报告：
"%PYTHON_EXE%" -c "import pathlib; out=pathlib.Path(r'%PROJECT_DIR%')/'data'/'output'; p=max(out.glob('amazon_ops_report_*.xlsx'), key=lambda x: x.stat().st_mtime, default=out/'amazon_ops_report_YYYY-MM-DD.xlsx'); print(p)"
echo.
echo 4. 导入日志：
echo %PROJECT_DIR%\data\output\import_manifest.xlsx

start "" "%PROJECT_DIR%\data\output\dashboard.html"

echo.
echo Done. Window will stay open.
popd
cmd /k
