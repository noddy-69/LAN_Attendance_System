"use client";

import { useEffect, useRef, useState } from "react";
import { Video, Loader2, CircleDot, AlertTriangle } from "lucide-react";

import { PortalLayout } from "@/components/shared/Layout";
import { ADMIN_NAV } from "@/components/admin/nav";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { whipPublish, type WhipSession } from "@/lib/whip";

// Same-origin path — nginx proxies /mediamtx/ to mediamtx on the host, so the
// browser never makes a cross-origin call (no CORS headaches).
const WHIP_PATH = "/mediamtx/webcam/whip";

export default function AdminCameraPage() {
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [deviceId, setDeviceId] = useState<string>("");
  const [whipUrl, setWhipUrl] = useState<string>("");
  const [streaming, setStreaming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const previewStream = useRef<MediaStream | null>(null);
  const session = useRef<WhipSession | null>(null);

  // ── Init: ask permission, enumerate cameras, preview the first one ──────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      // Default the WHIP endpoint to this app's own origin (same-origin via nginx).
      if (typeof window !== "undefined") setWhipUrl(window.location.origin + WHIP_PATH);
      if (typeof window !== "undefined" && !window.isSecureContext) {
        setError(
          "Your browser blocks camera access on this address. Open the app at " +
            "http://localhost (on the machine running the system), or enable HTTPS."
        );
        return;
      }
      try {
        // Permission first — device labels are hidden until the user grants access.
        const probe = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
        probe.getTracks().forEach((t) => t.stop());
        const list = (await navigator.mediaDevices.enumerateDevices()).filter(
          (d) => d.kind === "videoinput" && d.deviceId
        );
        if (cancelled) return;
        setDevices(list);
        const first = list[0]?.deviceId ?? "";
        setDeviceId(first);
        await openPreview(first);
      } catch {
        if (!cancelled)
          setError(
            "Camera permission was denied or no camera is available. Allow camera " +
              "access in the browser and reload."
          );
      }
    })();
    return () => {
      cancelled = true;
      stopEverything();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function openPreview(id: string) {
    // Stop the old preview only if we're not currently publishing it.
    if (previewStream.current && !streaming) {
      previewStream.current.getTracks().forEach((t) => t.stop());
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      video: id ? { deviceId: { exact: id } } : true,
      audio: false,
    });
    previewStream.current = stream;
    if (videoRef.current) videoRef.current.srcObject = stream;
  }

  async function onDeviceChange(id: string) {
    setDeviceId(id);
    setError(null);
    try {
      await openPreview(id);
    } catch {
      setError("Could not open that camera. It may be in use by another app.");
    }
  }

  async function startStreaming() {
    if (!previewStream.current) return;
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      session.current = await whipPublish(previewStream.current, whipUrl.trim());
      setStreaming(true);
      setInfo(
        "Streaming to the system. The face-recognition service connects within ~30s — " +
          "or restart it for an instant reconnect: docker compose restart face-recognition"
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start streaming.");
    } finally {
      setBusy(false);
    }
  }

  async function stopStreaming() {
    setBusy(true);
    try {
      await session.current?.close();
      session.current = null;
      setStreaming(false);
      setInfo(null);
      // Re-open a fresh preview (publishing may have ended the tracks).
      await openPreview(deviceId).catch(() => {});
    } finally {
      setBusy(false);
    }
  }

  function stopEverything() {
    session.current?.close();
    session.current = null;
    previewStream.current?.getTracks().forEach((t) => t.stop());
    previewStream.current = null;
  }

  return (
    <PortalLayout navItems={ADMIN_NAV} portalLabel="Admin" pageTitle="Camera">
      <div className="max-w-3xl space-y-6">
        <div>
          <h2 className="text-2xl font-bold">Camera</h2>
          <p className="text-sm text-muted-foreground">
            Pick which attached webcam feeds the attendance system, preview it, and stream it in —
            no command line needed.
          </p>
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="rounded-lg border bg-card p-5 shadow-sm space-y-4">
          {/* Device picker */}
          <div className="space-y-1.5">
            <Label>Camera device</Label>
            <Select value={deviceId} onValueChange={onDeviceChange} disabled={streaming || !devices.length}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder={devices.length ? "Select a camera" : "No cameras found"} />
              </SelectTrigger>
              <SelectContent>
                {devices.map((d, i) => (
                  <SelectItem key={d.deviceId} value={d.deviceId}>
                    {d.label || `Camera ${i + 1}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {streaming && (
              <p className="text-xs text-muted-foreground">Stop streaming to switch cameras.</p>
            )}
          </div>

          {/* Live preview */}
          <div className="relative overflow-hidden rounded-md border bg-black">
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="aspect-video w-full object-contain"
            />
            {streaming && (
              <Badge className="absolute left-3 top-3 gap-1 bg-red-600 text-white hover:bg-red-600">
                <CircleDot className="h-3 w-3 animate-pulse" /> LIVE
              </Badge>
            )}
          </div>

          {/* Stream control */}
          <div className="flex items-center gap-3">
            {!streaming ? (
              <Button onClick={startStreaming} disabled={busy || !deviceId}>
                {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Video className="mr-2 h-4 w-4" />}
                Use this camera
              </Button>
            ) : (
              <Button variant="destructive" onClick={stopStreaming} disabled={busy}>
                {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                Stop streaming
              </Button>
            )}
            <span className="text-sm text-muted-foreground">
              {streaming ? "● Streaming to system" : "Not streaming"}
            </span>
          </div>

          {info && (
            <div className="rounded-md border border-green-600/40 bg-green-600/10 px-4 py-3 text-sm text-green-700 dark:text-green-400">
              {info}
            </div>
          )}
        </div>

        {/* Advanced */}
        <div className="rounded-lg border bg-card p-5 shadow-sm space-y-1.5">
          <Label htmlFor="whip">Streaming server (WHIP endpoint)</Label>
          <Input id="whip" value={whipUrl} onChange={(e) => setWhipUrl(e.target.value)} disabled={streaming} />
          <p className="text-xs text-muted-foreground">
            Default points at mediamtx on this machine. The face service reads the matching RTSP path
            (<code>rtsp://host.docker.internal:8554/webcam</code>). Requires <code>mediamtx</code> to be running.
          </p>
        </div>
      </div>
    </PortalLayout>
  );
}
