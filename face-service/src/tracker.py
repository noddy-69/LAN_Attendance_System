"""
ByteTrack-style multi-object tracker for face-recognition pipeline.

Design
------
* Each physical person that appears in frame receives a persistent track_id.
* Track IDs are monotonically increasing integers within a service session.
* A track stays alive for `track_buffer` frames (≈ 6 s at 5 FPS) after its
  last detection.  After that it is removed, so a re-appearing person gets
  a new track_id.
* Two-stage association (ByteTrack innovation):
    Stage 1 — high-confidence detections  matched to ALL tracks (active + lost).
    Stage 2 — low-confidence detections   matched to remaining active tracks only.
  This prevents real faces from being lost when temporarily obscured.
* InsightFace deduplication — `needs_recognition` is True only on the first
  frame of each new/re-activated track appearance.  The engine clears it after
  running recognition so recognition happens exactly once per appearance.

Kalman Filter
-------------
State  : [cx, cy, s, r, dcx, dcy, ds]  — 7-dim
         cx, cy = bounding-box centre
         s      = area (w * h)
         r      = aspect ratio (w / h)
         d*     = first-order velocities (constant-velocity model)
Observation : [cx, cy, s, r]  — 4-dim
No external package needed — implemented directly with numpy.

Dependencies
------------
  numpy — state vectors and matrix arithmetic
  scipy.optimize.linear_sum_assignment — Hungarian algorithm
"""

from __future__ import annotations

import logging
from enum import IntEnum
from typing import Optional

import numpy as np
from scipy.optimize import linear_sum_assignment

log = logging.getLogger(__name__)

# Module-level monotonic ID counter — unique IDs across all BYTETracker instances
# Lock required because AttendanceEngine runs one thread per camera.
import threading as _threading
_NEXT_ID: int = 0
_ID_LOCK = _threading.Lock()


def _alloc_id() -> int:
    global _NEXT_ID
    with _ID_LOCK:
        _NEXT_ID += 1
        return _NEXT_ID


# ── Track states ──────────────────────────────────────────────────────────────

class TrackState(IntEnum):
    TRACKED = 1   # currently matched in this or a recent frame
    LOST    = 2   # not matched for 1..track_buffer frames
    REMOVED = 3   # exceeded track_buffer — marked for GC


# ── Kalman Filter ─────────────────────────────────────────────────────────────

class KalmanFilter:
    """
    Constant-velocity Kalman filter for 2-D bounding-box tracking.

    State  x: [cx, cy, s, r, dcx, dcy, ds]   (7 × 1)
    Obs    z: [cx, cy, s, r]                  (4 × 1)

    F  — state transition (constant velocity)
    H  — observation matrix
    Q  — process noise   (tuned for face tracking; tighter than person tracking)
    R  — measurement noise
    """

    _ndim = 4   # measurement dimension

    def __init__(self) -> None:
        n = self._ndim   # 4
        d = 2 * n        # 8? No — state is 7 for position+velocity; use 4+3

        # 7-dim state: positions (4) + velocities (3: dcx, dcy, ds; r is constant)
        self.dim_x = 7
        self.dim_z = n   # 4

        # Transition matrix — constant velocity for cx, cy, s; r is constant
        F = np.eye(self.dim_x, dtype=float)
        # position += velocity
        F[0, 4] = 1.0   # cx  += dcx
        F[1, 5] = 1.0   # cy  += dcy
        F[2, 6] = 1.0   # s   += ds
        # r (index 3) has no velocity column
        self.F = F

        # Observation matrix: we observe [cx, cy, s, r]
        H = np.zeros((self.dim_z, self.dim_x), dtype=float)
        H[0, 0] = H[1, 1] = H[2, 2] = H[3, 3] = 1.0
        self.H = H

    # Initial process-noise std relative to the bounding-box size (scale h)
    _pos_std_weight = 1.0 / 20   # position noise
    _vel_std_weight = 1.0 / 160  # velocity noise

    def _process_noise_cov(self, h: float) -> np.ndarray:
        """Build Q from current box height h."""
        pw = self._pos_std_weight * h
        vw = self._vel_std_weight * h
        std = [pw, pw, 1e-2, pw, vw, vw, 1e-5]  # r is near-constant → very small noise
        return np.diag(np.square(std))

    def _meas_noise_cov(self, h: float) -> np.ndarray:
        """Build R from current box height h."""
        mw = self._pos_std_weight * h
        std = [mw, mw, 1e-1, mw]
        return np.diag(np.square(std))

    def initiate(self, measurement: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        measurement: [cx, cy, s, r]
        Returns: (mean, covariance)
        """
        mean_pos = measurement.copy()
        mean_vel = np.zeros(3, dtype=float)
        mean = np.r_[mean_pos, mean_vel]   # 7-dim

        h = np.sqrt(max(measurement[2] / max(measurement[3], 1e-7), 1e-7))
        std = [
            2 * 10 * self._pos_std_weight * h,   # cx
            2 * 10 * self._pos_std_weight * h,   # cy
            1e-2,                                 # s (area) — high initial uncertainty
            2 * 10 * self._pos_std_weight * h,   # r
            10 * self._vel_std_weight * h,        # dcx
            10 * self._vel_std_weight * h,        # dcy
            1e-5,                                 # ds
        ]
        cov = np.diag(np.square(std))
        return mean, cov

    def predict(
        self, mean: np.ndarray, cov: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        h = np.sqrt(max(mean[2] / max(mean[3], 1e-7), 1e-7))
        Q = self._process_noise_cov(h)
        mean = self.F @ mean
        cov = self.F @ cov @ self.F.T + Q
        return mean, cov

    def update(
        self,
        mean: np.ndarray,
        cov: np.ndarray,
        measurement: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        h = np.sqrt(max(mean[2] / max(mean[3], 1e-7), 1e-7))
        R = self._meas_noise_cov(h)

        projected_mean = self.H @ mean
        projected_cov = self.H @ cov @ self.H.T + R

        K = cov @ self.H.T @ np.linalg.inv(projected_cov)
        new_mean = mean + K @ (measurement - projected_mean)
        new_cov = (np.eye(self.dim_x) - K @ self.H) @ cov
        return new_mean, new_cov


# Shared KF instance — all tracks share the same parameter matrices
_KF = KalmanFilter()


# ── Single track ──────────────────────────────────────────────────────────────

class STrack:
    """
    One tracked object with a persistent ID, Kalman-filtered position,
    and an InsightFace recognition flag.

    Attributes
    ----------
    track_id        : unique int for this appearance
    state           : TrackState enum
    needs_recognition : True on first frame of each new/re-activated appearance.
                        The engine sets this to False after running InsightFace.
    frame_id        : frame counter when this track was last updated
    score           : detection confidence of last matched detection
    """

    def __init__(self, tlbr: np.ndarray, score: float) -> None:
        # Raw detection bbox before KF is initialised
        self._det_tlbr = np.array(tlbr, dtype=float)
        self.score = float(score)

        # Kalman state (populated on activate())
        self._mean: Optional[np.ndarray] = None
        self._cov: Optional[np.ndarray] = None

        # Identity / lifecycle
        self.track_id: int = 0
        self.state: TrackState = TrackState.LOST   # not active until activate()
        self.is_activated: bool = False
        self.frame_id: int = 0
        self.start_frame: int = 0
        self.tracklet_len: int = 0

        # Recognition deduplication flag
        self.needs_recognition: bool = False

    # ── State transitions ─────────────────────────────────────────────────────

    def activate(self, frame_id: int) -> None:
        self.track_id = _alloc_id()
        self._mean, self._cov = _KF.initiate(self._to_xysr())
        self.state = TrackState.TRACKED
        self.is_activated = True
        self.frame_id = frame_id
        self.start_frame = frame_id
        self.tracklet_len = 0
        self.needs_recognition = True   # run InsightFace on next engine cycle
        log.debug("Track ACTIVATED  id=%d  frame=%d  score=%.2f  box=%s",
                  self.track_id, frame_id, self.score, self._det_tlbr.astype(int))

    def re_activate(self, tlbr: np.ndarray, score: float, frame_id: int) -> None:
        """Reuse this track_id — person came back within the buffer window."""
        self._det_tlbr = np.array(tlbr, dtype=float)
        self.score = float(score)
        self._mean, self._cov = _KF.update(self._mean, self._cov, self._to_xysr())
        self.state = TrackState.TRACKED
        self.is_activated = True
        self.tracklet_len = 0
        self.frame_id = frame_id
        self.needs_recognition = True   # re-appear → re-recognise
        log.debug("Track REACTIVATED  id=%d  frame=%d", self.track_id, frame_id)

    def update(self, tlbr: np.ndarray, score: float, frame_id: int) -> None:
        """Normal per-frame update — track is continuously matched."""
        self._det_tlbr = np.array(tlbr, dtype=float)
        self.score = float(score)
        self._mean, self._cov = _KF.update(self._mean, self._cov, self._to_xysr())
        self.state = TrackState.TRACKED
        self.tracklet_len += 1
        self.frame_id = frame_id

    def predict(self) -> None:
        """Advance the KF one step (called at the start of each frame)."""
        if self._mean is None:
            return
        # Zero scale velocity when lost — box size should stay constant
        mean = self._mean.copy()
        if self.state != TrackState.TRACKED:
            mean[6] = 0.0
        self._mean, self._cov = _KF.predict(mean, self._cov)

    def mark_lost(self) -> None:
        self.state = TrackState.LOST

    def mark_removed(self) -> None:
        self.state = TrackState.REMOVED

    # ── Bounding box accessors ────────────────────────────────────────────────

    @property
    def tlbr(self) -> np.ndarray:
        """Current [x1, y1, x2, y2] from KF state (or raw detection if not yet activated)."""
        if self._mean is None:
            return self._det_tlbr.copy()
        cx, cy, s, r = self._mean[:4]
        w = float(np.sqrt(max(s * r, 0.0)))
        h = float(np.sqrt(max(s / max(r, 1e-7), 0.0)))
        return np.array([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], dtype=float)

    @property
    def tlwh(self) -> np.ndarray:
        """[x1, y1, width, height]"""
        b = self.tlbr
        return np.array([b[0], b[1], b[2] - b[0], b[3] - b[1]], dtype=float)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _to_xysr(self) -> np.ndarray:
        """Convert _det_tlbr → [cx, cy, s, r] observation vector."""
        x1, y1, x2, y2 = self._det_tlbr
        w = max(x2 - x1, 1e-7)
        h = max(y2 - y1, 1e-7)
        return np.array([
            (x1 + x2) / 2,   # cx
            (y1 + y2) / 2,   # cy
            w * h,            # s = area
            w / h,            # r = aspect ratio
        ], dtype=float)

    def __repr__(self) -> str:
        return (
            f"STrack(id={self.track_id}, state={self.state.name}, "
            f"frame={self.frame_id}, len={self.tracklet_len})"
        )


# ── IoU helpers ───────────────────────────────────────────────────────────────

def _bbox_ious(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """
    Pairwise IoU between two sets of boxes.
    a: (N, 4)  [x1, y1, x2, y2]
    b: (M, 4)  [x1, y1, x2, y2]
    Returns: (N, M) float array
    """
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])   # (N,)
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])   # (M,)

    ix1 = np.maximum(a[:, None, 0], b[None, :, 0])
    iy1 = np.maximum(a[:, None, 1], b[None, :, 1])
    ix2 = np.minimum(a[:, None, 2], b[None, :, 2])
    iy2 = np.minimum(a[:, None, 3], b[None, :, 3])

    inter = np.maximum(0.0, ix2 - ix1) * np.maximum(0.0, iy2 - iy1)
    union = area_a[:, None] + area_b[None, :] - inter
    return inter / np.maximum(union, 1e-7)


def _iou_cost(tracks: list[STrack], dets: np.ndarray) -> np.ndarray:
    """
    Cost matrix = 1 − IoU.  Shape: (len(tracks), len(dets)).
    """
    if not tracks or len(dets) == 0:
        return np.empty((len(tracks), len(dets)), dtype=float)
    t_boxes = np.array([t.tlbr for t in tracks], dtype=float)
    d_boxes = dets[:, :4].astype(float)
    return 1.0 - _bbox_ious(t_boxes, d_boxes)


def _associate(
    tracks: list[STrack],
    dets: np.ndarray,
    iou_thresh: float,
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """
    Hungarian assignment with IoU gating.

    Parameters
    ----------
    tracks     : candidate tracks (list of STrack)
    dets       : (N, 5) detections [x1, y1, x2, y2, score]
    iou_thresh : minimum IoU required to accept a match

    Returns
    -------
    matched         : list of (track_idx, det_idx) pairs
    unmatched_tracks : list of unmatched track indices
    unmatched_dets   : list of unmatched detection indices
    """
    if not tracks or len(dets) == 0:
        return [], list(range(len(tracks))), list(range(len(dets)))

    cost = _iou_cost(tracks, dets)
    row_ind, col_ind = linear_sum_assignment(cost)

    matched: list[tuple[int, int]] = []
    matched_t: set[int] = set()
    matched_d: set[int] = set()

    for ri, ci in zip(row_ind, col_ind):
        if cost[ri, ci] <= 1.0 - iou_thresh:
            matched.append((ri, ci))
            matched_t.add(ri)
            matched_d.add(ci)

    unmatched_tracks = [i for i in range(len(tracks)) if i not in matched_t]
    unmatched_dets   = [i for i in range(len(dets))   if i not in matched_d]
    return matched, unmatched_tracks, unmatched_dets


def _normalise_dets(raw: np.ndarray) -> np.ndarray:
    """Ensure detections are (N, 5) float [x1, y1, x2, y2, score]."""
    if raw.ndim != 2 or raw.shape[0] == 0:
        return np.empty((0, 5), dtype=float)
    if raw.shape[1] == 4:
        return np.c_[raw.astype(float), np.ones(len(raw))]
    return raw[:, :5].astype(float)


# ── BYTETracker ───────────────────────────────────────────────────────────────

class BYTETracker:
    """
    ByteTrack-style multi-object tracker.

    Parameters
    ----------
    track_thresh    : min detection score for first-stage matching (default 0.5)
    low_thresh      : min score for second-stage low-confidence matching (default 0.1)
    new_track_thresh: min score to create a new track (default 0.6)
    track_buffer    : frames to keep a lost track before removal (default 30)
    match_thresh    : IoU threshold for accepting a track ↔ det match (default 0.8)

    Usage
    -----
        tracker = BYTETracker()
        for frame in camera.frames():
            detections = detector.detect(frame)   # (N, 5) [x1,y1,x2,y2,score]
            active_tracks = tracker.update(detections)
            for t in active_tracks:
                print(t.track_id, t.tlbr, t.needs_recognition)
    """

    def __init__(
        self,
        track_thresh: float = 0.5,
        low_thresh: float = 0.1,
        new_track_thresh: float = 0.6,
        track_buffer: int = 30,
        match_thresh: float = 0.8,
    ) -> None:
        self.track_thresh = track_thresh
        self.low_thresh = low_thresh
        self.new_track_thresh = new_track_thresh
        self.max_time_lost = track_buffer
        self.match_thresh = match_thresh

        self.tracked_stracks: list[STrack] = []   # state == TRACKED
        self.lost_stracks: list[STrack]    = []   # state == LOST
        self.frame_id: int = 0

    def update(self, detections: np.ndarray) -> list[STrack]:
        """
        Process one frame's worth of detections.

        Parameters
        ----------
        detections : (N, 5) float array [x1, y1, x2, y2, score]
                     or (N, 4) [x1, y1, x2, y2]  (scores default to 1.0)

        Returns
        -------
        List of currently active STrack objects (state == TRACKED).
        Each track carries `.track_id`, `.tlbr`, `.needs_recognition`.
        """
        self.frame_id += 1
        dets = _normalise_dets(
            detections if isinstance(detections, np.ndarray) else np.array(detections)
        )

        # Separate detections by confidence
        scores = dets[:, 4] if len(dets) else np.array([])
        high_mask = scores >= self.track_thresh
        low_mask  = (scores >= self.low_thresh) & ~high_mask

        high_dets = dets[high_mask]
        low_dets  = dets[low_mask]

        # ── Predict all existing tracks ───────────────────────────────────────
        pool = self.tracked_stracks + self.lost_stracks
        for t in pool:
            t.predict()

        newly_active: list[STrack] = []

        # ── Stage 1: high-conf dets  ↔  all tracks (active + lost) ──────────
        matched1, u_pool1, u_high1 = _associate(pool, high_dets, self.match_thresh)

        for ti, di in matched1:
            t = pool[ti]
            if t.state == TrackState.TRACKED:
                t.update(high_dets[di, :4], high_dets[di, 4], self.frame_id)
            else:   # LOST → re-activate (reuse same track_id)
                t.re_activate(high_dets[di, :4], high_dets[di, 4], self.frame_id)
            newly_active.append(t)

        # ── Stage 2: low-conf dets  ↔  unmatched *active* tracks only ────────
        unmatched_active = [
            pool[i] for i in u_pool1 if pool[i].state == TrackState.TRACKED
        ]
        matched2, u_active2, _ = _associate(unmatched_active, low_dets, 0.5)

        for ti, di in matched2:
            unmatched_active[ti].update(low_dets[di, :4], low_dets[di, 4], self.frame_id)
            newly_active.append(unmatched_active[ti])

        # Unmatched active tracks after both stages → mark lost
        matched2_t = {ti for ti, _ in matched2}
        for ti, t in enumerate(unmatched_active):
            if ti not in matched2_t:
                t.mark_lost()

        # ── Initialise new tracks from unmatched high-confidence dets ─────────
        for di in u_high1:
            det = high_dets[di]
            if det[4] >= self.new_track_thresh:
                new_t = STrack(det[:4], det[4])
                new_t.activate(self.frame_id)
                newly_active.append(new_t)

        # ── Rebuild bookkeeping lists ─────────────────────────────────────────
        active_ids = {t.track_id for t in newly_active if t.state == TrackState.TRACKED}

        # Lost: previous lost tracks still within the buffer + newly lost tracks
        new_lost: list[STrack] = []
        seen_ids: set[int] = set()
        for t in pool + newly_active:
            if (
                t.state == TrackState.LOST
                and t.track_id not in active_ids
                and t.track_id not in seen_ids
                and (self.frame_id - t.frame_id) <= self.max_time_lost
            ):
                new_lost.append(t)
                seen_ids.add(t.track_id)

        self.tracked_stracks = [t for t in newly_active if t.state == TrackState.TRACKED]
        self.lost_stracks = new_lost

        active = [t for t in self.tracked_stracks]
        if active:
            log.debug(
                "Frame %d  tracks=%d  new_lost=%d  ids=%s",
                self.frame_id,
                len(active),
                len(new_lost),
                [t.track_id for t in active],
            )
        return active

    def reset(self) -> None:
        """Clear all tracks (e.g. when switching camera streams)."""
        self.tracked_stracks.clear()
        self.lost_stracks.clear()
        self.frame_id = 0

    def active_count(self) -> int:
        return len(self.tracked_stracks)
