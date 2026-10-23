"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Camera, Check } from "lucide-react";
import { useAuthStore } from "@/stores/auth-store";
import { useMe } from "@/hooks/use-auth";
import { apiPatch, api } from "@/lib/api";
import { formatRoleName } from "@/lib/utils";
import { EmployeeLayout } from "@/components/employee/EmployeeLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ProfilePage() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  const { data: user, isLoading: userLoading } = useMe();
  const qc = useQueryClient();

  const avatarRef = useRef<HTMLInputElement>(null);

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName]   = useState("");
  const [phone, setPhone]         = useState("");
  const [saveMsg, setSaveMsg]     = useState<string | null>(null);
  const [saveErr, setSaveErr]     = useState<string | null>(null);

  // Populate form when user loads
  useEffect(() => {
    if (user) {
      setFirstName(user.first_name);
      setLastName(user.last_name);
      setPhone(user.phone ?? "");
    }
  }, [user]);

  useEffect(() => {
    if (!isAuthenticated && !userLoading) router.replace("/login");
  }, [isAuthenticated, userLoading, router]);

  // Update profile mutation
  const { mutate: saveProfile, isPending: saving } = useMutation({
    mutationFn: () =>
      apiPatch(`/employees/${user!.id}`, {
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        phone: phone.trim() || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
      setSaveMsg("Profile updated successfully.");
      setSaveErr(null);
      setTimeout(() => setSaveMsg(null), 3000);
    },
    onError: (e: Error) => setSaveErr(e.message ?? "Save failed"),
  });

  // Avatar upload mutation
  const { mutate: uploadAvatar, isPending: uploading } = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      await api.post(`/employees/${user!.id}/avatar`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["me"] });
    },
    onError: (e: Error) => setSaveErr(e.message ?? "Avatar upload failed"),
  });

  function handleSave() {
    setSaveErr(null);
    if (!firstName.trim()) return setSaveErr("First name is required");
    if (!lastName.trim())  return setSaveErr("Last name is required");
    saveProfile();
  }

  if (userLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  const initials = `${user.first_name[0]}${user.last_name[0]}`.toUpperCase();

  return (
    <EmployeeLayout pageTitle="Profile">
      <div className="mx-auto max-w-xl space-y-6">

        {/* Avatar */}
        <div className="flex flex-col items-center gap-3 py-2">
          <div className="relative">
            <Avatar className="h-24 w-24">
              <AvatarImage src={user.avatar_url ?? ""} alt={user.first_name} />
              <AvatarFallback className="text-2xl">{initials}</AvatarFallback>
            </Avatar>
            <button
              onClick={() => avatarRef.current?.click()}
              disabled={uploading}
              className="absolute bottom-0 right-0 flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-md transition-opacity active:opacity-80"
              aria-label="Change avatar"
            >
              {uploading ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
              ) : (
                <Camera className="h-4 w-4" />
              )}
            </button>
            <input
              ref={avatarRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="hidden"
              onChange={e => {
                const f = e.target.files?.[0];
                if (f) uploadAvatar(f);
                if (avatarRef.current) avatarRef.current.value = "";
              }}
            />
          </div>
          <div className="text-center">
            <p className="text-lg font-bold">{user.first_name} {user.last_name}</p>
            <p className="text-sm text-muted-foreground">{formatRoleName(user.role_name)}</p>
            <p className="text-sm text-muted-foreground">{user.email}</p>
          </div>
        </div>

        {/* Editable info */}
        <div className="rounded-xl border bg-card p-4 shadow-sm space-y-4">
          <h3 className="font-semibold">Personal Information</h3>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="first-name">First Name</Label>
              <Input
                id="first-name"
                value={firstName}
                onChange={e => setFirstName(e.target.value)}
                className="h-12"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="last-name">Last Name</Label>
              <Input
                id="last-name"
                value={lastName}
                onChange={e => setLastName(e.target.value)}
                className="h-12"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="phone">Phone Number</Label>
            <Input
              id="phone"
              type="tel"
              inputMode="tel"
              placeholder="+91 98765 43210"
              value={phone}
              onChange={e => setPhone(e.target.value)}
              className="h-12"
            />
          </div>

          {saveErr && <p className="text-sm font-medium text-destructive">{saveErr}</p>}
          {saveMsg && (
            <div className="flex items-center gap-2 text-sm font-medium text-green-600 dark:text-green-400">
              <Check className="h-4 w-4" />
              {saveMsg}
            </div>
          )}

          <Button
            className="h-12 w-full text-base"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? "Saving…" : "Save Changes"}
          </Button>
        </div>

        {/* Read-only employee info */}
        <div className="rounded-xl border bg-card p-4 shadow-sm space-y-3">
          <h3 className="font-semibold">Employee Information</h3>
          <div className="space-y-2 text-sm">
            {[
              { label: "Employee Code",  value: user.employee_code },
              { label: "Email",          value: user.email },
              { label: "Role",           value: formatRoleName(user.role_name) },
              { label: "Branch",         value: user.branch_name ?? "—" },
              { label: "Department",     value: user.department_name ?? "—" },
            ].map(({ label, value }) => (
              <div key={label} className="flex items-center gap-2">
                <span className="w-36 shrink-0 text-muted-foreground">{label}</span>
                <span className="min-w-0 flex-1 truncate font-medium">{value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Change password — placeholder (backend endpoint not yet implemented) */}
        <div className="rounded-xl border bg-card p-4 shadow-sm space-y-3">
          <h3 className="font-semibold">Security</h3>
          <p className="text-sm text-muted-foreground">
            Password changes must be requested through your HR administrator.
          </p>
        </div>
      </div>
    </EmployeeLayout>
  );
}
