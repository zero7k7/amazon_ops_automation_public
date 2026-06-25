@echo off
setlocal

cd /d "%~dp0.."
set "PROJECT_ROOT=%CD%"

set "PYTHON_EXE="
set "PYTHON_ARGS="

if exist "C:\Users\Admin\python-sdk\python3.13.2\python.exe" (
    set "PYTHON_EXE=C:\Users\Admin\python-sdk\python3.13.2\python.exe"
) else (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_EXE=python"
)

if not defined PYTHON_EXE (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3"
    )
)

if not defined PYTHON_EXE (
    echo [ERROR] Python was not found.
    echo Please install Python or check:
    echo C:\Users\Admin\python-sdk\python3.13.2\python.exe
    pause
    exit /b 1
)

echo ==========================================
echo UK Daily Report Runner
echo Project: %PROJECT_ROOT%
echo Python : %PYTHON_EXE% %PYTHON_ARGS%
echo ==========================================
echo.
echo [1/2] Running main.py --marketplace UK ...

call "%PYTHON_EXE%" %PYTHON_ARGS% main.py --marketplace UK
if errorlevel 1 (
    echo.
    echo [ERROR] main.py failed. Please check the log above.
    pause
    exit /b 1
)

echo.
echo [2/2] Reading summary ...
call "%PYTHON_EXE%" %PYTHON_ARGS% -c "import json; from pathlib import Path; from src.analyze_rules import build_report_view; root=Path(r'%PROJECT_ROOT%'); payload=json.loads((root/'data/output/latest_analysis.json').read_text(encoding='utf-8')); view=build_report_view(payload); excel=max((root/'data/output').glob('amazon_ops_report_*.xlsx'), key=lambda p: p.stat().st_mtime); print('latest_recommendations.html:'); print(root/'data/output/latest_recommendations.html'); print(); print('latest_recommendations.md:'); print(root/'data/output/latest_recommendations.md'); print(); print('Excel report:'); print(excel); print(); print('Data quality pass: {}'.format('YES' if view['quality_pass'] else 'NO')); print('Today must-fix count: {}'.format(len(view['today_rows']))); print('Negative keyword count: {}'.format(len(view['negative_rows']))); print('Scale-up count: {}'.format(len(view['scale_rows'])))"
if errorlevel 1 (
    echo.
    echo [ERROR] Report files were generated, but summary read failed.
    echo Please check the files in data\output manually.
    pause
    exit /b 1
)

echo.
echo Opening latest_recommendations.html ...
start "" "%PROJECT_ROOT%\data\output\latest_recommendations.html"
echo Opening latest Excel report ...
for /f "delims=" %%F in ('dir /b /o-d "%PROJECT_ROOT%\data\output\amazon_ops_report_*.xlsx"') do (
    start "" "%PROJECT_ROOT%\data\output\%%F"
    goto :after_excel_open
)
:after_excel_open
echo Opening output folder ...
start "" "%PROJECT_ROOT%\data\output"
echo.
echo Done.
exit /b 0
