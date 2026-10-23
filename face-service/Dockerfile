FROM python:3.12-slim

WORKDIR /app

# ── System dependencies ───────────────────────────────────────────────────────
# libgomp1   : OpenMP, required by ONNX Runtime CPU provider
# libglib2.0 : required by OpenCV headless (GLib I/O)
# ca-certs   : HTTPS for InsightFace model download at build time
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libglib2.0-0 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
# insightface ships as an sdist with Cython extensions — g++ is needed only at
# pip-install time, so purge it in the same layer to keep the image small.
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends g++ \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y g++ \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# ── Pre-download InsightFace buffalo_sc model ─────────────────────────────────
# Baking the model into the image avoids a slow network download on every
# container start.  If the download fails (air-gapped build), the container
# will still start and retry at runtime — the || true prevents a build failure.
ENV INSIGHTFACE_HOME=/opt/insightface
RUN python -c "\
import types, sys; \
stub = types.ModuleType('insightface.app.mask_renderer'); \
sys.modules['insightface.app.mask_renderer'] = stub; \
from insightface.app import FaceAnalysis; \
fa = FaceAnalysis(name='buffalo_sc', root='/opt/insightface', providers=['CPUExecutionProvider']); \
fa.prepare(ctx_id=0, det_size=(320, 320)); \
print('buffalo_sc model ready at /opt/insightface/models/buffalo_sc/'); \
" || echo "[WARN] buffalo_sc model pre-download failed — will download at first run"

# ── Non-root user ─────────────────────────────────────────────────────────────
# /opt/insightface/antispoof is the default mount point for optional MiniFASNet
# liveness models (FACE_ANTISPOOF_MODEL_DIR); created empty so the path exists.
RUN adduser --disabled-password --gecos "" --uid 1000 appuser \
    && mkdir -p /opt/insightface/antispoof \
    && chown -R appuser:appuser /opt/insightface

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8001

# Healthcheck polls /health every 30 s
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c \
        "import urllib.request; \
         r = urllib.request.urlopen('http://localhost:8001/health', timeout=5); \
         import json; d=json.loads(r.read()); \
         exit(0 if d.get('status')=='ok' else 1)" \
    || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]
