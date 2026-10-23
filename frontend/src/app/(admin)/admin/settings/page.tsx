"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { PortalLayout } from "@/components/shared/Layout";
import { ADMIN_NAV } from "@/components/admin/nav";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { Database, Download, Upload, Trash2, AlertTriangle } from "lucide-react";
import { api, apiGet, apiPut, apiPost } from "@/lib/api";
import { downloadFile } from "@/lib/utils";
import { API_BASE } from "@/lib/constants";
import { useAuthStore } from "@/stores/auth-store";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SystemPolicy {
  key: string;
  value: string;
  description: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function parsePolicyInt(policies: SystemPolicy[], key: string, fallback: number): number {
  const policy = policies.find((p) => p.key === key);
  if (!policy) return fallback;
  try {
    return parseInt(JSON.parse(policy.value), 10) || fallback;
  } catch {
    return parseInt(policy.value, 10) || fallback;
  }
}

function parsePolicyFloat(policies: SystemPolicy[], key: string, fallback: number): number {
  const policy = policies.find((p) => p.key === key);
  if (!policy) return fallback;
  try {
    const n = parseFloat(JSON.parse(policy.value));
    return Number.isFinite(n) ? n : fallback;
  } catch {
    const n = parseFloat(policy.value);
    return Number.isFinite(n) ? n : fallback;
  }
}

function parsePolicyBool(policies: SystemPolicy[], key: string, fallback: boolean): boolean {
  const policy = policies.find((p) => p.key === key);
  if (!policy) return fallback;
  try {
    return JSON.parse(policy.value) === true || policy.value === "true";
  } catch {
    return fallback;
  }
}

function parsePolicyStr(policies: SystemPolicy[], key: string, fallback: string): string {
  const policy = policies.find((p) => p.key === key);
  if (!policy) return fallback;
  try {
    const parsed = JSON.parse(policy.value);
    return typeof parsed === "string" ? parsed : policy.value;
  } catch {
    return policy.value;
  }
}

// ── AttendanceTab ─────────────────────────────────────────────────────────────

function AttendanceTab({
  policies,
  onSave,
  isSaving,
}: {
  policies: SystemPolicy[];
  onSave: (updates: Array<{ key: string; value: string }>) => void;
  isSaving: boolean;
}) {
  const [gracePeriod, setGracePeriod] = useState(
    parsePolicyInt(policies, "attendance.grace_period_minutes", 15)
  );
  // Late-penalty (percentage-of-a-day) model.
  const [lateDaysPerUnit, setLateDaysPerUnit] = useState(
    parsePolicyInt(policies, "payroll.late_days_per_unit", 3)
  );
  const [penaltyPercent, setPenaltyPercent] = useState(
    parsePolicyInt(policies, "payroll.penalty_percent_per_unit", 50)
  );
  const [graceDays, setGraceDays] = useState(
    parsePolicyFloat(policies, "payroll.grace_days", 1.5)
  );
  const [salaryDays, setSalaryDays] = useState(
    parsePolicyInt(policies, "payroll.salary_days_per_month", 30)
  );
  const [selfieEnabled, setSelfieEnabled] = useState(
    parsePolicyBool(policies, "selfie.enabled", true)
  );

  useEffect(() => {
    setGracePeriod(parsePolicyInt(policies, "attendance.grace_period_minutes", 15));
    setLateDaysPerUnit(parsePolicyInt(policies, "payroll.late_days_per_unit", 3));
    setPenaltyPercent(parsePolicyInt(policies, "payroll.penalty_percent_per_unit", 50));
    setGraceDays(parsePolicyFloat(policies, "payroll.grace_days", 1.5));
    setSalaryDays(parsePolicyInt(policies, "payroll.salary_days_per_month", 30));
    setSelfieEnabled(parsePolicyBool(policies, "selfie.enabled", true));
  }, [policies]);

  const handleSave = () => {
    onSave([
      { key: "attendance.grace_period_minutes", value: JSON.stringify(gracePeriod) },
      { key: "payroll.late_days_per_unit", value: JSON.stringify(lateDaysPerUnit) },
      { key: "payroll.penalty_percent_per_unit", value: JSON.stringify(penaltyPercent) },
      { key: "payroll.grace_days", value: JSON.stringify(graceDays) },
      { key: "payroll.salary_days_per_month", value: JSON.stringify(salaryDays) },
      { key: "selfie.enabled", value: JSON.stringify(selfieEnabled) },
    ]);
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="grace_period">Default Grace Period (minutes)</Label>
          <Input
            id="grace_period"
            type="number"
            min={0}
            max={120}
            value={gracePeriod}
            onChange={(e) => setGracePeriod(Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">
            Minutes after office start before a check-in counts as late. This is the
            org-wide default — a branch that sets its own grace (Admin → Branches)
            overrides it.
          </p>
        </div>

        <div className="space-y-1">
          <Label htmlFor="late_days_per_unit">Late Days per Penalty</Label>
          <Input
            id="late_days_per_unit"
            type="number"
            min={1}
            max={31}
            value={lateDaysPerUnit}
            onChange={(e) => setLateDaysPerUnit(Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">
            Every this many late days counts as one penalty. Default: 3.
          </p>
        </div>

        <div className="space-y-1">
          <Label htmlFor="penalty_percent">% of a Day&apos;s Salary per Penalty</Label>
          <Input
            id="penalty_percent"
            type="number"
            min={1}
            max={100}
            value={penaltyPercent}
            onChange={(e) => setPenaltyPercent(Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">
            Deducted per penalty unit. 50 = half a day. Default: 50.
          </p>
        </div>

        <div className="space-y-1">
          <Label htmlFor="grace_days">Grace Days per Month</Label>
          <Input
            id="grace_days"
            type="number"
            min={0}
            step={0.5}
            value={graceDays}
            onChange={(e) => setGraceDays(Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">
            Penalty-days forgiven each month before any deduction. Default: 1.5.
          </p>
        </div>

        <div className="space-y-1">
          <Label htmlFor="salary_days">Salary Days per Month</Label>
          <Input
            id="salary_days"
            type="number"
            min={1}
            max={31}
            value={salaryDays}
            onChange={(e) => setSalaryDays(Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">
            A day&apos;s salary = monthly salary ÷ this. Default: 30.
          </p>
        </div>
      </div>

      <div className="flex items-center justify-between rounded-lg border p-4">
        <div>
          <p className="font-medium">Self-service selfie check-in</p>
          <p className="text-sm text-muted-foreground">
            Let employees mark attendance from their phone with a live selfie (1:1 face
            match + liveness). Turn off to hide the Check In page.
          </p>
        </div>
        <Switch checked={selfieEnabled} onCheckedChange={setSelfieEnabled} />
      </div>

      <Button onClick={handleSave} disabled={isSaving}>
        {isSaving ? "Saving…" : "Save Attendance Rules"}
      </Button>
    </div>
  );
}

// ── NotificationsTab ──────────────────────────────────────────────────────────

function NotificationsTab({
  policies,
  onSave,
  isSaving,
}: {
  policies: SystemPolicy[];
  onSave: (updates: Array<{ key: string; value: string }>) => void;
  isSaving: boolean;
}) {
  // Email — recommended (free)
  const [emailEnabled, setEmailEnabled] = useState(parsePolicyBool(policies, "notifications.email_enabled", true));
  const [smtpHost, setSmtpHost] = useState(parsePolicyStr(policies, "notifications.smtp_host", ""));
  const [smtpPort, setSmtpPort] = useState(parsePolicyInt(policies, "notifications.smtp_port", 587));
  const [smtpUser, setSmtpUser] = useState(parsePolicyStr(policies, "notifications.smtp_user", ""));
  const [smtpPassword, setSmtpPassword] = useState(parsePolicyStr(policies, "notifications.smtp_password", ""));
  const [smtpFrom, setSmtpFrom] = useState(parsePolicyStr(policies, "notifications.smtp_from", ""));
  // WhatsApp — optional (Meta Cloud API)
  const [whatsappEnabled, setWhatsappEnabled] = useState(parsePolicyBool(policies, "notifications.whatsapp_enabled", false));
  const [waToken, setWaToken] = useState(parsePolicyStr(policies, "notifications.wa_token", ""));
  const [waPhoneId, setWaPhoneId] = useState(parsePolicyStr(policies, "notifications.wa_phone_number_id", ""));
  const [waTemplate, setWaTemplate] = useState(parsePolicyStr(policies, "notifications.wa_template", ""));
  const [waLanguage, setWaLanguage] = useState(parsePolicyStr(policies, "notifications.wa_language", "en_US"));

  useEffect(() => {
    setEmailEnabled(parsePolicyBool(policies, "notifications.email_enabled", true));
    setSmtpHost(parsePolicyStr(policies, "notifications.smtp_host", ""));
    setSmtpPort(parsePolicyInt(policies, "notifications.smtp_port", 587));
    setSmtpUser(parsePolicyStr(policies, "notifications.smtp_user", ""));
    setSmtpPassword(parsePolicyStr(policies, "notifications.smtp_password", ""));
    setSmtpFrom(parsePolicyStr(policies, "notifications.smtp_from", ""));
    setWhatsappEnabled(parsePolicyBool(policies, "notifications.whatsapp_enabled", false));
    setWaToken(parsePolicyStr(policies, "notifications.wa_token", ""));
    setWaPhoneId(parsePolicyStr(policies, "notifications.wa_phone_number_id", ""));
    setWaTemplate(parsePolicyStr(policies, "notifications.wa_template", ""));
    setWaLanguage(parsePolicyStr(policies, "notifications.wa_language", "en_US"));
  }, [policies]);

  const handleSave = () => {
    onSave([
      { key: "notifications.email_enabled", value: JSON.stringify(emailEnabled) },
      { key: "notifications.smtp_host", value: JSON.stringify(smtpHost.trim()) },
      { key: "notifications.smtp_port", value: JSON.stringify(smtpPort) },
      { key: "notifications.smtp_user", value: JSON.stringify(smtpUser.trim()) },
      { key: "notifications.smtp_password", value: JSON.stringify(smtpPassword) },
      { key: "notifications.smtp_from", value: JSON.stringify(smtpFrom.trim()) },
      { key: "notifications.whatsapp_enabled", value: JSON.stringify(whatsappEnabled) },
      { key: "notifications.wa_token", value: JSON.stringify(waToken.trim()) },
      { key: "notifications.wa_phone_number_id", value: JSON.stringify(waPhoneId.trim()) },
      { key: "notifications.wa_template", value: JSON.stringify(waTemplate.trim()) },
      { key: "notifications.wa_language", value: JSON.stringify(waLanguage.trim() || "en_US") },
    ]);
  };

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">
        In-app notifications always work (no setup). <strong>Email is free and recommended</strong>; WhatsApp is optional.
      </p>

      <div className="space-y-4">
        {/* ── Email: recommended / free ── */}
        <div className="flex items-center justify-between rounded-lg border p-4">
          <div>
            <p className="font-medium">
              Email Notifications (SMTP)
              <span className="ml-2 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/30 dark:text-green-400">Recommended · Free</span>
            </p>
            <p className="text-sm text-muted-foreground">
              Works with any SMTP provider. A free Gmail account with an App Password is the easiest.
            </p>
          </div>
          <Switch checked={emailEnabled} onCheckedChange={setEmailEnabled} />
        </div>

        {emailEnabled && (
          <div className="grid gap-4 rounded-lg border bg-muted/30 p-4 sm:grid-cols-2">
            <div className="space-y-1">
              <Label htmlFor="smtp_host">SMTP Host</Label>
              <Input id="smtp_host" value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} placeholder="smtp.gmail.com" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="smtp_port">SMTP Port</Label>
              <Input id="smtp_port" type="number" value={smtpPort} onChange={(e) => setSmtpPort(Number(e.target.value))} placeholder="587" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="smtp_user">SMTP Username</Label>
              <Input id="smtp_user" autoComplete="off" value={smtpUser} onChange={(e) => setSmtpUser(e.target.value)} placeholder="you@company.com" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="smtp_password">SMTP Password</Label>
              <Input id="smtp_password" type="password" autoComplete="new-password" value={smtpPassword}
                onChange={(e) => setSmtpPassword(e.target.value)} placeholder="App password" />
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="smtp_from">From Address</Label>
              <Input id="smtp_from" value={smtpFrom} onChange={(e) => setSmtpFrom(e.target.value)} placeholder="noreply@company.com" />
            </div>
          </div>
        )}

        {/* ── WhatsApp: optional (Meta Cloud API) ── */}
        <div className="flex items-center justify-between rounded-lg border p-4">
          <div>
            <p className="font-medium">
              WhatsApp Notifications
              <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">Optional</span>
            </p>
            <p className="text-sm text-muted-foreground">
              Needs a WhatsApp Business API key (Meta Cloud API — no monthly subscription). Leave off to use Email + in-app only.
            </p>
          </div>
          <Switch checked={whatsappEnabled} onCheckedChange={setWhatsappEnabled} />
        </div>

        {whatsappEnabled && (
          <div className="grid gap-4 rounded-lg border bg-muted/30 p-4 sm:grid-cols-2">
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="wa_token">Access Token</Label>
              <Input id="wa_token" type="password" autoComplete="off" value={waToken}
                onChange={(e) => setWaToken(e.target.value)} placeholder="Meta WhatsApp Cloud API access token" />
              <p className="text-xs text-muted-foreground">
                From Meta → WhatsApp → API Setup. Each employee also needs a phone number (Employees page).
              </p>
            </div>
            <div className="space-y-1">
              <Label htmlFor="wa_phone_id">Phone Number ID</Label>
              <Input id="wa_phone_id" value={waPhoneId} onChange={(e) => setWaPhoneId(e.target.value)} placeholder="e.g. 102938475610293" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="wa_template">Template Name</Label>
              <Input id="wa_template" value={waTemplate} onChange={(e) => setWaTemplate(e.target.value)} placeholder="e.g. attendance_alert" />
            </div>
            <div className="space-y-1 sm:col-span-2">
              <Label htmlFor="wa_language">Template Language</Label>
              <Input id="wa_language" value={waLanguage} onChange={(e) => setWaLanguage(e.target.value)} placeholder="en_US" />
              <p className="text-xs text-muted-foreground">
                Use an approved Meta template whose body is a single variable — it receives the message text.
              </p>
            </div>
          </div>
        )}
      </div>

      <Button onClick={handleSave} disabled={isSaving}>
        {isSaving ? "Saving…" : "Save Notification Settings"}
      </Button>
    </div>
  );
}

// ── StorageTab ────────────────────────────────────────────────────────────────

function StorageTab({ policies }: { policies: SystemPolicy[] }) {
  const minioEndpoint = parsePolicyStr(policies, "storage.minio_endpoint", "minio:9000");
  const minioBucket = parsePolicyStr(policies, "storage.minio_bucket", "attendance-proofs");

  return (
    <div className="space-y-4">
      <div className="rounded-lg border p-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/30">
            <span className="text-xs font-bold text-green-700 dark:text-green-400">S3</span>
          </div>
          <div>
            <p className="font-medium">MinIO Object Storage</p>
            <p className="text-sm text-muted-foreground">Running at {minioEndpoint}</p>
          </div>
          <span className="ml-auto inline-flex items-center rounded-full bg-green-100 px-2.5 py-0.5 text-xs font-medium text-green-800 dark:bg-green-900/30 dark:text-green-400">
            Running
          </span>
        </div>
      </div>

      <div className="rounded-lg border bg-muted/30 p-4">
        <p className="text-sm font-medium">Storage Configuration</p>
        <div className="mt-3 space-y-2 text-sm text-muted-foreground">
          <div className="flex items-center justify-between">
            <span>Endpoint</span>
            <code className="rounded bg-muted px-2 py-0.5">{minioEndpoint}</code>
          </div>
          <div className="flex items-center justify-between">
            <span>Bucket</span>
            <code className="rounded bg-muted px-2 py-0.5">{minioBucket}</code>
          </div>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          Configure <code className="rounded bg-muted px-1">MINIO_ROOT_USER</code>,{" "}
          <code className="rounded bg-muted px-1">MINIO_ROOT_PASSWORD</code>, and{" "}
          <code className="rounded bg-muted px-1">MINIO_BUCKET</code> in your{" "}
          <code className="rounded bg-muted px-1">.env</code> file.
        </p>
      </div>
    </div>
  );
}

// ── SecurityTab ───────────────────────────────────────────────────────────────

function SecurityTab({
  policies,
  onSave,
  isSaving,
}: {
  policies: SystemPolicy[];
  onSave: (updates: Array<{ key: string; value: string }>) => void;
  isSaving: boolean;
}) {
  const [sessionTimeout, setSessionTimeout] = useState(
    parsePolicyInt(policies, "security.session_timeout_minutes", 30)
  );
  const [maxLoginAttempts, setMaxLoginAttempts] = useState(
    parsePolicyInt(policies, "security.max_login_attempts", 5)
  );

  useEffect(() => {
    setSessionTimeout(parsePolicyInt(policies, "security.session_timeout_minutes", 30));
    setMaxLoginAttempts(parsePolicyInt(policies, "security.max_login_attempts", 5));
  }, [policies]);

  const handleSave = () => {
    onSave([
      { key: "security.session_timeout_minutes", value: JSON.stringify(sessionTimeout) },
      { key: "security.max_login_attempts", value: JSON.stringify(maxLoginAttempts) },
    ]);
  };

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="session_timeout">Session Timeout (minutes)</Label>
          <Input
            id="session_timeout"
            type="number"
            min={5}
            max={1440}
            value={sessionTimeout}
            onChange={(e) => setSessionTimeout(Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">
            Idle session timeout. Refresh token validity is controlled via JWT_REFRESH_DAYS in .env.
          </p>
        </div>

        <div className="space-y-1">
          <Label htmlFor="max_login_attempts">Max Login Attempts</Label>
          <Input
            id="max_login_attempts"
            type="number"
            min={1}
            max={20}
            value={maxLoginAttempts}
            onChange={(e) => setMaxLoginAttempts(Number(e.target.value))}
          />
          <p className="text-xs text-muted-foreground">
            Maximum failed login attempts before temporarily locking the account.
          </p>
        </div>
      </div>

      <Button onClick={handleSave} disabled={isSaving}>
        {isSaving ? "Saving…" : "Save Security Settings"}
      </Button>
    </div>
  );
}

// ── DataTab (restore / delete all data) ───────────────────────────────────────

function DataTab() {
  const { token } = useAuthStore();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null); // uploaded .dump to restore
  const [uploadOpen, setUploadOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);

  // Instant on-demand backup: streams a .dump to the admin's computer (no server copy).
  const handleBackupNow = async () => {
    setDownloading(true);
    try {
      const stamp = new Date()
        .toLocaleString("sv-SE", { timeZone: "Asia/Kolkata" })
        .replace(" ", "_")
        .replace(/:/g, "");
      await downloadFile(
        `${API_BASE}/system/data/backup/download`,
        `attendance-backup-${stamp}.dump`,
        token
      );
      toast.success("Backup downloaded");
    } catch (e: unknown) {
      toast.error((e as Error).message || "Backup failed");
    } finally {
      setDownloading(false);
    }
  };

  const uploadRestoreMut = useMutation({
    mutationFn: async (f: File) => {
      const form = new FormData();
      form.append("file", f);
      return api.post("/system/data/restore/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 120_000,
      });
    },
    onSuccess: () => {
      toast.success("Restore complete. Reloading…");
      setUploadOpen(false);
      setUploadFile(null);
      setTimeout(() => window.location.reload(), 1200);
    },
    onError: (e: unknown) => {
      const msg =
        (e as { response?: { data?: { error?: string } } })?.response?.data?.error ??
        (e as Error).message ??
        "Restore failed";
      toast.error(msg);
    },
  });

  const resetMut = useMutation({
    mutationFn: () => apiPost("/system/data/reset", { confirm: true }),
    onSuccess: () => {
      toast.success("Records deleted. Reloading…");
      setDeleteOpen(false); setConfirmText("");
      setTimeout(() => window.location.reload(), 1200);
    },
    onError: (e: Error) => toast.error(e.message || "Delete failed"),
  });

  return (
    <div className="space-y-6">
      {/* Backup — instant download + automatic month-end (no server-side backup list). */}
      <div className="rounded-lg border bg-card p-6 space-y-3">
        <div className="flex items-center gap-2"><Database className="h-5 w-5 text-primary" /><h3 className="text-lg font-semibold">Backup</h3></div>
        <p className="text-sm text-muted-foreground">
          Download a full backup <span className="font-medium">now</span> as a
          <code className="mx-1 rounded bg-muted px-1">.dump</code> file (nothing is kept on the
          server). A backup is <span className="font-medium">also taken automatically at the end of
          every month</span>, saved as <code className="mx-1 rounded bg-muted px-1">backup_&lt;Month&gt;_&lt;Year&gt;.dump</code>
          in the <code className="mx-1 rounded bg-muted px-1">backups</code> folder on this machine.
          To restore, upload a <code className="mx-1 rounded bg-muted px-1">.dump</code> below.
        </p>
        <Button onClick={handleBackupNow} disabled={downloading}>
          <Download className="mr-2 h-4 w-4" />{downloading ? "Preparing…" : "Download Backup Now"}
        </Button>
      </div>

      {/* Restore (from an uploaded .dump file only) */}
      <div className="rounded-lg border bg-card p-6 space-y-3">
        <div className="flex items-center gap-2"><Upload className="h-5 w-5 text-primary" /><h3 className="text-lg font-semibold">Restore</h3></div>
        <p className="text-sm text-muted-foreground">
          Restore by uploading a backup <code className="rounded bg-muted px-1">.dump</code> file
          from your computer (e.g. a month-end backup you copied off this machine). It is validated
          and then restored, <span className="font-medium"> replacing all current data</span>. This
          cannot be undone.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            id="upload_backup"
            type="file"
            accept=".dump"
            className="max-w-xs"
            onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
          />
          <Button
            variant="outline"
            disabled={!uploadFile}
            onClick={() => setUploadOpen(true)}
          >
            <Upload className="mr-2 h-4 w-4" />Upload &amp; Restore
          </Button>
        </div>
      </div>

      {/* Danger zone */}
      <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-6 space-y-3">
        <div className="flex items-center gap-2 text-destructive"><AlertTriangle className="h-5 w-5" /><h3 className="text-lg font-semibold">Danger Zone</h3></div>
        <p className="text-sm text-muted-foreground">
          Permanently delete all <b>attendance, leave, reimbursement and payroll</b> records
          (and the notifications they generated). <b>Employees are kept</b> — their profiles,
          profile pictures, enrolled face data, reporting lines, audit logs and the system setup
          (branches, roles, leave types, policies) all remain intact.
          <b> Back up first if you might need this data.</b>
        </p>
        <Button variant="destructive" onClick={() => { setConfirmText(""); setDeleteOpen(true); }}>
          <Trash2 className="mr-2 h-4 w-4" />Delete Records
        </Button>
      </div>

      <ConfirmDialog
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        title="Restore from uploaded file?"
        description={uploadFile ? `This will replace ALL current data with the uploaded backup "${uploadFile.name}". This cannot be undone.` : ""}
        destructive
        confirmLabel="Upload & Restore"
        onConfirm={() => uploadFile && uploadRestoreMut.mutate(uploadFile)}
        isLoading={uploadRestoreMut.isPending}
      />

      {/* Delete: type-to-confirm */}
      <Dialog open={deleteOpen} onOpenChange={(o) => { if (!resetMut.isPending) { setDeleteOpen(o); if (!o) setConfirmText(""); } }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-destructive">Delete all records?</DialogTitle>
            <DialogDescription>
              This permanently deletes all attendance, leave, reimbursement and payroll records
              (and their notifications). Employees, their profile pictures and enrolled face data
              are kept. Type <b>DELETE</b> below to confirm.
            </DialogDescription>
          </DialogHeader>
          <Input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} placeholder="Type DELETE" autoFocus />
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setDeleteOpen(false)} disabled={resetMut.isPending}>Cancel</Button>
            <Button variant="destructive" disabled={confirmText !== "DELETE" || resetMut.isPending} onClick={() => resetMut.mutate()}>
              {resetMut.isPending ? "Deleting…" : "Delete Records"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const qc = useQueryClient();

  const { data: policiesResp, isLoading } = useQuery({
    queryKey: ["system-policies"],
    queryFn: () => apiGet<SystemPolicy[]>("/system/policies"),
  });

  const policies = policiesResp?.data ?? [];

  const upsertMutation = useMutation({
    mutationFn: async (updates: Array<{ key: string; value: string }>) => {
      for (const update of updates) {
        await apiPut(`/system/policies/${update.key}`, { value: update.value });
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["system-policies"] });
      toast.success("Settings saved");
    },
    onError: (err: Error) => toast.error(err.message || "Failed to save settings"),
  });

  const handleSave = (updates: Array<{ key: string; value: string }>) => {
    upsertMutation.mutate(updates);
  };

  if (isLoading) {
    return (
      <PortalLayout navItems={ADMIN_NAV} portalLabel="Admin" pageTitle="Settings">
        <div className="space-y-4">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-64 w-full" />
        </div>
      </PortalLayout>
    );
  }

  return (
    <PortalLayout navItems={ADMIN_NAV} portalLabel="Admin" pageTitle="Settings">
      <div className="space-y-6">
        <div>
          <h2 className="text-2xl font-bold">System Settings</h2>
          <p className="text-muted-foreground">Configure system-wide policies and integrations</p>
        </div>

        <Tabs defaultValue="attendance">
          <TabsList className="grid w-full grid-cols-5">
            <TabsTrigger value="attendance">Attendance</TabsTrigger>
            <TabsTrigger value="notifications">Notifications</TabsTrigger>
            <TabsTrigger value="storage">Storage</TabsTrigger>
            <TabsTrigger value="security">Security</TabsTrigger>
            <TabsTrigger value="data">Data</TabsTrigger>
          </TabsList>

          <TabsContent value="attendance" className="mt-6">
            <div className="rounded-lg border bg-card p-6">
              <h3 className="mb-4 text-lg font-semibold">Attendance Rules</h3>
              <AttendanceTab
                policies={policies}
                onSave={handleSave}
                isSaving={upsertMutation.isPending}
              />
            </div>
          </TabsContent>

          <TabsContent value="notifications" className="mt-6">
            <div className="rounded-lg border bg-card p-6">
              <h3 className="mb-4 text-lg font-semibold">Notification Channels</h3>
              <NotificationsTab
                policies={policies}
                onSave={handleSave}
                isSaving={upsertMutation.isPending}
              />
            </div>
          </TabsContent>

          <TabsContent value="storage" className="mt-6">
            <div className="rounded-lg border bg-card p-6">
              <h3 className="mb-4 text-lg font-semibold">Object Storage (MinIO)</h3>
              <StorageTab policies={policies} />
            </div>
          </TabsContent>

          <TabsContent value="security" className="mt-6">
            <div className="rounded-lg border bg-card p-6">
              <h3 className="mb-4 text-lg font-semibold">Security Policies</h3>
              <SecurityTab
                policies={policies}
                onSave={handleSave}
                isSaving={upsertMutation.isPending}
              />
            </div>
          </TabsContent>

          <TabsContent value="data" className="mt-6">
            <DataTab />
          </TabsContent>
        </Tabs>
      </div>
    </PortalLayout>
  );
}
