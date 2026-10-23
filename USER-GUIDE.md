# Attendance & Workforce Management System — User Guide

Welcome! This guide explains how to **run and use** the system in your office. Your
data stays on **your** computer — nothing is sent to the cloud.

> Setting up a brand-new PC from zero (installing Docker, etc.)? See the printable
> **Attendance_System_Setup_Guide.pdf** included in this folder. This guide picks up
> once the system is installed and focuses on day-to-day use.

---

## 1. What this system does

- **Automatic attendance** from face-recognition cameras and/or a ZKTeco biometric device.
- **Self-service selfie check-in** — staff mark attendance from their own phone with a
  live selfie (no hardware needed).
- **Four web portals** in one app: **Employee, Manager, HR, Admin**.
- **Leave, reimbursements, attendance corrections** with a two-step approval chain.
- **Payroll deductions** for late arrivals, exported to Excel/CSV.
- **Holidays, notifications, reports** — all offline-capable.

---

## 2. Starting & stopping the system

The system runs as a set of background services on the host PC.

- **Start:** double-click **`start-attendance.bat`** (or use the **Attendance** tray
  icon → *Start*). The first start takes a few minutes while it loads.
- **Stop:** double-click **`stop-attendance.bat`** (or tray icon → *Stop*).
- **Open it:** in a browser, go to **http://localhost** on the host PC, or
  **http://<host-PC-IP>** from any other device on the same office Wi-Fi.

> **Find the host PC's IP:** open Command Prompt on the host and run `ipconfig` — use the
> `IPv4 Address` that looks like `192.168.x.x`. Share `http://192.168.x.x` with staff.
> On phones, use the browser's "Add to Home Screen" to get an app-like icon.

The system restarts automatically if the PC reboots (Docker starts on login).

---

## 3. Logging in & the four portals

Open **http://localhost** and sign in. The portal you see depends on your **role**:

| Role | What they do |
|---|---|
| **Admin** | Full control: employees, devices, branches, roles, holidays, settings, audit logs, license |
| **HR** | Employees, all attendance, final approvals, payroll export, reports, holidays |
| **Manager** | Their team's attendance + first-level approvals |
| **Employee** | Own dashboard, **selfie check-in**, leave, claims, corrections |

> Your provider gives you the **first admin login**. **Change its password immediately:**
> **Admin → Employees →** your own row → **edit → Reset Password**. Staff who forget their
> password ask an Admin/HR to reset it the same way (there is no self-service email reset).

---

## 4. First-time configuration (Admin)

Do these once, in the **Admin** portal:

1. **Branches** → set your office **name, address, start/end time, and grace period**
   (minutes before someone counts as "late").
2. **Departments / Roles** → add as needed.
3. **Employees → Add Employee** → name, email, password, role, **manager** (for
   approvals), date of joining. (Set a biometric UID here if you use a ZKTeco device.)
4. **Enroll faces** (needed for cameras *and* selfie check-in): **Employees → camera icon
   on a row → upload 1–3 clear, front-facing photos**.
5. **Holidays** → the year's national holidays are pre-loaded; add regional ones per branch.
6. **Settings → Attendance** → late-penalty policy, and the **Self-service selfie
   check-in** on/off switch.

---

## 5. Marking attendance — three methods

You can use any combination:

1. **Face-recognition cameras** — mount a camera at the entry/exit door (at face height,
   well lit). Add it in **Admin → Devices**. Staff are recognised automatically as they
   pass. *(Tip: a doorway camera works; a ceiling-corner CCTV usually does not.)*
2. **ZKTeco biometric device** — point its ADMS server setting at the host PC; it pushes
   punches automatically. Map each device UID to an employee in the Admin portal.
3. **Self-service selfie check-in** — see the next section.

---

## 6. Self-service selfie check-in (for employees)

A quick, buddy-punch-resistant way for staff to mark attendance from their **phone**.

**For the employee:**
1. On office Wi-Fi, open the portal and sign in.
2. Tap **Check In** (or the "Mark attendance with a selfie" card on the dashboard).
3. Follow the on-screen prompt (e.g. *turn your head*) and take the selfie.
4. The first selfie of the day is your **check-in**; **check-out is optional** afterwards.

**Good to know:**
- The employee must be **enrolled** first (Admin/HR uploads their photo — section 4.4).
- It matches the selfie **only against that person's own face**, so no one can check in
  for someone else.
- **Phones need HTTPS** for the camera to work (browsers block the camera on plain
  `http://<ip>`). The easiest way — with **nothing to install on any phone** — is a free
  DuckDNS subdomain + a Let's Encrypt certificate:
  1. Create a free subdomain + token at https://www.duckdns.org (sign in, make a
     subdomain like `youroffice`, copy the token).
  2. On the host, either **double-click `enable-phone-https.bat`** or use the **tray icon
     → "Enable phone HTTPS..."**, and paste your subdomain + token when asked. That's it —
     no command to type, and you only do this **once**.
  3. Staff then open **`https://youroffice.duckdns.org`** on the office Wi-Fi — trusted,
     nothing to install on any phone. It **keeps itself current automatically** after
     reboots and IP changes (a scheduled task refreshes the address and renews the cert).
  On the host PC itself, `http://localhost` already works for the camera without any of this.
- The on-screen **head-movement prompt** is what proves a live person — a printed photo or
  static phone screen can't follow it — and the selfie is matched only to that employee's
  **own enrolled face**. An optional **passive anti-spoofing** model (printed-photo / screen
  replay) ships **off by default**, because it currently misjudges genuine phone selfies;
  your provider can enable it per-site after validating it on your cameras.

---

## 7. Everyday workflows

- **Leave:** Employee applies → **Manager** approves → **HR** approves. Balances update
  automatically.
- **Reimbursements:** Employee submits + uploads a receipt → Manager → HR → mark paid.
- **Corrections:** Employee requests a fix to a wrong record → Manager → HR.
- **Payroll (HR):** **Payroll** tab → set the late policy, run deductions, and **export
  Excel/CSV** for your payroll software.
- **Reports (HR/Manager):** attendance / leave / payroll downloads.
- **Notifications:** staff get in-app alerts for attendance, leave, etc. Optionally,
  **WhatsApp** and/or **email** alerts too if configured in **Admin → Settings →
  Notifications** (in-app always works, no setup needed).

---

## 8. Backups (important)

Your data lives on this PC — **back it up**.

- Run **`backup.bat`** (Windows) to create a dated backup in the `backups` folder. Copy
  that folder to an external drive or network share regularly.
- You can schedule a daily backup with **`setup-backup-task.bat`**.
- To restore, use **`restore.bat`** with a backup file (your provider can assist).

---

## 9. Troubleshooting (quick)

| Problem | Try this |
|---|---|
| Can't open the portal | Is the system started? Is Docker running? Same Wi-Fi as the host? |
| Phone selfie camera error | Needs HTTPS — ask your provider to enable it (section 6). |
| "Too many attempts" at login | A safety limit — wait a minute and retry. |
| Face not recognised | Better lighting / face the camera; enroll 2–3 photos. |
| A staff member left after clocking in | Use HR → Attendance to review/correct. |
| Everything looks stuck | Stop and Start the system again (section 2). |

---

## 10. License & support

- The software runs under the license key your provider issued (see
  **LICENSE-AGREEMENT.txt**). Admin can view its status in **Admin → (license status)**.
- When the license nears expiry, contact your provider for a renewed key — just paste it
  in; no reinstall needed.
- For setup help (cameras, biometric device, HTTPS, backups), contact your provider.

---

*Your data never leaves this computer. Keep the host PC powered on during office hours
and backed up regularly.*
