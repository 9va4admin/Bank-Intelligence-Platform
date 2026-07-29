@echo off
REM ASTRA Local Services Launcher
REM Starts sig_detector (port 8020) and indic_ocr (port 8021) in background.
REM Run this once after boot — or add it to Windows Task Scheduler / Startup folder.
REM
REM Usage:  double-click start-local-services.bat
REM         or:  start-local-services.bat
REM
REM To stop:  close the two terminal windows it opens, or kill python on ports 8020/8021.

echo Starting ASTRA local services...

REM ── sig_detector on port 8020 ──────────────────────────────────────────────
if not exist "%~dp0apps\sig_detector\main.py" (
    echo [ERROR] apps\sig_detector\main.py not found. Run from repo root.
    pause
    exit /b 1
)
start "ASTRA sig_detector :8020" cmd /k "cd /d %~dp0apps\sig_detector && python main.py"

REM ── indic_ocr on port 8021 ─────────────────────────────────────────────────
if not exist "%~dp0apps\indic_ocr\main.py" (
    echo [WARN] apps\indic_ocr\main.py not found — skipping IndicOCR service.
) else (
    start "ASTRA indic_ocr :8021" cmd /k "cd /d %~dp0apps\indic_ocr && python main.py"
)

echo.
echo Both services starting in separate windows.
echo sig_detector : http://localhost:8020/health/live
echo indic_ocr    : http://localhost:8021/health/live
echo.
echo You can close THIS window — the service windows will keep running.
timeout /t 4
