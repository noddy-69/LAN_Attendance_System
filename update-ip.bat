@echo off
setlocal
rem ==========================================================================
rem  update-ip.bat  -  Point the DuckDNS domain at THIS PC's current IP.
rem
rem  Run this if a phone cannot reach the portal after the Wi-Fi or IP changed
rem  and you don't want to wait for the automatic updater. It re-points the
rem  domain to whatever address this PC has right now, keeps the webcam in sync,
rem  and renews the HTTPS certificate if it is close to expiry.
rem ==========================================================================
cd /d "%~dp0"

if not exist "%~dp0setup-https.ps1" (
  echo [ERROR] setup-https.ps1 was not found next to this file.
  echo         Run this from the delivery ^(dist^) folder.
  pause
  exit /b 1
)

echo Updating the domain to this PC's current IP address...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-https.ps1" -Sync
echo.
echo Done. If a phone still cannot connect, toggle its Wi-Fi / Airplane mode and retry.
pause
