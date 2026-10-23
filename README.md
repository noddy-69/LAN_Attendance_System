# Attendance & Workforce Management System — Complete Guide

A self-hosted, **offline-first** attendance system for small offices (≤ 20 employees).
It records attendance from **face-recognition cameras** and/or a **ZKTeco biometric
device**, and runs four web portals — **Employee, Manager, HR, Admin** — for leave,
reimbursements, attendance corrections, payroll deductions, reports, and holidays.

> **This single, self-contained README is the only guide you need.** Use it to explain
> the system to others, set it up from scratch, generate your own secret keys, and run a
> live demo with your laptop camera. A printable version is in
> `Attendance_System_Setup_Guide.pdf`.

## What it does (the elevator pitch)

- **Automatic attendance** from IP cameras (face recognition, CPU-only) and/or a
  ZKTeco K40 biometric device — no manual punching needed.
- **Four role-based portals** in one app: Employee, Manager, HR, Admin.
- **Leave, reimbursements, and corrections** with a two-level approval chain
  (Employee → Manager → HR).
- **Payroll deductions** for late arrivals, exported to Excel/CSV for HR.
- **Holidays** managed per branch; **notifications** via WhatsApp → email → in-app.
- **100% offline** — internet is only needed for WhatsApp/email notifications. Dark mode
  + mobile friendly on every portal.

---

## Table of contents

1. [What's inside (architecture)](#1-whats-inside-architecture)
2. [Prerequisites](#2-prerequisites)
3. [Secret keys — generate your own](#3-secret-keys--generate-your-own)
4. [Set up from scratch](#4-set-up-from-scratch)
5. [First login & basic configuration](#5-first-login--basic-configuration)
6. [Live demo with your laptop camera](#6-live-demo-with-your-laptop-camera)
7. [How to use each portal](#7-how-to-use-each-portal)
8. [Face enrollment (real cameras)](#8-face-enrollment-real-cameras)
9. [Everyday operations (start/stop/backup/reset)](#9-everyday-operations)
10. [Deploying for others (LAN)](#10-deploying-for-others)
11. [Troubleshooting](#11-troubleshooting)
12. [Quick reference](#12-quick-reference)

---

## 1. What's inside (architecture)

Everything runs in **Docker** — you don't install Python, Node, PostgreSQL, etc.
The whole system is **8 containers** started by one `docker compose` file:

| Container | What it does |
|---|---|
| **nginx** | Reverse proxy — the single entry point on port 80 (and 443 for HTTPS) |
| **frontend** | Next.js 14 web app — the 4 portals |
| **backend** | FastAPI REST API — all business logic |
| **face-recognition** | Reads camera streams (OpenCV + InsightFace + ByteTrack), recognises faces, posts attendance |
| **postgres** | PostgreSQL 16 database (all records) |
| **redis** | Cache + background-job queue |
| **celery-worker** | Background jobs — notifications, payroll, report generation |
| **minio** | S3-compatible file storage — proof photos, receipts |

**Tech stack:** Next.js 14 + TypeScript + Tailwind (frontend), FastAPI + SQLAlchemy 2.0
async (backend), PostgreSQL 16, Redis 7 + Celery, MinIO, InsightFace/ONNX (CPU-only),
all behind Nginx and orchestrated by Docker Compose. Total memory budget ≈ 4.2 GB.

**Data flow in one line:** camera/biometric → backend records attendance → portals show
it → HR exports payroll.

---

## 2. Prerequisites

| Need | Notes |
|---|---|
| **Windows 10/11** (or Ubuntu) | These instructions are Windows + PowerShell |
| **Docker Desktop** | Free — https://www.docker.com/products/docker-desktop (enable WSL 2 when asked) |
| **~8 GB RAM, ~10 GB disk free** | Face recognition is the heavy part |
| **Python 3.10+** *(optional)* | Only for generating secrets / running the test suite |
| The project folder | e.g. `C:\Users\ASUS\Desktop\attendance-system` |

Install Docker Desktop, **restart your PC**, and wait until the whale icon in the
system tray says *"Docker Desktop is running"* before continuing.

---

## 3. Secret keys — generate your own

The system has 4 secrets in the `.env` file. **Never demo or deploy with the
example placeholders.**

| Variable | What it protects |
|---|---|
| `SECRET_KEY` | Signs login tokens (JWT) **and** encrypts saved camera passwords |
| `POSTGRES_PASSWORD` | The database password (also embedded in `DATABASE_URL`) |
| `MINIO_SECRET_KEY` | The file-storage password |
| `SERVICE_ACCOUNT_PASSWORD` | The face-service's login used to post camera events |

### Option A — let the setup script generate them (easiest)

`setup-windows.bat` (Step 4 below) **creates `.env` with fresh strong random
secrets automatically** the first time it runs. If you use the script, you can
skip the rest of this section.

### Option B — generate them yourself

Generate values and paste them into `.env`.

**With Python (simplest):**
```powershell
# SECRET_KEY — 64-char hex
python -c "import secrets; print(secrets.token_hex(32))"

# A strong password (run once for EACH of the 3 passwords)
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

**Pure PowerShell (no Python):**
```powershell
# SECRET_KEY
[System.BitConverter]::ToString([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32)).Replace('-','').ToLower()
# A password
[System.BitConverter]::ToString([System.Security.Cryptography.RandomNumberGenerator]::GetBytes(18)).Replace('-','')
```

Then edit `.env` and set:
```ini
SECRET_KEY=<your 64-char hex>
POSTGRES_PASSWORD=<password-1>
# DATABASE_URL must contain the SAME password as POSTGRES_PASSWORD:
DATABASE_URL=postgresql+asyncpg://attendance_user:<password-1>@postgres:5432/attendance
MINIO_SECRET_KEY=<password-2>
SERVICE_ACCOUNT_PASSWORD=<password-3>
```

### ⚠️ Important rules about rotating secrets

- **Generate secrets BEFORE the first `docker compose up`.** `POSTGRES_PASSWORD` and
  `MINIO_SECRET_KEY` are baked into the data volumes when they're first created.
  Changing them later won't match the existing volume — the DB/MinIO won't start.
- **To rotate the DB/MinIO password after setup**, you must wipe the data:
  `docker compose down -v` (this deletes all data), set the new secret, then redo
  setup. So do a fresh wipe + re-seed when rotating those two.
- **`SECRET_KEY` can be rotated any time**, but it (a) logs everyone out (old tokens
  become invalid) and (b) makes previously-saved camera RTSP passwords unreadable —
  you'd just re-enter camera URLs in **Admin → Devices**.
- **`SERVICE_ACCOUNT_PASSWORD`** must match in two places: the value the face-service
  logs in with, and the seeded account. If you change it after seeding, re-run the
  seed (Step 4.6) so the account's password is updated to match.

---

## 4. Set up from scratch

You can do this two ways. **Option 1 (script)** is fastest; **Option 2 (manual)**
helps you understand each step — recommended the first time so you can explain it.

Open **PowerShell** in the project folder first:
```powershell
cd C:\Users\ASUS\Desktop\attendance-system
```

### Option 1 — One command

```powershell
.\setup-windows.bat
```
This checks Docker, detects your LAN IP, creates `.env` **with fresh secrets**,
builds all images, starts the 8 containers, runs the database migrations, and seeds
the data. When it prints *"Setup complete!"* you're done — jump to [Step 5](#5-first-login--basic-configuration).

### Option 2 — Manual, step by step

```powershell
# 4.1  Create your env file from the template
copy .env.example .env
notepad .env        # set your secrets (Section 3). For a local demo on ONE laptop,
                    # leave BASE_URL=http://localhost and NEXT_PUBLIC_API_URL=http://localhost/api/v1

# 4.2  Build all container images (first time: 10–15 min — face service is the slow one)
docker compose build

# 4.3  Start all 8 services. The backend SELF-INITIALISES on first start —
#      it runs the database migrations and seeds the baseline data automatically.
#      (No manual migrate/seed commands needed.)
docker compose up -d

# 4.4  Confirm everything is healthy (first boot takes ~60–90s while it initialises)
docker compose ps
#      → all 8 should say "Up ... (healthy)"
```

> Migrations + seed run automatically via the backend's entrypoint. To manage them
> yourself, set `AUTO_INIT=false` in `.env` and run
> `docker compose exec backend alembic upgrade head` and
> `docker compose exec backend python seed_db_full.py` by hand.

### Verify it came up

```powershell
docker compose ps                          # all 8 "healthy"
curl.exe http://localhost/api/v1/health    # → {"status":"ok","db":"ok","redis":"ok"}
```

Open **http://localhost** in a browser.

> **What "from scratch" really means:** if you ever want a clean slate, run
> `docker compose down -v` (deletes all data + volumes), then `docker compose up -d`
> again — the backend re-initialises itself. Because the whole system rebuilds
> reproducibly, this is also the safest reset if anything gets into a weird state.

---

## 5. First login & basic configuration

The seed creates one ready-to-use login **per portal** (set `SEED_DEMO_ACCOUNTS=false`
before seeding to skip these in production):

| Portal | Email | Password |
|---|---|---|
| Admin | `admin@test.com` | `Admin@1234` |
| HR | `hr@test.com` | `Demo@1234` |
| Manager | `manager@test.com` | `Demo@1234` |
| Employee | `employee@test.com` | `Demo@1234` |

(The demo Employee reports to the demo Manager, so the leave/approval chain has a real team.)

1. Go to **http://localhost** → sign in:
   - **Email:** `admin@test.com`
   - **Password:** `Admin@1234`
2. **Change the admin password immediately** — **Admin → Employees →** your own row →
   **edit → Reset Password**.
3. Set up your office:
   - **Admin → Branches → Head Office** — office name, address, **start time**,
     **end time**, and **grace period** (minutes before someone counts as "late").
   - **Admin → Departments / Roles** — as needed.
   - **Admin → Employees → Add Employee** — name, email, password, role
     (Employee/Manager/HR/Admin), manager (for approvals), date of joining.
   - **Admin → Holidays** — 17 Indian Gazetted holidays for 2026 are pre-loaded;
     add/remove regional ones per branch here.
   - **Admin → Settings** — late-penalty policy, thresholds, notification config.

<a name="password-reset"></a>
**Password reset:** there is no self-service email reset. An **Admin or HR** resets any
user's password from **Employees → edit the person → Reset Password**. The employee's own
profile page and the login page's *"Forgot your password?"* link both point them to
contact their Admin/HR.

---

## 6. Live demo with your laptop camera

This is the best way to show the system working. You'll **enroll your own face**,
**stream your webcam into the system**, and watch your attendance get marked.

> **Easiest way:** use the built-in **Admin → Camera** page — pick a camera, preview it,
> and click **"Use this camera"**; it streams into the system over WebRTC (you only need
> `mediamtx` running, step 6.2). The manual `ffmpeg` commands below are an alternative if
> you prefer the command line. Docker can't see the webcam directly, so either way the
> feed reaches the (dockerized) face engine over RTSP, exactly like a real CP Plus camera.

### 6.1 — Create a demo employee and enroll your face

1. As admin: **HR portal** → **Employees** → **Add Employee** (give yourself a name,
   email, password, role `employee`, branch Head Office).
2. Take a clear, front-facing, well-lit photo of your face (JPG/PNG, one face).
3. **HR portal → Employees** → click the **camera icon** on your row → select **one
   or more** photos → they upload and enroll. (2–3 varied photos = better accuracy.)
   - *Alternative (API):* see [Section 8](#8-face-enrollment-real-cameras).
4. Tell the face service to load the new face immediately:
   ```powershell
   docker compose exec face-recognition python -c "import urllib.request; urllib.request.urlopen(urllib.request.Request('http://localhost:8001/reload-embeddings', method='POST'))"
   ```

### 6.2 — Stream your webcam into the system

Install two small tools (one time):
```powershell
winget install Gyan.FFmpeg
winget install bluenviron.mediamtx
```

> **After installing, open a NEW PowerShell window** so `mediamtx`/`ffmpeg` are on
> your PATH. If you stay in the same window and get *"mediamtx is not recognized"*,
> add them to the current session's PATH first:
> `$env:PATH += ";$env:LOCALAPPDATA\Microsoft\WinGet\Links"`

Open **two PowerShell windows** and keep both running:

**Window 1 — start the RTSP server:**
```powershell
mediamtx
```

**Window 2 — find your camera name, then publish it:**
```powershell
ffmpeg -list_devices true -f dshow -i dummy     # note your camera's exact name

ffmpeg -f dshow -rtbufsize 64M -framerate 15 -i video="Integrated Camera" `
       -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p `
       -f rtsp rtsp://localhost:8554/webcam
```
(Replace `"Integrated Camera"` with the exact name `-list_devices` printed.)

### 6.3 — Point the system at the stream

Edit `.env`:
```ini
ENTRY_CAMERA_URL=rtsp://host.docker.internal:8554/webcam
EXIT_CAMERA_URL=
```
Then restart the face service and watch its logs:
```powershell
docker compose up -d face-recognition
docker compose logs -f face-recognition
```

### 6.4 — Walk in front of the camera 🙂

Within a few seconds the logs show:
```
MATCH  track_id=1  employee=<id>  camera=entry  sim=0.97
Event accepted by backend: ... type=ENTRY status=200
```

### 6.5 — Show the result to your audience

- **Employee portal** (log in as the demo employee): the dashboard shows **Today's
  Attendance** with your check-in time and a *PRESENT/LATE* badge, plus a notification.
- **HR portal → Attendance**: the record shows `source = face_recognition`; click the
  **proof image** to show the captured frame.
- **Cooldown demo:** step in front again within 5 minutes → the logs say
  `[cooldown] … remaining …s` and **no** duplicate is created (that's the spec working).
- **Check-out demo:** set `EXIT_CAMERA_URL` to the same stream (clear `ENTRY_CAMERA_URL`),
  restart the face service, wait out the 5-min cooldown, and show your face again →
  check-out time + work hours fill in.

> **Optional — anti-spoofing (liveness):** by default a printed photo would be
> accepted. To reject printed-photo/screen attacks, mount one or more MiniFASNet ONNX
> models into the face-service anti-spoof folder (`/opt/insightface/antispoof`, named
> `<scale>_<h>x<w>_*.onnx`, e.g. `2.7_80x80_MiniFASNetV2.onnx`) and set
> `FACE_ANTISPOOF_ENABLED=true`. It fails open if enabled without a model.

When done with the demo, set `ENTRY_CAMERA_URL=`/`EXIT_CAMERA_URL=` back to empty and
run `docker compose up -d face-recognition` to stop capturing.

### Restarting the webcam demo later

The 8 Docker containers come back on their own (`docker compose up -d`, or automatically
if Docker Desktop starts on login) — **you do NOT re-migrate, re-seed, or re-enroll;**
all data and enrolled faces persist. But the **webcam pieces are not part of Docker**, so
each time you restart the machine you must redo only these:

1. Plug in the (external) webcam.
2. Window 1: `mediamtx` (after the PATH line above).
3. Window 2: the `ffmpeg … -f rtsp rtsp://localhost:8554/webcam` publish command.
4. The face-recognition container auto-reconnects within ~30 s; if not,
   `docker compose restart face-recognition`.

### Where images are stored

- **Enrollment photos are NOT kept** — only the 512-number face embedding is stored
  (PostgreSQL `face_embeddings`). The raw photo is discarded after extraction.
- **Attendance proof frames, avatars, and receipts** are stored in **MinIO** (bucket
  `attendance-proofs`). Browse them at http://localhost:9001 (login = `MINIO_ACCESS_KEY`
  / `MINIO_SECRET_KEY` from `.env`) or via the proof thumbnail in HR → Attendance.

---

## 7. How to use each portal

The portal you see is decided by your **role**. One account = one role.

### Employee portal
- **Dashboard** — today's status, check-in/out, work hours, overtime, leave balances,
  notifications.
- **Attendance** — monthly calendar with proof photos.
- **Leave** — apply / track / cancel; see balances.
- **Claims** — submit reimbursements with a receipt photo.
- **Corrections** — request a fix to a wrong attendance record.
- **Profile** — avatar, phone, password.

### Manager portal
- **Team** attendance for the day, **late arrivals** widget.
- **Approvals** — first-level approval of the team's leave, reimbursements, and
  attendance corrections.
- **Reports** — team attendance export.

### HR portal
- **Employees** — full CRUD + **face enrollment** (the camera icon; multi-photo).
- **Attendance** — view/edit all records, approve corrections (final level).
- **Leave** — final approval, leave-type setup, balance adjustments.
- **Reimbursements** — final approval + mark paid.
- **Payroll** — late-penalty policy + run deductions + **Excel/CSV export**.
- **Reports** — attendance / leave / payroll downloads.
- **Holidays** — add/edit/remove holidays per branch (national or branch-specific).

### Admin portal
- Everything HR can do, **plus**: Devices (cameras + biometric), Branches,
  Departments, **Roles** (per-permission toggles), **Holidays**, **Audit Logs**,
  and **Settings** (thresholds, WhatsApp, SMTP email, storage).

**Approval workflows** (two levels): Leave, Reimbursements, and Corrections all go
**Employee → Manager → HR**.

---

## 8. Face enrollment (real cameras)

Enroll each employee **once** so cameras recognise them.

**Via the HR portal (recommended):** HR → Employees → **camera icon** on the row →
select one or more clear, front-facing photos → they upload and enroll. Uploading
more photos adds reference images (improves accuracy).

**Via the API (bulk):**
```powershell
# 1. Get an admin token
$tok = (Invoke-RestMethod -Method Post -Uri http://localhost/api/v1/auth/login `
        -ContentType application/json `
        -Body '{"email":"admin@test.com","password":"Admin@1234"}').data.access_token

# 2. Find the employee's id
(Invoke-RestMethod -Uri "http://localhost/api/v1/employees?per_page=100" `
        -Headers @{Authorization="Bearer $tok"}).data | Select-Object id, email

# 3. Upload a photo
curl.exe -X POST "http://localhost/api/v1/face/employees/<EMPLOYEE-ID>/enroll" `
        -H "Authorization: Bearer $tok" -F "file=@C:\path\to\photo.jpg"
```

**Photo tips:** JPG/PNG, ≥ 300×300 px, one face, even lighting, no sunglasses/hat,
face occupies ≥ 30% of the frame. Recognition uses a **cosine-similarity threshold
(default `0.40`)** — tune it in **Admin → Settings** if lighting is difficult (raise
it to reject more, lower it to match more).

**How recognition works:** camera @ 5 FPS → ByteTrack tracks each person → InsightFace
makes a 512-d face embedding → cosine-similarity vs enrolled faces (≥ the configured
threshold, default `0.40`) → 5-min cooldown per person per camera → ENTRY = check-in,
EXIT = check-out. Embeddings can't be reversed into a photo, and raw photos aren't kept
after enrollment.

### Self-service selfie check-in (no camera needed)

Besides the fixed cameras and the ZKTeco device, employees can mark their own
attendance from their **phone** via **Employee portal → Check In**. It's designed to be
**buddy-punch-resistant** and is gated to the office network:

- The employee logs in and takes a quick **live selfie** while following a random
  **head-movement prompt** (active liveness, always on). **Passive anti-spoofing is on by
  default for selfie** — with the MiniFASNet model present it rejects printed-photo /
  screen attacks; with no model it fails open and the active liveness still applies (run
  **`setup-antispoof.ps1`** to install the model — see [`models/antispoof/`](models/antispoof/README.md)). The
  selfie is matched **1:1 against that employee's own enrolled face** (so it can't be used
  for anyone else — a colleague can't check you in without *your* live face).
- The first selfie of the day is the **check-in**; a **check-out** is then offered but
  **optional**.
- **LAN flag & audit:** the office-network check is recorded, not enforced — check-ins
  from outside the configured subnet (`SELFIE_ALLOWED_SUBNETS`) are still saved but
  flagged in the audit log with the source IP and match similarity.
- Records appear like any other attendance with `source = selfie` and the selfie stored
  as the proof image.

> **Requires HTTPS on phones.** Browsers only allow camera access in a secure context.
> On a phone, serve the app over HTTPS (`bash generate-certs.sh`, then install the
> generated root CA on the phone once). On the host PC itself, `http://localhost` also
> works. Admins can toggle the method in **Admin → Settings → Attendance** ("Self-service
> selfie check-in"), which writes the `selfie.enabled` system policy.

---

## 9. Everyday operations

```powershell
cd C:\Users\ASUS\Desktop\attendance-system

docker compose up -d         # start (or start again after a reboot)
docker compose stop          # stop, keep data
docker compose ps            # health of all 8 containers
docker compose logs -f backend           # watch backend logs
docker compose logs -f face-recognition  # watch camera/recognition logs

docker compose down          # remove containers (data volumes kept)
docker compose down -v       # FULL RESET — also deletes all data volumes
```

**Backups** (database dump → `backups/` folder):
```powershell
bash backup.sh                                   # manual backup
bash restore.sh backups/<backup-file>.sql.gz     # restore
```
Copy the `backups/` folder to an external drive weekly. On Windows you can also use
`setup-backup-task.bat` to schedule a daily backup.

**After editing code** (not config): rebuild the affected image, e.g.
`docker compose build backend` then `docker compose up -d backend`. Config-only
changes in `.env` just need `docker compose up -d <service>`.

---

## 10. Deploying for others

**Single laptop (this guide):** `BASE_URL=http://localhost`, open `http://localhost`.

**Whole office on the same WiFi (recommended for real use):**
1. In `.env` set `BASE_URL=http://<this-PC-LAN-IP>` and
   `NEXT_PUBLIC_API_URL=http://<this-PC-LAN-IP>/api/v1`.
2. Find the IP: `ipconfig | findstr IPv4` (look for `192.168.x.x`).
3. `docker compose up -d` and share `http://192.168.x.x` with the office.
   On phones, "Add to Home Screen" makes an app-like icon (no app store).

**Connecting real devices:**
- **CP Plus camera** — RTSP URL `rtsp://admin:PASSWORD@CAMERA_IP:554/cam/realmonitor?channel=1&subtype=0`;
  add it in **Admin → Devices**, then enroll faces (Section 8).
- **ZKTeco K40 biometric** — on the device set ADMS server to your PC's IP, port 8000;
  it pushes to `http://<server-ip>/api/v1/attendance/biometric-event`. Map each
  device `uid` to an employee via **biometric_uid** in the Admin portal.

**Deployment:** this is an **on-premises, local-LAN product** — it runs on one always-on
office PC and the data never leaves it. There is no cloud-hosting mode.

**HTTPS (green padlock) on LAN:** run `setup-https.ps1` (in the delivery folder), then
have each device trust the generated certificate once. A free DuckDNS hostname can give
the PC a stable web address on the LAN; `update-ip.bat` re-points it if the PC's IP changes.

### Selling this as on-prem software (no source code shared)

This repo is also packaged to sell as a **licensed on-prem product** — each customer
runs it on their own always-on PC, their data never leaves that PC, and you never hand
over the source code. The mechanics:

1. **Build the delivery once** (vendor side): `.\vendor\package.ps1`. This builds the
   app images, `docker save`s **all** images (app + Postgres/Redis/MinIO/Nginx) into a
   single tarball, and assembles a `dist\` folder with the prod compose file, config,
   `start-attendance.bat`, the tray launcher, and `LICENSE-AGREEMENT.txt`. The customer
   receives **only built images** — no Python/TypeScript source.
2. **Wrap it in an installer** (optional, friendliest): `vendor\AttendanceSystem.iss`
   (Inno Setup) turns `dist\` into one `Setup.exe` with Start-menu shortcuts and
   auto-start.
3. **Issue a license key per customer** (offline, RSA-signed, no server needed):
   ```powershell
   cd vendor
   python make_license.py keygen                              # one time — keep license_private.pem SECRET
   python make_license.py sign --company "Acme Pvt Ltd" --employees 20 --days 365 --out acme.lic
   ```
   Paste the token into the customer's `.env` as `LICENSE_KEY` (with
   `LICENSE_ENFORCE=true`). The app verifies it with the embedded public key
   (`backend/app/core/license_public.pem`); an expired or over-limit license blocks
   non-admin logins / new employees until renewed. **Never ship `license_private.pem`.**

See `vendor\` for `package.ps1`, `make_license.py`, `AttendanceSystem.iss`, and
`LICENSE-AGREEMENT.txt`. Customer-facing setup is in `README-INSTALL.txt` (shipped in
`dist\`) and the PDF guide.

---

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| Can't open the portal | Docker Desktop running? `docker compose ps` all healthy? Same WiFi as the host? |
| `docker compose exec ... alembic` shows only 2 lines | That means the DB is already migrated (up to date) — fine. |
| Tables/login errors right after first start | You skipped Step 4.4 — run `docker compose exec backend alembic upgrade head`, then re-seed. |
| Login says invalid for a known user | After a `down -v` wipe + re-seed, only `admin@test.com` exists; recreate other users. |
| `429 Too Many Requests` on login | The brute-force rate limit kicked in — wait a minute. (Working as intended.) |
| Face not recognised | Better lighting / front-facing; enroll 2–3 photos; lower threshold in Admin → Settings; check `docker compose logs face-recognition`. |
| `Failed to open camera` in demo | Close Zoom/Teams/Camera app (they hold the webcam); re-check the ffmpeg device name. |
| DB/MinIO won't start after changing a password | You changed `POSTGRES_PASSWORD`/`MINIO_SECRET_KEY` on an existing volume — `docker compose down -v` and redo setup (see Section 3). |
| Everything is in a weird state | `docker compose down -v` → repeat Steps 4.2–4.6 for a clean rebuild. |

---

## 12. Quick reference

| Thing | Value |
|---|---|
| Portal URL (single PC) | http://localhost |
| Portal URL (office) | http://&lt;LAN-IP&gt; |
| Admin login | `admin@test.com` / `Admin@1234` *(change immediately)* |
| Health check | `curl.exe http://localhost/api/v1/health` |
| MinIO storage console | http://localhost:9001 (login = `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` from `.env`) |
| Face-service machine account | `face-service@attendance.app` (password = `SERVICE_ACCOUNT_PASSWORD`) |
| Full automated test | `$env:API_URL="http://localhost/api/v1"; python -m pytest tests/integration -v` (E2E + selfie audits) |
| Selfie liveness audit | `docker compose exec -T face-recognition python - < tests/audits/audit_selfie_liveness.py` |
| Config file | `.env` (copied from `.env.example`) |
| Migrations + seed | **Automatic** on backend start (set `AUTO_INIT=false` to do it manually) |
| Manual migrate (if needed) | `docker compose exec backend alembic upgrade head` |
| Manual seed (if needed) | `docker compose exec backend python seed_db_full.py` |

**Setup order to remember:** `build → up -d` — the backend migrates and seeds itself.

---

*Self-contained setup, deployment, and testing guide. Version 1.2 — June 2026.*
