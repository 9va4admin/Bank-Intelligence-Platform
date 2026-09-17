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
REM Uses its own venv (apps\indic_ocr\.venv) -- paddleocr/paddlepaddle/easyocr
REM pin protobuf<=3.20.2 and a numpy1-ABI opencv build that conflict with the
REM rest of ASTRA's shared environment (immudb-py needs protobuf>=4.25,
REM everything else needs numpy>=2). Never run this service on the shared
REM interpreter -- see apps/indic_ocr/main.py's torch-preload comment too.
if not exist "%~dp0apps\indic_ocr\main.py" (
    echo [WARN] apps\indic_ocr\main.py not found — skipping IndicOCR service.
) else if not exist "%~dp0apps\indic_ocr\.venv\Scripts\python.exe" (
    echo [ERROR] apps\indic_ocr\.venv not found. Create it first:
    echo   cd apps\indic_ocr ^&^& python -m venv .venv
    echo   .venv\Scripts\pip install -r ..\..\requirements.txt
    echo   .venv\Scripts\pip install paddlepaddle==2.6.2 paddleocr==2.7.3 easyocr
    echo   .venv\Scripts\pip install "numpy>=2" "opencv-python>=4.9" "opencv-contrib-python>=4.9" "opencv-python-headless>=4.9"
    pause
) else (
    start "ASTRA indic_ocr :8021" cmd /k "cd /d %~dp0apps\indic_ocr && .venv\Scripts\python.exe main.py"
)

echo.
echo Both services starting in separate windows.
echo sig_detector : http://localhost:8020/health/live
echo indic_ocr    : http://localhost:8021/health/live
echo.
echo You can close THIS window — the service windows will keep running.
timeout /t 4
