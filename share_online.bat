@echo off
cd /d "%~dp0"
title Clinic EHR - ONLINE (temporary link)
echo.
echo   Clinic EHR - share a TEMPORARY online link from this PC
echo   - Uses its own EMPTY database (folder data_shared), not your local test data.
echo   - Use SAMPLE patients only. The link works only while this PC and this window stay on.
echo   - The link changes every time you run this file.
echo.
:askpw
set "ADMINPW="
set /p "ADMINPW=Choose an ADMIN password for the online copy (12+ characters, type it here): "
if not defined ADMINPW goto askpw
echo %ADMINPW%| findstr /r "^............" >nul || (echo Too short - use at least 12 characters. & goto askpw)
set "MAILFLAG="
set "DOCMAIL="
set /p "DOCMAIL=Optional: the doctor's e-mail (only this address can open the link; Enter to skip): "
if defined DOCMAIL set MAILFLAG=--allowed-mail %DOCMAIL%

echo.
echo   Checking libraries...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if not exist cloudflared.exe (
  echo   Downloading cloudflared from github.com/cloudflare/cloudflared ^(about 40 MB, once^)...
  curl.exe -L --fail -o cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
  if errorlevel 1 (echo Download failed. Check your internet and try again. & del cloudflared.exe 2>nul & pause & exit /b 1)
)
set EHR_ENV=production
set "EHR_DATA_DIR=%~dp0data_shared"
set "EHR_ADMIN_PASSWORD=%ADMINPW%"
start "Clinic EHR server (keep open)" ".venv\Scripts\python.exe" -m uvicorn main:app --app-dir app --host 127.0.0.1 --port 8001
timeout /t 8 >nul
echo.
echo   Look below for a line like:  https://something-random.trycloudflare.com
echo   Send THAT link to the doctor. Sign in as  admin  with the password you just chose.
echo   Then use  Account  to create the doctor's own user.
echo   Close this window to stop sharing.
echo.
cloudflared.exe tunnel --url http://localhost:8001 %MAILFLAG%
echo.
pause
