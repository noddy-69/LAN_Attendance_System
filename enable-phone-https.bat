@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo   Enable HTTPS for phone selfie check-in   (one time only)
echo ============================================================
echo.
echo This lets staff use the phone camera for selfie check-in,
echo with NOTHING to install on their phones. After this one-time
echo step it stays working by itself (even after reboots).
echo.
echo You need a FREE DuckDNS account first:
echo    1) Go to  https://www.duckdns.org  and sign in (Google/GitHub).
echo    2) Create a subdomain (for example: youroffice).
echo    3) Copy your "token" shown at the top of the page.
echo.
set /p OPEN=Open the DuckDNS website now? (Y/N):
if /I "%OPEN%"=="Y" start "" https://www.duckdns.org
echo.
set /p SUB=DuckDNS subdomain (e.g. youroffice):
if "%SUB%"=="" echo [cancelled] no subdomain entered. & pause & exit /b 1
set /p TOK=DuckDNS token:
if "%TOK%"=="" echo [cancelled] no token entered. & pause & exit /b 1
set /p EML=Email for renewal notices (optional, press Enter to skip):
echo.
echo Setting up HTTPS - this can take a minute...
echo.
if "%EML%"=="" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-https.ps1" -Domain "%SUB%" -DuckToken "%TOK%"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-https.ps1" -Domain "%SUB%" -DuckToken "%TOK%" -Email "%EML%"
)
echo.
if errorlevel 1 (
  echo [FAILED] HTTPS setup did not complete - see the error above.
  echo Nothing permanent was changed. Fix the issue and run this again.
) else (
  echo [SUCCESS] HTTPS is ready and keeps itself current automatically.
  echo On the office Wi-Fi, open  https://%SUB%.duckdns.org  on phones.
)
pause
