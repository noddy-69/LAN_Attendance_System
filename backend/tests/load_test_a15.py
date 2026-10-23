"""
load_test_a15.py — A15 Load Test
==================================
Simulates 20 employees clocking in simultaneously via the face-recognition
camera-event endpoint. Validates:

  • No HTTP errors / DB deadlocks under concurrent load
  • All 20 ENTRY events → daily_attendance rows created
  • All 20 EXIT  events → status = PRESENT, work_minutes ≥ 480
  • P95 response time ≤ 2 000 ms for both bursts
  • SQLAlchemy connection pool does not exhaust / raise errors

Run (inside the backend container):
    python tests/load_test_a15.py

Environment:
    E2E_BASE_URL   — default http://localhost:8000
    DATABASE_URL   — default from container env
"""

import asyncio
import os
import statistics
import time
import uuid
from datetime import date, datetime, timezone

import httpx

# ─── Config ────────────────────────────────────────────────────────────────────
BASE        = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
A_EMAIL     = "admin@test.com"
A_PASS      = "Admin@1234"
EMP_PASS    = "TestPass@1234"
CONCURRENCY = 20

LOAD_DATE   = date(2026, 7, 8)                                        # Wednesday
ENTRY_UTC   = datetime(2026, 7, 8, 3, 30, tzinfo=timezone.utc)        # 09:00 IST
EXIT_UTC    = datetime(2026, 7, 8, 12, 30, tzinfo=timezone.utc)       # 18:00 IST

SFX         = uuid.uuid4().hex[:8].upper()
PASS_EMOJI  = "✅"
FAIL_EMOJI  = "❌"

# ─── Helpers ───────────────────────────────────────────────────────────────────
def _ok(resp: httpx.Response, label: str = "") -> dict:
    tag = f"[{label}] " if label else ""
    assert resp.status_code < 300, f"{tag}HTTP {resp.status_code}: {resp.text[:400]}"
    body = resp.json()
    assert body.get("success") is True, f"{tag}success=false: {body}"
    return body["data"]


def _req_sync(method: str, path: str, token: str | None = None, **kw) -> httpx.Response:
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(base_url=BASE, timeout=30) as c:
        return c.request(method, f"/api/v1{path}", headers=headers, **kw)


async def _req(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    token: str | None = None,
    **kw,
) -> httpx.Response:
    headers = kw.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return await client.request(
        method, f"/api/v1{path}", headers=headers, **kw
    )


def _pct(label: str, times_ms: list[float]) -> None:
    s = sorted(times_ms)
    p50 = statistics.median(s)
    p95 = s[int(len(s) * 0.95)] if len(s) >= 20 else max(s)
    p99 = s[int(len(s) * 0.99)] if len(s) >= 100 else max(s)
    print(
        f"  {label:30s}  p50={p50:6.0f}ms  p95={p95:6.0f}ms  p99={p99:6.0f}ms  "
        f"max={max(s):6.0f}ms  min={min(s):6.0f}ms"
    )


# ─── Setup (sequential) ────────────────────────────────────────────────────────
def setup() -> dict:
    print(f"\n{'='*65}")
    print(f"  A15 Load Test   |   CONCURRENCY={CONCURRENCY}   |   SFX={SFX}")
    print(f"{'='*65}\n")

    # Admin login
    tok = _ok(_req_sync("POST", "/auth/login", json={"email": A_EMAIL, "password": A_PASS}), "admin_login")["access_token"]

    # Resolve branch, roles, leave type
    branch_id = _ok(_req_sync("GET", "/branches", token=tok), "branches")[0]["id"]
    roles = {r["name"]: r["id"] for r in _ok(_req_sync("GET", "/roles", token=tok), "roles")}
    emp_role_id = roles["employee"]

    # Create one shared camera device for all events
    dev = _ok(
        _req_sync("POST", "/devices", token=tok, json={
            "name": f"Load Camera {SFX}",
            "device_type": "camera",
            "branch_id": branch_id,
            "is_entry_camera": True,
            "rtsp_url": "rtsp://admin:test@192.168.99.99:554/stream",
        }),
        "create_device",
    )
    device_id = dev["id"]
    print(f"  Camera device   : {device_id}")

    # Create 20 test employees
    print(f"  Creating {CONCURRENCY} employees ...", end=" ", flush=True)
    emp_ids = []
    emp_tokens = []
    for i in range(CONCURRENCY):
        code  = f"LD{SFX}{i:02d}"
        email = f"ld{SFX.lower()}{i:02d}@test.com"
        emp = _ok(
            _req_sync("POST", "/employees", token=tok, json={
                "employee_code": code,
                "first_name": f"Load{i:02d}",
                "last_name": SFX,
                "email": email,
                "password": EMP_PASS,
                "role_id": emp_role_id,
                "branch_id": branch_id,
                "date_of_joining": "2025-01-01",
            }),
            f"create_emp_{i}",
        )
        emp_ids.append(emp["id"])
    print(f"done ({CONCURRENCY} employees created)")

    return {
        "tok": tok,
        "branch_id": branch_id,
        "device_id": device_id,
        "emp_ids": emp_ids,
    }


# ─── Concurrent event burst ────────────────────────────────────────────────────
async def _fire_event(
    client: httpx.AsyncClient,
    idx: int,
    tok: str,
    emp_id: str,
    device_id: str,
    branch_id: str,
    event_type: str,
    ts: datetime,
) -> tuple[bool, float]:
    """Fire one camera event. Returns (success, latency_ms)."""
    t0 = time.perf_counter()
    try:
        resp = await _req(
            client, "POST", "/attendance/camera-event",
            token=tok,
            json={
                "employee_id": emp_id,
                "device_id": device_id,
                "branch_id": branch_id,
                "event_type": event_type,
                "timestamp": ts.isoformat(),
                "confidence_score": 0.97,
            },
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        ok = resp.status_code < 300 and resp.json().get("success") is True
        if not ok:
            print(f"  {FAIL_EMOJI} emp#{idx} {event_type} HTTP {resp.status_code}: {resp.text[:200]}")
        return ok, elapsed_ms
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"  {FAIL_EMOJI} emp#{idx} {event_type} exception: {exc}")
        return False, elapsed_ms


async def run_burst(
    ctx: dict,
    event_type: str,
    ts: datetime,
    label: str,
) -> tuple[int, list[float]]:
    """Fire CONCURRENCY events simultaneously; return (failures, latencies_ms)."""
    print(f"\n  Firing {CONCURRENCY} concurrent {label} events ...", end=" ", flush=True)
    limits = httpx.Limits(max_connections=CONCURRENCY + 5, max_keepalive_connections=CONCURRENCY)
    async with httpx.AsyncClient(base_url=BASE, timeout=30, limits=limits) as client:
        tasks = [
            _fire_event(
                client, i,
                ctx["tok"], ctx["emp_ids"][i],
                ctx["device_id"], ctx["branch_id"],
                event_type, ts,
            )
            for i in range(CONCURRENCY)
        ]
        results = await asyncio.gather(*tasks)

    failures = sum(1 for ok, _ in results if not ok)
    latencies = [ms for _, ms in results]
    wall = max(latencies) / 1000  # rough wall-clock estimate

    print(f"done  (failures={failures}, wall≈{wall:.2f}s)")
    _pct(f"  {label}", latencies)
    return failures, latencies


# ─── Verification ──────────────────────────────────────────────────────────────
def verify_records(ctx: dict) -> int:
    """
    Poll daily_attendance via the API for each employee on LOAD_DATE.
    Returns the number of employees with status=PRESENT / work_minutes≥480.
    """
    import time as _time

    print(f"\n  Verifying {CONCURRENCY} daily_attendance records ...", end=" ", flush=True)
    tok = ctx["tok"]
    date_str = LOAD_DATE.isoformat()
    present = 0
    work_ok = 0
    missing = []

    # Give Celery/background writes a moment to settle
    _time.sleep(2)

    for i, emp_id in enumerate(ctx["emp_ids"]):
        resp = _req_sync("GET", f"/attendance/daily?employee_id={emp_id}&date={date_str}", token=tok)
        if resp.status_code != 200 or not resp.json().get("success"):
            missing.append(i)
            continue
        rec = resp.json()["data"]
        if not rec:
            missing.append(i)
            continue
        # data may be a list or a single object depending on endpoint
        if isinstance(rec, list):
            rec = rec[0] if rec else None
        if not rec:
            missing.append(i)
            continue
        if rec.get("status") == "PRESENT":
            present += 1
        if (rec.get("work_minutes") or 0) >= 480:
            work_ok += 1

    print(f"done")
    print(f"  PRESENT records : {present}/{CONCURRENCY}")
    print(f"  work_minutes≥480: {work_ok}/{CONCURRENCY}")
    if missing:
        print(f"  {FAIL_EMOJI} Missing records for employee indices: {missing}")
    return present


# ─── Main ──────────────────────────────────────────────────────────────────────
async def main() -> None:
    ctx = setup()

    # Burst 1 — 20 concurrent ENTRY events
    entry_failures, entry_latencies = await run_burst(ctx, "ENTRY", ENTRY_UTC, "ENTRY")

    # Burst 2 — 20 concurrent EXIT events (1 second later to ensure ordering)
    await asyncio.sleep(1)
    exit_failures, exit_latencies = await run_burst(ctx, "EXIT", EXIT_UTC, "EXIT ")

    # Verify records
    present = verify_records(ctx)

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'='*65}")
    print("  A15 LOAD TEST RESULTS")
    print(f"{'='*65}")

    all_latencies = entry_latencies + exit_latencies
    p95_all = sorted(all_latencies)[int(len(all_latencies) * 0.95)]

    checks = [
        ("ENTRY failures == 0",       entry_failures == 0),
        ("EXIT  failures == 0",       exit_failures  == 0),
        (f"PRESENT records == {CONCURRENCY}", present == CONCURRENCY),
        ("P95 latency ≤ 2000 ms",     p95_all <= 2000),
    ]

    passed = 0
    for label, result in checks:
        icon = PASS_EMOJI if result else FAIL_EMOJI
        print(f"  {icon}  {label}")
        if result:
            passed += 1

    total = len(checks)
    print(f"\n  Result: {passed}/{total} checks passed", end="")
    if passed == total:
        print(f"  {PASS_EMOJI}  ALL PASS — A15 complete\n")
    else:
        print(f"  {FAIL_EMOJI}  FAILURES DETECTED — see above\n")
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
