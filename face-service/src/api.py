"""
Face-service FastAPI router.

Endpoints
---------
  GET  /health              — liveness probe: model loaded, cameras running
  GET  /status              — operational stats per camera
  POST /reload-embeddings   — immediately re-fetch known embeddings from backend
  POST /embed               — extract 512-dim embedding from uploaded image
                              (called by the backend during face enrollment)
"""

from __future__ import annotations

import logging
import os

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Request

from src.config import settings

log = logging.getLogger(__name__)

router = APIRouter()

# ── Selfie liveness tuning (env-overridable) ──────────────────────────────────
# Minimum frames in the burst that must contain a detectable face.
_SELFIE_MIN_FRAMES = int(os.environ.get("SELFIE_MIN_FACE_FRAMES", "3"))
# Required spread of the yaw-proxy across the burst to prove a real head turn.
# A rigid printed photo translated in front of the camera keeps this ~0 because
# the nose-to-eye geometry does not change; only a real rotating head moves it.
_SELFIE_MOVE_THRESHOLD = float(os.environ.get("SELFIE_MOVE_THRESHOLD", "0.12"))
_SELFIE_MAX_FRAMES = int(os.environ.get("SELFIE_MAX_FRAMES", "16"))

# ── Direction-matched challenge ───────────────────────────────────────────────
# When the client sends which way it asked the user to turn ("left"/"right"), we
# verify the head actually turned *that* way, not just that it moved. This defeats a
# generic replayed head-movement video: it only matches the randomly-chosen prompt
# by luck, and symmetric motions (circles / shaking) have no dominant side so they
# fail outright.
_SELFIE_REQUIRE_DIRECTION = os.environ.get("SELFIE_REQUIRE_DIRECTION", "true").strip().lower() in ("1", "true", "yes")
# Minimum dominant-side yaw excursion to count as a deliberate turn.
_SELFIE_DIR_THRESHOLD = float(os.environ.get("SELFIE_DIR_THRESHOLD", "0.12"))
# The prompted side's excursion must exceed the opposite side's by at least this
# factor, so a two-way sweep (circles / shakes) can't satisfy a one-sided prompt.
_SELFIE_DIR_DOMINANCE = float(os.environ.get("SELFIE_DIR_DOMINANCE", "1.5"))
# Sign mapping: with the un-mirrored selfie frame, turning to YOUR left moves the
# nose toward the image's right (positive yaw proxy). Flip to -1 if a given camera
# rig proves inverted, without a code change.
_SELFIE_YAW_SIGN = 1.0 if os.environ.get("SELFIE_YAW_SIGN", "1").strip() not in ("-1", "-1.0") else -1.0


# ── /health ───────────────────────────────────────────────────────────────────

@router.get("/health")
async def health(request: Request):
    """
    Liveness probe used by Docker healthcheck and Nginx upstream checks.
    Returns 200 when the model is loaded, 503 while still initialising.
    """
    engine = getattr(request.app.state, "engine", None)
    recognizer = getattr(request.app.state, "recognizer", None)

    model_ready = recognizer is not None and recognizer._fa is not None
    cameras_up = engine.is_running if engine else False
    embeddings = recognizer.known_employee_count if recognizer else 0

    status = "ok" if model_ready else "starting"
    return {
        "status": status,
        "service": "face-recognition",
        "model_ready": model_ready,
        "cameras_running": cameras_up,
        "known_employees": embeddings,
    }


# ── /status ───────────────────────────────────────────────────────────────────

@router.get("/status")
async def status(request: Request):
    """Detailed operational statistics for monitoring dashboards."""
    engine = getattr(request.app.state, "engine", None)
    recognizer = getattr(request.app.state, "recognizer", None)

    camera_stats = engine.get_stats() if engine else {}

    return {
        "camera_stats": camera_stats,
        "known_employees": recognizer.known_employee_count if recognizer else 0,
        "known_embeddings": recognizer.known_embedding_count if recognizer else 0,
    }


# ── /reload-embeddings ────────────────────────────────────────────────────────

@router.post("/reload-embeddings")
async def reload_embeddings(request: Request):
    """
    Immediately reload the known-face-embedding cache from the backend.
    Call this after enrolling or deleting a face embedding so the face service
    recognises the change without waiting for the 5-min refresh cycle.
    """
    recognizer = getattr(request.app.state, "recognizer", None)
    if recognizer is None:
        raise HTTPException(503, "Recognizer not initialised yet")

    recognizer.force_refresh()
    return {
        "status": "ok",
        "known_employees": recognizer.known_employee_count,
        "known_embeddings": recognizer.known_embedding_count,
        "confidence_threshold": recognizer._threshold,
    }


# ── /embed ────────────────────────────────────────────────────────────────────

@router.post("/embed")
async def embed(request: Request):
    """
    Extract a 512-dimensional face embedding from an uploaded image.
    Called by the backend's POST /api/v1/face/employees/{id}/enroll endpoint.
    Accepts multipart/form-data with a 'file' field.

    Returns:
        { "embedding": [512 floats], "model_version": "buffalo_sc" }

    Raises 422 if no face is detected or the image cannot be decoded.
    """
    recognizer = getattr(request.app.state, "recognizer", None)
    if recognizer is None or recognizer._fa is None:
        raise HTTPException(503, "Face recognition model not loaded yet")

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        try:
            form = await request.form()
            file_field = form.get("file")
            if file_field is None:
                raise HTTPException(422, "Missing 'file' field in multipart form")
            data = await file_field.read()
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, f"Failed to parse multipart form: {exc}") from exc
    else:
        data = await request.body()

    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(422, "Image too large — max 10 MB")
    if len(data) == 0:
        raise HTTPException(422, "Empty file")

    try:
        embedding, model_version = recognizer.extract_embedding_from_image(data)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except Exception as exc:
        log.error("Embedding extraction failed: %s", exc)
        raise HTTPException(500, "Internal error during face embedding extraction")

    return {"embedding": embedding, "model_version": model_version}


# ── /verify-selfie ──────────────────────────────────────────────────────────

def _get_antispoofer(app):
    """
    Anti-spoofer for the selfie path.

    Reuse the camera pipeline's AntiSpoofer when it is actually active; otherwise
    build a selfie-dedicated one that defaults ON (SELFIE_ANTISPOOF_ENABLED), so
    the selfie path uses a MiniFASNet model whenever one is present — even if the
    camera pipeline has anti-spoofing disabled. With no model it fails open and the
    active head-movement liveness still applies.
    """
    engine = getattr(app.state, "engine", None)
    cam = engine.antispoof if engine is not None and getattr(engine, "antispoof", None) else None
    if cam is not None and cam.active:
        return cam
    cached = getattr(app.state, "_selfie_antispoof", None)
    if cached is None:
        from src.antispoof import AntiSpoofer
        cached = AntiSpoofer(enabled=settings.SELFIE_ANTISPOOF_ENABLED)
        app.state._selfie_antispoof = cached
    return cached


def _yaw_proxy(kps) -> float | None:
    """
    Approximate head yaw from the 5 detection keypoints
    [left_eye, right_eye, nose, left_mouth, right_mouth].

    Returns the nose's horizontal offset from the eye midpoint, normalised by the
    inter-eye distance. ~0 when frontal; grows as the head rotates. Because it is
    a *relative* geometry, simply translating a rigid printed photo in front of
    the camera does not change it — only a genuinely rotating head does.
    """
    if kps is None or len(kps) < 3:
        return None
    le, re_, nose = kps[0], kps[1], kps[2]
    inter = abs(float(re_[0]) - float(le[0]))
    if inter < 1e-3:
        return None
    eye_mid_x = (float(le[0]) + float(re_[0])) / 2.0
    return (float(nose[0]) - eye_mid_x) / inter


@router.post("/verify-selfie")
async def verify_selfie(request: Request):
    """
    Verify a self-service selfie check-in burst.

    Accepts multipart/form-data with one or more 'frames' image fields captured
    while the employee performed a head-movement challenge. Runs, per frame:
      • InsightFace detection + 512-d embedding
      • passive anti-spoofing (MiniFASNet) on the face crop
      • a yaw proxy from the keypoints (active-liveness motion signal)

    Returns the embedding from the most frontal real frame plus a liveness
    verdict. The BACKEND owns the final allow/deny + the 1:1 identity match;
    this endpoint only extracts and scores.
    """
    recognizer = getattr(request.app.state, "recognizer", None)
    if recognizer is None or recognizer._fa is None:
        raise HTTPException(503, "Face recognition model not loaded yet")

    if "multipart/form-data" not in request.headers.get("content-type", ""):
        raise HTTPException(422, "Expected multipart/form-data with 'frames' fields")

    challenge_dir = ""
    try:
        form = await request.form()
        files = form.getlist("frames")
        frames_bytes: list[bytes] = []
        for f in files[:_SELFIE_MAX_FRAMES]:
            if hasattr(f, "read"):
                frames_bytes.append(await f.read())
        # Which way the client asked the user to turn ("left"/"right"), if any.
        raw_dir = form.get("challenge")
        if isinstance(raw_dir, str):
            challenge_dir = raw_dir.strip().lower()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"Failed to parse multipart form: {exc}") from exc

    if not frames_bytes:
        raise HTTPException(422, "No 'frames' provided")

    antispoof = _get_antispoofer(request.app)

    # Per-frame analysis
    candidates: list[dict] = []   # {embedding, yaw, is_real, det_score}
    yaws: list[float] = []
    for data in frames_bytes:
        if not data:
            continue
        arr = np.frombuffer(data, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            continue
        dets = recognizer.detect_and_embed(img)
        if not dets:
            continue
        best = dets[0]   # highest detection score
        yaw = _yaw_proxy(best.kps)
        is_real, real_score = antispoof.is_real(img, best.bbox)
        candidates.append({
            "embedding": best.embedding,
            "yaw": yaw,
            "is_real": bool(is_real),
            "real_score": float(real_score),
            "det_score": float(best.score),
        })
        if yaw is not None:
            yaws.append(yaw)

    frames_with_face = len(candidates)
    hi = max(yaws) if yaws else 0.0            # most positive yaw (nose to image-right)
    lo = min(yaws) if yaws else 0.0            # most negative yaw (nose to image-left)
    movement = (hi - lo) if len(yaws) >= 2 else 0.0
    antispoof_active = bool(antispoof.active)
    real_count = sum(1 for c in candidates if c["is_real"])
    real_fraction = (real_count / frames_with_face) if frames_with_face else 0.0

    # ── Direction match: verify the head turned the way the client prompted ──────
    # Dominant excursion = whichever extreme is larger in magnitude; its sign maps to
    # a human direction via _SELFIE_YAW_SIGN. A one-sided turn has a clearly dominant
    # side; a circle/shake has two comparable extremes and fails the dominance test.
    dom_signed = hi if abs(hi) >= abs(lo) else lo
    dom_mag = abs(dom_signed)
    opp_mag = min(abs(hi), abs(lo))
    detected_dir = "left" if (dom_signed * _SELFIE_YAW_SIGN) > 0 else "right"
    enforce_dir = _SELFIE_REQUIRE_DIRECTION and challenge_dir in ("left", "right")
    if enforce_dir:
        direction_passed = (
            detected_dir == challenge_dir
            and dom_mag >= _SELFIE_DIR_THRESHOLD
            and dom_mag >= _SELFIE_DIR_DOMINANCE * opp_mag
        )
    else:
        direction_passed = True

    # Liveness verdict — enough faces, real movement, and (if prompted) the right way.
    active_passed = (
        frames_with_face >= _SELFIE_MIN_FRAMES
        and movement >= _SELFIE_MOVE_THRESHOLD
        and direction_passed
    )
    # Passive fails open when anti-spoofing isn't active (mirrors camera pipeline).
    passive_passed = (real_fraction >= 0.5) if antispoof_active else True

    # Per-frame diagnostics so a site can see why a selfie was accepted/rejected and
    # tune FACE_ANTISPOOF_THRESHOLD. real_scores is the model's "real" probability per
    # frame (higher = more confidently a live face).
    log.info(
        "verify-selfie: frames=%d faces=%d antispoof_active=%s real_scores=%s "
        "real_fraction=%.2f movement=%.3f prompt=%s detected=%s dom=%.3f opp=%.3f "
        "dir_ok=%s -> passive=%s active=%s",
        len(frames_bytes), frames_with_face, antispoof_active,
        [round(c["real_score"], 3) for c in candidates],
        real_fraction, movement, challenge_dir or "-", detected_dir, dom_mag, opp_mag,
        direction_passed, passive_passed, active_passed,
    )

    # Pick the embedding from the most frontal REAL frame (smallest |yaw|),
    # tie-broken by detection score. Fall back to any frame if none are "real".
    pool = [c for c in candidates if c["is_real"]] or candidates
    chosen = None
    if pool:
        chosen = min(
            pool,
            key=lambda c: (
                abs(c["yaw"]) if c["yaw"] is not None else 9.9,
                -c["det_score"],
            ),
        )

    liveness = {
        "passive_passed": passive_passed,
        "active_passed": active_passed,
        "movement": round(movement, 4),
        "frames_total": len(frames_bytes),
        "frames_with_face": frames_with_face,
        "real_fraction": round(real_fraction, 3),
        "antispoof_active": antispoof_active,
        "challenge": challenge_dir or None,
        "detected_direction": detected_dir if yaws else None,
        "direction_passed": direction_passed,
    }

    from src.config import settings as _cfg
    if chosen is None:
        return {
            "ok": False,
            "reason": "No face detected in any frame",
            "embedding": None,
            "model_version": _cfg.MODEL_PACK,
            "liveness": liveness,
        }

    return {
        "ok": True,
        "embedding": chosen["embedding"].tolist(),
        "model_version": _cfg.MODEL_PACK,
        "liveness": liveness,
    }
