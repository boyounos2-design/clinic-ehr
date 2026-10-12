@echo off
rem keep this window open no matter what happens, so any error stays readable
if not defined CLINIC_INNER (
  set CLINIC_INNER=1
  cmd /k ""%~f0""
  exit /b
)
setlocal
cd /d "%~dp0"
title Clinic EHR
echo.
echo   Clinic EHR  -  starting...
echo   Folder: %CD%
echo.

set PY=
py -3 -c "import sys" >nul 2>nul && set PY=py -3
if "%PY%"=="" python -c "import sys" >nul 2>nul && set PY=python
if "%PY%"=="" for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do call :try "%%~D\python.exe"
if "%PY%"=="" for /d %%D in ("%ProgramFiles%\Python3*") do call :try "%%~D\python.exe"
if "%PY%"=="" for /d %%D in ("C:\Python3*") do call :try "%%~D\python.exe"
if "%PY%"=="" (
  echo   Python was not found. (A Microsoft Store shortcut named "python" does not count.)
  echo   Install Python 3.11 or newer from https://www.python.org/downloads/windows/
  echo   and TICK "Add python.exe to PATH" on the first installer screen. Then run start.bat again.
  goto :end
)
echo   Using Python: %PY%
%PY% --version

if not exist ".venv\Scripts\python.exe" (
  echo   First run: setting up. This takes 1-3 minutes...
  %PY% -m venv .venv
  if errorlevel 1 goto :fail
)
if not exist ".venv\.installed2" (
  echo   Installing libraries ^(needs internet^)...
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 goto :fail
  echo ok> ".venv\.installed2"
)

start "" /min cmd /c "timeout /t 5 >nul & start http://localhost:8000"
echo.
echo   Open:  http://localhost:8000     (a browser tab opens automatically)
echo   Keep this window open while you use the app. Close it to stop the app.
echo.
".venv\Scripts\python.exe" -m uvicorn main:app --app-dir app --host 127.0.0.1 --port 8000
echo.
echo   The app stopped. If this is an error, read the message above.
goto :end

:fail
echo.
echo   Setup failed - read the message above. Check your internet connection and try again.
goto :end

:try
if not "%PY%"=="" goto :eof
if not exist %1 goto :eof
%1 -c "import sys" >nul 2>nul && set PY=%1
goto :eof

:end
echo.
pause
