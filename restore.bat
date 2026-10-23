@echo off
setlocal
:: restore.bat -- restore the database from a backup .sql made by backup.bat.
:: WARNING: this OVERWRITES the current data with the backup.
cd /d "%~dp0"

if "%~1"=="" (
  echo Usage: restore.bat backups\backup_YYYY-MM-DD_HHmmss.sql
  echo.
  echo Available backups:
  dir /b backups\*.sql 2>nul
  pause
  exit /b 1
)
if not exist "%~1" ( echo [ERROR] File not found: %~1 & pause & exit /b 1 )

echo WARNING: this will OVERWRITE the current database with:
echo    %~1
set /p OK=Type YES to continue:
if /I not "%OK%"=="YES" ( echo Cancelled. & pause & exit /b 0 )

docker compose -f docker-compose.prod.yml exec -T postgres psql -U attendance_user -d attendance < "%~1"
if errorlevel 1 ( echo [ERROR] Restore failed. & pause & exit /b 1 )

echo [OK] Restore complete.
pause
