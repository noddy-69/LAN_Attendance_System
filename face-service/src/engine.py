"""
AttendanceEngine — ties camera + tracker + recognizer into the full pipeline.

Pipeline (from CLAUDE.md verbatim):
  1. Connect to RTSP streams (Entry + Exit camera)
  2. OpenCV reads frames at 5 FPS
  3. ByteTrack assigns track IDs per physical person
  4. InsightFace extracts 512-dim embeddings (ONNX INT8, CPU-only)
  5. Cosine similarity vs stored embeddings (threshold 0.95)
  6. Cooldown: 5 min per employee per camera (no double-marking)
  7. Sequence validation handled by backend (it owns daily_attendance)
  8. On valid detection:
       a. Save proof frame to MinIO (entry_{emp_id}_{date}.jpg)
       b. POST event to backend /api/v1/attendance/camera-event
  9. If camera offline: log warning, continue accepting biometric events

Threading model:
  One daemon thread per enabled camera stream.
  Cooldown map is protected by a threading.Lock.
  Track ID counter (in tracker.py) is also lock-protected.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
import numpy as np

from src.antispoof import AntiSpoofer
from src.camera import CameraType, FrameResult, RTSPCamera
from src.config import settings
from src.recognizer import FaceDetection, FaceRecognizer
from src.tracker import BYTETracker

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _iou(a: np.ndarray, b: np.ndarray) -> float:
    """IoU between two boxes [x1, y1, x2, y2]."""
    ix1 = max(a[0], b[0]); iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2]); iy2 = min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return inter / max(area_a + area_b - inter, 1e-7)


def _best_det_for_track(
    track_box: np.ndarray,
    dets: list[FaceDetection],
    min_iou: float = 0.1,
) -> Optional[FaceDetection]:
    """Return the detection whose bbox overlaps most with the track box."""
    best: Optional[FaceDetection] = None
    best_iou: float = min_iou
    for d in dets:
        iou = _iou(track_box, d.bbox)
        if iou > best_iou:
            best_iou = iou
            best = d
    return best


# ── Engine state per camera ───────────────────────────────────────────────────

@dataclass
class CameraStats:
    camera_type: CameraType
    frames_processed: int = 0
    faces_detected: int = 0
    events_fired: int = 0
    spoofs_rejected: int = 0
    last_event_at: Optional[float] = None
    is_running: bool = False
    last_error: Optional[str] = None


# ── AttendanceEngine ──────────────────────────────────────────────────────────

class AttendanceEngine:
    """
    Orchestrates the full attendance detection pipeline.

    Call start() after the recognizer is initialised.
    Call stop() before shutdown.
    """

    def __init__(self, recognizer: FaceRecognizer) -> None:
        self.recognizer = recognizer
        self.antispoof = AntiSpoofer()
        if self.antispoof.active:
            log.info("Anti-spoofing ENABLED (threshold=%.2f)", self.antispoof.threshold)
        elif self.antispoof.enabled:
            log.warning("Anti-spoofing requested but no model loaded — failing open")

        # cooldown_key = f"{employee_id}:{camera_type.value}"  → last event monotonic ts
        self._cooldown: dict[str, float] = {}
        self._cooldown_lock = threading.Lock()

        self._stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._stats: dict[str, CameraStats] = {}

        # Synchronous httpx client shared across the camera threads
        self._http = httpx.Client(timeout=10.0, follow_redirects=True)
        self._token: Optional[str] = None
        self._token_expiry: float = 0.0
        self._token_lock = threading.Lock()
        # Branch the events are attributed to. Falls back to the service
        # account's own branch (fetched from /auth/me) when BRANCH_ID is unset.
        self._branch_id: Optional[str] = settings.BRANCH_ID or None

        # Camera-type → registered device UUID, for liveness heartbeats.
        self._device_ids: dict[CameraType, str] = {
            CameraType.ENTRY: settings.ENTRY_CAMERA_DEVICE_ID,
            CameraType.EXIT:  settings.EXIT_CAMERA_DEVICE_ID,
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._stop_event.clear()
        cameras = self._build_cameras()
        if not cameras:
            log.warning(
                "No cameras configured (ENTRY_CAMERA_URL / EXIT_CAMERA_URL are empty). "
                "Face recognition pipeline is idle."
            )
            return

        for cam in cameras:
            key = cam.camera_type.value
            self._stats[key] = CameraStats(camera_type=cam.camera_type)
            tracker = BYTETracker(
                track_thresh=settings.TRACK_THRESH,
                low_thresh=settings.LOW_THRESH,
                new_track_thresh=settings.NEW_TRACK_THRESH,
                track_buffer=settings.TRACK_BUFFER,
                match_thresh=settings.MATCH_THRESH,
            )
            t = threading.Thread(
                target=self._camera_loop,
                args=(cam, tracker),
                daemon=True,
                name=f"face-cam-{key}",
            )
            t.start()
            self._threads.append(t)
            log.info("Camera thread started: %s", key)

        # Heartbeat thread — reports camera liveness to the backend dashboard.
        if any(self._device_ids.values()):
            hb = threading.Thread(
                target=self._heartbeat_loop, daemon=True, name="face-heartbeat"
            )
            hb.start()
            self._threads.append(hb)
            log.info("Heartbeat thread started")

    def stop(self) -> None:
        self._stop_event.set()
        for t in self._threads:
            t.join(timeout=5.0)
        self._http.close()
        log.info("AttendanceEngine stopped")

    @property
    def is_running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def get_stats(self) -> dict:
        return {
            k: {
                "frames": s.frames_processed,
                "faces": s.faces_detected,
                "events": s.events_fired,
                "spoofs_rejected": s.spoofs_rejected,
                "running": s.is_running,
                "last_error": s.last_error,
            }
            for k, s in self._stats.items()
        }

    # ── Camera building ───────────────────────────────────────────────────────

    def _build_cameras(self) -> list[RTSPCamera]:
        cameras: list[RTSPCamera] = []
        for url, cam_type in (
            (settings.ENTRY_CAMERA_URL, CameraType.ENTRY),
            (settings.EXIT_CAMERA_URL, CameraType.EXIT),
        ):
            if url:
                cameras.append(
                    RTSPCamera(
                        source=url,
                        camera_type=cam_type,
                        target_fps=settings.CAMERA_FPS,
                        frame_skip=settings.FRAME_SKIP,
                        reconnect_interval_s=settings.CAMERA_RECONNECT_S,
                    )
                )
        return cameras

    # ── Per-camera loop ───────────────────────────────────────────────────────

    def _camera_loop(self, camera: RTSPCamera, tracker: BYTETracker) -> None:
        stats = self._stats[camera.camera_type.value]
        stats.is_running = True
        log.info("Camera loop running: source=%s type=%s", camera.source, camera.camera_type.value)

        try:
            for fr in camera.frames():
                if self._stop_event.is_set():
                    break
                try:
                    self.recognizer.refresh_embeddings_if_needed()
                    self._process_frame(fr, tracker, stats)
                except Exception:
                    log.exception("Unhandled error in _process_frame")
        except Exception as exc:
            stats.last_error = str(exc)
            log.error("Camera loop exited with error: %s", exc)
        finally:
            stats.is_running = False
            log.info("Camera loop finished: %s", camera.camera_type.value)

    # ── Frame processing ──────────────────────────────────────────────────────

    def _process_frame(
        self,
        fr: FrameResult,
        tracker: BYTETracker,
        stats: CameraStats,
    ) -> None:
        stats.frames_processed += 1

        # Step 1 — detect all faces in the frame (InsightFace)
        face_dets = self.recognizer.detect_and_embed(fr.frame)
        stats.faces_detected += len(face_dets)

        # Step 2 — feed bounding boxes + scores to ByteTrack
        if face_dets:
            det_arr = np.array(
                [[*d.bbox, d.score] for d in face_dets], dtype=float
            )
        else:
            det_arr = np.empty((0, 5), dtype=float)

        active_tracks = tracker.update(det_arr)

        # Step 3 — for each new/re-activated track, attempt recognition
        for track in active_tracks:
            if not track.needs_recognition:
                continue

            # Clear the flag immediately so even if we skip, it won't re-run
            track.needs_recognition = False

            # Find the detection that best overlaps this track's KF-predicted box
            best_det = _best_det_for_track(track.tlbr, face_dets)
            if best_det is None:
                log.debug(
                    "Track %d: no matching detection for recognition (IoU too low)",
                    track.track_id,
                )
                continue

            # Step 4 — cosine similarity against all known embeddings
            result = self.recognizer.identify_face(best_det.embedding)
            if result is None:
                log.debug("Track %d: unknown face (sim below %.2f)", track.track_id, settings.FACE_CONFIDENCE_THRESHOLD)
                continue

            employee_id, similarity = result

            # Step 4b — liveness / anti-spoofing (printed photo & screen replay)
            if self.antispoof.active:
                is_real, spoof_score = self.antispoof.is_real(fr.frame, best_det.bbox)
                if not is_real:
                    stats.spoofs_rejected += 1
                    log.warning(
                        "SPOOF rejected  employee=%s camera=%s real_score=%.3f",
                        employee_id, fr.camera_type.value, spoof_score,
                    )
                    continue

            # Step 5 — cooldown check (per employee per camera)
            cooldown_key = f"{employee_id}:{fr.camera_type.value}"
            with self._cooldown_lock:
                if self._is_cooling_down(cooldown_key):
                    remaining = settings.FACE_COOLDOWN_SECONDS - (
                        time.monotonic() - self._cooldown[cooldown_key]
                    )
                    log.info(
                        "[cooldown] employee=%s camera=%s remaining=%.0fs",
                        employee_id, fr.camera_type.value, remaining,
                    )
                    continue
                # Reserve the slot atomically
                self._cooldown[cooldown_key] = time.monotonic()

            # Step 6 — fire the attendance event
            stats.events_fired += 1
            stats.last_event_at = time.monotonic()
            log.info(
                "MATCH  track_id=%d  employee=%s  camera=%s  sim=%.4f",
                track.track_id, employee_id, fr.camera_type.value, similarity,
            )
            self._fire_event(employee_id, fr, track, best_det, similarity)

    # ── Cooldown helpers ──────────────────────────────────────────────────────

    def _is_cooling_down(self, key: str) -> bool:
        ts = self._cooldown.get(key)
        if ts is None:
            return False
        return (time.monotonic() - ts) < settings.FACE_COOLDOWN_SECONDS

    # ── Attendance event ──────────────────────────────────────────────────────

    def _fire_event(
        self,
        employee_id: str,
        fr: FrameResult,
        track,        # STrack
        det: FaceDetection,
        similarity: float,
    ) -> None:
        """Save proof frame + POST camera-event to backend (or mock-log)."""
        now_utc = datetime.now(timezone.utc)
        event_type = "ENTRY" if fr.camera_type == CameraType.ENTRY else "EXIT"
        ts_tag = now_utc.strftime("%Y%m%d_%H%M%S")
        object_key = f"{event_type.lower()}/{employee_id}/{ts_tag}_{track.track_id}.jpg"

        # Step 8a — save proof frame to MinIO
        proof_path: Optional[str] = None
        try:
            proof_path = self.recognizer.save_proof_frame(object_key, fr.frame)
        except Exception as exc:
            log.error("Proof frame save failed: %s", exc)

        payload = {
            "employee_id": employee_id,
            "branch_id": self._resolve_branch_id(),
            "device_id": None,
            "event_type": event_type,
            "timestamp": now_utc.isoformat(),
            "confidence_score": round(similarity, 4),
            "proof_storage_path": proof_path,
        }

        # Step 8b — POST to backend (or mock-log)
        if settings.MOCK_BACKEND:
            log.info("[MOCK EVENT] %s", payload)
            return

        try:
            headers = {"Authorization": f"Bearer {self._get_service_token()}"}
            resp = self._http.post(
                f"{settings.BACKEND_URL}/api/v1/attendance/camera-event",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            log.info(
                "Event accepted by backend: employee=%s type=%s status=%d",
                employee_id, event_type, resp.status_code,
            )
        except httpx.HTTPStatusError as exc:
            log.error(
                "Backend rejected event: %s %s — %s",
                exc.response.status_code, exc.response.url, exc.response.text[:200],
            )
        except Exception as exc:
            log.error("Failed to POST camera event: %s", exc)

    # ── Heartbeat ──────────────────────────────────────────────────────────────

    def _heartbeat_loop(self) -> None:
        """Periodically tell the backend each running camera is alive."""
        while not self._stop_event.is_set():
            # Sleep first so we don't double-fire right at startup.
            if self._stop_event.wait(settings.HEARTBEAT_INTERVAL_S):
                break
            for cam_type, dev_id in self._device_ids.items():
                if not dev_id:
                    continue
                stats = self._stats.get(cam_type.value)
                if stats and stats.is_running:
                    self._post_heartbeat(dev_id)

    def _post_heartbeat(self, device_id: str) -> None:
        if settings.MOCK_BACKEND:
            log.debug("[MOCK HEARTBEAT] device=%s", device_id)
            return
        try:
            headers = {"Authorization": f"Bearer {self._get_service_token()}"}
            resp = self._http.post(
                f"{settings.BACKEND_URL}/api/v1/devices/{device_id}/heartbeat",
                headers=headers,
            )
            resp.raise_for_status()
            log.debug("Heartbeat ok: device=%s", device_id)
        except Exception as exc:
            log.warning("Heartbeat failed for device=%s: %s", device_id, exc)

    # ── Branch resolution ─────────────────────────────────────────────────────

    def _resolve_branch_id(self) -> Optional[str]:
        """
        BRANCH_ID env var wins; otherwise use the service account's own branch
        (camera events require a branch — single-branch installs need no config).
        """
        if self._branch_id:
            return self._branch_id
        try:
            headers = {"Authorization": f"Bearer {self._get_service_token()}"}
            resp = self._http.get(
                f"{settings.BACKEND_URL}/api/v1/auth/me", headers=headers
            )
            resp.raise_for_status()
            self._branch_id = resp.json()["data"]["branch_id"]
            log.info("Resolved branch_id from service account: %s", self._branch_id)
        except Exception as exc:
            log.error("Could not resolve branch_id from /auth/me: %s", exc)
        return self._branch_id

    # ── Service-account JWT ───────────────────────────────────────────────────

    def _get_service_token(self) -> str:
        """Obtain (and cache) a JWT by logging in with the service account."""
        with self._token_lock:
            # Refresh 60 s before expiry so in-flight requests don't fail
            if self._token and time.monotonic() < self._token_expiry - 60:
                return self._token

            if not (settings.SERVICE_ACCOUNT_EMAIL and settings.SERVICE_ACCOUNT_PASSWORD):
                raise RuntimeError(
                    "SERVICE_ACCOUNT_EMAIL / SERVICE_ACCOUNT_PASSWORD not configured — "
                    "cannot authenticate with backend"
                )

            resp = self._http.post(
                f"{settings.BACKEND_URL}/api/v1/auth/login",
                json={
                    "email": settings.SERVICE_ACCOUNT_EMAIL,
                    "password": settings.SERVICE_ACCOUNT_PASSWORD,
                },
            )
            resp.raise_for_status()
            token = resp.json()["data"]["access_token"]
            self._token = token
            self._token_expiry = time.monotonic() + 14 * 60   # 15-min token, refresh 1 min early
            log.info("Service account JWT acquired (expires in ~14 min)")
            return token
