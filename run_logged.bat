@echo off
cd /d "%~dp0"
title Clinic EHR - keep this window open
echo.
echo   Checking libraries (first time may take a minute)...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
echo.
echo   Clinic EHR is running. KEEP THIS WINDOW OPEN (minimize it).
echo   Open in Chrome:  http://localhost:8000
echo   Close this window to stop the app.
echo.
start "" /min cmd /c "timeout /t 5 >nul & start http://localhost:8000"
".venv\Scripts\python.exe" -m uvicorn main:app --app-dir app --host 127.0.0.1 --port 8000 > "%~dp0server_log.txt" 2>&1
echo.
echo   The app stopped. Details are in server_log.txt
pause
