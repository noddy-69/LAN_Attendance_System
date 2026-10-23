"""
RTSPCamera — managed video stream for the face-recognition pipeline.

Supported sources
-----------------
  CP Plus RTSP  rtsp://admin:{password}@{ip}:554/cam/realmonitor?channel=1&subtype=0
  File path     /data/test.mp4  or  test.mp4
  Webcam index  0  (integer or the string "0")

Design notes
------------
* Frames are grabbed at the hardware rate; only every `frame_skip`-th grabbed
  frame is decoded and returned.  This achieves ~5 decoded FPS on a 25 FPS
  stream without decoding every frame (saves CPU).
* If cv2.VideoCapture.read() fails, the camera reconnects automatically
  after `reconnect_interval_s` seconds — handles brief network blips common
  with cheap CP Plus IP cameras.
* Every returned frame is tagged with `camera_type` ("entry" or "exit") so
  the engine can route detections to the correct attendance event type.
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Generator, Optional

import cv2
import numpy as np

log = logging.getLogger(__name__)


class CameraType(str, Enum):
    ENTRY = "entry"
    EXIT  = "exit"


class FrameResult:
    """One decoded frame plus its routing metadata."""
    __slots__ = ("frame", "camera_type", "timestamp", "frame_index")

    def __init__(
        self,
        frame: np.ndarray,
        camera_type: CameraType,
        timestamp: float,
        frame_index: int,
    ) -> None:
        self.frame = frame
        self.camera_type = camera_type
        self.timestamp = timestamp      # time.monotonic() at grab
        self.frame_index = frame_index  # monotonically increasing decoded count


class RTSPCamera:
    """
    Managed camera wrapper for RTSP streams, video files, and webcams.

    Parameters
    ----------
    source:
        RTSP URL, file path, or webcam index (int or stringified int "0").
    camera_type:
        "entry" or "exit" — stamped on every FrameResult.
    target_fps:
        Target decoded frame rate (used for wall-clock throttle).
    frame_skip:
        Decode 1 of every `frame_skip` grabbed frames.
        E.g. frame_skip=5 on a 25 FPS stream → ~5 decoded FPS.
    reconnect_interval_s:
        Seconds between reconnect attempts when an RTSP stream drops.
        File sources and webcam indices do NOT reconnect (EOF = stop).
    """

    def __init__(
        self,
        source: str | int,
        camera_type: str | CameraType,
        target_fps: int = 5,
        frame_skip: int = 5,
        reconnect_interval_s: float = 30.0,
    ) -> None:
        self.source = source
        self.camera_type = CameraType(camera_type)
        self.target_fps = target_fps
        self.frame_skip = max(1, frame_skip)
        self.reconnect_interval_s = reconnect_interval_s

        self._cap: Optional[cv2.VideoCapture] = None
        self._grab_count: int = 0
        self._decoded_count: int = 0
        self._last_reconnect_at: float = 0.0
        self._last_frame_at: float = 0.0
        self._min_frame_gap: float = 1.0 / max(target_fps, 1)

    # ── Public API ────────────────────────────────────────────────────────────

    def open(self) -> bool:
        """Open (or reopen) the video source.  Returns True on success."""
        self._release()
        # Coerce "0", "1", ... to int so cv2.VideoCapture treats them as webcam
        src: str | int = (
            int(self.source)
            if isinstance(self.source, str) and self.source.isdigit()
            else self.source
        )
        log.info("Opening camera source=%s type=%s", src, self.camera_type.value)

        cap = cv2.VideoCapture(src)
        if not cap.isOpened():
            cap.release()
            log.warning("Failed to open camera source=%s", src)
            return False

        # Keep buffer minimal for RTSP — we always want the *latest* frame,
        # not a stale one that has been queued waiting to be read.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._cap = cap
        self._grab_count = 0
        self._decoded_count = 0
        self._last_reconnect_at = time.monotonic()

        native_fps = cap.get(cv2.CAP_PROP_FPS) or 0
        log.info(
            "Camera ready  native_fps=%.1f  frame_skip=%d  decoded_fps~=%.1f",
            native_fps,
            self.frame_skip,
            (native_fps / self.frame_skip) if native_fps else self.target_fps,
        )
        return True

    def read(self) -> tuple[bool, Optional[FrameResult]]:
        """
        Grab (and selectively decode) the next frame.

        Returns
        -------
        (True, FrameResult)   — decoded frame ready for processing
        (True, None)          — frame grabbed but skipped (not decode turn or FPS throttle)
        (False, None)         — EOF (files/webcams) or unrecoverable failure
        """
        if self._cap is None or not self._cap.isOpened():
            return self._maybe_reconnect()

        grabbed = self._cap.grab()
        if not grabbed:
            log.warning("Grab failed  source=%s", self.source)
            self._release()
            return self._maybe_reconnect()

        self._grab_count += 1

        # Skip undecoded frames
        if self._grab_count % self.frame_skip != 0:
            return True, None

        # Wall-clock FPS throttle: skip if we're ahead of the target interval
        now = time.monotonic()
        if now - self._last_frame_at < self._min_frame_gap:
            return True, None

        ret, frame = self._cap.retrieve()
        if not ret or frame is None:
            return True, None

        self._decoded_count += 1
        self._last_frame_at = now

        return True, FrameResult(
            frame=frame,
            camera_type=self.camera_type,
            timestamp=now,
            frame_index=self._decoded_count,
        )

    def frames(self) -> Generator[FrameResult, None, None]:
        """
        Generator that yields decoded FrameResult objects until the stream ends
        (EOF for files/webcams, or permanent RTSP failure after retries).

        Usage::

            cam = RTSPCamera("0", "entry")
            for fr in cam.frames():
                process(fr.frame, fr.camera_type)
        """
        if not self.open():
            if not self._is_rtsp():
                # Files / webcam indices: a failed initial open is terminal.
                log.error("Cannot open source=%s - aborting", self.source)
                return
            # RTSP: the stream may not exist yet (e.g. the in-app webcam hasn't started
            # publishing). Don't abort - fall into the loop so the reconnect logic keeps
            # retrying until the stream appears.
            log.info("RTSP source not available yet - retrying until it appears: %s", self.source)
            self._last_reconnect_at = time.monotonic() - self.reconnect_interval_s
        try:
            while True:
                ok, result = self.read()
                if not ok:
                    break
                if result is not None:
                    yield result
        finally:
            self.close()

    def close(self) -> None:
        """Release the VideoCapture and log final frame stats."""
        self._release()
        log.info(
            "Camera closed  source=%s  decoded=%d  grabbed=%d",
            self.source, self._decoded_count, self._grab_count,
        )

    @property
    def is_opened(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    @property
    def decoded_frame_count(self) -> int:
        return self._decoded_count

    # ── Context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "RTSPCamera":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"RTSPCamera(source={self.source!r}, type={self.camera_type.value}, "
            f"opened={self.is_opened}, decoded={self._decoded_count})"
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _is_rtsp(self) -> bool:
        return isinstance(self.source, str) and self.source.lower().startswith("rtsp")

    def _maybe_reconnect(self) -> tuple[bool, None]:
        """
        For RTSP streams: sleep briefly then retry after reconnect_interval_s.
        For files and webcams: return False (EOF / permanent stop).
        """
        if not self._is_rtsp():
            return False, None   # EOF for files / webcams — stop iteration

        now = time.monotonic()
        elapsed = now - self._last_reconnect_at
        if elapsed < self.reconnect_interval_s:
            time.sleep(0.1)
            return True, None

        log.info("Reconnecting to %s (%.0f s since last attempt)", self.source, elapsed)
        self._last_reconnect_at = now
        if self.open():
            log.info("Reconnected to %s", self.source)
        else:
            log.warning(
                "Reconnect failed for %s — will retry in %.0f s",
                self.source, self.reconnect_interval_s,
            )
        return True, None
