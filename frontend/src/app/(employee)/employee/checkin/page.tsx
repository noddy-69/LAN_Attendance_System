"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ScanFace, Loader2, AlertTriangle, CheckCircle2, RefreshCw } from "lucide-react";

import { useAuthStore } from "@/stores/auth-store";
import { useMe } from "@/hooks/use-auth";
import { api, apiGet } from "@/lib/api";
import { EmployeeLayout } from "@/components/employee/EmployeeLayout";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SelfieConfig {
  enabled: boolean;
  enrolled: boolean;
  checked_in: boolean;
  checked_out: boolean;
  check_in: string | null;
  check_out: string | null;
}

interface DailyAtt {
  status: string;
  check_in: string | null;
  check_out: string | null;
}

type Phase = "idle" | "capturing" | "submitting" | "done";

// ── Liveness challenge (direction-matched head turn) ────────────────────────────
// A specific side is chosen at random and the face-service verifies the head actually
// turned THAT way (not just that it moved). A generic replayed head-movement video
// only matches the random prompt by luck, and circular/shaking motion has no dominant
// side, so it fails.
const DIRECTIONS = [
  { key: "left", label: "Turn your head to your LEFT, then back to centre" },
  { key: "right", label: "Turn your head to your RIGHT, then back to centre" },
] as const;

type Direction = (typeof DIRECTIONS)[number];

function pickChallenge(): Direction {
  return DIRECTIONS[Math.floor(Math.random() * DIRECTIONS.length)];
}

function timeIST(utc: string | null) {
  if (!utc) return "—";
  return new Date(utc).toLocaleTimeString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SelfieCheckinPage() {
  const router = useRouter();
  const { isAuthenticated } = useAuthStore();
  const { data: user, isLoading: userLoading } = useMe();
  const qc = useQueryClient();

  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const [camReady, setCamReady] = useState(false);
  const [camError, setCamError] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [challenge, setChallenge] = useState<Direction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<DailyAtt | null>(null);

  useEffect(() => {
    if (!isAuthenticated && !userLoading) router.replace("/login");
  }, [isAuthenticated, userLoading, router]);

  // ── Config (enabled / enrolled / today's status) ──────────────────────────
  const { data: cfgResp, isLoading: cfgLoading } = useQuery({
    queryKey: ["selfie-config", user?.id],
    queryFn: () => apiGet<SelfieConfig>("/attendance/selfie-config"),
    enabled: !!user?.id,
  });
  const cfg = cfgResp?.data ?? null;

  // ── Camera lifecycle ───────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (typeof window !== "undefined" && !window.isSecureContext) {
        setCamError(
          "Your browser blocks the camera on this address. Open the app over HTTPS " +
            "(install the provided certificate on your phone), or use http://localhost on the host PC."
        );
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) videoRef.current.srcObject = stream;
        setCamReady(true);
      } catch {
        if (!cancelled)
          setCamError(
            "Camera permission was denied or no camera is available. Allow camera access and reload."
          );
      }
    })();
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, []);

  // ── Frame capture ───────────────────────────────────────────────────────────
  async function grabFrame(): Promise<Blob | null> {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || !video.videoWidth) return null;
    const maxW = 640;
    const scale = Math.min(1, maxW / video.videoWidth);
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    // Draw the true (un-mirrored) pixels — only the CSS preview is mirrored.
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    return await new Promise((res) => canvas.toBlob((b) => res(b), "image/jpeg", 0.85));
  }

  async function captureBurst(n = 6, intervalMs = 350): Promise<Blob[]> {
    const blobs: Blob[] = [];
    for (let i = 0; i < n; i++) {
      const b = await grabFrame();
      if (b) blobs.push(b);
      if (i < n - 1) await new Promise((r) => setTimeout(r, intervalMs));
    }
    return blobs;
  }

  async function doCheckin(eventType: "ENTRY" | "EXIT") {
    setError(null);
    if (!camReady) {
      setError("Camera is not ready yet.");
      return;
    }
    const ch = pickChallenge();
    setChallenge(ch);
    setPhase("capturing");
    // Give the user a moment to read the prompt and start moving.
    await new Promise((r) => setTimeout(r, 1000));
    const blobs = await captureBurst();
    if (blobs.length < 3) {
      setError("Could not capture enough frames — check your camera and try again.");
      setPhase("idle");
      return;
    }
    setPhase("submitting");
    const form = new FormData();
    form.append("event_type", eventType);
    form.append("challenge", ch.key); // which way we asked them to turn
    blobs.forEach((b, i) => form.append("frames", b, `frame_${i}.jpg`));
    try {
      const res = await api.post("/attendance/selfie-checkin", form, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 60_000,
      });
      setResult(res.data?.data ?? null);
      setPhase("done");
      qc.invalidateQueries({ queryKey: ["selfie-config"] });
      qc.invalidateQueries({ queryKey: ["emp-today"] });
    } catch (e) {
      const msg =
        (e as { response?: { data?: { error?: string } } })?.response?.data?.error ??
        "Check-in failed. Please try again.";
      setError(msg);
      setPhase("idle");
    }
  }

  function reset() {
    setResult(null);
    setError(null);
    setPhase("idle");
    qc.invalidateQueries({ queryKey: ["selfie-config"] });
  }

  if (userLoading || !user) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  const busy = phase === "capturing" || phase === "submitting";
  // After a successful check-in, check-out is OPTIONAL — offered, never forced.
  const canCheckIn = cfg && cfg.enabled && cfg.enrolled && !cfg.checked_in;
  const canCheckOut = cfg && cfg.enabled && cfg.enrolled && cfg.checked_in && !cfg.checked_out;

  return (
    <EmployeeLayout pageTitle="Selfie Check-in">
      <div className="mx-auto max-w-xl space-y-5">
        <div>
          <h2 className="text-xl font-bold">Selfie Check-in</h2>
          <p className="text-sm text-muted-foreground">
            Mark your attendance from the office network with a quick live selfie.
          </p>
        </div>

        {cfgLoading ? (
          <Skeleton className="h-64 rounded-2xl" />
        ) : !cfg?.enabled ? (
          <Banner kind="warn">Selfie check-in is currently disabled by your administrator.</Banner>
        ) : !cfg?.enrolled ? (
          <Banner kind="warn">
            You aren&apos;t enrolled for face check-in yet. Ask HR or an administrator to enroll
            your face, then come back here.
          </Banner>
        ) : (
          <>
            {/* Today's status */}
            <div className="flex items-center justify-between rounded-2xl border bg-card p-4 shadow-sm">
              <div className="flex gap-6 text-sm">
                <div>
                  <p className="text-xs text-muted-foreground">Check-in</p>
                  <p className="text-lg font-bold tabular-nums">{timeIST(cfg.check_in)}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Check-out</p>
                  <p className="text-lg font-bold tabular-nums">{timeIST(cfg.check_out)}</p>
                </div>
              </div>
            </div>

            {camError ? (
              <Banner kind="error">{camError}</Banner>
            ) : (
              <div className="overflow-hidden rounded-2xl border bg-card shadow-sm">
                {/* Camera preview (CSS-mirrored for natural selfie feel) */}
                <div className="relative aspect-[3/4] w-full bg-black sm:aspect-video">
                  <video
                    ref={videoRef}
                    autoPlay
                    playsInline
                    muted
                    className="h-full w-full object-cover [transform:scaleX(-1)]"
                  />
                  {phase === "capturing" && (
                    <div className="absolute inset-0 flex flex-col items-center justify-end bg-black/35 p-5 text-center">
                      <div className="mb-3 h-10 w-10 animate-pulse rounded-full border-4 border-white/80 border-t-transparent" />
                      <p className="rounded-lg bg-black/60 px-3 py-2 text-sm font-medium text-white">
                        {challenge?.label}
                      </p>
                    </div>
                  )}
                  {phase === "submitting" && (
                    <div className="absolute inset-0 flex items-center justify-center bg-black/45">
                      <div className="flex items-center gap-2 rounded-lg bg-black/70 px-4 py-2 text-sm text-white">
                        <Loader2 className="h-4 w-4 animate-spin" /> Verifying…
                      </div>
                    </div>
                  )}
                </div>

                <div className="space-y-3 p-4">
                  {phase === "done" && result ? (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 rounded-lg border border-green-600/40 bg-green-600/10 px-4 py-3 text-sm text-green-700 dark:text-green-400">
                        <CheckCircle2 className="h-5 w-5 shrink-0" />
                        <span>
                          Attendance recorded —{" "}
                          {result.check_out ? "checked out" : "checked in"} at{" "}
                          <b>{timeIST(result.check_out ?? result.check_in)}</b>.
                        </span>
                        <StatusBadge status={result.status} />
                      </div>
                      <Button variant="outline" className="w-full" onClick={reset}>
                        <RefreshCw className="mr-2 h-4 w-4" /> Done
                      </Button>
                    </div>
                  ) : (
                    <>
                      {error && <Banner kind="error">{error}</Banner>}

                      {canCheckIn && (
                        <Button
                          className="h-12 w-full text-base"
                          disabled={busy || !camReady}
                          onClick={() => doCheckin("ENTRY")}
                        >
                          {busy ? (
                            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                          ) : (
                            <ScanFace className="mr-2 h-5 w-5" />
                          )}
                          Check In
                        </Button>
                      )}

                      {canCheckOut && (
                        <>
                          <Button
                            className="h-12 w-full text-base"
                            variant="secondary"
                            disabled={busy || !camReady}
                            onClick={() => doCheckin("EXIT")}
                          >
                            {busy ? (
                              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                            ) : (
                              <ScanFace className="mr-2 h-5 w-5" />
                            )}
                            Check Out (optional)
                          </Button>
                          <p className="text-center text-xs text-muted-foreground">
                            You&apos;re already checked in. Checking out is optional.
                          </p>
                        </>
                      )}

                      {cfg.checked_in && cfg.checked_out && (
                        <Banner kind="ok">
                          You&apos;ve checked in and out for today. Nothing more to do.
                        </Banner>
                      )}

                      {!busy && (canCheckIn || canCheckOut) && (
                        <p className="text-center text-xs text-muted-foreground">
                          When you tap, follow the on-screen prompt and move your head so the system
                          can confirm you&apos;re live.
                        </p>
                      )}
                    </>
                  )}
                </div>
              </div>
            )}
          </>
        )}

        <canvas ref={canvasRef} className="hidden" />
      </div>
    </EmployeeLayout>
  );
}

// ── Small banner ────────────────────────────────────────────────────────────
function Banner({
  kind,
  children,
}: {
  kind: "warn" | "error" | "ok";
  children: React.ReactNode;
}) {
  const styles = {
    warn: "border-yellow-600/40 bg-yellow-600/10 text-yellow-700 dark:text-yellow-400",
    error: "border-destructive/50 bg-destructive/10 text-destructive",
    ok: "border-green-600/40 bg-green-600/10 text-green-700 dark:text-green-400",
  }[kind];
  return (
    <div className={`flex items-start gap-2 rounded-lg border px-4 py-3 text-sm ${styles}`}>
      {kind !== "ok" && <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />}
      <span>{children}</span>
    </div>
  );
}
