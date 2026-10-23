"use client";

import Link from "next/link";
import { Building2, ArrowLeft, KeyRound } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export default function ForgotPasswordPage() {
  return (
    <div className="w-full max-w-md">
      <div className="mb-8 flex flex-col items-center gap-2">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary shadow-lg">
          <Building2 className="h-7 w-7 text-primary-foreground" />
        </div>
        <h1 className="text-2xl font-bold tracking-tight">Attendance System</h1>
        <p className="text-sm text-muted-foreground">Workforce management, simplified</p>
      </div>

      <Card className="shadow-xl">
        <CardHeader className="space-y-1">
          <CardTitle className="text-xl">Forgot your password?</CardTitle>
          <CardDescription>
            Passwords are managed by your HR / administrator.
          </CardDescription>
        </CardHeader>

        <CardContent>
          <div className="flex flex-col items-center gap-4 py-2 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
              <KeyRound className="h-6 w-6 text-primary" />
            </div>
            <p className="text-sm text-muted-foreground">
              To reset your password, please contact your HR or system administrator.
              They can set a new password for your account from the admin portal and
              share it with you securely.
            </p>
          </div>
        </CardContent>
      </Card>

      <p className="mt-4 text-center text-sm">
        <Link
          href="/login"
          className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-3 w-3" /> Back to sign in
        </Link>
      </p>
    </div>
  );
}
