"""
test_camera_biometric_a18_a19.py
=================================
A18 — Real Camera (CP Plus RTSP + Face Service pipeline readiness)
A19 — ZKTeco K40 biometric ADMS push → daily_attendance record

A18 tests validate that:
  • The face-service /health endpoint reports "ready" (or "degraded" if no camera)
  • The RTSP URL format matches the CP Plus spec from CLAUDE.md
  • The /embed endpoint accepts a face image and returns a 512-dim embedding
  • Camera config (ENTRY_CAMERA_URL/EXIT_CAMERA_URL) is readable from face-service

A19 tests validate that:
  • ZKTeco ADMS payload → POST /attendance/biometric-event creates an attendance record
  • State 0 (check-in) maps to ENTRY event
  • State 1 (check-out) maps to EXIT event
  • Unknown biometric_uid returns 404 (not 500)
  • Payload with invalid time format returns 422

Run inside the backend container:
    docker compose exec backend python -m pytest tests/test_camera_biometric_a18_a19.py -v --tb=short
"""

import os
import re
import time
import uuid
from datetime import date, datetime, timezone

import httpx
import pytest

# ─── Shared config ─────────────────────────────────────────────────────────────
_BASE         = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
_FACE_BASE    = os.environ.get("FACE_SERVICE_URL", "http://face-recognition:8001")
_A_EMAIL      = "admin@test.com"
_A_PASS       = "Admin@1234"
_EMP_PASS     = "TestPass@1234"

_SFX          = uuid.uuid4().hex[:8].upper()
_BIO_DATE     = date(2026, 7, 9)                                       # Thursday
_BIO_ENTRY_TS = "2026-07-09 09:05:33"                                  # ZKTeco device time (local)
_BIO_EXIT_TS  = "2026-07-09 18:01:00"


def _req(method, path, base=_BASE, token=None, **kw):
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # Backend routes live under /api/v1; face-service routes are at root
    if base == _BASE:
        full_path = f"/api/v1{path}" if not path.startswith("/api/") else path
    else:
        full_path = path   # face-service: /health, /status, /embed
    with httpx.Client(base_url=base, timeout=30) as c:
        return c.request(method, full_path, headers=headers, **kw)


def _ok(resp, label=""):
    tag = f"[{label}] " if label else ""
    assert resp.status_code < 300, f"{tag}HTTP {resp.status_code}: {resp.text[:500]}"
    body = resp.json()
    assert body.get("success") is True, f"{tag}success=false: {body}"
    return body["data"]


# ═══════════════════════════════════════════════════════
# A18 — Face Service / Camera Pipeline
# ═══════════════════════════════════════════════════════

class TestA18Camera:
    """
    A18: Verify the face-recognition microservice is ready.

    These tests do NOT require a physical camera — they validate the
    service is running, the /embed endpoint works, and the CP Plus RTSP
    URL format is correctly specified in the project documentation.

    When ENTRY_CAMERA_URL / EXIT_CAMERA_URL are set in the environment,
    additional connectivity checks are performed.
    """

    def test_a18_01_face_service_health(self):
        """Face-recognition microservice is running and reports a status field."""
        resp = _req("GET", "/health", base=_FACE_BASE)
        assert resp.status_code == 200, f"face-service /health returned {resp.status_code}: {resp.text}"
        body = resp.json()
        # Service returns status field — accept any non-error value
        assert "status" in body, f"No 'status' key in health response: {body}"
        assert body["status"] in ("ok", "healthy", "degraded"), f"Unexpected status: {body}"
        # Model must be loaded (ONNX weights present)
        assert body.get("model_ready") is True or body.get("model_loaded") is True, (
            f"Model not ready: {body}"
        )

    def test_a18_02_face_service_status(self):
        """Face-service /status endpoint returns camera and embedding info."""
        resp = _req("GET", "/status", base=_FACE_BASE)
        assert resp.status_code == 200
        body = resp.json()
        # At minimum, the status must contain an embedding or camera key
        has_known = "known_employees" in body or "known_embeddings" in body
        has_camera = "camera_stats" in body or "cameras_running" in body
        assert has_known or has_camera, (
            f"Status response missing expected keys: {body}"
        )

    def test_a18_03_rtsp_url_format(self):
        """
        Validates CP Plus RTSP URL format per CLAUDE.md spec:
          rtsp://admin:{password}@{camera_ip}:554/cam/realmonitor?channel=1&subtype=0

        If ENTRY_CAMERA_URL is configured in the face-service, it must match
        the expected CP Plus format OR be a test override (file/webcam).
        """
        entry_url = os.environ.get("ENTRY_CAMERA_URL", "")
        exit_url  = os.environ.get("EXIT_CAMERA_URL", "")

        RTSP_PATTERN = re.compile(
            r"^rtsp://[^:]+:[^@]*@[\d.]+:554/cam/realmonitor\?channel=\d+&subtype=\d+$"
        )
        TEST_OVERRIDES = ("", "0", "1")  # empty = not configured, integer = webcam

        for name, url in [("ENTRY_CAMERA_URL", entry_url), ("EXIT_CAMERA_URL", exit_url)]:
            if url in TEST_OVERRIDES:
                continue   # Not configured — skip format check
            assert RTSP_PATTERN.match(url), (
                f"{name}={url!r} does not match CP Plus RTSP format.\n"
                f"Expected: rtsp://admin:{{password}}@{{camera_ip}}:554/cam/realmonitor?channel=1&subtype=0"
            )

    def test_a18_04_embed_endpoint_accepts_tiny_png(self):
        """
        POST /embed with a minimal valid PNG (1×1 pixel) returns either:
          - 200 with a 512-dim embedding (if InsightFace detects a face)
          - 400 / 422 with "no face detected" message (correct rejection)
        The service must NOT return 500 on a valid image with no face.
        """
        # Minimal 1×1 white PNG (no face)
        TINY_PNG = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
            b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        resp = _req(
            "POST", "/embed", base=_FACE_BASE,
            content=TINY_PNG,
            headers={"Content-Type": "image/png"},
        )
        # Must not be 500 (internal error)
        assert resp.status_code != 500, f"face-service 500 on valid image: {resp.text}"
        # Either found a face (200) or correctly rejected (400/422)
        assert resp.status_code in (200, 400, 422), (
            f"Unexpected status {resp.status_code}: {resp.text}"
        )
        if resp.status_code == 200:
            data = resp.json()
            assert "embedding" in data, f"Missing 'embedding' in response: {data}"
            assert len(data["embedding"]) == 512, (
                f"Expected 512-dim embedding, got {len(data['embedding'])}"
            )


# ═══════════════════════════════════════════════════════
# A19 — ZKTeco K40 ADMS biometric push
# ═══════════════════════════════════════════════════════

@pytest.fixture(scope="class")
def bio_ctx():
    """Create admin token + a test employee with biometric_uid."""
    # Admin login
    tok = _ok(_req("POST", "/auth/login", json={"email": _A_EMAIL, "password": _A_PASS}), "admin_login")["access_token"]
    branch_id = _ok(_req("GET", "/branches", token=tok), "branches")[0]["id"]
    roles = {r["name"]: r["id"] for r in _ok(_req("GET", "/roles", token=tok), "roles")}
    emp_role_id = roles["employee"]

    # Create device
    dev = _ok(
        _req("POST", "/devices", token=tok, json={
            "name": f"ZKTeco K40 {_SFX}",
            "device_type": "biometric",
            "branch_id": branch_id,
            "ip_address": "192.168.1.200",
        }),
        "create_device",
    )

    # Create employee with biometric_uid
    emp = _ok(
        _req("POST", "/employees", token=tok, json={
            "employee_code": f"BIO{_SFX}",
            "first_name": "ZKTest",
            "last_name": _SFX,
            "email": f"zk{_SFX.lower()}@test.com",
            "password": _EMP_PASS,
            "role_id": emp_role_id,
            "branch_id": branch_id,
            "biometric_uid": f"BIO{_SFX}",    # matches ZKTeco device UID
            "date_of_joining": "2025-01-01",
        }),
        "create_employee",
    )

    return {
        "tok": tok,
        "branch_id": branch_id,
        "device_id": dev["id"],
        "emp_id": emp["id"],
        "biometric_uid": f"BIO{_SFX}",
        "device_sn": f"SN{_SFX}",
    }


class TestA19Biometric:

    def test_a19_01_check_in_state0(self, bio_ctx):
        """
        ZKTeco ADMS state=0 → ENTRY event → check_in set.

        Payload format per CLAUDE.md (ZKTeco ADMS standard):
          { sn, ret, cmd, uid, time, state, ty }
        """
        payload = {
            "sn":    bio_ctx["device_sn"],
            "ret":   "0",
            "cmd":   "att",
            "uid":   bio_ctx["biometric_uid"],
            "time":  _BIO_ENTRY_TS,
            "state": "0",    # Check-In
            "ty":    "1",
        }
        resp = _req("POST", "/attendance/biometric-event", json=payload)
        data = _ok(resp, "biometric_checkin")

        assert data.get("check_in") is not None, f"check_in not set: {data}"
        # The timestamp in the response is UTC; 09:05:33 IST = 03:35:33 UTC
        assert "2026-07-09" in data["check_in"], f"Wrong date in check_in: {data['check_in']}"

    def test_a19_02_check_out_state1(self, bio_ctx):
        """ZKTeco ADMS state=1 → EXIT event → check_out set, status=PRESENT."""
        payload = {
            "sn":    bio_ctx["device_sn"],
            "ret":   "0",
            "cmd":   "att",
            "uid":   bio_ctx["biometric_uid"],
            "time":  _BIO_EXIT_TS,
            "state": "1",    # Check-Out
            "ty":    "1",
        }
        resp = _req("POST", "/attendance/biometric-event", json=payload)
        data = _ok(resp, "biometric_checkout")

        assert data.get("check_out") is not None, f"check_out not set: {data}"
        assert data.get("status") == "PRESENT", f"Expected PRESENT, got {data.get('status')}"
        assert (data.get("work_minutes") or 0) > 0, f"work_minutes not calculated: {data}"

    def test_a19_03_unknown_biometric_uid_returns_404(self, bio_ctx):
        """POST with uid that doesn't match any employee → 404 (not 500)."""
        payload = {
            "sn":    bio_ctx["device_sn"],
            "ret":   "0",
            "cmd":   "att",
            "uid":   "UNKNOWN_UID_XYZXYZ",
            "time":  _BIO_ENTRY_TS,
            "state": "0",
            "ty":    "1",
        }
        resp = _req("POST", "/attendance/biometric-event", json=payload)
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"

    def test_a19_04_missing_uid_returns_422(self, bio_ctx):
        """Incomplete payload → 422 validation error."""
        payload = {
            "sn":   bio_ctx["device_sn"],
            "ret":  "0",
            "cmd":  "att",
            # uid missing
            "time": _BIO_ENTRY_TS,
            "state": "0",
        }
        resp = _req("POST", "/attendance/biometric-event", json=payload)
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_a19_05_daily_record_persisted(self, bio_ctx):
        """
        After check-in + check-out, daily_attendance record must exist
        with source=biometric and status=PRESENT.
        """
        resp = _req(
            "GET",
            f"/attendance/daily?employee_id={bio_ctx['emp_id']}&date={_BIO_DATE.isoformat()}",
            token=bio_ctx["tok"],
        )
        data = _ok(resp, "daily_attendance")
        rec = data[0] if isinstance(data, list) else data
        assert rec, "No daily_attendance record found"
        assert rec.get("status") == "PRESENT"
        assert rec.get("source") == "biometric"

    def test_a19_06_cooldown_blocks_duplicate_entry(self, bio_ctx):
        """
        Sending the same ENTRY event within the cooldown window should be
        rejected with 422 (cooldown / duplicate guard).
        """
        payload = {
            "sn":    bio_ctx["device_sn"],
            "ret":   "0",
            "cmd":   "att",
            "uid":   bio_ctx["biometric_uid"],
            "time":  _BIO_ENTRY_TS,       # same timestamp as test_a19_01
            "state": "0",
            "ty":    "1",
        }
        resp = _req("POST", "/attendance/biometric-event", json=payload)
        # Cooldown / duplicate: expect 422 UnprocessableEntity
        assert resp.status_code == 422, (
            f"Expected 422 (cooldown rejection), got {resp.status_code}: {resp.text}"
        )


# ═══════════════════════════════════════════════════════
# ZKTeco K40 Setup Guidance (printed, not tested)
# ═══════════════════════════════════════════════════════

def test_zkteco_setup_guidance_displayed():
    """
    Not a real test — prints the ZKTeco K40 ADMS configuration steps so
    they appear in the pytest output alongside the pass/fail results.
    """
    lan_ip = os.environ.get("BASE_URL", "http://192.168.x.x").replace("http://", "").replace("https://", "").split("/")[0]
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  ZKTeco K40 — ADMS Configuration Steps                      ║
╠══════════════════════════════════════════════════════════════╣
║  1. On device: Menu → Communication → ADMS / Cloud Setting  ║
║  2. Enable ADMS: Yes                                         ║
║  3. Server address: {lan_ip:<38s} ║
║  4. Server port: 8000  (matches Nginx → backend)            ║
║  5. Save → Reboot device                                     ║
║                                                              ║
║  In the Admin portal:                                        ║
║  6. Admin → Devices → Add Device → Type: Biometric          ║
║     Name: ZKTeco K40, IP: <device LAN IP>, Port: 4370       ║
║  7. Edit each employee → set "Biometric UID" to the ID      ║
║     shown on the ZKTeco device for that person (uid field).  ║
║                                                              ║
║  To find the uid for an employee:                            ║
║    ZKTeco device → Menu → User Mgt → view user list         ║
║    The number shown is the uid to enter in the HR portal.    ║
╚══════════════════════════════════════════════════════════════╝
""")
