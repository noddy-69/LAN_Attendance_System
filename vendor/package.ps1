# ════════════════════════════════════════════════════════════════════════════
# vendor\package.ps1 — VENDOR build & package (run on your machine only).
#
# Produces a self-contained delivery folder (dist\) for a customer office:
#   • attendance-images-<tag>.tar   — ALL images (app + postgres/redis/minio/nginx)
#   • docker-compose.prod.yml        — runs from those images (no source)
#   • nginx\, mediamtx.yml           — bind-mounted config (not in images)
#   • gen-env.ps1, .env.example      — first-run secret generation
#   • start-attendance.bat           — the customer's one step (until the .exe installer)
#   • README-INSTALL.txt
#
# The customer never receives your source code — only built images.
#
# Usage:   .\vendor\package.ps1                 (tag 1.0.0)
#          .\vendor\package.ps1 -Tag 1.1.0
# ════════════════════════════════════════════════════════════════════════════
param([string]$Tag = "1.0.0")

# NOTE: keep this "Continue", not "Stop". Native tools (docker build/save, buildkit)
# write progress to stderr, which Windows PowerShell 5.1 turns into terminating
# errors under -Stop and aborts the build for no real reason. Every critical step
# below is instead guarded by an explicit `if ($LASTEXITCODE -ne 0) { throw }`.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:IMAGE_TAG = $Tag

$APP = @("attendance-backend:$Tag", "attendance-frontend:$Tag", "attendance-face:$Tag")
$STOCK = @("postgres:16-alpine", "redis:7-alpine", "minio/minio:latest", "nginx:1.25-alpine", "bluenviron/mediamtx:latest")

Write-Host "== [1/4] Building app images (tag $Tag) ==" -ForegroundColor Cyan
docker compose build backend face-recognition
if ($LASTEXITCODE -ne 0) { throw "build failed" }
# Frontend MUST be built --no-cache: NEXT_PUBLIC_* is inlined into the client bundle
# at build time, and `docker compose build` has been observed serving a stale cached
# image (baking the wrong API URL). A direct no-cache build guarantees the current
# source is compiled. The relative /api/v1 keeps the app same-origin on any host.
docker build --no-cache -t "attendance-frontend:$Tag" --build-arg NEXT_PUBLIC_API_URL=/api/v1 ./frontend
if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }

Write-Host "== [2/4] Pulling stock images ==" -ForegroundColor Cyan
foreach ($i in $STOCK) { docker pull $i | Out-Null }

$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Force -Path $dist | Out-Null

# Regenerate the customer setup PDF from make_setup_pdf.py (best-effort: needs python +
# reportlab on the build machine; if unavailable, the existing PDF at the repo root is shipped).
Write-Host "== Regenerating setup guide PDF ==" -ForegroundColor Cyan
try {
    python "$root\make_setup_pdf.py"
    if ($LASTEXITCODE -ne 0) { Write-Host "   [note] PDF regen returned $LASTEXITCODE — shipping existing PDF" -ForegroundColor Yellow }
} catch {
    Write-Host "   [note] could not run make_setup_pdf.py ($_). Shipping existing PDF." -ForegroundColor Yellow
}

Write-Host "== [3/4] Saving all images to one tarball (this is large, be patient) ==" -ForegroundColor Cyan
$tar = Join-Path $dist "attendance-images-$Tag.tar"
docker save -o $tar @($APP + $STOCK)
if ($LASTEXITCODE -ne 0) { throw "docker save failed" }
$sizeMB = [math]::Round((Get-Item $tar).Length / 1MB, 0)
Write-Host "   images tarball: $sizeMB MB" -ForegroundColor Green

Write-Host "== [4/4] Assembling delivery folder ==" -ForegroundColor Cyan
Copy-Item "docker-compose.prod.yml" $dist -Force
Copy-Item "mediamtx.yml" $dist -Force -ErrorAction SilentlyContinue
Copy-Item "gen-env.ps1" $dist -Force
Copy-Item "Attendance-Launcher.ps1" $dist -Force
Copy-Item "Attendance-Launcher.vbs" $dist -Force
Copy-Item "LICENSE-AGREEMENT.txt" $dist -Force -ErrorAction SilentlyContinue
Copy-Item "setup-antispoof.ps1" $dist -Force -ErrorAction SilentlyContinue
Copy-Item "setup-https.ps1" $dist -Force -ErrorAction SilentlyContinue
Copy-Item "update-ip.bat" $dist -Force -ErrorAction SilentlyContinue
Copy-Item "enable-phone-https.bat" $dist -Force -ErrorAction SilentlyContinue
# Customer-facing guides + backup/restore helpers
Copy-Item "USER-GUIDE.md" $dist -Force -ErrorAction SilentlyContinue
Copy-Item "Attendance_System_Setup_Guide.pdf" $dist -Force -ErrorAction SilentlyContinue
Copy-Item "backup.bat" $dist -Force -ErrorAction SilentlyContinue
Copy-Item "restore.bat" $dist -Force -ErrorAction SilentlyContinue
Copy-Item "setup-backup-task.bat" $dist -Force -ErrorAction SilentlyContinue
# Remove any previous nginx copy first so retired conf files (e.g. an old cloud.conf)
# don't linger in the delivery — Copy-Item -Force overwrites but never deletes.
Remove-Item (Join-Path $dist "nginx") -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item "nginx" $dist -Recurse -Force
# ship an empty certs dir so the nginx bind-mount exists, but NEVER ship our own
# dev certs/keys — the customer generates their own (generate-certs / mkcert).
New-Item -ItemType Directory -Force -Path (Join-Path $dist "nginx\certs") | Out-Null
# If dist\ is also a LIVE test stack on this machine, the running nginx bind-mounts these
# cert files; scrubbing them here will crash that nginx on its next recreate. Detect &
# warn so the operator knows to restore local HTTPS with: .\dist\setup-https.ps1 -Sync
$script:scrubbedLiveCerts = Test-Path (Join-Path $dist "nginx\certs\attendance.crt")
Get-ChildItem (Join-Path $dist "nginx\certs") -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne ".gitkeep" } | Remove-Item -Force -ErrorAction SilentlyContinue
# ship the anti-spoof model dir so the face-service bind-mount path exists, and
# include the pre-converted MiniFASNet ONNX models (from the vendor store) so
# passive liveness works out of the box on delivery.
New-Item -ItemType Directory -Force -Path (Join-Path $dist "models\antispoof") | Out-Null
Copy-Item "models\antispoof\README.md" (Join-Path $dist "models\antispoof") -Force -ErrorAction SilentlyContinue
if (Test-Path "vendor\antispoof-models\*.onnx") {
    Copy-Item "vendor\antispoof-models\*.onnx" (Join-Path $dist "models\antispoof") -Force
    Write-Host "   bundled anti-spoof liveness models" -ForegroundColor Green
} else {
    Write-Host "   [note] no anti-spoof models in vendor\antispoof-models — run vendor\convert-minifasnet.py to enable passive liveness" -ForegroundColor Yellow
}

# ── prod .env.example (no dev camera URLs; cameras come from the in-app page) ──
@"
# Auto-filled by start-attendance.bat on first run. Edit only if you know why.
DEPLOYMENT_MODE=local
BASE_URL=http://localhost
# Relative on purpose: the browser calls the same origin nginx served (works on
# localhost, any LAN IP and HTTPS). The frontend image bakes this default too.
NEXT_PUBLIC_API_URL=/api/v1
HTTP_PORT=80
HTTPS_PORT=443
IMAGE_TAG=$Tag
# Host LAN IP (auto-filled by gen-env on first run). Used by mediamtx so the in-app
# webcam's WebRTC media is reachable by the browser.
HOST_LAN_IP=192.168.1.100

POSTGRES_DB=attendance
POSTGRES_USER=attendance_user
POSTGRES_PASSWORD=CHANGE_ME
DATABASE_URL=postgresql+asyncpg://attendance_user:CHANGE_ME@postgres:5432/attendance

REDIS_URL=redis://redis:6379/0
SECRET_KEY=CHANGE_ME
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
COOKIE_SECURE=false

MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=CHANGE_ME
MINIO_BUCKET_ATTENDANCE=attendance-proofs
MINIO_SECURE=false

SERVICE_ACCOUNT_EMAIL=face-service@attendance.app
SERVICE_ACCOUNT_PASSWORD=CHANGE_ME
# RTSP camera streams. For the in-app webcam (Admin -> Camera), set:
#   ENTRY_CAMERA_URL=rtsp://mediamtx:8554/webcam
ENTRY_CAMERA_URL=
EXIT_CAMERA_URL=
FACE_CONFIDENCE_THRESHOLD=0.40

# Production: no demo accounts.
SEED_DEMO_ACCOUNTS=false

# Self-service selfie check-in. Empty = any private/LAN address counts as on-site
# (flag-and-audit only; off-LAN check-ins are still recorded, just flagged).
SELFIE_ALLOWED_SUBNETS=

# Passive anti-spoofing on the selfie path is OFF by default: the bundled MiniFASNet
# models misclassify genuine phone selfies (lock real staff out). Active head-movement
# liveness + the 1:1 self-match are the guards. Enable (=true, lenient via
# FACE_ANTISPOOF_THRESHOLD) only after validating the model on your own cameras.
SELFIE_ANTISPOOF_ENABLED=false

# Software license — REQUIRED. Generate per customer with vendor\make_license.py
# (python make_license.py sign --company "Acme" --employees 20 --days 365) and
# paste the token here. Without a valid key, only the admin can log in.
LICENSE_ENFORCE=true
LICENSE_KEY=
"@ | Set-Content -Path (Join-Path $dist ".env.example") -Encoding ascii

# ── start-attendance.bat (customer's single step) ────────────────────────────
@"
@echo off
setlocal enabledelayedexpansion
:: Attendance System — start / first-run. Double-click to run.
cd /d "%~dp0"
echo Checking Docker...
docker info >nul 2>&1
if errorlevel 1 ( echo [ERROR] Docker Desktop is not running. Start it and try again. & pause & exit /b 1 )

if not exist ".env" (
  echo First run: generating configuration and secrets...
  copy ".env.example" ".env" >nul
  set LAN_IP=
  for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /i "IPv4" ^| findstr /v "127.0.0.1"') do if "!LAN_IP!"=="" set LAN_IP=%%i
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0gen-env.ps1" -LanIp "%LAN_IP: =%"
)

echo Loading application images (first run only, may take a few minutes)...
docker image inspect attendance-backend:$Tag >nul 2>&1 || docker load -i "attendance-images-$Tag.tar"

echo Starting the attendance system...
docker compose -f docker-compose.prod.yml up -d
echo.
echo Done. Open http://localhost in your browser.
echo (To stop: run stop-attendance.bat)
pause
"@ | Set-Content -Path (Join-Path $dist "start-attendance.bat") -Encoding ascii

@"
@echo off
cd /d "%~dp0"
docker compose -f docker-compose.prod.yml down
pause
"@ | Set-Content -Path (Join-Path $dist "stop-attendance.bat") -Encoding ascii

# ── installer-firstrun.bat (silent: called by the .exe installer; no pause) ───
@"
@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
if not exist ".env" (
  copy ".env.example" ".env" >nul
  set LAN_IP=
  for /f "tokens=2 delims=:" %%i in ('ipconfig ^| findstr /i "IPv4" ^| findstr /v "127.0.0.1"') do if "!LAN_IP!"=="" set LAN_IP=%%i
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0gen-env.ps1" -LanIp "!LAN_IP: =!"
)
docker image inspect attendance-backend:$Tag >nul 2>&1 || docker load -i "attendance-images-$Tag.tar"
docker compose -f docker-compose.prod.yml up -d
"@ | Set-Content -Path (Join-Path $dist "installer-firstrun.bat") -Encoding ascii

@"
# Attendance & Workforce Management System

On-premises attendance, leave, reimbursement and payroll for your office.
Everything runs on **this PC** inside Docker — your data never leaves the computer.

## Quick start (first time)

1. **Install Docker Desktop** — https://www.docker.com/products/docker-desktop
   Run it, keep "Use WSL 2" ticked, then **restart the PC**. Start Docker Desktop and
   wait until the whale icon says "running". In Docker Desktop **Settings -> General**,
   tick **"Start Docker Desktop when you sign in"** so the system comes back on its own
   after every reboot.
2. Copy this whole folder somewhere permanent (e.g. C:\AttendanceSystem).
3. Double-click **start-attendance.bat**. The first run loads the app (a few minutes)
   and configures itself. Wait until it says "Done".
4. Open **http://localhost** and sign in as the **admin** (credentials provided
   separately by your provider). Paste your **license key** in Admin -> Settings.

## Every day / after a reboot

Nothing to do — Docker Desktop starts on login and the system starts with it.
Just open **http://localhost** (wait 1-2 minutes after turning the PC on).
To stop on purpose: **stop-attendance.bat**. To start again: **start-attendance.bat**.

## Let staff use it from their phones

Double-click **update-ip.bat** — it prints the web address staff should open on the
office Wi-Fi. If phones ever stop connecting after a Wi-Fi/router change, run
**update-ip.bat** again. For phone selfie check-in (needs HTTPS), run **setup-https.ps1**
once (right-click -> Run with PowerShell).

## Back up your data (important)

An automatic backup is taken at the end of every month into the **backups** folder.
For an instant backup: Admin -> Settings -> Data -> Download Backup Now (or **backup.bat**).
**Copy the backups folder onto a USB drive / another PC regularly.**

## Files & guides in this folder

  - **Attendance_System_Setup_Guide.pdf** — full step-by-step setup, reboot and
    troubleshooting guide (start here if anything is unclear).
  - **USER-GUIDE.md** — how to use the system day to day (attendance, leave, reports).
  - **LICENSE-AGREEMENT.txt** — the software license terms.
  - start-attendance.bat / stop-attendance.bat — start / stop the system.
  - update-ip.bat — fix the address after the PC's IP changes.
  - setup-https.ps1 — turn on HTTPS (needed for phone camera check-in).
  - backup.bat / setup-backup-task.bat — back up now / schedule automatic backups.

Need help? Contact your provider.
"@ | Set-Content -Path (Join-Path $dist "README.md") -Encoding utf8

# Tiny plain-text pointer for anyone who opens the folder in Notepad.
@"
ATTENDANCE SYSTEM
Open README.md (or Attendance_System_Setup_Guide.pdf) for setup instructions.
Quick start: install Docker Desktop, then double-click start-attendance.bat, then open http://localhost
"@ | Set-Content -Path (Join-Path $dist "README-INSTALL.txt") -Encoding ascii

Write-Host ""
Write-Host "DONE. Delivery folder ready: $dist" -ForegroundColor Green
Write-Host "Hand the customer the entire 'dist' folder (or the .exe installer once built)." -ForegroundColor Green
if ($script:scrubbedLiveCerts) {
    Write-Host ""
    Write-Host "[!] Removed existing HTTPS certs from dist\nginx\certs (delivery must ship clean)." -ForegroundColor Yellow
    Write-Host "    If you run this 'dist' as a LIVE test stack with HTTPS, its nginx will crash" -ForegroundColor Yellow
    Write-Host "    on next recreate. Restore local HTTPS with:  .\dist\setup-https.ps1 -Sync" -ForegroundColor Yellow
}
if (Test-Path (Join-Path $dist ".env")) {
    Write-Host ""
    Write-Host "[!] dist\.env exists (your TEST config: demo accounts / license key)." -ForegroundColor Yellow
    Write-Host "    DELETE it before delivering so the customer gets a fresh .env from .env.example." -ForegroundColor Yellow
}
