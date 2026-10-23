"""
Passive face anti-spoofing (liveness) for the recognition pipeline.

Defends against the trivial attack of holding a printed photo or a phone screen
showing an enrolled employee's face in front of the camera. Runs a CPU-only
ONNX MiniFASNet classifier on the detected face crop and rejects predicted
spoofs before an attendance event is fired.

Design
------
* Disabled by default (FACE_ANTISPOOF_ENABLED). When enabled, it loads every
  *.onnx under FACE_ANTISPOOF_MODEL_DIR and ensembles their softmax outputs —
  the Silent-Face / minivision project ships two complementary MiniFASNet
  models (scales 2.7 and 4.0) that are summed for the final decision.
* Filename convention carries the crop scale and input size, e.g.
  "2.7_80x80_MiniFASNetV2.onnx" → scale=2.7, input=80x80. Defaults: 2.7 / 80.
* FAIL-OPEN: if it is enabled but no model is present, or inference errors,
  the frame is treated as REAL (with a warning). A misconfiguration must never
  silently block every employee from marking attendance.

Model files are not bundled (they are third-party). Drop the ONNX files into
the model dir and flip FACE_ANTISPOOF_ENABLED=true. See WEBCAM_TESTING_GUIDE.md.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass

import cv2
import numpy as np

try:
    import onnxruntime as ort
except Exception:  # pragma: no cover - onnxruntime always present in the image
    ort = None  # type: ignore

from src.config import settings

log = logging.getLogger(__name__)

# Parses "2.7_80x80_MiniFASNetV2.onnx" → scale=2.7, h=80, w=80
_NAME_RE = re.compile(r"(?P<scale>[\d.]+)_(?P<h>\d+)x(?P<w>\d+)_")


@dataclass
class _Model:
    session: "ort.InferenceSession"
    input_name: str
    scale: float
    height: int
    width: int


def _new_box(src_w: int, src_h: int, box: tuple[int, int, int, int], scale: float):
    """minivision crop: expand the bbox by `scale` around its centre, clamped to the image."""
    x, y, bw, bh = box
    scale = min((src_h - 1) / bh, (src_w - 1) / bw, scale)
    new_w, new_h = bw * scale, bh * scale
    cx, cy = x + bw / 2.0, y + bh / 2.0
    lx, ly = cx - new_w / 2.0, cy - new_h / 2.0
    rx, ry = cx + new_w / 2.0, cy + new_h / 2.0
    if lx < 0:
        rx -= lx; lx = 0
    if ly < 0:
        ry -= ly; ly = 0
    if rx > src_w:
        lx -= (rx - src_w); rx = src_w
    if ry > src_h:
        ly -= (ry - src_h); ry = src_h
    return int(lx), int(ly), int(rx), int(ry)


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / np.sum(e)


class AntiSpoofer:
    """Ensemble MiniFASNet liveness check. Safe no-op when disabled or unconfigured."""

    def __init__(self, enabled: bool | None = None) -> None:
        self._models: list[_Model] = []
        # `enabled` override lets the selfie path turn liveness on independently of
        # the camera pipeline's FACE_ANTISPOOF_ENABLED. Defaults to the camera flag.
        self.enabled: bool = settings.FACE_ANTISPOOF_ENABLED if enabled is None else enabled
        self.threshold: float = settings.FACE_ANTISPOOF_THRESHOLD
        if self.enabled:
            self._load()

    def _load(self) -> None:
        model_dir = settings.FACE_ANTISPOOF_MODEL_DIR
        if ort is None:
            log.warning("onnxruntime unavailable — anti-spoofing disabled")
            self.enabled = False
            return
        if not os.path.isdir(model_dir):
            log.warning(
                "FACE_ANTISPOOF_ENABLED but model dir %s missing — failing open "
                "(all faces treated as live until models are added)", model_dir,
            )
            return
        for fn in sorted(os.listdir(model_dir)):
            if not fn.lower().endswith(".onnx"):
                continue
            path = os.path.join(model_dir, fn)
            m = _NAME_RE.search(fn)
            scale = float(m.group("scale")) if m else 2.7
            h = int(m.group("h")) if m else 80
            w = int(m.group("w")) if m else 80
            try:
                sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
                self._models.append(
                    _Model(sess, sess.get_inputs()[0].name, scale, h, w)
                )
                log.info("Anti-spoof model loaded: %s (scale=%.1f %dx%d)", fn, scale, h, w)
            except Exception as exc:
                log.error("Failed to load anti-spoof model %s: %s", fn, exc)
        if not self._models:
            log.warning("No anti-spoof models loaded — failing open")

    @property
    def active(self) -> bool:
        """True only when enabled AND at least one model is loaded."""
        return self.enabled and bool(self._models)

    def is_real(self, frame: np.ndarray, bbox: np.ndarray) -> tuple[bool, float]:
        """
        Return (is_real, score). score is the ensembled probability of "real".
        Fails open (True, 1.0) when not active or on any error.
        """
        if not self.active:
            return True, 1.0
        try:
            src_h, src_w = frame.shape[:2]
            x1, y1, x2, y2 = (int(v) for v in bbox[:4])
            box = (x1, y1, max(1, x2 - x1), max(1, y2 - y1))

            accum = np.zeros(3, dtype=np.float64)
            for model in self._models:
                lx, ly, rx, ry = _new_box(src_w, src_h, box, model.scale)
                crop = frame[ly:ry, lx:rx]
                if crop.size == 0:
                    continue
                crop = cv2.resize(crop, (model.width, model.height))
                blob = crop.astype(np.float32).transpose(2, 0, 1)[None, ...] / 255.0
                out = model.session.run(None, {model.input_name: blob})[0]
                accum += _softmax(np.asarray(out).reshape(-1)[:3])

            if accum.sum() == 0:
                return True, 1.0
            probs = accum / len(self._models)
            real_score = float(probs[1])  # class 1 = real in MiniFASNet
            # Lenient policy: treat the face as REAL unless the model is *confident*
            # it is a spoof. We reject only when the real-score drops below
            # self.threshold (i.e. combined spoof probability is high). The older
            # "argmax==1 AND real>=0.6" rule false-rejected genuine phone selfies; a
            # low threshold here still blocks an obvious printed-photo/screen replay
            # while letting real faces through. Tune via FACE_ANTISPOOF_THRESHOLD.
            is_real = real_score >= self.threshold
            return is_real, real_score
        except Exception as exc:
            log.error("Anti-spoof inference error (failing open): %s", exc)
            return True, 1.0
