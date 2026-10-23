"""
Audit suite — self-service selfie check-in (contract / behavior)
================================================================
Deterministic audits that need NO real face: auth, config shape, the admin
enable/disable toggle + RBAC, and the guard rails on POST /attendance/selfie-checkin
(disabled, not-enrolled, bad event_type). The face-driven happy path (liveness,
1:1 match, source=selfie, cooldown, audit log) is covered by the in-container
audit tests/audits/audit_selfie_liveness.py.

Run:
    $env:API_URL="http://localhost/api/v1"; pytest tests/integration/test_selfie_checkin.py -v
"""

import os
import uuid
from datetime import datetime, timezone

import httpx
import pytest

BASE = os.environ.get("API_URL", "http://localhost:8000/api/v1")
ADMIN_EMAIL = "admin@test.com"
ADMIN_PASS = "Admin@1234"
TIMEOUT = 20


class State:
    admin_token: str = ""
    branch_id: str = ""
    emp_id: str = ""
    emp_email: str = ""
    emp_token: str = ""


S = State()


def api(method: str, path: str, *, token: str = "", **kw) -> httpx.Response:
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.request(method, f"{BASE}{path}", headers=headers, timeout=TIMEOUT, **kw)


def ok(r: httpx.Response) -> dict:
    assert r.status_code < 300, f"HTTP {r.status_code} for {r.request.method} {r.request.url}\n{r.text[:400]}"
    body = r.json()
    assert body.get("success"), f"success=false: {body.get('error')}"
    return body["data"]


def login(email: str, password: str) -> str:
    return ok(api("POST", "/auth/login", json={"email": email, "password": password}))["access_token"]


def _tiny_jpeg() -> bytes:
    """Minimal valid 1x1 JPEG — a real image file, but with no detectable face."""
    return bytes([
        0xFF,0xD8,0xFF,0xE0,0x00,0x10,0x4A,0x46,0x49,0x46,0x00,0x01,0x01,0x00,0x00,0x01,
        0x00,0x01,0x00,0x00,0xFF,0xDB,0x00,0x43,0x00,0x08,0x06,0x06,0x07,0x06,0x05,0x08,
        0x07,0x07,0x07,0x09,0x09,0x08,0x0A,0x0C,0x14,0x0D,0x0C,0x0B,0x0B,0x0C,0x19,0x12,
        0x13,0x0F,0x14,0x1D,0x1A,0x1F,0x1E,0x1D,0x1A,0x1C,0x1C,0x20,0x24,0x2E,0x27,0x20,
        0x22,0x2C,0x23,0x1C,0x1C,0x28,0x37,0x29,0x2C,0x30,0x31,0x34,0x34,0x34,0x1F,0x27,
        0x39,0x3D,0x38,0x32,0x3C,0x2E,0x33,0x34,0x32,0xFF,0xC0,0x00,0x0B,0x08,0x00,0x01,
        0x00,0x01,0x01,0x01,0x11,0x00,0xFF,0xC4,0x00,0x1F,0x00,0x00,0x01,0x05,0x01,0x01,
        0x01,0x01,0x01,0x01,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01,0x02,0x03,0x04,
        0x05,0x06,0x07,0x08,0x09,0x0A,0x0B,0xFF,0xC4,0x00,0xB5,0x10,0x00,0x02,0x01,0x03,
        0x03,0x02,0x04,0x03,0x05,0x05,0x04,0x04,0x00,0x00,0x01,0x7D,0x01,0x02,0x03,0x00,
        0x04,0x11,0x05,0x12,0x21,0x31,0x41,0x06,0x13,0x51,0x61,0x07,0x22,0x71,0x14,0x32,
        0x81,0x91,0xA1,0x08,0x23,0x42,0xB1,0xC1,0x15,0x52,0xD1,0xF0,0x24,0x33,0x62,0x72,
        0x82,0x09,0x0A,0x16,0x17,0x18,0x19,0x1A,0x25,0x26,0x27,0x28,0x29,0x2A,0x34,0x35,
        0x36,0x37,0x38,0x39,0x3A,0x43,0x44,0x45,0x46,0x47,0x48,0x49,0x4A,0x53,0x54,0x55,
        0x56,0x57,0x58,0x59,0x5A,0x63,0x64,0x65,0x66,0x67,0x68,0x69,0x6A,0x73,0x74,0x75,
        0x76,0x77,0x78,0x79,0x7A,0x83,0x84,0x85,0x86,0x87,0x88,0x89,0x8A,0x93,0x94,0x95,
        0x96,0x97,0x98,0x99,0x9A,0xA2,0xA3,0xA4,0xA5,0xA6,0xA7,0xA8,0xA9,0xAA,0xB2,0xB3,
        0xB4,0xB5,0xB6,0xB7,0xB8,0xB9,0xBA,0xC2,0xC3,0xC4,0xC5,0xC6,0xC7,0xC8,0xC9,0xCA,
        0xD2,0xD3,0xD4,0xD5,0xD6,0xD7,0xD8,0xD9,0xDA,0xE1,0xE2,0xE3,0xE4,0xE5,0xE6,0xE7,
        0xE8,0xE9,0xEA,0xF1,0xF2,0xF3,0xF4,0xF5,0xF6,0xF7,0xF8,0xF9,0xFA,0xFF,0xDA,0x00,
        0x08,0x01,0x01,0x00,0x00,0x3F,0x00,0xFB,0xD0,0xFF,0xD9,
    ])


def _frames():
    """A 'frames' multipart payload (one junk frame — enough for the guard-rail tests)."""
    return [("frames", ("f.jpg", _tiny_jpeg(), "image/jpeg"))]


# ── AS-00: setup — admin + a fresh, un-enrolled employee ──────────────────────

def test_as_00_setup():
    S.admin_token = login(ADMIN_EMAIL, ADMIN_PASS)
    me = ok(api("GET", "/auth/me", token=S.admin_token))
    S.branch_id = me["branch_id"]
    role_id = next(r for r in ok(api("GET", "/roles", token=S.admin_token)) if r["name"] == "employee")["id"]

    u = uuid.uuid4().hex[:8]
    S.emp_email = f"selfieaudit_{u}@example.com"
    pw = "TestPass@1234"
    emp = ok(api("POST", "/employees", token=S.admin_token, json={
        "employee_code": f"SA{u.upper()}",
        "first_name": "Selfie", "last_name": "Audit",
        "email": S.emp_email, "password": pw,
        "role_id": role_id, "branch_id": S.branch_id,
        "date_of_joining": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }))
    S.emp_id = emp["id"]
    S.emp_token = login(S.emp_email, pw)
    assert S.emp_token


# ── AS-01: selfie-config requires authentication ──────────────────────────────

def test_as_01_config_requires_auth():
    r = api("GET", "/attendance/selfie-config")
    assert r.status_code == 401, f"expected 401 without token, got {r.status_code}"


# ── AS-02: selfie-config shape + defaults for a fresh employee ────────────────

def test_as_02_config_shape():
    cfg = ok(api("GET", "/attendance/selfie-config", token=S.emp_token))
    for key in ("enabled", "enrolled", "checked_in", "checked_out"):
        assert key in cfg, f"missing '{key}' in selfie-config: {cfg}"
    assert cfg["enabled"] is True, "selfie check-in should default to enabled"
    assert cfg["enrolled"] is False, "a brand-new employee must not be enrolled"
    assert cfg["checked_in"] is False and cfg["checked_out"] is False


# ── AS-03: admin enable/disable toggle + RBAC ─────────────────────────────────

def test_as_03_admin_toggle_and_rbac():
    # A normal employee may NOT change a system policy.
    forbidden = api("PUT", "/system/policies/selfie.enabled",
                    token=S.emp_token, json={"value": "false"})
    assert forbidden.status_code == 403, f"employee must not toggle policy: {forbidden.status_code}"

    # Admin disables → config reflects it.
    ok(api("PUT", "/system/policies/selfie.enabled", token=S.admin_token, json={"value": "false"}))
    assert ok(api("GET", "/attendance/selfie-config", token=S.emp_token))["enabled"] is False

    # Admin re-enables → config reflects it.
    ok(api("PUT", "/system/policies/selfie.enabled", token=S.admin_token, json={"value": "true"}))
    assert ok(api("GET", "/attendance/selfie-config", token=S.emp_token))["enabled"] is True


# ── AS-04: when disabled, check-in is refused (422) ───────────────────────────

def test_as_04_checkin_blocked_when_disabled():
    ok(api("PUT", "/system/policies/selfie.enabled", token=S.admin_token, json={"value": "false"}))
    try:
        r = api("POST", "/attendance/selfie-checkin", token=S.emp_token,
                data={"event_type": "ENTRY"}, files=_frames())
        assert r.status_code == 422, f"expected 422 when disabled, got {r.status_code}: {r.text[:200]}"
        assert "disabled" in r.json().get("error", "").lower()
    finally:
        # Always restore to default (delete the policy → back to default enabled).
        api("DELETE", "/system/policies/selfie.enabled", token=S.admin_token)
    assert ok(api("GET", "/attendance/selfie-config", token=S.emp_token))["enabled"] is True


# ── AS-05: enrolled requirement — un-enrolled employee is refused (422) ───────

def test_as_05_checkin_requires_enrollment():
    r = api("POST", "/attendance/selfie-checkin", token=S.emp_token,
            data={"event_type": "ENTRY"}, files=_frames())
    assert r.status_code == 422, f"expected 422 (not enrolled), got {r.status_code}: {r.text[:200]}"
    assert "enroll" in r.json().get("error", "").lower()


# ── AS-06: invalid event_type is rejected (422) ───────────────────────────────

def test_as_06_invalid_event_type():
    r = api("POST", "/attendance/selfie-checkin", token=S.emp_token,
            data={"event_type": "SIDEWAYS"}, files=_frames())
    assert r.status_code == 422, f"expected 422 for bad event_type, got {r.status_code}"
    assert "event_type" in r.json().get("error", "").lower()


# ── AS-07: selfie-checkin requires authentication ─────────────────────────────

def test_as_07_checkin_requires_auth():
    r = api("POST", "/attendance/selfie-checkin",
            data={"event_type": "ENTRY"}, files=_frames())
    assert r.status_code == 401, f"expected 401 without token, got {r.status_code}"


# ── AS-08: cleanup — soft-delete the audit employee ───────────────────────────

def test_as_08_cleanup():
    if S.emp_id:
        api("DELETE", f"/employees/{S.emp_id}", token=S.admin_token)
