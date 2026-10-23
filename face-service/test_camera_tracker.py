"""
Standalone test: camera + tracker integration.

Uses OpenCV's built-in Haar cascade face detector (no InsightFace needed)
to generate bounding boxes, feeds them to BYTETracker, and logs track IDs.

Usage
-----
  python test_camera_tracker.py                # webcam, show window
  python test_camera_tracker.py --source 0     # webcam explicit
  python test_camera_tracker.py --source path/to/video.mp4
  python test_camera_tracker.py --no-display   # headless (stdout only)
  python test_camera_tracker.py --max-frames 100
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import cv2
import numpy as np

# ── Add face-service/src to path so we can import camera + tracker ────────────
sys.path.insert(0, str(Path(__file__).parent))
from src.camera import CameraType, RTSPCamera
from src.tracker import BYTETracker

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("test")


# ── Face detector (Haar cascade — bundled with OpenCV, no extra install) ──────

def load_face_detector() -> cv2.CascadeClassifier:
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    det = cv2.CascadeClassifier(cascade_path)
    if det.empty():
        raise RuntimeError(f"Could not load Haar cascade from: {cascade_path}")
    log.info("Loaded face detector: %s", cascade_path)
    return det


def detect_faces(
    detector: cv2.CascadeClassifier,
    frame: np.ndarray,
    scale_factor: float = 1.1,
    min_neighbors: int = 4,
    min_size: tuple[int, int] = (40, 40),
) -> np.ndarray:
    """
    Returns (N, 5) array [x1, y1, x2, y2, score].
    Haar cascade doesn't output confidence, so score is fixed at 1.0.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)   # improve contrast for low-light faces

    faces = detector.detectMultiScale(
        gray,
        scaleFactor=scale_factor,
        minNeighbors=min_neighbors,
        minSize=min_size,
        flags=cv2.CASCADE_SCALE_IMAGE,
    )
    if len(faces) == 0:
        return np.empty((0, 5), dtype=float)

    # Convert (x, y, w, h) → (x1, y1, x2, y2)
    x1 = faces[:, 0].astype(float)
    y1 = faces[:, 1].astype(float)
    x2 = (faces[:, 0] + faces[:, 2]).astype(float)
    y2 = (faces[:, 1] + faces[:, 3]).astype(float)
    scores = np.ones(len(faces), dtype=float)
    return np.stack([x1, y1, x2, y2, scores], axis=1)


# ── Visualisation ─────────────────────────────────────────────────────────────

# Distinct colours for track IDs (cycle through them)
_PALETTE = [
    (0, 255, 0),    (255, 128, 0),  (0, 128, 255),  (255, 0, 255),
    (0, 255, 255),  (255, 255, 0),  (128, 0, 255),  (0, 128, 128),
]


def draw_tracks(frame: np.ndarray, active_tracks: list) -> np.ndarray:
    vis = frame.copy()
    for t in active_tracks:
        x1, y1, x2, y2 = [int(v) for v in t.tlbr]
        colour = _PALETTE[t.track_id % len(_PALETTE)]
        cv2.rectangle(vis, (x1, y1), (x2, y2), colour, 2)

        label = f"ID:{t.track_id}"
        if t.needs_recognition:
            label += " [NEW]"

        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 1)
        cv2.rectangle(vis, (x1, y1 - th - 8), (x1 + tw + 4, y1), colour, -1)
        cv2.putText(
            vis, label, (x1 + 2, y1 - 4),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1,
        )
    return vis


# ── Main loop ─────────────────────────────────────────────────────────────────

def run(source: str | int, show_display: bool, max_frames: int) -> None:
    detector = load_face_detector()
    tracker = BYTETracker(
        track_thresh=0.5,
        low_thresh=0.1,
        new_track_thresh=0.5,
        track_buffer=30,
        match_thresh=0.4,   # lower threshold for Haar (no score confidence)
    )

    camera = RTSPCamera(
        source=source,
        camera_type=CameraType.ENTRY,
        target_fps=10,     # allow higher rate for testing so Haar can keep up
        frame_skip=2,      # process every 2nd grabbed frame
        reconnect_interval_s=5.0,
    )

    log.info("Starting camera+tracker test  source=%s  max_frames=%s", source, max_frames)
    log.info("Press Q (in video window) or Ctrl+C to stop.\n")

    t0 = time.monotonic()
    frame_count = 0
    total_detections = 0
    total_track_events = 0
    unique_track_ids: set[int] = set()

    try:
        for fr in camera.frames():
            frame_count += 1
            if max_frames and frame_count > max_frames:
                log.info("Reached max_frames=%d — stopping", max_frames)
                break

            # ── Detect faces ──────────────────────────────────────────────────
            detections = detect_faces(detector, fr.frame)
            total_detections += len(detections)

            # ── Update tracker ────────────────────────────────────────────────
            active = tracker.update(detections)
            total_track_events += len(active)

            for t in active:
                unique_track_ids.add(t.track_id)

            # ── Log to stdout ─────────────────────────────────────────────────
            ids = [t.track_id for t in active]
            new_ids = [t.track_id for t in active if t.needs_recognition]
            print(
                f"frame={frame_count:4d}  "
                f"dets={len(detections)}  "
                f"tracks={len(active)}  "
                f"ids={ids}  "
                f"new_recognitions={new_ids}",
                flush=True,
            )

            # Mark recognised (simulate InsightFace completing)
            for t in active:
                if t.needs_recognition:
                    t.needs_recognition = False   # cleared after "recognition"

            # ── Display ───────────────────────────────────────────────────────
            if show_display:
                vis = draw_tracks(fr.frame, active)
                elapsed = time.monotonic() - t0
                fps_str = f"{frame_count / elapsed:.1f} fps" if elapsed > 0 else ""
                cv2.putText(
                    vis,
                    f"Frame {frame_count}  {fps_str}  Tracks: {len(active)}",
                    (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1,
                )
                cv2.imshow("Camera + Tracker test (Q to quit)", vis)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or key == 27:  # Q or Esc
                    log.info("User requested stop")
                    break

    except KeyboardInterrupt:
        log.info("Interrupted by user (Ctrl-C)")
    finally:
        camera.close()
        if show_display:
            cv2.destroyAllWindows()

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = time.monotonic() - t0
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"  Frames processed   : {frame_count}")
    print(f"  Elapsed time       : {elapsed:.1f} s")
    print(f"  Avg decoded FPS    : {frame_count / elapsed:.1f}" if elapsed else "  Avg decoded FPS    : N/A")
    print(f"  Total detections   : {total_detections}")
    print(f"  Unique track IDs   : {len(unique_track_ids)}  {sorted(unique_track_ids)}")
    print(f"  BYTETracker.frame_id: {tracker.frame_id}")
    print("=" * 60)

    if len(unique_track_ids) > 0:
        print("\nPASS — track IDs are being assigned and logged to stdout.")
    else:
        print("\nWARN — no faces detected. Check lighting or try a video file.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Camera + BYTETracker integration test")
    parser.add_argument(
        "--source", default="0",
        help="Video source: webcam index (0, 1, …), file path, or RTSP URL",
    )
    parser.add_argument(
        "--no-display", action="store_true",
        help="Run headless (no cv2.imshow window)",
    )
    parser.add_argument(
        "--max-frames", type=int, default=0,
        help="Stop after N frames (0 = unlimited)",
    )
    args = parser.parse_args()

    # Determine source: integer webcam or string path/URL
    source: str | int = args.source
    if source.isdigit():
        source = int(source)

    run(
        source=source,
        show_display=not args.no_display,
        max_frames=args.max_frames,
    )


if __name__ == "__main__":
    main()
