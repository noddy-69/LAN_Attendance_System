# CHANGELOG

All notable changes and fixes to the Attendance & Workforce Management System.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.2.2] — 2026-07-02

### Fixed
- **Camera attendance appeared "not marked" on a repeat detection.** A single entry-only
  camera re-detects an employee who is already checked in for the day; the backend's
  sequence guard rejected that second `ENTRY` with a 422 *"cannot record ENTRY after
  ENTRY — employee must EXIT before entering again"*, which surfaced in the face-service
  logs and made the camera look broken even though the first detection had already
  recorded the check-in. `process_event` now treats a repeat **same-day** `ENTRY` (with no
  `EXIT` since) as an **idempotent no-op**: it returns the day's existing record with a 200
  and creates no duplicate event and no notification. The first `ENTRY` of the day is still
  the check-in, cross-day entries are unaffected (the lookup is scoped to the IST day), and
  `EXIT` events are never blocked. The cooldown guard is unchanged and still runs first.

### Fixed (continued, employees)
- **HR's Add/Edit Employee Branch and Role dropdowns were empty.** The HR role lacked
  `branches:read` and `roles:read`, so those reference-list calls 403'd and the dropdowns had
  no options. HR now has read-only access to branches and roles (added to the seed and granted
  on the live DB). *Permissions are captured at login, so an HR user must sign out and back in
  (or wait for the token to refresh) for the dropdowns to populate.*
- **The system-admin row can no longer be deactivated or deleted from the HR portal.** Those
  two action buttons are hidden for `admin`-role rows when viewed in the HR portal (still
  available in the Admin portal).

### Fixed / Changed (continued, batch 3)
- **Late-arrival notification shows hours + minutes.** The in-app/email/WhatsApp LATE_ARRIVAL
  message said "You arrived 90 minute(s) late"; it now reads "You arrived 1h 30m late" (helper
  `_fmt_minutes`).
- **Correction & reimbursement proofs open in a popup, not a new page.** Correction proofs
  (Admin/HR attendance, Manager approvals, Employee corrections) and reimbursement receipts
  (Manager approvals, HR/Admin management) now open in the same image popup used for attendance
  proofs, instead of navigating to a separate tab. PDFs get a clean "Open PDF document" tile.
- **Clicking a proof image opens it full-size in a new tab** — in the popup, the image (or
  "Open in new tab" link) opens the original; applied to the attendance entry/exit proof too.

### Fixed (continued, batch 2)
- **Attendance correction proof now shows in the Admin portal.** The Admin attendance
  Corrections table was missing the proof column (HR's had it); it now shows a "View" link to
  the employee's uploaded correction proof.
- **Pending badges now show on Admin/HR (not just Manager).** They previously counted only the
  HR stage, so they read 0 while items sat at the manager stage. Admin/HR badges now count
  everything still pending (manager *or* HR stage — since a higher role can finalise either);
  managers still count their own department stage.
- **Holidays and manual attendance changes are audited.** Any holiday **add/edit/delete** (by
  HR or Admin) and manual attendance-event entry now write an `audit_logs` row with the actor
  (the attendance *override* was already audited). Holiday endpoints now record the acting user.

### Added (continued, batch 2)
- **Instant backup download.** Admin → Settings → Data has a **"Download Backup Now"** button
  again (`GET /api/v1/system/data/backup/download`) that streams a fresh `.dump` to the browser
  — written to a temp file and deleted after sending, so nothing is kept on the server. This is
  in addition to the automatic month-end backup.

### Fixed (continued, batch)
- **Error alerts now show the real reason.** The API client rejected the raw Axios error, so
  toasts read "Request failed with status code NNN". The response interceptor now surfaces the
  backend's `error` message (e.g. "Employee with this email or code already exists") as the
  Error message, so every alert explains *why* the request failed.
- **Manager approvals showed nothing.** The manager approvals queries used uppercase status
  values (`PENDING`, `PENDING_MANAGER`) but the enums are lowercase (`pending_manager`), so they
  422'd and returned empty. Fixed to `pending_manager`.
- **Excel exports show late/overtime as hours + minutes.** The attendance report (team reports
  etc.) printed raw "Late Minutes"/"Overtime Minutes"; columns are now "Late Time"/"Overtime"
  formatted like `1h 30m` (helper `_hm`).

### Added (continued)
- **Pending-approval count badges in the sidebar (all portals).** Red count badges now appear on
  the nav — **Approvals** (Manager), and **Leave / Reimbursements / Attendance** (HR/Admin) —
  showing items awaiting that portal's action (manager stage vs HR stage; manager counts are
  department-scoped). They clear as items are approved. Centralised in `PortalLayout`.
- **Saturday weekly-off toggle.** Admin/HR → Holidays has a "Saturday is a weekly off" switch
  (Sunday is always off). Backed by policy `attendance.saturday_off` via holiday-gated
  `GET/PUT /system/weekend-config` (so HR can set it without `system:write`); the attendance
  engine marks Saturdays WEEKEND only when it's on.

### Changed (continued)
- **Backups are automatic-only (month-end), named by month.** Removed the in-app "Take Backup"
  button and the server-side backup list/create/download endpoints. The Celery beat still backs
  up at month-end, now saved as `backup_<Month>_<Year>.dump` in the `backups` folder; restore is
  only via uploading a `.dump`.
- **Managers are now scoped to their own department.** A manager tracks only the
  `employee`-role staff in the **same department** as the manager (set via the manager's
  `department_id`). Applied consistently across the manager portal:
  - **Team / Dashboard / Reports** roster (`/employees/{id}/direct-reports`) now returns the
    manager's department members (was `manager_id` direct-reports), and a manager can only
    request their own team.
  - **Attendance** (`/attendance/daily`), **leave** (`/leave/requests`), **reimbursement**
    (`/reimbursements`), and **corrections** (`/attendance/corrections`) lists are filtered to
    the manager's department. HR/Admin remain unrestricted; employees still see only their own.
  - **Approve/reject guards**: a manager can only approve/reject leave, reimbursement, and
    correction items for employees in their department (defense-in-depth beyond the filtered
    lists). A new `app/core/scoping.py` centralises the `visible_employee_ids` logic.
  - *Setup:* assign each manager a Department (Admin/HR → Employees → edit → Department). A
    manager with no department sees an empty team until one is assigned.
- **HR and Admin employee sections are now one shared screen.** They were two separate pages
  that had drifted apart; both now render a single `EmployeeManagement` component, so the table
  columns and the **Add/Edit Employee form are identical** in both portals. Also:
  - The internal **`service` role is hidden** from the Add/Edit role dropdowns (it's the
    face-service machine account and must never be assigned to a person).
  - The **Active/Inactive "Status" column was removed**; active/inactive is now shown by the
    action icon (and still filterable). That icon is an **activate/deactivate toggle** in both
    portals — HR keeps the ability to reactivate, and Admin gained it.

### Fixed (continued)
- **Employees table now shows each person's *today's attendance* status, not their account
  state.** The HR employees "Status" column derived Present/Absent from `is_active` (the account
  flag), so everyone active showed **Present** regardless of whether they'd actually checked in.
  Both the HR and Admin employees tables now have a **"Today"** column driven by the day's
  `daily_attendance` — Present / Late / Half Day / On Leave / Absent (Absent = no check-in yet).
  Admin accounts show "—" (they aren't attendance-tracked). The Admin table keeps its separate
  Active/Inactive account column.
- **Admin accounts no longer appear in attendance records.** System-administrator accounts aren't
  attendance-tracked staff, so they were being materialised as ABSENT and listed alongside
  employees. The nightly materialisation and `list_daily` now exclude the `admin` role (as they
  already did `service`), and existing admin attendance rows were soft-deleted.
- **Audit log now captures attendance overrides, and all leave/reimbursement actions.**
  Previously only employee edits/deletes, device deletes, the selfie flag, HR's *correction*
  approval, and HR's *final* leave approval were logged — so a direct **manual attendance
  override**, and every **leave/reimbursement create, approve, reject, pay, or cancel** by an
  admin/HR/manager, left no trace. Now:
  - `manual_override` writes one `daily_attendance` audit row (before → after check-in/out +
    status, with the actor) for **every** manual attendance change — the direct override *and*
    the correction-approval path (the old duplicate audit in the correction path was removed).
  - **Leave**: apply (CREATE), manager-approve, HR-approve, reject, cancel all audited.
  - **Reimbursement**: submit (CREATE), manager-approve, HR-approve, reject, mark-paid, cancel
    all audited.
  - A shared `audit_service.record_audit(...)` helper backs the new sites. Each row records the
    acting user and the status before → after, so who-did-what is fully traceable in
    Admin → Audit Logs.
- **`LATE_ARRIVAL` notification was sent twice.** It fired inside `process_event`, which runs
  on **every** attendance event, so a late employee who checked in (ENTRY) *and* checked out
  (EXIT) got two identical "Late Arrival" notifications (seen most easily via selfie check-in
  then check-out). It now fires **only on the ENTRY** (the arrival). Reviewed every other
  notification source — leave/reimbursement/payroll/correction each fire once per action, and
  reimbursement's repeated `REIMBURSEMENT_UPDATE`s are legitimately distinct stages (pending →
  approved → paid), so nothing else was double-sending. Existing duplicate `LATE_ARRIVAL` rows
  were de-duplicated (kept the earliest per employee/day).

### Changed
- **Restore now lets you choose *which* backup to restore.** The Restore card (Admin → Settings
  → Data) has a dropdown of all available backups (newest first, with date/size); "Restore
  Selected Backup" restores the chosen one. `POST /api/v1/system/data/restore` accepts an
  optional `{ filename }` (omitted = most recent, as before); the filename is validated against
  the backups directory (regex + existence) before any restore runs.
- **Restore is now upload-only (a `.dump` file), and the server-side-list restore was removed.**
  Restoring from the list of on-machine backups (dropdown + `POST /api/v1/system/data/restore`)
  is gone; the Restore card now only accepts a `.dump` file uploaded from the admin's computer
  via `POST /api/v1/system/data/restore/upload`. The upload validates the file is a real
  custom-format pg_dump (`PGDMP` magic, size cap), stores it, then restores it. nginx
  `client_max_body_size` raised to 256 MB so a full dump can be uploaded (the backend still
  enforces per-endpoint limits; proof uploads stay at 10 MB). Backups are still downloaded and
  auto-created monthly — only the restore *source* changed.
- **HTTPS/DuckDNS self-heals instantly on a network change.** The `AttendanceHTTPS` scheduled
  task (which repoints the DuckDNS A record to the PC's current LAN IP) previously only ran at
  logon + daily, so a mid-session DHCP IP change left the domain stale until the next run. It now
  also has an **on-network-connect** trigger (NetworkProfile event 10000) — a Wi-Fi reconnect /
  wake / reboot re-runs `-Sync` within seconds. Baked into `setup-https.ps1` for new installs.
  Also added **`update-ip.bat`** to the delivery folder: a double-click that runs `-Sync` on
  demand to point the domain at the PC's current IP (bundled by `vendor/package.ps1`).
- **Grace period is now a real Settings default with per-branch override (was a dead
  duplicate).** "Grace Period (minutes)" existed in both Admin → Branches and Admin →
  Settings, but the late-detection engine only ever read the per-branch column — the
  Settings value (`attendance.grace_period_minutes`) was inert, so changing it did nothing.
  Now the engine resolves the *effective* grace as: the branch's own value if it sets one
  (0 = truly no grace), otherwise the org-wide Settings default (falling back to
  `settings.DEFAULT_GRACE_PERIOD_MINUTES` = 15 if the policy is missing).
  `branches.grace_period_minutes` is now **nullable** (Alembic `a1b2c3d4e5f6`): NULL =
  inherit. In Admin → Branches the grace field is optional (blank = "use the default",
  shown as *Default* in the table); the Settings field is relabelled **"Default Grace
  Period"** and now actually drives late-detection. Existing branches keep their stored
  values, so no branch's behaviour changes on upgrade — inheritance is opt-in by clearing
  the field. The redundant, never-wired **"Late Threshold (minutes)"** field was removed
  from Settings (it described the same thing as grace and the engine never used it).
- **"Take Backup" now downloads the backup file to the admin's computer.** Previously the
  button only wrote a `.dump` into the server's `backups` folder. Admin → Settings → Data
  now streams the backup to the browser as a normal file download (Save/"Save As"),
  pre-named `attendance-backup-<date>_<time>.dump` — via a new
  `GET /api/v1/system/data/backup/download` (FileResponse, `Content-Disposition:
  attachment`). A server-side copy is still kept, so **Restore Last Backup** and the
  automatic month-end backup stay in sync with what was downloaded.
- **Employee role names display consistently.** Roles are stored lowercase; the Admin/HR
  employee add & edit forms and the role column now show them title-cased via a shared
  `formatRoleName` helper, with **HR** kept fully uppercase (e.g. `hr → HR`, `admin → Admin`).
- **The "Late" column shows hours + minutes.** The HR/Admin attendance tables rendered raw
  minutes (`+90m`); they now use `formatMinutes`, so it reads `+1h 30m` (the employee
  attendance calendar already did).
- **Late duration is now measured from office start, not from the end of grace.** Grace still
  decides *whether* a check-in counts as late (must be after `office_start + grace`), but once
  it's late the minutes are counted from the actual office start time. e.g. 09:00 start,
  15-min grace, check-in 09:20 → late, `late_minutes = 20` (previously reported 5). Late-day
  *counts* (and therefore payroll penalties) are unchanged — only the displayed/notified
  duration changed.
- **Payroll penalty config is now edited in one place (Settings).** The Payroll section's
  editable "Policy Config" tab duplicated the four penalty settings that also live in
  Admin → Settings → Attendance Rules (both wrote the same `payroll.*` policies). The Payroll
  tab is now a **read-only** summary that shows the current values and points to Settings —
  mirroring the grace-period fix (single source of truth). The `/payroll/policy` read endpoint
  still backs the display; nothing writes penalty config from the Payroll screen anymore.
- **Leave & Reimbursements default filter is now "All".** Both shared management screens
  (Admin/HR/Manager) opened filtered to "Awaiting HR Approval", hiding everything else until
  you changed the dropdown; they now default to showing all requests.
- **Creating an employee is now recorded in the audit log.** Only employee *edits* and
  *deletes* were audited; a new hire wrote no audit row. `create_employee` now writes a
  `CREATE` entry on `employees` (actor + the new record's fields, never the password), so it
  shows up in Admin → Audit Logs like edits and deletes.
- **Attendance proof viewer now shows the exit image too, not just entry.** The HR/Admin
  attendance "view proofs" modal only ever rendered the first proof (entry), even though the
  backend returns every proof for the day. `ProofImageModal` is now a navigable multi-image
  viewer (prev/next + Entry/Exit chips); the HR & Admin tables pass the full proof list. The
  single-image callers (employee attendance/dashboard) are unchanged.
- **Selfie liveness is now direction-matched (harder to fool with a replayed video).**
  Previously the head-movement challenge was cosmetic — the face service only checked that
  the head *moved at all*, so circles/shaking (or any head-movement video) passed regardless
  of the prompt. The client now picks a random side (**LEFT/RIGHT**), sends it with the burst,
  and the face service verifies the head actually turned **that** way: it takes the dominant
  signed-yaw excursion, requires it to exceed a magnitude threshold **and** clearly dominate
  the opposite side (so symmetric circle/shake motion fails), and matches it to the prompt.
  A generic replayed video only matches the random prompt by luck. New face-service env knobs:
  `SELFIE_REQUIRE_DIRECTION` (default on), `SELFIE_DIR_THRESHOLD` (0.12), `SELFIE_DIR_DOMINANCE`
  (1.5), and `SELFIE_YAW_SIGN` (flip to `-1` if a camera rig proves inverted). *Note:* this
  raises the bar but isn't a full anti-spoof — a targeted attacker with per-direction clips
  could still match; passive MiniFASNet anti-spoof remains the defense against that (still off
  by default due to false-rejects).

---

## [1.2.1] — 2026-06-25

### Fixed
- **The face-service machine account no longer appears as an employee.** The
  `face-service@attendance.app` account (role `service`) exists only so the
  face-recognition microservice can authenticate — it now gets filtered out of employee
  lists/counts, the nightly attendance materialization, payroll calculation, and the
  attendance/payroll reports, so it can't show up as an "employee" or be marked absent.
- **Refreshing any page logged the user out (bounced to /login), and approvals didn't
  appear without a manual refresh.**
  - *Logout on refresh:* a page reload reset the in-memory auth store, and the protected
    pages redirected to /login before the session could be restored (the token in
    sessionStorage was never re-hydrated on those pages). A new root `AuthBootstrap` now
    restores the session on load — it calls `/auth/me` (auto-refreshing the token via the
    HttpOnly refresh cookie if expired) and gates rendering behind an `initialized` flag,
    so pages no longer bounce to login on refresh.
  - *No live updates:* the React Query client had `refetchOnWindowFocus: false` and no
    polling, so an approval in the admin/HR/manager portal wasn't reflected in the employee
    portal until a manual refresh. It now refetches on window/tab focus and polls every 20 s
    while focused, so status changes propagate on their own within seconds. (No WebSockets —
    lightweight polling suits the ≤20-user scale.)
- **The employee "Cancel" button on leave requests never appeared.** It was gated on
  `status === "PENDING"`, but the enum is lowercase (`pending_manager`/`pending_hr`); the
  gate and the status timeline now use the real values, so pending leave can be cancelled.
- **HR/Admin attendance tables now show recent days (e.g. an employee's just-marked
  attendance).** The daily list was ordered by DB insertion time (`created_at`) and capped
  at 100 rows, so a whole-company date range could push the newest days past the cap /
  scatter a day's rows across pages — making a fresh check-in look "missing" for HR/Admin
  even though the employee saw it. `list_daily` now orders by attendance **date
  (descending)** with a higher row cap, and the HR/Admin tables also sort by date.
- **Attendance status badges were hard to read / could break layout.** "PENDING_CORRECTION"
  (and other long labels) rendered in ALL‑CAPS and could wrap inside the pill; the badge is
  now Title‑Case with `whitespace-nowrap`, and the previously‑uncoloured `pending_manager` /
  `pending_hr` states got proper colours.
- **Employee reimbursement claims returned HTTP 422 on submit.** The claims form sent
  display labels (`Travel`, `Meals`, `Office Supplies`, `Training`, `Communication`) as the
  `category`, but the API validates the `ReimbursementCategory` enum by value
  (`travel`, `food`, `accommodation`, `medical`, `office_supplies`, `other`). The form now
  submits the enum value and shows a friendly label; the category list was aligned to the
  six real categories. Frontend-only change (`employee/claims/page.tsx`).
- **Employee attendance summary now includes Half Day, with counter/calendar colours
  matched.** The summary counters were missing a HALF_DAY tile, and "Late" was tallied by
  the `is_late` flag while the calendar colours by `status` — so a late half-day appeared
  orange in the calendar but was counted in the yellow "Late" box. All counters are now
  `status`-based (Present/Late/Half Day/Absent/Leave), so each tile's colour matches that
  day's colour in the calendar (lateness still shows as the "LATE" tag on the cell and in
  the day drawer). Frontend-only change (`employee/attendance/page.tsx`).
- **Attendance corrections showed the wrong requested check-in/out time (off by the IST
  offset).** The submit helper parsed `new Date("YYYY-MM-DDTHH:MM")` in the browser's local
  zone and then subtracted 5h30m again, so on an IST machine a 09:00 entry was stored — and
  shown back — as 03:30. `istToUTC` now builds the instant from parsed components via
  `Date.UTC`, independent of the browser timezone. Frontend-only (`employee/corrections/page.tsx`).
- **Leave status filter was broken in the HR portal.** It sent `MANAGER_APPROVED`/`PENDING`
  (and uppercase `APPROVED`) but the `LeaveStatus` enum is lowercase
  (`pending_manager`/`pending_hr`/`approved`/…), so the default filter 422'd and the
  approve buttons never rendered. Now uses the real enum values in both the filter and the
  action gate (fixed once in the shared component, so HR and Admin both benefit).

### Added
- **Data management in Admin → Settings → Data.** Three admin-only tools (guarded by
  `system:write`):
  - **Backup** — a full `pg_dump` (custom format) of the database, saved to the host
    `backups/` folder. Also runs **automatically at the end of every month** (Celery beat).
  - **Restore last backup** — a full `pg_restore` that replaces all current data with the
    most recent backup. Uses the schema-exact dump, so there is no schema mismatch. The
    endpoint commits its own request first (releasing table locks) and runs with a bounded
    `lock_timeout`, so it can't deadlock against the live app; benign client/server version
    notices are ignored. Confirmation dialog required.
  - **Delete all data** — wipes all attendance, leave, reimbursements, corrections,
    notifications, payroll, face data and audit logs, plus every employee except admins and
    the face-service account. Setup/config (branches, roles, leave types, policies, devices)
    and the admin login are kept. Requires a type-**DELETE**-to-confirm dialog.
  - Needs the PostgreSQL client tools — added to the backend image; a `./backups` volume is
    mounted on the backend + worker. Verified end-to-end: backup → delete-all (18→2
    employees) → restore (fully back, API queries OK, no schema mismatch).
- **Employees can withdraw their own pending requests.** Cancel/delete controls now appear
  on pending **leave** requests, **reimbursement** claims, and **attendance corrections**
  (only while still awaiting approval; blocked once approved). New endpoints:
  `DELETE /reimbursements/{id}` and `DELETE /attendance/corrections/{daily_id}` (+ the
  existing leave `cancel`), all ownership-checked.
- **Grouped, collapsible sidebar.** Long sidebars are now organised into collapsible
  sections (Admin: *Workforce / Devices / Organization / System*; HR: *Workforce*) that
  auto-expand on the active page. The employee bottom-nav is unchanged.
- **Leave, Reimbursements and Payroll now in the Admin portal**, alongside the existing
  HR portal. Each screen was extracted into a shared component
  (`LeaveManagement`/`ReimbursementManagement`/`PayrollManagement`) rendered by both the
  HR and Admin pages, so the two portals stay in lockstep (single source of truth).
- **Hierarchical direct approval.** A higher role can finalize an item still waiting on a
  lower step: HR **or** Admin can directly approve a request awaiting *manager* approval,
  and Admin can approve one awaiting *HR*. Implemented by relaxing the `hr-approve`
  finalize path (leave, reimbursement, attendance-correction) to accept the manager stage
  too, guarded so **managers cannot self-finalize** (new `require_hr_tier_final_approval`;
  HR/Admin are distinguished from managers by the `employees:write` permission). Verified:
  HR & Admin finalize a manager-pending leave/claim; Manager gets 403.
- **Per-employee salary + percentage-of-a-day late-penalty model.** Replaces the flat
  "₹X per excess late" scheme. Each employee now has a **gross monthly salary**
  (`employees.monthly_salary_paise`, INTEGER paise), entered on the Add/Edit Employee form
  in both the HR and Admin portals. The monthly late deduction is now:
  `units = late_count ÷ N`, `gross_days = units × P%`, `net_days = max(0, gross_days − G)`,
  `deduction = net_days × (monthly_salary ÷ D)` — where **N** = late days per penalty (3),
  **P** = percent of a day per penalty (50), **G** = grace days per month (1.5), **D** = salary
  days per month (30). All four parameters are editable in **Admin → Settings → Attendance**
  (and HR → Payroll → Policy). Example: ₹30,000/mo, 12 lates → 4 units → 2.0 days − 1.5 grace
  = 0.5 day → **₹500**. Money stays INTEGER paise (penalty-days as integer centidays). New
  Alembic `f1a2b3c4d5e6`; both calculators (on-demand API + monthly Celery beat) and all three
  report generators updated; PAYROLL_DEDUCTION notification reworded. Verified: payroll unit
  tests + full 15/15 E2E green.
- **Optional proof upload on attendance-correction requests.** Employees can attach a
  supporting image/PDF (≤10 MB) when submitting a correction; it is stored privately in
  MinIO under `corrections/{daily_id}/` and surfaced as a presigned `proof_url`. New endpoint
  `POST /attendance/corrections/{daily_id}/proof`; the proof is shown as a "View proof" link
  in the employee list and to the approvers (Manager approvals queue + HR attendance
  corrections table). No DB migration — the proof path is stored in the correction JSON.

### Changed
- **A pending correction no longer hides the day's real status.** Submitting an attendance
  correction used to overwrite the day's status with `PENDING_CORRECTION`, so e.g. a genuine
  half-day was masked while the request sat in the queue. The day now keeps its **computed
  status** (HALF_DAY / ABSENT / …) while the correction is pending — and only changes when
  the correction is **approved** (to the corrected status). Corrections are still surfaced in
  the Corrections tab and the employee's page (found via the request data, not the status).
  Existing stuck `PENDING_CORRECTION` rows were recomputed to their real status.
- **Absence alerts replace daily "attendance marked" notifications.** A normal on-time
  check-in no longer generates any notification — that previously emailed/messaged every
  employee every working day. Notifications are now exception-only:
  - The nightly attendance-materialization beat task (00:30 IST) now emits a new
    **`ABSENT_ALERT`** notification for any employee marked **ABSENT** for the day that
    just ended. It fires only on a *fresh* transition to ABSENT and is guarded against
    duplicates, so re-running/backfilling never re-blasts old absent days.
  - `LATE_ARRIVAL` (on a late check-in) and the leave/reimbursement/payroll/correction
    events are unchanged. The in-app feed still records every notification; WhatsApp →
    Email is the same one-channel cascade.
  - New `ABSENT_ALERT` value on the `notification_event` enum (Alembic `e0f1a2b3c4d5`).
  - Verified: 15/15 E2E green; `ABSENT_ALERT` confirmed to fire once per absent employee
    on the nightly run and not duplicate on re-run.

---

## [1.2.0] — 2026-06-19

Adds a third attendance method on top of the fixed cameras and ZKTeco device. All 12
E2E integration tests pass against a from-scratch rebuild; the new flow was verified
end-to-end (enroll → liveness → 1:1 match sim≈0.99 → ENTRY/optional EXIT → audit).

### Added
- **Self-service selfie check-in (LAN-gated, buddy-punch-resistant)** — employees mark
  their own attendance from a phone via **Employee portal → Check In**:
  - New face-service endpoint `POST /verify-selfie` runs **passive anti-spoofing**
    (MiniFASNet) + **active liveness** (a random head-movement challenge verified from a
    keypoint yaw-proxy across a burst of frames) and returns the most-frontal embedding.
  - New backend `POST /attendance/selfie-checkin` (+ `GET /attendance/selfie-config`):
    **1:1 match** against the caller's own enrolled face (reuses the existing threshold),
    stores the selfie proof to MinIO, and records the event. First selfie of the day =
    **check-in**; **check-out is optional**.
  - **Flag & audit LAN gate** — `SELFIE_ALLOWED_SUBNETS` (default: any private/loopback
    counts as on-LAN). Off-LAN check-ins are recorded, not blocked, and flagged in
    `audit_logs` with the source IP + match similarity.
  - New `SELFIE` value on the `attendance_source` enum (Alembic `d8e9f0a1b2c3`); new
    Employee portal **Check In** page + dashboard CTA.
  - Requires HTTPS for phone camera access (mkcert on LAN); `http://localhost` works on
    the host.
  - **Admin toggle** in **Settings → Attendance** ("Self-service selfie check-in") writes
    the `selfie.enabled` policy (default on); the employee Check In page reflects it.
  - **Passive anti-spoofing defaults ON for the selfie path** (`SELFIE_ANTISPOOF_ENABLED`,
    independent of the camera `FACE_ANTISPOOF_ENABLED`): uses a MiniFASNet model when
    present, fails open otherwise (active liveness still applies).
  - **`setup-antispoof.ps1` / `setup-antispoof.sh` helper** + bind-mounted
    `./models/antispoof` → `/opt/insightface/antispoof` (both compose files) so operators
    can drop in the MiniFASNet ONNX for true passive liveness. The helper copies local
    files (`-FromDir`) or downloads from a vendor-pinned URL **with mandatory SHA-256
    verification**, then restarts the face service. Models are third-party (not bundled);
    `package.ps1` ships the `models/antispoof` dir in `dist/`.
  - **`vendor/convert-minifasnet.py`** — converts the official Silent-Face MiniFASNet
    `.pth` weights to the exact `<scale>_<h>x<w>_<Type>.onnx` files this service loads
    (imports the architecture from a local clone of the upstream repo so weights always
    match). Outputs single self-contained `2.7_80x80_MiniFASNetV2.onnx` +
    `4.0_80x80_MiniFASNetV1SE.onnx`. The converted models are kept in the vendor store
    (`vendor/antispoof-models/`) and **bundled into `dist/models/antispoof` by
    `package.ps1`**, so delivered systems get passive liveness out of the box; the in-repo
    runtime dir stays empty so photo-based tests remain valid.

### Tests
- **Selfie check-in audits** (all green): `tests/integration/test_selfie_checkin.py`
  (9 contract audits — auth, config shape, admin toggle + RBAC, disabled gate,
  enrollment requirement, bad input) runs with the host suite (**21 passed** total);
  `tests/audits/audit_selfie_liveness.py` (7 face-driven audits — enroll, passive+active
  liveness, no-face rejection, ENTRY source=selfie, optional EXIT, cooldown guard, flag &
  audit log) runs inside the face container:
  `docker compose exec -T face-recognition python - < tests/audits/audit_selfie_liveness.py`.

### Added (HTTPS without per-phone certificates)
- **`setup-https.ps1`** — one-command trusted HTTPS for phone selfie check-in with
  **nothing to install on any phone**. Uses a free DuckDNS subdomain + a Let's Encrypt
  cert via DNS-01 (pure-PowerShell **Posh-ACME** + its DuckDNS plugin — no Python/certbot):
  points the subdomain's A record at the host LAN IP, issues the cert into
  `nginx\certs\attendance.crt/.key`, flips `.env` to `DEPLOYMENT_MODE=local-ssl` +
  `BASE_URL=https://<domain>`, restarts nginx, and registers a weekly auto-renewal task.
  LAN-IP detection prefers the adapter with a default gateway (skips Docker/WSL virtual
  adapters). Shipped in `dist\`.

### Fixed (found by an isolated dist-folder acceptance test)
- **LAN/phone access was broken:** the frontend baked an absolute `http://localhost/api/v1`
  into the client bundle (Next.js inlines `NEXT_PUBLIC_*` at build time, and the Dockerfile
  never set it), so the app only worked on the host PC. Now defaults to a **relative
  `/api/v1`** (same-origin via nginx) — works on localhost, any LAN IP, and HTTPS — plus a
  real `NEXT_PUBLIC_API_URL` build arg for cloud overrides.
- **First-run secret generation crashed on Windows PowerShell 5.1:** `gen-env.ps1` used
  `RandomNumberGenerator::GetBytes(int)`, a .NET-Core-only static method absent on the
  default customer shell. Replaced with the instance API that works on 5.1 and 7.
- **Packaging shipped a stale frontend:** `package.ps1`'s `docker compose build` served a
  cached frontend image (re-baking the wrong API URL). The frontend is now built with
  `docker build --no-cache` so the delivered image always matches source.

## [1.1.0] — 2026-06-16

Hardening + UX upgrades on top of 1.0. All 12 E2E integration tests pass against
a from-scratch rebuild; face-service load test passes (0 errors, ~80 req/s).

### Added
- **Password reset flow** — `POST /auth/forgot-password` + `POST /auth/reset-password`
  with a new `password_reset_tokens` table (Alembic `c7d8e9f0a1b2`), SHA-256-hashed
  single-use tokens (1 h TTL), SMTP email (falls back to logging the link when SMTP
  is unconfigured), and frontend `/forgot-password` + `/reset-password` pages. The
  login page now links to it. No account enumeration (generic response either way).
- **Face anti-spoofing (liveness)** — optional CPU-only MiniFASNet ONNX check in the
  face service (`FACE_ANTISPOOF_ENABLED`, default off; `src/antispoof.py`), wired into
  the pipeline before an event fires. Fails open if enabled without a model so a
  misconfig never blocks attendance. Rejects printed-photo / screen-replay spoofs.
- **Device heartbeats** — `POST /devices/{id}/heartbeat`; events stamp `last_heartbeat`,
  and the face service heartbeats each running camera (`ENTRY/EXIT_CAMERA_DEVICE_ID`)
  so the admin dashboard reflects real camera liveness.
- **Multi-photo face enrollment** — HR portal accepts multiple photos per employee in
  one go (sequential upload); enroll/delete now nudge the face service to reload its
  embedding cache immediately instead of waiting for the 5-min refresh.
- **nginx rate limiting** — strict zone on `/auth/login` (brute-force defence), plus
  `api` and `biometric` zones; returns HTTP 429 when exceeded. Added the missing
  `/media/` proxy to `cloud.conf`.
- **Biometric webhook hardening** — `BIOMETRIC_REQUIRE_REGISTERED_DEVICE` (default off)
  rejects pushes whose serial isn't a registered device (403).

### Changed
- Setup scripts (`setup-local.sh`, `setup-windows.bat`) now generate strong random
  secrets for `SECRET_KEY`, `POSTGRES_PASSWORD`, `MINIO_SECRET_KEY`, and
  `SERVICE_ACCOUNT_PASSWORD` (keeping `DATABASE_URL` in sync) instead of shipping the
  `.env.example` placeholders.
- `ApiResponse.ok()` gained an optional `message` field (backward-compatible).

### Fixed
- `record_heartbeat` re-fetches with the branch eager-loaded to avoid an async
  lazy-load 500 on the `updated_at` column after the UPDATE.

---

## [1.0.0] — 2026-06-11

Initial production release. All 14 internal audits (A1–A14) passed plus
load testing, HTTPS setup, integration validation, and operational scripts.

---

### Summary of what was built

| Component | Details |
|---|---|
| Backend | FastAPI (Python 3.12), SQLAlchemy 2.0 async, Alembic migrations, Pydantic v2, JWT (access 15 min + refresh 7 days), RBAC middleware |
| Database | PostgreSQL 16 — 21 tables, UUID PKs, soft-delete, audit triggers |
| Frontend | Next.js 14 App Router, TypeScript, Tailwind CSS + shadcn/ui — 4 portals (employee, manager, hr, admin), 30 routes |
| Face Service | InsightFace ONNX INT8 + ByteTrack + OpenCV — RTSP stream reader, 5 FPS, 95% confidence threshold, 5 min cooldown |
| Celery | Redis-backed async task queue — notifications (WhatsApp/Email/in-app), payroll deduction batch, report generation |
| Storage | MinIO (S3-compatible) — proof frames, reimbursement receipts; presigned URLs via Nginx proxy |
| Infrastructure | Docker Compose (8 services), Nginx reverse proxy, bind-mount TLS certs, resource limits enforced |
| Notifications | Wati.io WhatsApp → SMTP email → in-app fallback; offline queue with Celery retry (5 min, max 3 attempts) |
| Integrations | ZKTeco K40 biometric (ADMS push), CP Plus cameras (RTSP), Wati.io WhatsApp |

---

## Fixes by Audit

### A1 — Infrastructure Audit (2026-06-06)

**Fixed: HEAD method not registered on `/api/v1/health`**
- `GET /api/v1/health` worked but `HEAD` returned 405; Nginx uses HEAD for healthchecks
- File: `backend/app/api/v1/routers/health.py`
- Fix: Changed `@router.get` to `@router.api_route(methods=["GET", "HEAD"])`

**Fixed: Celery-worker healthcheck stuck in "starting"**
- `${HOSTNAME}` in the `CMD` healthcheck expanded to empty string on the host before the container ran it
- File: `docker-compose.yml`
- Fix: Changed to `CMD-SHELL` with `$$HOSTNAME` so the container shell expands it at runtime

---

### A3 — Auth + RBAC Audit (2026-06-06)

**Fixed: `GET /leave/requests` returned all employees' records to any authenticated user**
- Any employee could read every leave request in the system
- File: `backend/app/api/v1/routers/leave.py`
- Fix: Force `employee_id = current_user.id` when caller lacks `employees:read` / `admin:*`

**Fixed: `GET /attendance/daily` returned all records to any employee**
- File: `backend/app/api/v1/routers/attendance.py`
- Fix: Added `_can_see_all()` helper; employees are silently scoped to their own ID

**Fixed: `GET /attendance/daily/{emp_id}/{date}` had no ownership check**
- Any employee could read any other employee's attendance record for a specific day
- File: `backend/app/api/v1/routers/attendance.py`
- Fix: Added 403 guard when `employee_id != current_user.id` and caller lacks manager/HR access

**Fixed: `GET /attendance/events` returned all events to any employee**
- File: `backend/app/api/v1/routers/attendance.py`
- Fix: Scoped to own employee ID for non-privileged callers

**Fixed: `GET /attendance/corrections` comment said "filter by self" but was never implemented**
- File: `backend/app/api/v1/routers/attendance.py`
- Fix: Added own-ID filter for employees

---

### A4 — Attendance Engine Audit (2026-06-06)

**Fixed: No cooldown guard — duplicate events within 5 minutes were accepted**
- Sending the same ENTRY event twice within 5 minutes created two check-in records
- Files: `backend/app/services/attendance_service.py`, `backend/app/core/config.py`
- Fix: Added Guard 1 in `process_event()`: query same `event_type` within `ATTENDANCE_COOLDOWN_SECONDS` (default 300); raise 422 on duplicate

**Fixed: No sequence validation — ENTRY→ENTRY was accepted**
- Employee could trigger two consecutive ENTRY events without an EXIT between them
- File: `backend/app/services/attendance_service.py`
- Fix: Added Guard 2 in `process_event()`: when event is ENTRY, query last event today; raise 422 if last event was also ENTRY

---

### A5 — Leave Management Audit (2026-06-06)

**Fixed: `hr_approve()` never wrote `ON_LEAVE` status to `daily_attendance`**
- Approved leave was not reflected in daily attendance records — employee showed ABSENT instead of ON_LEAVE
- File: `backend/app/services/leave_service.py`
- Fix: Added `_mark_on_leave()` helper called in `hr_approve()` and auto-approved `apply()`

**Fixed: `cancel()` left `daily_attendance` as `ON_LEAVE` after cancellation**
- Cancelling an approved leave request left the employee appearing on leave for those days
- File: `backend/app/services/leave_service.py`
- Fix: Added `_revert_on_leave()` helper called in `cancel()` when `was_approved=True`

**Fixed: Insufficient leave balance silently allowed request creation**
- Employee could request more leave days than their balance — request was created with no error
- File: `backend/app/services/leave_service.py`
- Fix: Changed advisory warning to hard `UnprocessableError` 422 when balance insufficient

**Fixed: No half-day leave support**
- Leave days were stored as INTEGER; no way to request a half-day
- Files: `models/leave.py`, `schemas/leave.py`, `routers/leave.py`, `leave_service.py`, new Alembic migration
- Fix: Changed `INTEGER` columns to `NUMERIC(5,1)`; added `is_half_day` boolean; half-day deducts 0.5 and sets status `HALF_DAY`

**Fixed: Leave could be applied on public holidays**
- System allowed employees to apply for leave on holidays, wasting their leave balance
- File: `backend/app/services/leave_service.py`
- Fix: Added `holiday_calendar` query before overlap check; raises 422 naming the specific holiday

---

### A6 — Reimbursements, Corrections & Payroll Audit (2026-06-06)

**Fixed: `hr_approve_correction()` wrote no `AuditLog`**
- HR-approved attendance corrections left no record of who changed what
- File: `backend/app/services/attendance_service.py`
- Fix: Captured before values, inserted `AuditLog` (UPDATE, before/after check_in, `performed_by_id=hr_id`) after correction applied

**Fixed: No self-approval guard on correction requests**
- An employee who was also a manager/HR could approve their own correction request
- File: `backend/app/services/attendance_service.py`
- Fix: Added `if str(actor_id) == corr["requested_by"]: raise ForbiddenError` in both `manager_approve_correction()` and `hr_approve_correction()`

**Fixed: `calculate_deduction()` REST API did not fire `PAYROLL_DEDUCTION` notification**
- Notification was only sent from the Celery batch job, not from the API endpoint used by HR
- File: `backend/app/services/payroll_service.py`
- Fix: Added `_queue_payroll_notification()` call at end of `calculate_deduction()` when `excess > 0`

---

### A7 — Notifications + Celery Audit (2026-06-06)

**Fixed: 7 of 8 notification event types never triggered**
- `send_notification.delay()` was only called from the Celery payroll batch task; attendance, leave, reimbursement, and correction events were never notified
- Files: `attendance_service.py`, `leave_service.py`, `reimbursement_service.py`
- Fix: Added `send_notification.delay()` at the end of each relevant service function for events: `ATTENDANCE_MARKED`, `LATE_ARRIVAL`, `LEAVE_APPLIED`, `LEAVE_APPROVED`, `LEAVE_REJECTED`, `REIMBURSEMENT_UPDATE`, `CORRECTION_STATUS`

**Fixed: `notification:read` permission did not exist**
- All employees received 403 on every notification endpoint
- Fix: Created `notification:read` permission in DB; assigned to employee, manager, hr, admin roles

**Fixed: `PATCH /notifications/{id}/read` returned 500 (MissingGreenlet)**
- SQLAlchemy object accessed outside async context after flush
- File: `backend/app/services/notification_service.py`
- Fix: Added `await db.refresh(notif)` after `await db.flush()` in `mark_read()`

---

### A8 — Face Recognition Audit (2026-06-06)

**Fixed: Face-recognition container missing all ML packages**
- Image was built from an incomplete `requirements.txt`; numpy, opencv-python, insightface, onnxruntime, minio were absent
- Fix: Installed all packages in the running container; committed as `:patched` image; updated `requirements.txt` to include all dependencies

**Fixed: `pydantic_settings` import crashed face-service at startup**
- File: `face-service/src/config.py`
- Fix: Rewrote config using plain `os.environ` helpers (`_str`, `_int`, `_float`, `_bool`) — no external dependency, same `settings.X` interface

**Fixed: `api.py` was an empty stub — only `/health` registered**
- `/status`, `/reload-embeddings`, `/embed` endpoints were absent
- Files: `face-service/src/api.py`, `face-service/src/main.py`, all `src/*.py`
- Fix: Deployed all face-service source files; fixed `/embed` to use `request.form()` instead of `UploadFile=File(...)` to avoid python-multipart startup failure

**Fixed: `FACE_SERVICE_KEY` not in face-recognition service environment**
- Face service sent empty `X-Service-Key` to backend → 403 on all embedding API calls → embeddings never loaded
- File: `docker-compose.yml`
- Fix: Added `FACE_SERVICE_KEY: ${SECRET_KEY}` to face-recognition environment block

**Fixed: Camera URL env var mismatch**
- Docker Compose passed `CAMERA_ENTRY_URL`/`CAMERA_EXIT_URL` but `config.py` reads `ENTRY_CAMERA_URL`/`EXIT_CAMERA_URL`
- File: `docker-compose.yml`
- Fix: Fixed to `ENTRY_CAMERA_URL: ${ENTRY_CAMERA_URL:-}` and `EXIT_CAMERA_URL: ${EXIT_CAMERA_URL:-}`

**Fixed: Presigned URLs used internal `minio:9000` hostname**
- Presigned URLs returned to the browser contained `http://minio:9000/...` — not accessible outside Docker
- File: `backend/app/services/storage_service.py`
- Fix: Rewrote presigned URL base from internal MinIO endpoint to `{BASE_URL}/media/`; Nginx `/media/` proxy sets `Host: minio:9000` so HMAC signatures remain valid

**Fixed: Confidence threshold was static (env var only)**
- Updating `system_policies` in the Admin portal had no effect on the running face service
- Files: `face-service/src/recognizer.py`, `face-service/src/api.py`, `backend/app/api/v1/routers/face.py`
- Fix: Added `_reload_threshold()` method that fetches `face.*` policies via `GET /api/v1/face/policies`; called on every `_load_known_embeddings()`; `identify_face()` uses instance-level `self._threshold`

---

### A9 — Frontend Portals Audit (2026-06-07)

**Fixed: 24 TypeScript/ESLint build errors across 15 files**
- Errors: `no-unused-vars`, `no-empty-object-type` — build failed entirely
- Files: 15 frontend source files (UI components, hooks, portal pages)
- Fix: Removed unused imports/variables/interfaces; changed empty interfaces to type aliases

**Fixed: Frontend container serving Phase 1 stub (4-line JSON server)**
- The real Next.js app was never deployed to the container
- Files: `frontend/Dockerfile`, `frontend/next.config.mjs`, `frontend/.dockerignore`
- Fix: Replaced stub with 3-stage multi-stage Dockerfile; added `output: "standalone"` to `next.config.mjs`

**Fixed: `GET /api/v1/reports/attendance` returned 500**
- `ORDER BY employees.employee_code` was applied without the employees JOIN when no `branch_id` filter was given
- File: `backend/app/services/report_service.py`
- Fix: Moved `order_by(Employee.employee_code)` inside the `if branch_id` branch; bare date filter uses `order_by(DailyAttendance.date.desc())` only

---

### A10 — Multi-branch + Shifts Audit (2026-06-07)

**Fixed: No `/api/v1/shifts` CRUD router**
- Shift definitions had no management API; Admin portal could not create or edit shifts
- Files: `backend/app/api/v1/routers/shifts.py` (new), `backend/app/api/v1/router.py`
- Fix: Created full CRUD router: `GET/POST /shifts`, `GET/PATCH/DELETE /shifts/{id}`; protected by `branches:read` (list) and `admin:*` (write)

---

### A11 — Security + Audit Trail Audit (2026-06-07)

**Fixed: Manager role had `employees:read` — full company list exposed to managers**
- `GET /employees` returned 200 with all employee records for manager role
- Files: DB (runtime), `backend/app/api/v1/routers/employees.py`
- Fix: Removed `employees:read` from manager role in DB; changed `/employees/{id}/direct-reports` permission from `employees:read` → `attendance:read` so manager team-view still works

**Fixed: `/face/embeddings/all` returned 403 instead of 401 when `X-Service-Key` header was missing**
- Missing credentials should return 401 (unauthenticated), wrong credentials should return 403 (unauthorized)
- File: `backend/app/api/v1/routers/face.py`
- Fix: Added `if not x_service_key: raise UnauthorizedError(...)` guard before the wrong-key check; applied same fix to `/face/policies`

**Fixed: Employee update/delete wrote no `AuditLog`**
- No record of who changed employee records or what was changed
- Files: `backend/app/services/employee_service.py`, `backend/app/api/v1/routers/employees.py`
- Fix: Added `actor_id` param to `update_employee()` and `delete_employee()`; captures before-state dict, applies change, writes `AuditLog(UPDATE/DELETE, before_value, after_value, performed_by_id=actor_id)`

**Fixed: Leave HR approval wrote no `AuditLog`**
- No trace of who approved leave or what the status changed from/to
- File: `backend/app/services/leave_service.py`
- Fix: Added `AuditLog(table_name="leave_requests", action=UPDATE, before_value={"status": old_status}, after_value={"status": "approved", "hr_id": ...})` in `hr_approve()`

**Fixed: Malicious filename path traversal via reimbursement upload**
- `../../../etc/passwd.jpg` was stored verbatim in the DB `file_name` column
- File: `backend/app/api/v1/routers/reimbursements.py`
- Fix: Applied `os.path.basename()` to strip all directory path components before storing; also strips null bytes

---

### A12 — Reports + Exports Audit (2026-06-07)

**Fixed: `GET /reports/attendance/export` endpoint missing (404)**
- File: `backend/app/api/v1/routers/reports.py`
- Fix: Added endpoint accepting `start`/`end` query params, optional `branch_id`; defaults to CSV download

**Fixed: Attendance CSV column headers wrong**
- Columns had wrong names and order: "Employee Name" first (should be "Employee Code"), "Check-In (IST)" (should be "Check In"), "Is Late" (should be "Late"), "Overtime Minutes" (should be "Overtime")
- File: `backend/app/services/report_service.py`
- Fix: Rewrote `_ATT_HEADERS` and row construction in `_attendance_rows()` to match audit spec

**Fixed: `GET /payroll/deductions/report` returned 422**
- FastAPI matched literal string "report" as UUID for the `/{deduction_id}` wildcard route
- File: `backend/app/api/v1/routers/payroll.py`
- Fix: Added `GET /deductions/report` endpoint BEFORE `/{deduction_id}` in the router file

**Fixed: Payroll report — no `branch_id` filter, wrong currency symbol, no total row, redundant columns**
- Report had no branch isolation; used "Rs" instead of "₹"; no total-sum row; included Month/Year/Net columns not in spec
- File: `backend/app/services/payroll_service.py`
- Fix: Added `branch_id` param throughout the report pipeline; fixed headers to use ₹; removed redundant columns; added TOTAL row with SUM formulas

**Fixed: `GET /reports/leave/export` endpoint missing (404)**
- File: `backend/app/api/v1/routers/reports.py`
- Fix: Added endpoint with `start`/`end`/`branch_id` params; defaults to CSV download

---

### A13 — Setup Scripts Audit (2026-06-07)

**Fixed: `seed_db_full.py` — payroll policy key mismatch**
- Seed used `payroll.late_penalty_paise` but `payroll_service.py` reads `payroll.penalty_per_late_paise`
- The penalty was seeded but the payroll service always fell back to the default (policy key never found)
- File: `backend/seed_db_full.py`
- Fix: Changed seed key to `payroll.penalty_per_late_paise`

**Fixed: `seed_db_full.py` — manager role retained `employees:read`**
- A11 removed it from the live DB but the seed still listed it — fresh installs would expose full employee list to managers
- File: `backend/seed_db_full.py`
- Fix: Removed `employees:read` from `_ROLE_PERMS["manager"]`; added comment explaining `attendance:read` covers the direct-reports endpoint

**Fixed: `seed_db_full.py` — `notification:read` missing from all roles**
- A7 added the permission at runtime but the seed was never updated — fresh installs would 403 on all notification endpoints
- File: `backend/seed_db_full.py`
- Fix: Added `notification:read` to admin, hr, manager, and employee roles in `_ROLE_PERMS`

**Fixed: `.env.example` — `COOKIE_SECURE` missing**
- HTTPS deployments need to set this to `true`; operators had no documentation for it
- File: `.env.example`
- Fix: Added `COOKIE_SECURE=false` under the JWT Security section with explanatory comment

**Fixed: `.env.example` — `ATTENDANCE_COOLDOWN_SECONDS` missing**
- Added to `config.py` in A4 but never documented
- File: `.env.example`
- Fix: Added `ATTENDANCE_COOLDOWN_SECONDS=300` under a new "Attendance Engine" section

**Fixed: `.env.example` — camera URL variable names wrong**
- Had `CAMERA_ENTRY_URL`/`CAMERA_EXIT_URL` but `docker-compose.yml` (corrected in A8) uses `ENTRY_CAMERA_URL`/`EXIT_CAMERA_URL`
- File: `.env.example`
- Fix: Renamed to `ENTRY_CAMERA_URL`/`EXIT_CAMERA_URL` to match Compose

**Fixed: `LOCAL_SETUP_GUIDE.md` — missing Ubuntu/Linux LAN IP instructions**
- Guide only explained Windows (`ipconfig`); Ubuntu users had no instructions
- File: `LOCAL_SETUP_GUIDE.md`
- Fix: Added "### On Ubuntu / Linux" subsection with `ip addr show | grep "inet "` and `hostname -I` commands; noted to ignore Docker's `172.x.x.x` network

**Fixed: `LOCAL_SETUP_GUIDE.md` — missing employee face enrollment walkthrough**
- Guide explained camera setup but not how to enroll employee faces
- File: `LOCAL_SETUP_GUIDE.md`
- Fix: Added Step 7 "Enroll Employee Faces" with 9-step walkthrough, photo tips, and verification steps

---

### A14 — Final End-to-End Test (2026-06-08)

**Fixed: Frontend container healthcheck used `localhost` instead of `127.0.0.1`**
- BusyBox `wget` in the Next.js Alpine container cannot resolve `localhost` via DNS lookup in the minimal container environment; container showed "unhealthy" indefinitely despite Next.js serving pages correctly
- File: `docker-compose.yml`
- Fix: Changed healthcheck URL from `http://localhost:3000/` to `http://127.0.0.1:3000/`

---

### A15 — Load Test (2026-06-11)

**Fixed: P95 latency exceeded 2000 ms threshold under 20 concurrent users**
- Root cause 1: `pool_size=5, max_overflow=10` = 15 max DB connections for 20 concurrent requests; last 5 queued
- Root cause 2: `_is_holiday()` and `_is_on_approved_leave()` ran sequentially inside each attendance event handler
- File: `backend/app/core/database.py`
- Fix 1: Raised `pool_size=20, max_overflow=5`
- File: `backend/app/services/attendance_service.py`
- Fix 2: Parallelized the two independent DB queries with `asyncio.gather()`
- Result: P95 dropped from 2283 ms → 1638 ms; all 20 concurrent events processed with 0 failures

---

### A16 — HTTPS (Local LAN SSL) (2026-06-11)

**Added: `nginx/conf.d/local-ssl.conf`**
- HTTP → HTTPS 301 redirect + TLS termination (TLSv1.2/1.3, HSTS `max-age=15768000`)
- Activated when `DEPLOYMENT_MODE=local-ssl` in `.env`

**Fixed: `generate-certs.sh` wrote certs to host bind mount, but docker-compose used a named volume**
- `./nginx/certs/` on the host and the `nginx_certs` Docker named volume are unrelated storage
- File: `docker-compose.yml`
- Fix: Changed nginx cert mount from named volume to bind mount `./nginx/certs:/etc/nginx/certs:ro`; removed `nginx_certs:` from the volumes section

**Updated: `generate-certs.sh`**
- Now sets `DEPLOYMENT_MODE=local-ssl` in `.env` automatically after generating certs
- Restarts nginx container after cert generation

**Added: `nginx/certs/.gitkeep`**
- Empty placeholder so the bind-mount directory exists on fresh clones

---

### A17 — Wati WhatsApp Integration (2026-06-11)

**Added: `backend/tests/test_wati_a17.py`** — 18 unit tests for the Wati notification dispatch pipeline

Scenarios covered:
- Happy path: correct template + E.164 phone → HTTP 200 → notification marked SENT
- Phone normalisation: `+91-9876543210`, `9876543210`, `91-9876543210` → `919876543210`
- Network error (`ConnectError`) → status `QUEUED_OFFLINE` for Celery retry
- Auth error (403 from Wati) → does not retry (not a transient error); falls through to email
- No phone → WhatsApp skipped, email fallback attempted
- No Wati token → WhatsApp skipped entirely
- Email fallback on WhatsApp failure
- Retry task: `QUEUED_OFFLINE` notification → retry succeeds → status `SENT`
- Template rendering for all 8 event types with and without context fields

---

### A18 — Camera / Face Service Integration (2026-06-11)

**Added: `backend/tests/test_camera_biometric_a18_a19.py`** — A18 and A19 tests

A18 validations:
- Face-service `/health` endpoint reachable and reports model status
- `/status` endpoint returns camera and embedding info
- CP Plus RTSP URL format regex validated against CLAUDE.md spec
- `/embed` endpoint: valid image returns 200 or 400 (never 500)

---

### A19 — ZKTeco K40 Biometric ADMS (2026-06-11)

A19 validations (in `test_camera_biometric_a18_a19.py`):
- ZKTeco ADMS payload `state=0` → ENTRY event → `check_in` set in `daily_attendance`
- ZKTeco ADMS payload `state=1` → EXIT event → `check_out` set, `status=PRESENT`
- Unknown `biometric_uid` → 404 (not 500)
- Incomplete payload (missing `uid`) → 422 validation error
- `daily_attendance.source = "biometric"` — source correctly tagged
- Duplicate ENTRY within cooldown window → 422 rejected

---

### A20 — Backup / Restore (2026-06-11)

**Verified: `backup.sh`** — `pg_dump` → gzip compressed archive in `./backups/`
- Compression ratio: 362 KB SQL → 46 KB gzip (~87% reduction)
- 30-day retention: archives older than `KEEP_DAYS=30` auto-pruned

**Verified: `restore.sh`** — TRUNCATE CASCADE + `psql --single-transaction`, restarts backend and celery-worker after restore

**Added: `setup-backup-cron.sh`** — installs Ubuntu crontab entry, daily at 02:00 AM

**Added: `setup-backup-task.bat`** — creates Windows Task Scheduler entry via `schtasks`, daily at 02:00 AM

**Note:** After restore, run `nginx -s reload` to force Nginx to re-resolve upstream IPs (stale keepalive connections from before restart)

---

### Operational Setup (2026-06-11)

**Added: MinIO lifecycle policies**
- `proofs/` bucket prefix: objects expire after 90 days
- `receipts/` bucket prefix: objects expire after 365 days
- Applied via `mc ilm rule add` in `minio-setup.sh`

**Added: `FACE_ENROLLMENT_GUIDE.md`**
- Step-by-step admin portal walkthrough for enrolling employee faces
- Bulk enrollment script (bash + curl)
- Photo requirements (200×200 px min, 30% face coverage, front-facing, no hats)
- How the camera recognition pipeline works
- Re-enrollment steps for appearance changes
- Troubleshooting section

---

## Known Limitations (v1.0.0)

| Limitation | Notes |
|---|---|
| Physical CP Plus cameras not tested in CI | Face recognition pipeline confirmed via simulated events |
| Wati.io production account not tested | Unit tests cover full dispatch pipeline; configure `WATI_API_TOKEN` to activate |
| Physical ZKTeco K40 not tested | ADMS API endpoint tested with correct payload format |
| GPU face recognition not supported | CPU-only ONNX INT8 — sufficient for ≤20 employees |
| Payroll export only | No direct integration with Zoho/Razorpay; export Excel/CSV for import |
| Max 20 employees | System designed and load-tested for this scale |

---

## Upgrade Path (v1.1.0 candidates)

See `## Next Features` in the project README for a prioritised roadmap.
