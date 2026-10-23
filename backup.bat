@echo off
setlocal
:: backup.bat -- one-click PostgreSQL backup for Windows hosts.
:: Saves backups\backup_YYYY-MM-DD_HHmmss.sql . Copy that folder off-machine regularly.
cd /d "%~dp0"
if not exist backups mkdir backups

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmmss"') do set STAMP=%%I
set OUT=backups\backup_%STAMP%.sql

echo Backing up the database to %OUT% ...
docker compose -f docker-compose.prod.yml exec -T postgres pg_dump -U attendance_user -d attendance --no-password --clean --if-exists > "%OUT%"
if errorlevel 1 ( echo [ERROR] Backup failed. Is the system running (start-attendance.bat)? & del "%OUT%" 2>nul & pause & exit /b 1 )

echo [OK] Backup saved: %OUT%
echo Tip: copy the whole "backups" folder to an external drive or network share.
pause
