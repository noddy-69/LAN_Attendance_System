CONTEXT MANAGEMENT: Read only files directly relevant to the 
current task. Do not scan the entire project at once. 
Load files on demand as needed per task.

═══════════════════════════════════════════════════════════
SYSTEM BUILD BRIEF — ATTENDANCE & WORKFORCE MANAGEMENT
Version 1.0 | Full System | Local-First | Max 20 Employees
═══════════════════════════════════════════════════════════

# ── ROLE ──────────────────────────────────────────────────────────────
You are a senior full-stack engineer building a production-ready
Attendance & Workforce Management System from scratch. Build the
entire system end-to-end: database schema, backend APIs, face
recognition pipeline, and all four user portals (Employee, Manager,
HR, Admin). No stubs, no placeholders — every feature listed must
be fully implemented and wired up.

# ── DEPLOYMENT PHILOSOPHY ─────────────────────────────────────────────
PRIMARY TARGET: Local deployment on a single office machine or mini PC.
The system must work 100% offline — no internet dependency for core
attendance, leave, and payroll features.

Cloud is OPTIONAL and only considered if:
  a) The hosting is completely free (no credit card required), AND
  b) Performance is smooth for ≤20 concurrent users

Design all components to be deployment-agnostic:
  - No hardcoded IPs or hostnames anywhere
  - All config via .env file
  - Works on LAN (192.168.x.x) with no domain name
  - Works with self-signed SSL cert (or plain HTTP on LAN)
  - Docker Compose is the ONLY orchestrator (no Kubernetes, no cloud-native)

# ── DEPLOYMENT TIERS (build all three, user picks one) ────────────────

Tier 1 — Local LAN (PRIMARY, zero cost):
  Host machine: Office Windows 10/11 PC or Ubuntu mini PC
  Min specs:    4-core CPU, 8 GB RAM, 100 GB free disk
  Recommended:  Intel NUC / Beelink mini PC (₹15,000–25,000 one-time)
  Access:       http://192.168.x.x:3000 from any office device on WiFi
  SSL:          Optional (self-signed cert via mkcert for LAN HTTPS)
  Internet:     Only needed for WhatsApp notifications (Wati API calls)
  Camera:       RTSP streams on same LAN — zero latency
  Biometric:    Device on same LAN — direct HTTP push

Tier 2 — Free Cloud (OPTIONAL, if Tier 1 isn't preferred):
  Platform:     Oracle Cloud Free Tier (Always Free — 4 OCPUs, 24 GB RAM)
  Why Oracle:   Only cloud that gives enough free RAM to run this stack
                without throttling. Render/Railway/Fly.io free tiers are
                too small (512 MB RAM) for face recognition + PostgreSQL.
  Alternative:  Google Cloud e2-micro (free tier, 1 vCPU, 1 GB RAM)
                — only viable if face-recognition runs on local machine
                and backend alone is on cloud
  SSL:          Let's Encrypt via Certbot (auto, free)
  Domain:       Use Oracle's public IP or grab free subdomain from
                duckdns.org (e.g. youroffice.duckdns.org)
  Limitation:   Face recognition service is heavy — run it locally even
                on cloud tier, push only events to cloud backend

Tier 3 — Hybrid (best of both):
  Face recognition service: runs locally (needs camera LAN access)
  Backend + DB + Frontend:  runs on Oracle Free Tier cloud
  Face service POSTs events to cloud API over internet
  Employees access portals via public URL from anywhere

Provide a .env variable: DEPLOYMENT_MODE=local|cloud|hybrid
The system adapts based on this value (CORS origins, base URLs, etc.)

# ── LOCAL SETUP REQUIREMENTS ──────────────────────────────────────────
Provide these scripts/files for local deployment:

  setup-local.sh       — installs Docker + Docker Compose on Ubuntu,
                         sets up .env from .env.example, runs compose up
  setup-windows.bat    — same for Windows (using Docker Desktop)
  generate-certs.sh    — runs mkcert to create LAN SSL certs
  seed-db.sh           — seeds DB with: admin user, sample branches,
                         departments, Indian Gazetted holidays 2026,
                         default system policies
  backup.sh            — daily cron: pg_dump → compressed archive in /backups
  restore.sh           — restores from a backup archive

Also provide a LOCAL_SETUP_GUIDE.md:
  - Step-by-step from zero (install Docker → access portal in browser)
  - How to find the machine's LAN IP and share it with office staff
  - How to connect cameras (RTSP URL discovery)
  - How to connect ZKTeco K40 biometric device (ADMS setup)
  - How to enroll employee faces (admin portal walkthrough)
  - Common troubleshooting (camera not connecting, port conflicts)

# ── TECH STACK ────────────────────────────────────────────────────────

Frontend:
  - Next.js 14 (App Router) + TypeScript
  - Tailwind CSS + shadcn/ui component library
  - React Query (server state), Zustand (client state)
  - Four portals in one Next.js monorepo:
      /employee   → Employee Self-Service Portal
      /manager    → Manager Dashboard
      /hr         → HR Operations Portal
      /admin      → System Admin Portal

Backend:
  - FastAPI (Python 3.12) — async, fully typed with Pydantic v2
  - SQLAlchemy 2.0 ORM (async)
  - Alembic (database migrations, versioned)
  - JWT auth (access token 15min + refresh token 7 days, HttpOnly cookie)
  - RBAC middleware (permission-per-endpoint)
  - Celery + Redis (async jobs: notifications, payroll, reports)
  - MinIO (S3-compatible object storage — runs locally in Docker)
  - SMTP + Wati.io WhatsApp API (notifications)

Face Recognition Service (separate lightweight microservice):
  - Python 3.12, FastAPI
  - OpenCV (RTSP stream reader, 5 FPS, configurable)
  - ByteTrack (multi-object tracking, prevents duplicate events)
  - InsightFace + ONNX Runtime (face recognition)
  - Confidence threshold: 95% (configurable via admin portal)
  - Cooldown window: 5 minutes per employee per camera (configurable)
  - Saves entry.jpg / exit.jpg proof frames to MinIO
  - Resource-optimized for low-end hardware:
      Use ONNX INT8 quantized models
      Frame skip: process 1 of every N frames (configurable)
      CPU-only inference (no GPU required)

Database:
  - PostgreSQL 16 (primary store)
  - Redis 7 Alpine (cache + Celery broker)

Infrastructure:
  - Docker Compose (single file, works on any OS with Docker)
  - Nginx (reverse proxy, handles HTTP and optional HTTPS)
  - All secrets in .env (never hardcoded)
  - Healthchecks + restart: unless-stopped on all containers

# ── RESOURCE OPTIMIZATION (critical for local/free-tier) ──────────────
The system must run on 8 GB RAM total. Enforce these limits in
docker-compose.yml under deploy.resources.limits:

  nginx:            64 MB
  frontend:         256 MB
  backend:          512 MB
  face-recognition: 1.5 GB   (ONNX model + OpenCV frames)
  postgres:         1 GB
  redis:            128 MB
  celery-worker:    256 MB
  minio:            512 MB
  TOTAL:            ~4.2 GB   (leaves 3.8 GB headroom for OS)

Use PostgreSQL connection pooling (PgBouncer or SQLAlchemy pool_size=5)
to keep DB connections low on limited hardware.

# ── DATABASE SCHEMA ───────────────────────────────────────────────────
Implement all 21 tables with proper FK constraints, indexes, audit
triggers. Tables:

  employees, roles, permissions, branches, departments,
  employee_hierarchy, face_embeddings, attendance_events,
  daily_attendance, attendance_proofs, leave_types,
  leave_requests, leave_balances, reimbursements,
  reimbursement_documents, notifications, salary_deductions,
  shift_definitions, holiday_calendar, audit_logs, system_policies

Key schema rules:
  - All tables: id (UUID PK), created_at, updated_at
  - Soft-delete via deleted_at (never hard-delete business records)
  - audit_logs: who, what, before_value, after_value, ip, timestamp
  - daily_attendance.source = ENUM('face_recognition','biometric','manual')
  - attendance_events.event_type = ENUM('ENTRY','EXIT')
  - All monetary values stored as INTEGER (paise, not float)
  - All timestamps stored as UTC in DB, displayed as IST on frontend

# ── ANSWERS TO INTEGRATION QUESTIONS ─────────────────────────────────

1. WhatsApp provider: Wati.io
   REST API — POST to https://live-server.wati.io/api/v1/sendTemplateMessage
   Auth: Bearer token in .env as WATI_API_TOKEN
   Fallback: if Wati call fails → send email via SMTP
   Offline fallback: if no internet → store notification as in-app only,
   retry Wati/email when internet is restored (Celery retry with backoff)

2. Biometric device: ZKTeco K40 (ADMS protocol)
   Device pushes attendance records via HTTP POST to:
     http://{server_ip}:8000/api/v1/attendance/biometric-event
   Payload format (ZKTeco ADMS standard):
     { "sn": "device_serial", "ret": "0", "cmd": "att",
       "uid": "employee_uid", "time": "2026-06-03 09:01:25",
       "state": "0", "ty": "1" }
   Map device uid → employee_id via biometric_uid field in employees table
   State 0 = Check-In, State 1 = Check-Out (configurable in admin)

3. Camera RTSP format: CP Plus
   Entry camera:  rtsp://admin:{password}@{camera_ip}:554/cam/realmonitor?channel=1&subtype=0
   Exit camera:   rtsp://admin:{password}@{camera_ip}:554/cam/realmonitor?channel=1&subtype=0
   Store RTSP URLs + credentials in devices table (encrypted at rest)
   OpenCV connects via: cv2.VideoCapture(rtsp_url)
   Reconnect logic: if stream drops, retry every 30 seconds automatically

4. Domains / URLs:
   Local:  http://192.168.{x}.{x}:3000  (discovered via setup script)
   Cloud:  https://youroffice.duckdns.org  (free DuckDNS subdomain)
   Admin configures BASE_URL in .env — all internal links use this

5. SSL:
   Local:  mkcert — generates trusted cert for LAN IP + hostname
           script: generate-certs.sh (installs mkcert, generates, configures Nginx)
           Employees install the mkcert root CA on their devices once
   Cloud:  Let's Encrypt via Certbot (certbot --nginx, auto-renew cronjob)
   Both:   Nginx config has separate server blocks for HTTP→HTTPS redirect

6. Payroll integration: Standalone export only
   Generate monthly Excel (.xlsx) report with:
     Employee name, Employee ID, Month, Days Present, Days Absent,
     Days on Leave, Late Count, Allowed Lates, Excess Lates,
     Penalty per Late (₹), Total Deduction (₹), Net Deduction
   Also export as CSV for import into any payroll software
   HR downloads from portal — no external API integration
   Add Zoho Payroll / Razorpay Payroll integration in v2 if needed

7. Indian public holidays: Manual + seed script
   seed-db.sh pre-loads Central Govt Gazetted holidays for current year
   HR can add/edit/remove holidays per branch via Admin portal
   Holiday calendar is branch-specific (state holidays differ by branch)
   System automatically marks attendance as HOLIDAY on matching dates

# ── FACE RECOGNITION PIPELINE ─────────────────────────────────────────
  1. Connect to RTSP streams (Entry + Exit camera, CP Plus)
  2. OpenCV reads frames at 5 FPS
  3. ByteTrack assigns track IDs per physical person
  4. InsightFace extracts 512-dim embeddings (ONNX INT8, CPU-only)
  5. Cosine similarity vs stored embeddings (threshold 0.95)
  6. Cooldown: 5 min per employee per camera (no double-marking)
  7. Sequence validation: reject ENTRY→ENTRY, require ENTRY→EXIT order
  8. On valid detection:
       a. Save proof frame to MinIO (entry_{emp_id}_{date}.jpg)
       b. POST event to backend /api/v1/attendance/camera-event
       c. Trigger Wati WhatsApp to employee (with retry on failure)
  9. If camera offline: log warning, continue accepting biometric events
  10. If both offline: HR sees "No Data" status, can add manual correction

# ── ATTENDANCE ENGINE ─────────────────────────────────────────────────
  check_in      = first ENTRY event of the day
  check_out     = last EXIT event of the day
  work_hours    = check_out − check_in (minutes)
  late_threshold = branch.office_start_time + branch.grace_period
  is_late       = check_in > late_threshold
  late_minutes  = check_in − late_threshold (if is_late)
  overtime      = max(0, work_hours − shift.required_hours)

  Status ENUM: PRESENT, ABSENT, HALF_DAY, LATE, ON_LEAVE,
               HOLIDAY, WEEKEND, PENDING_CORRECTION

# ── BUSINESS WORKFLOWS ────────────────────────────────────────────────

Leave:  Employee → Manager Approval → HR Final Approval
Reimbursement:  Employee + Receipt Upload → Manager → HR/Finance → Paid
Correction:  Employee Request → Manager Review → HR Review → Updated
Payroll deduction:
  policy: allowed_late_count=3, penalty=₹200 (configurable)
  deduction = max(0, late_count − allowed) × penalty
  stored in salary_deductions, monthly report generated by Celery task

# ── USER PORTALS ──────────────────────────────────────────────────────

Employee Portal:
  Dashboard (today's status), attendance calendar, proof images,
  leave apply/track/cancel, reimbursement submit/track,
  correction request, profile edit, notification feed

Manager Portal:
  Team attendance today, late arrivals widget, approvals queue
  (leave/reimbursement/correction), team reports, employee drill-down

HR Portal:
  Employee CRUD, all attendance view/edit, leave final approval,
  payroll deduction config, Excel/CSV report export, holiday calendar

Admin Portal:
  All HR permissions + attendance rules, device management (cameras,
  biometric), branch/department/role management, system settings
  (Wati config, SMTP config, storage config, thresholds),
  full audit log viewer

# ── API STRUCTURE ─────────────────────────────────────────────────────
All endpoints: /api/v1/
Groups: /auth, /employees, /attendance, /leave, /reimbursements,
        /payroll, /notifications, /devices, /branches, /departments,
        /roles, /reports, /face, /system, /health

Standards:
  Response envelope: { success, data, error, pagination }
  Pagination: cursor-based
  File uploads: multipart/form-data → MinIO (10MB limit, MIME validated)
  Biometric webhook: POST /api/v1/attendance/biometric-event
  Camera event:      POST /api/v1/attendance/camera-event (internal)

# ── NOTIFICATIONS ─────────────────────────────────────────────────────
Events: ATTENDANCE_MARKED, LATE_ARRIVAL, LEAVE_APPLIED, LEAVE_APPROVED,
        LEAVE_REJECTED, REIMBURSEMENT_UPDATE, PAYROLL_DEDUCTION,
        CORRECTION_STATUS
Channel priority: WhatsApp (Wati) → Email (SMTP) → In-App only
Offline queue: failed notifications stored, retried via Celery beat
               every 5 minutes (max 3 retries then mark as failed)

# ── PROJECT STRUCTURE ─────────────────────────────────────────────────
  /
  ├── docker-compose.yml
  ├── .env.example
  ├── setup-local.sh          ← Ubuntu local setup script
  ├── setup-windows.bat       ← Windows local setup script
  ├── generate-certs.sh       ← mkcert LAN SSL script
  ├── seed-db.sh              ← DB seed (admin user, holidays, policies)
  ├── backup.sh               ← pg_dump daily backup
  ├── restore.sh              ← restore from backup
  ├── LOCAL_SETUP_GUIDE.md    ← step-by-step for non-technical HR/admin
  ├── nginx/
  │   ├── nginx.conf
  │   └── conf.d/             ← local.conf + cloud.conf (swap via .env)
  ├── frontend/               ← Next.js 14, App Router
  │   └── src/app/
  │       ├── (employee)/
  │       ├── (manager)/
  │       ├── (hr)/
  │       └── (admin)/
  ├── backend/                ← FastAPI
  │   ├── app/
  │   │   ├── api/v1/routers/
  │   │   ├── models/
  │   │   ├── schemas/
  │   │   ├── services/
  │   │   ├── tasks/
  │   │   └── core/
  │   └── alembic/
  └── face-service/           ← standalone Python service
      ├── src/
      │   ├── camera.py
      │   ├── tracker.py
      │   ├── recognizer.py
      │   ├── engine.py
      │   └── api.py
      └── models/             ← ONNX files (gitignored, downloaded on setup)

# ── DOCKER COMPOSE SERVICES ───────────────────────────────────────────
Services: nginx, frontend, backend, face-recognition, postgres,
          redis, celery-worker, minio
All: restart: unless-stopped + healthcheck
Memory limits enforced (see resource section above)
Internal services (postgres, redis, minio) NOT exposed externally
Nginx exposes only ports 80 and 443

# ── BUILD ORDER ───────────────────────────────────────────────────────
  1. Docker Compose + Nginx skeleton (all services boot cleanly)
  2. PostgreSQL schema — all 21 tables + Alembic migration
  3. FastAPI backend — auth, RBAC, all API routes, full business logic
  4. Face recognition service — camera → detect → track → recognize → event
  5. Celery tasks — notifications (with offline retry), payroll, reports
  6. Next.js frontend — Admin portal → HR → Manager → Employee
  7. Setup scripts + LOCAL_SETUP_GUIDE.md
  8. Integration test — camera event → daily record → portal display
  9. Nginx HTTPS config (both local mkcert + cloud Certbot paths)

# ── NON-NEGOTIABLE QUALITY RULES ──────────────────────────────────────
  - NO placeholders, NO TODOs, NO mock data in any file
  - Every API endpoint: proper error handling + HTTP status codes
  - Every DB write through service layer (no raw queries in routers)
  - All monetary amounts in INTEGER paise (never float)
  - All timestamps: stored UTC, displayed IST on frontend
  - Mobile-responsive frontend (managers use phones)
  - Dark mode on all portals
  - WCAG 2.1 AA accessibility
  - System works fully offline — internet only needed for Wati/SMTP
  - Face recognition must run on CPU-only (no GPU assumption)
═══════════════════════════════════════════════════════════
END OF BUILD BRIEF
═══════════════════════════════════════════════════════════

## Current Status
Production-ready and live-verified (E2E suite green). Since the original build:
added password reset, holiday management in the Admin portal, login rate-limiting,
face anti-spoofing, device heartbeats, multi-photo enrollment, and an in-app
**Admin → Camera** page (WebRTC/WHIP webcam → mediamtx, no ffmpeg).

**Self-service selfie check-in (1.2.0, 2026-06-19):** a 3rd attendance method beside
cameras + ZKTeco. Employee portal → **Check In** takes a live selfie with a random
head-movement **active-liveness** challenge + passive MiniFASNet anti-spoof
(face-service `POST /verify-selfie`), then the backend (`POST /attendance/selfie-checkin`,
`GET /attendance/selfie-config`) does a **1:1 match** vs the caller's own enrolled face,
stores the proof, and records it. First selfie = check-in; check-out optional. **LAN gate
is flag-and-audit** (`SELFIE_ALLOWED_SUBNETS`; off-LAN still recorded, flagged with IP +
similarity in `audit_logs`). New `SELFIE` enum value (Alembic `d8e9f0a1b2c3`). Needs HTTPS
for phone cameras. Verified E2E (sim≈0.99, ENTRY/EXIT, cooldown guard) + 12/12 E2E green.

Productized for on-prem distribution to companies:
- Backend **self-initialises** (auto migrate + seed on first start; entrypoint.sh).
- `docker-compose.prod.yml` runs from pre-built images only (no source shipped);
  `vendor/package.ps1` bundles all images + config into a `dist/` delivery folder.
- Demo accounts seeded automatically (admin/hr/manager/employee; off in prod via
  `SEED_DEMO_ACCOUNTS=false`).

Repo cleaned: removed 20 empty placeholder model files, unused dev scripts, and the
old standalone guides (consolidated into README.md + Attendance_System_Setup_Guide.pdf).
Single source of truth = README.md; history in CHANGELOG.md.

Ready to SELL as licensed on-prem software (2026-06-19):
- **Offline RSA-signed license keys** (`backend/app/core/license.py`; public key embedded
  at `backend/app/core/license_public.pem`). Vendor tool `vendor/make_license.py`
  (`keygen` + `sign --company --employees --days`). Enforcement (`LICENSE_ENFORCE=true`):
  expired/invalid license blocks non-admin login; over-cap blocks new employees; admin
  always retains access. GET `/api/v1/system/license` returns status. **3 enforcement
  tests passed** (valid / expired / cap) + full 12-test E2E green afterward.
- **`vendor/AttendanceSystem.iss`** (Inno Setup) wraps `dist/` into one `Setup.exe`.
- **Tray launcher** (`Attendance-Launcher.ps1`/`.vbs`): Open/Start/Stop/Status/Backup.
- **`LICENSE-AGREEMENT.txt`** EULA template (lawyer-review placeholder).
- PDF guide gained a **Step 0 — bare-machine** section (install Docker on a fresh PC).
- `vendor/license_private.pem` is SECRET (gitignored intent) — NEVER ship it.

**Notifications are exception-only (1.2.1, 2026-06-25):** a normal on-time check-in no
longer emits any notification (it used to email/message every employee daily). The
nightly materialization beat (00:30 IST) now emits a new **`ABSENT_ALERT`** for each
employee marked ABSENT for the completed day — fired only on a fresh transition to ABSENT,
duplicate-guarded so backfills don't re-blast. `LATE_ARRIVAL` and the leave/reimbursement/
payroll/correction events are unchanged. New `ABSENT_ALERT` enum value (Alembic
`e0f1a2b3c4d5`). Verified: 15/15 E2E green + nightly-task absent check (fires once, no dup).
**Note:** the live `dist` stack runs the rebuilt `attendance-backend:1.0.0`; re-run
`vendor/package.ps1` before delivery so the bundled image tarball includes this change.

**Dormant features removed + delivery hardened (2026-07-05):** per owner decision, three
now-unused features were stripped from code AND the shipped images:
- **Self-service email password reset** — endpoints `/auth/forgot-password` + `/auth/reset-password`,
  `auth_service.request_password_reset`/`reset_password`, `send_password_reset_email` Celery
  task, `ForgotPasswordRequest`/`ResetPasswordRequest` schemas, the `password_reset` model and
  the frontend `reset-password` page all deleted. Table dropped via Alembic `c3d4e5f6a7b8` (new
  head). Canonical reset = HR/Admin via the employee edit form (see [[password-reset-policy]]).
  The `forgot-password` page stays as an informational "contact HR/Admin" page.
- **Cloud / hybrid deployment** — `DEPLOYMENT_MODE` narrowed to `local` | `local-ssl`; removed
  `nginx/conf.d/cloud.conf`, Certbot/Let's-Encrypt/ACME bits. This is now a pure on-prem LAN
  product. (DuckDNS + `setup-https.ps1`/`update-ip.bat` for a LAN hostname + HTTPS **stay** —
  that's LAN tooling, not the cloud-hosting tier.)
- ~~WhatsApp notifications~~ — **RE-ADDED on owner request (2026-07-05, same day).** The
  WhatsApp **Meta Cloud API** channel is back in full: `_send_whatsapp` in `tasks/notifications.py`
  (WhatsApp → Email → In-App cascade), `WHATSAPP_*` settings in `config.py` + compose passthrough,
  the `whatsapp_enabled` seed policy, and the Admin → Settings → Notifications UI. Configure it in
  the DB via that UI (env vars are fallbacks). Only the old dead `WATI_*` (legacy Wati) env vars
  stay gone.
Aggressive file cleanup: deleted Linux `.sh` setup scripts, dev certs (`auto.crt/key`), logs,
caches, old root `backups/`, `setup-windows.bat`, `vendor/_test.lic`. Backend + frontend rebuilt
and E2E-equivalent verified on the live dist stack (migration applied, endpoint 404s,
notification pipeline works through the real worker). **Repackaged** `dist/` via `vendor/package.ps1`
(now generates a customer `dist/README.md` and regenerates the customer-facing
`Attendance_System_Setup_Guide.pdf`; also cleans stale nginx files before copy). Delivery
hygiene done: removed `dist/.env` and the vendor-test `dist/.https-config.json`
(acmedomain123.duckdns.org); certs scrubbed — do NOT run `setup-https.ps1 -Sync` on the final package.

## Possible next steps
- In-app first-run setup wizard for new admins.
- Python source obfuscation (Cython/Nuitka/PyArmor) for extra IP protection — discussed,
  not implemented; built images already withhold source.
- Admin UI banner showing license status / days remaining (data already at
  `/api/v1/system/license`).