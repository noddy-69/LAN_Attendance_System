"""Generate the customer-facing Attendance System Setup & Operating Guide PDF.

Audience: a non-technical office admin who received ONLY the delivery (dist) folder
(built Docker images + .bat/.ps1 helpers) — no source code, no Python, no bash.
Everything here is done with Docker Desktop + the double-click .bat files in the folder.
"""
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

OUT = "Attendance_System_Setup_Guide.pdf"

NAVY = colors.HexColor("#1f2d5a")
BLUE = colors.HexColor("#2563eb")
LIGHT = colors.HexColor("#eef2ff")
CODEBG = colors.HexColor("#0f172a")
CODEFG = colors.HexColor("#e2e8f0")
GREY = colors.HexColor("#475569")
GREEN = colors.HexColor("#047857")

styles = getSampleStyleSheet()

h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=NAVY, fontSize=15,
                    spaceBefore=14, spaceAfter=6)
h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=BLUE, fontSize=11.5,
                    spaceBefore=9, spaceAfter=3)
body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9.5, leading=14,
                      spaceAfter=4, alignment=TA_LEFT)
note = ParagraphStyle("note", parent=body, textColor=GREY, fontSize=8.8, leading=12)
good = ParagraphStyle("good", parent=body, textColor=GREEN, fontSize=9.5, leading=13)
title = ParagraphStyle("title", parent=styles["Title"], textColor=NAVY, fontSize=22, leading=26)
subtitle = ParagraphStyle("subtitle", parent=styles["Normal"], textColor=GREY, fontSize=10.5,
                          spaceAfter=2)
cellcode = ParagraphStyle("cellcode", parent=styles["Code"], fontSize=8.7, leading=12.5,
                          textColor=CODEFG, fontName="Courier")


def code(text):
    safe = escape(text).replace("\n", "<br/>")
    p = Paragraph(f'<font face="Courier">{safe}</font>', cellcode)
    t = Table([[p]], colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODEBG),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
    ]))
    return t


def bullet(text):
    return Paragraph("• " + text, body)


def step(n, text):
    return Paragraph(f"<b>{n}.</b> {text}", body)


def hr():
    return HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#cbd5e1"),
                      spaceBefore=6, spaceAfter=6)


def kv_table(rows, c0=62, c1=100, head=("Symptom", "Fix")):
    data = [list(head)] + [list(r) for r in rows]
    t = Table(data, colWidths=[c0 * mm, c1 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c7d2fe")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


story = []

# ── Title ────────────────────────────────────────────────────────────────────
story.append(Paragraph("Attendance &amp; Workforce Management System", title))
story.append(Paragraph("Setup &amp; Operating Guide — install from scratch, run every day, and fix common issues", subtitle))
story.append(Paragraph("On-premises install for a Windows office PC · Your data never leaves this computer", note))
story.append(hr())

# ── What you need ──────────────────────────────────────────────────────────
story.append(Paragraph("What you need", h1))
story.append(bullet("A <b>Windows 10 or 11</b> PC (64-bit), at least <b>8 GB RAM</b> and <b>~20 GB</b> free disk. "
                    "This PC stays on during office hours and acts as the server."))
story.append(bullet("The <b>delivery folder</b> you were given (it contains this guide, the app images, and the "
                    "<font face='Courier'>start-attendance.bat</font> launcher)."))
story.append(bullet("Your <b>admin sign-in</b> and <b>license key</b> (sent to you separately by your provider)."))
story.append(Paragraph("You do NOT install Python, databases, or anything else. Everything runs inside Docker. "
                       "The only program you install is Docker Desktop (Step 1).", note))

# ── Step 1: Docker ─────────────────────────────────────────────────────────
story.append(Paragraph("Step 1 — Install Docker Desktop (one time, ~15 min)", h1))
story.append(step(1, "Open <b>https://www.docker.com/products/docker-desktop</b> and download "
                     "<b>Docker Desktop for Windows</b>."))
story.append(step(2, "Run the installer. Keep <b>“Use WSL 2”</b> ticked. Finish, then <b>restart the PC</b>."))
story.append(step(3, "If Docker warns that virtualization is off: restart, enter the PC's BIOS/UEFI, turn on "
                     "<b>Virtualization</b> (also called <i>SVM</i> or <i>Intel VT-x</i>), save, and reboot. This is a one-time step."))
story.append(step(4, "Start <b>Docker Desktop</b> from the Start menu and wait until the whale icon in the taskbar "
                     "says <b>“Docker Desktop is running.”</b>"))
story.append(Paragraph("<b>Important — make it start by itself after every reboot:</b>", h2))
story.append(step(5, "In Docker Desktop click the <b>gear (Settings) → General</b>, tick "
                     "<b>“Start Docker Desktop when you sign in to your computer,”</b> then <b>Apply &amp; Restart</b>."))
story.append(Paragraph("This one setting is what makes the whole system come back on its own after a power cut or "
                       "reboot — you will not have to start anything manually (see “Every reboot” below).", note))

# ── Step 2: First run ──────────────────────────────────────────────────────
story.append(Paragraph("Step 2 — Start the Attendance System (first run)", h1))
story.append(step(1, "Copy the delivery folder to a permanent place, for example "
                     "<font face='Courier'>C:\\AttendanceSystem</font>. Don't run it from a USB stick or Downloads."))
story.append(step(2, "Double-click <b>start-attendance.bat</b>. The first run loads the app (a few minutes) and "
                     "creates its configuration automatically. Leave the window until it says <b>Done</b>."))
story.append(step(3, "On this PC, open a browser and go to <b>http://localhost</b>."))
story.append(step(4, "Sign in as <b>admin</b> with the credentials your provider gave you. "
                     "In <b>Admin → Settings</b>, paste your <b>license key</b> if it isn't already active."))
story.append(Paragraph("From now on every part of the system is set to restart automatically, so after Step 1's "
                       "auto-start setting you normally never touch these files again.", good))

# ── Step 3: Staff access ───────────────────────────────────────────────────
story.append(Paragraph("Step 3 — Let staff use it from their phones / other PCs", h1))
story.append(Paragraph("Everyone on the same office Wi-Fi opens the system in their browser using this PC's address.", body))
story.append(step(1, "Find this PC's address: double-click <b>update-ip.bat</b> — it prints the address to use "
                     "(for example <font face='Courier'>http://192.168.1.50</font> or your "
                     "<font face='Courier'>.duckdns.org</font> web address if one was set up for you)."))
story.append(step(2, "Share that address with staff. They open it on the office Wi-Fi and sign in."))
story.append(Paragraph("<b>Phone camera (selfie check-in) needs HTTPS.</b> Phone browsers only open the camera on a "
                       "secure (https) address. To enable it, right-click <b>setup-https.ps1 → Run with PowerShell</b> "
                       "once, then have each phone trust the certificate the first time (the guide it prints explains how). "
                       "After that, staff use the <font face='Courier'>https://</font> address.", note))

# ── Every reboot ───────────────────────────────────────────────────────────
story.append(Paragraph("Every reboot / turning the PC on", h1))
story.append(Paragraph("If you ticked the auto-start setting in Step 1, there is <b>nothing to do</b>:", body))
story.append(bullet("Turn the PC on → Docker Desktop starts by itself → the attendance system starts by itself."))
story.append(bullet("Give it 1–2 minutes after login, then open <b>http://localhost</b> to confirm it's up."))
story.append(Paragraph("If the page does not load after a couple of minutes:", h2))
story.append(step(1, "Check the taskbar for the Docker <b>whale icon</b>. If it isn't there, open "
                     "<b>Docker Desktop</b> from the Start menu and wait for “running.”"))
story.append(step(2, "Still not loading? Double-click <b>start-attendance.bat</b> once — it will start anything "
                     "that didn't come up."))
story.append(Paragraph("To stop the system on purpose (e.g. before shutting the PC for a long holiday), double-click "
                       "<b>stop-attendance.bat</b>. To start it again, use <b>start-attendance.bat</b>.", note))

# ── Backups ────────────────────────────────────────────────────────────────
story.append(Paragraph("Backups (do this — it protects your data)", h1))
story.append(bullet("A backup is taken <b>automatically at the end of every month</b> into the "
                    "<font face='Courier'>backups</font> folder next to these files."))
story.append(bullet("For an instant backup any time, use <b>Admin → Settings → Data → Download Backup Now</b> "
                    "(saves a <font face='Courier'>.dump</font> file), or double-click <b>backup.bat</b>."))
story.append(bullet("<b>Copy the backups off this PC regularly</b> — onto a USB drive or another computer. A backup "
                    "on the same PC won't help if the PC itself fails."))
story.append(bullet("To restore: <b>Admin → Settings → Data → Restore</b> and upload a "
                    "<font face='Courier'>.dump</font> file (this replaces current data)."))
story.append(Paragraph("Optional: double-click <b>setup-backup-task.bat</b> once to add a Windows scheduled task "
                       "that backs up on a regular schedule automatically.", note))

# ── Using it day to day ────────────────────────────────────────────────────
story.append(Paragraph("Enrolling faces &amp; daily use", h1))
story.append(bullet("<b>Add staff:</b> Admin or HR → <b>Employees → Add Employee</b>."))
story.append(bullet("<b>Enrol a face:</b> on the Employees list, click the <b>camera icon</b> on a person's row and "
                    "upload 1–3 clear, front-facing photos. Only a numeric face fingerprint is stored; the photos are discarded."))
story.append(bullet("<b>Three ways to mark attendance:</b> office camera (Admin → Camera), each employee's phone "
                    "<b>selfie check-in</b>, or a connected <b>ZKTeco</b> fingerprint device."))
story.append(bullet("<b>Passwords:</b> staff who forget a password ask Admin/HR, who set a new one from "
                    "<b>Employees → edit the person → Reset Password</b>."))
story.append(bullet("<b>Notifications:</b> in-app alerts always work with no setup. To also send "
                    "<b>WhatsApp</b> and/or <b>email</b> alerts, turn them on in <b>Admin → Settings → "
                    "Notifications</b> (WhatsApp needs a free Meta WhatsApp Cloud API key; email needs an SMTP account)."))
story.append(Paragraph("The separate <b>USER-GUIDE</b> in this folder covers leave, reimbursements, approvals and "
                       "reports for everyday users.", note))

# ── Troubleshooting ────────────────────────────────────────────────────────
story.append(Paragraph("Troubleshooting — common problems &amp; fixes", h1))
story.append(kv_table([
    ["Staff / phones suddenly can't open the address (it worked before)",
     "The PC's IP changed after a Wi-Fi or router change. Double-click update-ip.bat — it "
     "re-points the address to this PC and prints the address to use. Then reopen that address "
     "(toggle the phone's Wi-Fi off/on if it still won't connect)."],
    ["The site doesn't load at all (even http://localhost)",
     "Docker isn't running yet. Open Docker Desktop, wait for the whale to say 'running' (1-2 min), "
     "then reload. If needed, double-click start-attendance.bat."],
    ["start-attendance.bat says 'Docker is not running'",
     "Start Docker Desktop first and wait for 'running', then run start-attendance.bat again."],
    ["Phone won't open the camera for selfie check-in",
     "The camera needs HTTPS. Run setup-https.ps1 (right-click - Run with PowerShell) and trust the "
     "certificate on the phone once. Then use the https:// address."],
    ["Someone forgot their password",
     "Admin/HR opens Employees - edit that person - Reset Password, and shares the new password."],
    ["Data looks empty / you moved to a new PC",
     "Install Docker + start-attendance.bat on the new PC, then restore your latest .dump from "
     "Admin - Settings - Data - Restore."],
    ["'Port 80 is already in use' on first start",
     "Another app (e.g. IIS or an old web server) is using port 80. Stop it, or ask your provider to "
     "change HTTP_PORT in the .env file."],
    ["A setting changed in Admin isn't taking effect",
     "Give it a moment and refresh the browser. If it still lags, restart via stop-attendance.bat then "
     "start-attendance.bat."],
], c0=62, c1=100))

story.append(Spacer(1, 8))
story.append(hr())
story.append(Paragraph("Your data (staff, attendance, enrolled faces) stays on this PC inside Docker and is never "
                       "sent to the internet. Keep Docker Desktop set to start on login, and keep copies of the "
                       "backups folder off-machine. For anything not covered here, contact your provider.", note))


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY)
    canvas.drawString(20 * mm, 12 * mm, "Attendance System — Setup & Operating Guide")
    canvas.drawRightString(190 * mm, 12 * mm, f"Page {doc.page}")
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                        topMargin=18 * mm, bottomMargin=18 * mm,
                        title="Attendance System Setup & Operating Guide")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("WROTE", OUT)
