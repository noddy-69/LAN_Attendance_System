"""
load_test_face_service.py
=========================
Load / stress test for the face-recognition microservice's /embed endpoint.

The /embed endpoint runs CPU-intensive InsightFace ONNX inference.  This test
fires concurrent requests at increasing parallelism levels and reports:
  - Latency: p50 / p95 / p99 / max (ms)
  - Throughput: requests per second (sequential baseline)
  - Error rate: counts of 5xx responses (must be zero)

Acceptable responses per request:
  200  — face detected, 512-dim embedding returned
  400  — no face detected (valid rejection on synthetic test image)
  422  — validation error (should not occur on valid PNG bytes)
  5xx  — FAILURE (server error under load — zero tolerance)

The test image is a synthetic 64×64 greyscale PNG (no real face).
InsightFace will correctly report "no face detected" but still run
through the full ONNX detection pipeline — which is what we are
measuring under load.

Concurrency levels tested: 1, 5, 10, 20
Sustained sequential test: 30 requests

Run from inside the backend container (on the same Docker network):
    docker compose exec backend python tests/load_test_face_service.py

Run directly against the exposed face-service port:
    FACE_BASE=http://localhost:8001 python tests/load_test_face_service.py
"""

import asyncio
import os
import struct
import sys
import time
import zlib

import httpx

# ── Target ──────────────────────────────────────────────────────────────────
_FACE_BASE = os.environ.get(
    "FACE_BASE",
    os.environ.get("FACE_SERVICE_URL", "http://face-recognition:8001"),
)


# ── Synthetic test image (64×64 greyscale PNG, no face) ─────────────────────

def _make_grey_png(size: int = 64) -> bytes:
    """Generate a valid greyscale PNG of `size` × `size` pixels (all 0x80 grey).

    The PNG exercises the full InsightFace input pipeline:
      resize → normalise → ONNX forward pass → no face found → return 400
    No external dependencies — uses only stdlib zlib + struct.
    """
    def _chunk(name: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", crc)

    # IHDR: width, height, bit_depth=8, color_type=0 (greyscale), compress=0, filter=0, interlace=0
    ihdr_data = struct.pack(">IIBBBBB", size, size, 8, 0, 0, 0, 0)
    # IDAT: each row = filter_byte(0x00) + size grey pixels (0x80)
    raw_row = b"\x00" + bytes([0x80] * size)
    idat_data = zlib.compress(raw_row * size, level=1)

    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr_data)
        + _chunk(b"IDAT", idat_data)
        + _chunk(b"IEND", b"")
    )


_TEST_IMAGE: bytes = _make_grey_png(64)   # ~700 bytes compressed


# ── Percentile printer ───────────────────────────────────────────────────────

def _pct(label: str, times_ms: list[float]) -> None:
    if not times_ms:
        print(f"  {label}: no data")
        return
    s = sorted(times_ms)
    n = len(s)
    p50 = s[int(n * 0.50)]
    p95 = s[min(int(n * 0.95), n - 1)]
    p99 = s[min(int(n * 0.99), n - 1)]
    print(
        f"  {label}: "
        f"p50={p50:6.0f}ms  p95={p95:6.0f}ms  "
        f"p99={p99:6.0f}ms  max={s[-1]:6.0f}ms  min={s[0]:6.0f}ms"
    )


# ── Single async /embed request ──────────────────────────────────────────────

async def _fire_embed(client: httpx.AsyncClient) -> tuple[int, float]:
    """POST /embed with the synthetic test image.  Returns (status_code, latency_ms).
    Returns status_code=0 on connection exception.
    """
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            "/embed",
            content=_TEST_IMAGE,
            headers={"Content-Type": "image/png"},
            timeout=120.0,
        )
        status = resp.status_code
    except Exception as exc:
        print(f"    [EXCEPTION] {exc}")
        status = 0
    latency_ms = (time.perf_counter() - t0) * 1000.0
    return status, latency_ms


# ── Burst: N concurrent /embed requests ─────────────────────────────────────

async def _run_burst(concurrency: int, cooldown_s: float = 2.0) -> dict:
    """Fire `concurrency` concurrent /embed requests; wait `cooldown_s` after.

    Returns a stats dict with ok, errors, exceptions, and latency list.
    """
    async with httpx.AsyncClient(base_url=_FACE_BASE) as client:
        results = await asyncio.gather(
            *[_fire_embed(client) for _ in range(concurrency)]
        )

    await asyncio.sleep(cooldown_s)

    statuses  = [r[0] for r in results]
    latencies = [r[1] for r in results]
    return {
        "concurrency": concurrency,
        "ok":          sum(1 for s in statuses if s in (200, 400, 422)),
        "errors":      sum(1 for s in statuses if s >= 500),
        "exceptions":  sum(1 for s in statuses if s == 0),
        "latencies":   latencies,
        "statuses":    statuses,
    }


# ── Health check + warmup ────────────────────────────────────────────────────

async def _health_check() -> bool:
    """Return True if face-service is reachable and reports a status."""
    try:
        async with httpx.AsyncClient(base_url=_FACE_BASE, timeout=15.0) as c:
            resp = await c.get("/health")
        if resp.status_code == 200:
            body = resp.json()
            model_ready = body.get("model_ready") or body.get("model_loaded") or False
            print(
                f"  /health → status={body.get('status', '?')}  "
                f"model_ready={model_ready}  "
                f"known_employees={body.get('known_employees', '?')}"
            )
            if not model_ready:
                print(
                    "  [WARN] model_ready=False — model may still be loading.\n"
                    "         Warmup request will trigger lazy model initialisation."
                )
            return True
        print(f"  /health returned HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        print(f"  [ERROR] Cannot reach face-service at {_FACE_BASE}: {exc}")
    return False


async def _warmup() -> float:
    """Single /embed to trigger lazy ONNX model load.  Returns latency (ms)."""
    print("  Sending single warmup /embed request (may take 10–30 s for model load) …")
    async with httpx.AsyncClient(base_url=_FACE_BASE, timeout=120.0) as c:
        t0 = time.perf_counter()
        resp = await c.post(
            "/embed",
            content=_TEST_IMAGE,
            headers={"Content-Type": "image/png"},
        )
        ms = (time.perf_counter() - t0) * 1000.0
    print(f"  Warmup: HTTP {resp.status_code} in {ms:.0f}ms")
    if resp.status_code >= 500:
        print(f"  [WARN] Warmup returned 5xx — service may be degraded: {resp.text[:200]}")
    return ms


# ── Sustained sequential throughput ─────────────────────────────────────────

async def _sequential_throughput(count: int = 30) -> tuple[list[float], float]:
    """Fire `count` sequential /embed requests.  Returns (latencies_ms, req_per_sec)."""
    latencies: list[float] = []
    async with httpx.AsyncClient(base_url=_FACE_BASE, timeout=120.0) as client:
        for i in range(count):
            _, ms = await _fire_embed(client)
            latencies.append(ms)
            if (i + 1) % 10 == 0:
                print(f"    … {i + 1}/{count} done")
    total_s = sum(latencies) / 1000.0
    throughput = count / total_s if total_s > 0 else 0.0
    return latencies, throughput


# ── Main ─────────────────────────────────────────────────────────────────────

async def main() -> int:
    CONCURRENCY_LEVELS = [1, 5, 10, 20]
    SEQUENTIAL_COUNT   = 30
    # Thresholds
    MAX_5XX            = 0        # zero tolerance on server errors
    MIN_THROUGHPUT     = 0.5      # req/s — CPU-only ONNX INT8: ~0.5–5 req/s
    MAX_SEQ_P95_MS     = 10_000   # 10 s — generous for CPU-only inference

    print("=" * 64)
    print("  Face Recognition Service — /embed Load Test")
    print(f"  Target  : {_FACE_BASE}")
    print(f"  Image   : 64×64 greyscale PNG ({len(_TEST_IMAGE)} bytes)")
    print("=" * 64)

    # ── Health check ────────────────────────────────────────────────────────
    print("\n── 1. Health Check ───────────────────────────────────────")
    if not await _health_check():
        print("[ABORT] Face-service unreachable.  Is it running?")
        return 1

    # ── Warmup ──────────────────────────────────────────────────────────────
    print("\n── 2. Warmup ─────────────────────────────────────────────")
    await _warmup()

    # ── Concurrent bursts ───────────────────────────────────────────────────
    all_results: list[dict] = []
    print("\n── 3. Concurrent /embed Bursts ───────────────────────────")
    for c in CONCURRENCY_LEVELS:
        print(f"\n  Burst: {c} concurrent requests")
        result = await _run_burst(c, cooldown_s=2.0)
        all_results.append(result)

        status_counts: dict[int, int] = {}
        for s in result["statuses"]:
            status_counts[s] = status_counts.get(s, 0) + 1

        _pct(f"    c={c:2d}", result["latencies"])
        print(f"         status counts : {status_counts}")
        if result["errors"]:
            print(f"  ❌  {result['errors']} server error(s) (5xx)!")
        if result["exceptions"]:
            print(f"  ❌  {result['exceptions']} connection exception(s)!")

    # ── Sequential throughput baseline ──────────────────────────────────────
    print(f"\n── 4. Sequential Throughput ({SEQUENTIAL_COUNT} requests) ─────────────")
    seq_latencies, throughput = await _sequential_throughput(SEQUENTIAL_COUNT)
    _pct(f"  seq({SEQUENTIAL_COUNT})", seq_latencies)
    print(f"  Throughput : {throughput:.2f} req/s")

    # ── Assertions ───────────────────────────────────────────────────────────
    print("\n── 5. Pass / Fail Assertions ─────────────────────────────")
    failures: list[str] = []

    total_5xx = sum(r["errors"] for r in all_results)
    total_exc = sum(r["exceptions"] for r in all_results)

    if total_5xx > MAX_5XX:
        failures.append(f"Server errors (5xx) = {total_5xx}  (threshold: {MAX_5XX})")
    if total_exc > 0:
        failures.append(f"Connection exceptions = {total_exc}  (expected: 0)")
    if throughput < MIN_THROUGHPUT:
        failures.append(
            f"Sequential throughput = {throughput:.2f} req/s  (threshold: ≥ {MIN_THROUGHPUT})"
        )
    seq_p95 = sorted(seq_latencies)[min(int(SEQUENTIAL_COUNT * 0.95), SEQUENTIAL_COUNT - 1)]
    if seq_p95 > MAX_SEQ_P95_MS:
        failures.append(
            f"Sequential p95 = {seq_p95:.0f}ms  (threshold: ≤ {MAX_SEQ_P95_MS}ms)"
        )

    print(f"  Zero 5xx server errors     : {total_5xx == 0}  ({total_5xx} errors)")
    print(f"  Zero connection exceptions : {total_exc == 0}  ({total_exc} exceptions)")
    print(f"  Throughput ≥ {MIN_THROUGHPUT} req/s       : {throughput >= MIN_THROUGHPUT}  ({throughput:.2f} req/s)")
    print(f"  Sequential p95 ≤ {MAX_SEQ_P95_MS}ms    : {seq_p95 <= MAX_SEQ_P95_MS}  ({seq_p95:.0f}ms)")

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 64)
    if failures:
        print(f"  RESULT: ❌ FAIL — {len(failures)} assertion(s) failed:")
        for f in failures:
            print(f"    • {f}")
        print("=" * 64)
        return 1

    print("  RESULT: ✅ PASS")
    print("  Face-service handles concurrent /embed load without errors.")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
