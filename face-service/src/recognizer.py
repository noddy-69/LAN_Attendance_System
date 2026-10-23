"""
FaceRecognizer — InsightFace CPU inference wrapper.

Model: buffalo_sc (det_500m.onnx detector + w600k_mbf.onnx ArcFace embedder)
  • det_500m  — lightweight RetinaFace detector (500 k params)
  • w600k_mbf — MobileNetFace trained on WebFace600K, outputs 512-dim embeddings
  • Both run on CPUExecutionProvider (no GPU required)
  • Models are downloaded automatically by InsightFace on first run and cached
    in ${INSIGHTFACE_HOME}/models/buffalo_sc/

Public interface
----------------
  recognizer = FaceRecognizer()
  recognizer.initialize()               # load model, fetch embeddings, init MinIO
  dets = recognizer.detect_and_embed(frame)     # list[FaceDetection]
  result = recognizer.identify_face(embedding)  # (employee_id, sim) | None
  recognizer.refresh_embeddings_if_needed()     # auto-refresh every 5 min
  path = recognizer.save_proof_frame(key, frame) # upload JPEG to MinIO

Known-embeddings cache
----------------------
  Fetched from: GET {BACKEND_URL}/api/v1/face/embeddings/all
  Auth: X-Service-Key header = settings.FACE_SERVICE_KEY
  Format: {"count": N, "embeddings": [{"employee_id":..., "embedding":[512 floats]},...]}
  Refreshed every EMBED_REFRESH_SECONDS (default 300 s).
"""

from __future__ import annotations

import io
import logging
import os
import sys
import time
import types
from dataclasses import dataclass, field
from typing import Optional

import cv2
import httpx
import numpy as np

# ── ImportFix: prevent mask_renderer from pulling in torch/albumentations ──────
# In production Docker (no torch installed) this is a no-op; the module will
# load normally.  On dev machines where torch is present but has numpy compat
# issues, this stub avoids the error without affecting recognition functionality.
if "insightface.app.mask_renderer" not in sys.modules:
    _stub = types.ModuleType("insightface.app.mask_renderer")
    sys.modules["insightface.app.mask_renderer"] = _stub

from insightface.app import FaceAnalysis  # noqa: E402

from src.config import settings

log = logging.getLogger(__name__)


# ── Data class for one detected face ─────────────────────────────────────────

@dataclass
class FaceDetection:
    bbox: np.ndarray          # [x1, y1, x2, y2]  float
    embedding: np.ndarray     # 512-dim, L2-normalised
    score: float              # detection confidence [0, 1]
    kps: Optional[np.ndarray] = field(default=None)  # 5 facial keypoints


# ── Recognizer ────────────────────────────────────────────────────────────────

class FaceRecognizer:
    """
    Wraps InsightFace buffalo_sc for detection + embedding extraction,
    known-embedding management, cosine identification, and MinIO proof upload.
    """

    def __init__(self) -> None:
        self._fa: Optional[FaceAnalysis] = None
        # {employee_id: [normalised_embedding, ...]}
        self._known: dict[str, list[np.ndarray]] = {}
        self._last_refresh: float = 0.0
        self._http = httpx.Client(timeout=15.0, follow_redirects=True)
        self._minio = None     # minio.Minio — initialised lazily
        # Confidence threshold — loaded from backend system_policies at each refresh
        self._threshold: float = settings.FACE_CONFIDENCE_THRESHOLD

    # ── Initialisation ────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Load model, fetch embeddings from backend, connect to MinIO."""
        self._load_model()
        self._load_known_embeddings()
        self._init_minio()

    def _load_model(self) -> None:
        det_size = (settings.DET_SIZE, settings.DET_SIZE)
        log.info("Loading InsightFace model pack=%s det_size=%s", settings.MODEL_PACK, det_size)
        # FaceAnalysis ignores the INSIGHTFACE_HOME env var unless root= is
        # passed explicitly — without it the model baked into the Docker image
        # is never found and gets re-downloaded on every container recreation.
        fa = FaceAnalysis(
            name=settings.MODEL_PACK,
            root=os.environ.get(
                "INSIGHTFACE_HOME", os.path.expanduser("~/.insightface")
            ),
            providers=["CPUExecutionProvider"],
        )
        fa.prepare(ctx_id=0, det_size=det_size)
        self._fa = fa
        log.info("InsightFace ready — pack=%s", settings.MODEL_PACK)

    def _init_minio(self) -> None:
        if not settings.MINIO_SECRET_KEY:
            log.warning("MINIO_SECRET_KEY not set — proof frames will not be saved")
            return
        try:
            from minio import Minio
            self._minio = Minio(
                settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE,
            )
            # Ensure bucket exists
            if not self._minio.bucket_exists(settings.MINIO_BUCKET):
                self._minio.make_bucket(settings.MINIO_BUCKET)
            log.info("MinIO connected — bucket=%s", settings.MINIO_BUCKET)
        except Exception as exc:
            log.error("MinIO init failed: %s — proof frames disabled", exc)
            self._minio = None

    # ── Known-embedding management ────────────────────────────────────────────

    def _load_known_embeddings(self) -> None:
        """Fetch all active face embeddings from the backend."""
        if not settings.BACKEND_URL:
            log.warning("BACKEND_URL not set — known-embedding cache is empty")
            return
        try:
            resp = self._http.get(
                f"{settings.BACKEND_URL}/api/v1/face/embeddings/all",
                headers={"X-Service-Key": settings.FACE_SERVICE_KEY},
                timeout=10.0,
            )
            if resp.status_code != 200:
                log.warning(
                    "Backend returned %d loading embeddings — keeping stale cache",
                    resp.status_code,
                )
                return

            payload = resp.json()
            new_known: dict[str, list[np.ndarray]] = {}
            for item in payload.get("embeddings", []):
                emp_id = item["employee_id"]
                raw = np.array(item["embedding"], dtype=np.float32)
                norm = np.linalg.norm(raw)
                if norm < 1e-9:
                    continue
                new_known.setdefault(emp_id, []).append(raw / norm)

            self._known = new_known
            self._last_refresh = time.monotonic()
            total = sum(len(v) for v in new_known.values())
            log.info(
                "Loaded %d embedding(s) for %d employee(s)",
                total, len(new_known),
            )
        except Exception as exc:
            log.error("Failed to load embeddings: %s", exc)
        # Also reload configurable threshold from backend system_policies
        self._reload_threshold()

    def _reload_threshold(self) -> None:
        """Fetch face.confidence_threshold from backend /face/policies internal endpoint."""
        if not settings.BACKEND_URL:
            return
        try:
            resp = self._http.get(
                f"{settings.BACKEND_URL}/api/v1/face/policies",
                headers={"X-Service-Key": settings.FACE_SERVICE_KEY},
                timeout=5.0,
            )
            if resp.status_code == 200:
                policies = resp.json().get("policies", {})
                val = policies.get("face.confidence_threshold")
                if val is not None:
                    self._threshold = float(val)
                    log.info("Confidence threshold updated from backend: %.4f", self._threshold)
        except Exception as exc:
            log.warning("Could not fetch face policies from backend: %s", exc)

    def refresh_embeddings_if_needed(self) -> None:
        """Reload known embeddings if the cache is older than EMBED_REFRESH_SECONDS."""
        age = time.monotonic() - self._last_refresh
        if age >= settings.EMBED_REFRESH_SECONDS:
            log.info("Refreshing known embeddings (age=%.0f s)", age)
            self._load_known_embeddings()

    def force_refresh(self) -> None:
        """Immediately reload known embeddings (called from /reload-embeddings API)."""
        self._last_refresh = 0.0
        self._load_known_embeddings()

    @property
    def known_employee_count(self) -> int:
        return len(self._known)

    @property
    def known_embedding_count(self) -> int:
        return sum(len(v) for v in self._known.values())

    # ── Detection + embedding ─────────────────────────────────────────────────

    def detect_and_embed(self, frame: np.ndarray) -> list[FaceDetection]:
        """
        Run InsightFace on one BGR frame.
        Returns a list of FaceDetection objects sorted by detection score (desc).
        Embeddings are L2-normalised.  Faces with score below 0.5 are discarded.
        """
        if self._fa is None:
            return []
        try:
            raw_faces = self._fa.get(frame)
        except Exception as exc:
            log.warning("InsightFace.get() failed: %s", exc)
            return []

        results: list[FaceDetection] = []
        for f in raw_faces:
            if f.det_score < 0.5:
                continue
            emb = getattr(f, "embedding", None)
            if emb is None:
                continue
            emb = np.array(emb, dtype=np.float32)
            norm = np.linalg.norm(emb)
            if norm < 1e-9:
                continue
            results.append(FaceDetection(
                bbox=np.array(f.bbox, dtype=float),
                embedding=emb / norm,
                score=float(f.det_score),
                kps=getattr(f, "kps", None),
            ))

        results.sort(key=lambda d: d.score, reverse=True)
        return results

    def extract_embedding_from_image(self, image_bytes: bytes) -> tuple[list[float], str]:
        """
        Decode raw image bytes, detect the largest face, return its embedding.
        Used by the backend enrollment endpoint (POST /embed).
        Raises ValueError if no face is found.
        """
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode image bytes")

        dets = self.detect_and_embed(img)
        if not dets:
            raise ValueError("No face detected in the uploaded image")

        # Use the highest-confidence detection
        best = dets[0]
        return best.embedding.tolist(), settings.MODEL_PACK

    # ── Identification ────────────────────────────────────────────────────────

    def identify_face(
        self,
        query_emb: np.ndarray,
    ) -> Optional[tuple[str, float]]:
        """
        Find the closest known embedding using cosine similarity.
        Returns (employee_id, similarity) if similarity >= FACE_CONFIDENCE_THRESHOLD,
        otherwise None.

        query_emb must be L2-normalised (detect_and_embed() guarantees this).
        All stored embeddings are also L2-normalised, so cosine sim = dot product.
        """
        if not self._known:
            return None

        best_emp: Optional[str] = None
        best_sim: float = 0.0

        for emp_id, embeddings in self._known.items():
            for ref in embeddings:
                sim = float(np.dot(query_emb, ref))   # both normalised → cosine
                if sim > best_sim:
                    best_sim = sim
                    best_emp = emp_id

        if best_sim >= self._threshold:
            return best_emp, best_sim
        return None

    # ── MinIO proof frame ─────────────────────────────────────────────────────

    def save_proof_frame(self, object_key: str, frame: np.ndarray) -> str:
        """
        JPEG-encode frame and upload to MinIO.
        Returns object_key (unchanged) so callers can embed it in the event payload.
        Logs a warning and returns the key unchanged on any failure.
        """
        if self._minio is None:
            log.debug("MinIO not available — skipping proof frame: %s", object_key)
            return object_key
        try:
            ok, buf = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85]
            )
            if not ok:
                log.warning("Failed to JPEG-encode proof frame")
                return object_key

            data = buf.tobytes()
            self._minio.put_object(
                settings.MINIO_BUCKET,
                object_key,
                io.BytesIO(data),
                length=len(data),
                content_type="image/jpeg",
            )
            log.info("Proof frame saved: %s (%d bytes)", object_key, len(data))
        except Exception as exc:
            log.error("MinIO upload failed for %s: %s", object_key, exc)

        return object_key
