"""
Full pipeline integration test — camera + tracker + recognizer + (mock) backend.

Usage
-----
  # Webcam with a pre-enrolled face (uses synthetic embedding for the demo)
  python test_full_pipeline.py --source 0 --enroll-webcam --max-frames 200

  # Specific video file
  python test_full_pipeline.py --source test.mp4

  # Headless CI mode
  python test_full_pipeline.py --no-display --max-frames 100

Expected log output when a face is detected
-------------------------------------------
  MATCH  track_id=1  employee=demo-employee  camera=entry  sim=0.9743
  Proof frame saved: entry/demo-employee/20260604_090123_1.jpg (if MinIO configured)
  [MOCK EVENT] {employee_id: ..., event_type: ENTRY, confidence_score: 0.97, ...}
  [cooldown] employee=demo-employee camera=entry remaining=299s  (on 2nd detection)

Requirements (all already installed):
  opencv-python, numpy, scipy, insightface (buffalo_sc downloaded on first run)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import types
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# Patch mask_renderer before any insightface import
stub = types.ModuleType("insightface.app.mask_renderer")
sys.modules["insightface.app.mask_renderer"] = stub

import cv2
import numpy as np

# Add face-service/src to path
sys.path.insert(0, str(Path(__file__).parent))

# Force mock-backend mode for standalone testing
import os
os.environ.setdefault("MOCK_BACKEND", "true")
os.environ.setdefault("FACE_CONFIDENCE_THRESHOLD", "0.80")   # lower for demo
os.environ.setdefault("FACE_COOLDOWN_SECONDS", "15")         # 15s cooldown for demo
os.environ.setdefault("TRACK_THRESH", "0.3")
os.environ.setdefault("NEW_TRACK_THRESH", "0.3")
os.environ.setdefault("ENTRY_CAMERA_URL", "")  # engine won't auto-start cameras

from src.camera import CameraType, RTSPCamera
from src.config import settings
from src.engine import AttendanceEngine, _best_det_for_track
from src.recognizer import FaceDetection, FaceRecognizer
from src.tracker import BYTETracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("test_pipeline")


# ── Visual overlay ────────────────────────────────────────────────────────────

_PALETTE = [(0,255,0),(255,128,0),(0,128,255),(255,0,255),(0,255,255),(255,255,0)]

def _draw(frame, tracks, face_dets, employee_map):
    vis = frame.copy()
    # Draw raw detections (thin grey)
    for det in face_dets:
        x1,y1,x2,y2 = det.bbox.astype(int)
        cv2.rectangle(vis,(x1,y1),(x2,y2),(128,128,128),1)

    # Draw tracks (thick coloured)
    for t in tracks:
        x1,y1,x2,y2 = t.tlbr.astype(int)
        col = _PALETTE[t.track_id % len(_PALETTE)]
        cv2.rectangle(vis,(x1,y1),(x2,y2),col,2)
        emp = employee_map.get(t.track_id, "?")
        label = f"ID:{t.track_id} {emp}"
        cv2.putText(vis, label, (x1, y1-6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, col, 1)
    return vis


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(source, show_display, max_frames, enroll_webcam):
    log.info("Initialising FaceRecognizer (buffalo_sc)...")
    rec = FaceRecognizer()
    rec._load_model()
    log.info("Model loaded.")

    # ── Enrol a demo employee from webcam ─────────────────────────────────────
    if enroll_webcam:
        log.info("Capturing face for demo enrollment (hold still)...")
        cap = cv2.VideoCapture(0)
        enrolled = False
        for _ in range(60):
            ret, frame = cap.read()
            if not ret:
                break
            dets = rec.detect_and_embed(frame)
            if dets:
                best = dets[0]
                rec._known = {"demo-employee": [best.embedding]}
                rec._last_refresh = time.monotonic()
                log.info(
                    "Enrolled demo-employee  score=%.3f  emb_norm=%.4f",
                    best.score, float(np.linalg.norm(best.embedding)),
                )
                enrolled = True
                break
        cap.release()
        if not enrolled:
            log.warning("No face detected for enrollment — using synthetic embedding")
            fake = np.random.randn(512).astype(np.float32)
            rec._known = {"demo-employee": [fake / np.linalg.norm(fake)]}
    else:
        # Synthetic demo embedding (will match any high-quality frontal face
        # with low probability, but demonstrates the pipeline flow)
        log.info("Using synthetic demo embedding (pass --enroll-webcam to use your face)")
        fake = np.random.randn(512).astype(np.float32)
        rec._known = {"demo-employee": [fake / np.linalg.norm(fake)]}

    engine = AttendanceEngine(rec)
    tracker = BYTETracker(
        track_thresh=settings.TRACK_THRESH,
        low_thresh=settings.LOW_THRESH,
        new_track_thresh=settings.NEW_TRACK_THRESH,
        track_buffer=settings.TRACK_BUFFER,
        match_thresh=settings.MATCH_THRESH,
    )

    camera = RTSPCamera(
        source=source,
        camera_type=CameraType.ENTRY,
        target_fps=10,
        frame_skip=2,
        reconnect_interval_s=5.0,
    )

    employee_map: dict[int, str] = {}   # track_id -> employee display name
    frame_count = 0
    t0 = time.monotonic()

    log.info("Pipeline running  source=%s  max_frames=%s  (Q to quit)", source, max_frames)
    log.info("Cooldown = %ds, confidence threshold = %.2f", settings.FACE_COOLDOWN_SECONDS, settings.FACE_CONFIDENCE_THRESHOLD)
    print()

    try:
        for fr in camera.frames():
            frame_count += 1
            if max_frames and frame_count > max_frames:
                break

            # ── Detect + embed ────────────────────────────────────────────────
            face_dets = rec.detect_and_embed(fr.frame)

            det_arr = (
                np.array([[*d.bbox, d.score] for d in face_dets], dtype=float)
                if face_dets else np.empty((0, 5), dtype=float)
            )

            # ── Track ─────────────────────────────────────────────────────────
            active = tracker.update(det_arr)

            # ── Identify new tracks ───────────────────────────────────────────
            for t in active:
                if not t.needs_recognition:
                    continue

                t.needs_recognition = False
                best_det = _best_det_for_track(t.tlbr, face_dets)
                if best_det is None:
                    continue

                result = rec.identify_face(best_det.embedding)
                if result is None:
                    log.info(
                        "Track %d: unknown face (best_sim < %.2f)",
                        t.track_id, settings.FACE_CONFIDENCE_THRESHOLD,
                    )
                    employee_map[t.track_id] = "unknown"
                    continue

                emp_id, sim = result
                employee_map[t.track_id] = emp_id

                cooldown_key = f"{emp_id}:{fr.camera_type.value}"
                if engine._is_cooling_down(cooldown_key):
                    remaining = settings.FACE_COOLDOWN_SECONDS - (
                        time.monotonic() - engine._cooldown.get(cooldown_key, 0)
                    )
                    log.info(
                        "[COOLDOWN] employee=%s camera=%s remaining=%.0fs",
                        emp_id, fr.camera_type.value, remaining,
                    )
                    continue

                engine._cooldown[cooldown_key] = time.monotonic()

                log.info(
                    "MATCH  track_id=%d  employee=%s  camera=%s  sim=%.4f",
                    t.track_id, emp_id, fr.camera_type.value, sim,
                )
                engine._fire_event(emp_id, fr, t, best_det, sim)

            # ── Display ───────────────────────────────────────────────────────
            if show_display:
                elapsed = time.monotonic() - t0
                vis = _draw(fr.frame, active, face_dets, employee_map)
                fps = frame_count / elapsed if elapsed else 0
                cv2.putText(
                    vis,
                    f"Frame {frame_count}  {fps:.1f}fps  tracks={len(active)}  known={rec.known_employee_count}",
                    (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200,200,200), 1,
                )
                cv2.imshow("Full Pipeline Test (Q=quit)", vis)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break

    except KeyboardInterrupt:
        log.info("Interrupted (Ctrl-C)")
    finally:
        camera.close()
        if show_display:
            cv2.destroyAllWindows()

    elapsed = time.monotonic() - t0
    print()
    print("=" * 60)
    print("PIPELINE TEST SUMMARY")
    print("=" * 60)
    print(f"  Frames           : {frame_count}")
    print(f"  Elapsed          : {elapsed:.1f} s")
    print(f"  Decoded FPS      : {frame_count/elapsed:.1f}" if elapsed else "  Decoded FPS      : N/A")
    print(f"  Known employees  : {rec.known_employee_count}")
    print(f"  Total events     : {sum(s.events_fired for s in engine._stats.values())}")
    print(f"  Active cooldowns : {sum(1 for k,ts in engine._cooldown.items() if engine._is_cooling_down(k))}")
    print("=" * 60)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Face recognition pipeline test")
    parser.add_argument("--source", default="0", help="Video source: webcam index, file path, or RTSP URL")
    parser.add_argument("--no-display", action="store_true", help="Headless mode")
    parser.add_argument("--max-frames", type=int, default=300)
    parser.add_argument("--enroll-webcam", action="store_true", help="Capture your face from webcam for demo enrollment")
    args = parser.parse_args()

    src = int(args.source) if args.source.isdigit() else args.source
    run(src, not args.no_display, args.max_frames, args.enroll_webcam)


if __name__ == "__main__":
    main()
