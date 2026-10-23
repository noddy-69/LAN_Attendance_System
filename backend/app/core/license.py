"""
Software licensing — verifies the RSA-signed license token shipped with each
deployment. The vendor signs licenses with a private key (vendor/make_license.py);
the app verifies with the bundled public key (license_public.pem), so a customer
cannot forge or extend their own license.

A license token (JWT, RS256) carries: company, max_employees, exp (expiry).

Enforcement (only when LICENSE_ENFORCE=true — off in dev so tests are unaffected):
  • invalid/expired/missing license  → non-admin logins are blocked
    (the admin can still log in to view the status and renew).
  • max_employees                     → cannot add employees beyond the cap.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from jose import jwt
from jose.exceptions import ExpiredSignatureError, JWTError

_PUB_PATH = Path(__file__).with_name("license_public.pem")


def _public_key() -> str:
    env = os.environ.get("LICENSE_PUBLIC_KEY")
    if env:
        return env
    try:
        return _PUB_PATH.read_text()
    except Exception:
        return ""


def _enforce() -> bool:
    return os.environ.get("LICENSE_ENFORCE", "false").strip().lower() in ("1", "true", "yes")


def get_status() -> dict:
    """Return a dict describing the current license state (safe to expose)."""
    enforce = _enforce()
    token = (os.environ.get("LICENSE_KEY") or "").strip()
    pub = _public_key()

    if not token:
        return {"licensed": False, "status": "missing", "enforced": enforce,
                "message": "No license installed."}
    if not pub:
        return {"licensed": False, "status": "no_public_key", "enforced": enforce,
                "message": "License public key missing from this build."}
    try:
        claims = jwt.decode(token, pub, algorithms=["RS256"])
        exp = datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc)
        days_left = (exp - datetime.now(timezone.utc)).days
        return {
            "licensed": True,
            "status": "valid",
            "enforced": enforce,
            "company": claims.get("company"),
            "max_employees": claims.get("max_employees"),
            "expires_at": exp.isoformat(),
            "days_left": days_left,
            "message": "Licensed.",
        }
    except ExpiredSignatureError:
        return {"licensed": False, "status": "expired", "enforced": enforce,
                "message": "Your software license has expired. Please contact your provider."}
    except (JWTError, KeyError, ValueError):
        return {"licensed": False, "status": "invalid", "enforced": enforce,
                "message": "Your software license is invalid. Please contact your provider."}


def is_valid() -> bool:
    return bool(get_status().get("licensed"))


def enforced() -> bool:
    return _enforce()


def max_employees() -> int | None:
    s = get_status()
    return s.get("max_employees") if s.get("licensed") else None


def blocks_non_admin() -> bool:
    """When enforcing and the license is not valid, non-admin logins are blocked."""
    return _enforce() and not is_valid()
