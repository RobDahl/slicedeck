@echo off
REM Starts the pipeline and the local API/demo server in one window.
REM Configure the camera in .env first - see .env.example.

cd /d "%~dp0"

where slicedeck >NUL 2>&1
if errorlevel 1 (
    echo slicedeck is not installed. Run:
    echo     pip install -e ".[server]"
    pause
    exit /b 1
)

echo Starting Slicedeck on http://localhost:8080
slicedeck --serve
