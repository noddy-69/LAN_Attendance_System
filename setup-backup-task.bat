@echo off
:: ═══════════════════════════════════════════════════════════════════════════
:: setup-backup-task.bat — Schedule daily automated backup (Windows)
::
:: Creates a Windows Task Scheduler entry that runs backup.sh at 02:00 AM
:: every night via Git Bash. Requires Git for Windows to be installed.
::
:: Run as Administrator:
::   Right-click setup-backup-task.bat → Run as administrator
:: ═══════════════════════════════════════════════════════════════════════════

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo ERROR: Please run this script as Administrator.
    echo Right-click the file and select "Run as administrator".
    pause
    exit /b 1
)

:: Get the directory of this script
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
set "BACKUP_SCRIPT=%SCRIPT_DIR%\backup.sh"
set "LOG_FILE=%SCRIPT_DIR%\attendance-backup.log"
set "TASK_NAME=AttendanceSystemDailyBackup"

:: Verify Git Bash exists
set "GIT_BASH=C:\Program Files\Git\bin\bash.exe"
if not exist "%GIT_BASH%" (
    echo ERROR: Git Bash not found at %GIT_BASH%
    echo Please install Git for Windows from https://git-scm.com/download/win
    pause
    exit /b 1
)

:: Verify backup.sh exists
if not exist "%BACKUP_SCRIPT%" (
    echo ERROR: backup.sh not found at %BACKUP_SCRIPT%
    pause
    exit /b 1
)

echo ══════════════════════════════════════════════════
echo   Setting up Daily Backup Task (Windows Scheduler)
echo ══════════════════════════════════════════════════
echo.

:: Delete existing task if present (don't fail if it doesn't exist)
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

:: Create the task — runs daily at 02:00 AM
schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "\"%GIT_BASH%\" -c \"bash '%BACKUP_SCRIPT%' >> '%LOG_FILE%' 2>&1\"" ^
    /sc daily ^
    /st 02:00 ^
    /ru SYSTEM ^
    /f

if %errorLevel% equ 0 (
    echo.
    echo [OK] Task created successfully!
    echo.
    echo   Task name : %TASK_NAME%
    echo   Schedule  : Daily at 02:00 AM
    echo   Script    : %BACKUP_SCRIPT%
    echo   Log file  : %LOG_FILE%
    echo   Retention : Last 30 days (KEEP_DAYS in backup.sh)
    echo.
    echo   To verify: Open Task Scheduler ^(taskschd.msc^)
    echo   To run now: schtasks /run /tn "%TASK_NAME%"
    echo   To remove: schtasks /delete /tn "%TASK_NAME%" /f
) else (
    echo [ERROR] Failed to create task. Check permissions.
)

echo.
pause
