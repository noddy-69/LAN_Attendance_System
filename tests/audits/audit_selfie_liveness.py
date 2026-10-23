"""
Audit — selfie check-in: liveness, 1:1 match, source, cooldown, audit log.
==========================================================================
Face-driven audit that MUST run inside the face-recognition container (it needs
InsightFace + OpenCV). It creates a throwaway employee, enrolls a real face, then
exercises the full selfie path end-to-end and self-cleans (soft-deletes the
employee) afterwards.

Run from the project root:
    docker compose exec -T face-recognition python - < tests/audits/audit_selfie_liveness.py

Exit code 0 = all audits passed.
"""
import os
import sys
import types
import uuid

import cv2
import httpx

# Import FaceAnalysis the same way the recognizer does (stub mask_renderer so it
# loads without torch), only used here to crop a single, consistent face.
sys.modules.setdefault("insightface.app.mask_renderer", types.ModuleType("insightface.app.mask_renderer"))
from insightface.app import FaceAnalysis            # noqa: E402
from insightface.data import get_image as get_image  # noqa: E402

BACKEND = "http://backend:8000/api/v1"
FACE = "http://localhost:8001"
c = httpx.Client(timeout=120.0)
passed = []


def check(name, cond, detail=""):
    assert cond, f"[FAIL] {name}: {detail}"
    passed.append(name)
    print(f"[ok] {name}" + (f" -- {detail}" if detail else ""))


def login(email, pw):
    r = c.post(f"{BACKEND}/auth/login", json={"email": email, "password": pw})
    r.raise_for_status()
    return r.json()["data"]["access_token"]


def jpg(im):
    ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return buf.tobytes()


def rot(im, ang):
    h, w = im.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    return cv2.warpAffine(im, M, (w, h), borderMode=cv2.BORDER_REPLICATE)


def main():
    # ── Prepare a single-face crop + a head-movement burst ────────────────────
    fa = FaceAnalysis(name="buffalo_sc",
                      root=os.environ.get("INSIGHTFACE_HOME", os.path.expanduser("~/.insightface")),
                      providers=["CPUExecutionProvider"])
    fa.prepare(ctx_id=0, det_size=(320, 320))
    img = get_image("t1")
    f = max(fa.get(img), key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
    x1, y1, x2, y2 = (int(v) for v in f.bbox)
    pad = int(0.7 * (x2 - x1))
    H, W = img.shape[:2]
    crop = img[max(0, y1 - pad):min(H, y2 + pad), max(0, x1 - pad):min(W, x2 + pad)].copy()
    frames = [("frames", (f"f{i}.jpg", jpg(rot(crop, a)), "image/jpeg")) for i, a in enumerate([-12, -6, 0, 6, 12, 0])]
    junk = [("frames", ("j.jpg", jpg(cv2.resize(img[0:8, 0:8], (64, 64))), "image/jpeg"))]  # no face

    # ── Create a throwaway employee + enroll the face ─────────────────────────
    atok = login("admin@test.com", "Admin@1234")
    ah = {"Authorization": f"Bearer {atok}"}
    branch = c.get(f"{BACKEND}/auth/me", headers=ah).json()["data"]["branch_id"]
    role_id = next(r for r in c.get(f"{BACKEND}/roles", headers=ah).json()["data"] if r["name"] == "employee")["id"]
    u = uuid.uuid4().hex[:8]
    email = f"selfielive_{u}@example.com"
    emp = c.post(f"{BACKEND}/employees", headers=ah, json={
        "employee_code": f"SL{u.upper()}", "first_name": "Selfie", "last_name": "Live",
        "email": email, "password": "TestPass@1234", "role_id": role_id, "branch_id": branch,
        "date_of_joining": "2026-01-01",
    }).json()["data"]
    emp_id = emp["id"]

    try:
        er = c.post(f"{BACKEND}/face/employees/{emp_id}/enroll", headers=ah,
                    files={"file": ("base.jpg", jpg(crop), "image/jpeg")})
        check("AS-L0 enroll", er.status_code == 201, f"status={er.status_code}")

        etok = login(email, "TestPass@1234")
        eh = {"Authorization": f"Bearer {etok}"}

        # AS-L1 — liveness verdict from the face service
        v = c.post(f"{FACE}/verify-selfie", files=frames).json()
        lv = v.get("liveness", {})
        check("AS-L1 liveness passive+active", v.get("ok") and lv.get("active_passed") and lv.get("passive_passed"),
              f"ok={v.get('ok')} liveness={lv}")

        # AS-L2 — a no-face image is rejected (422), before any real check-in
        r = c.post(f"{BACKEND}/attendance/selfie-checkin", headers=eh,
                   data={"event_type": "ENTRY"}, files=junk)
        check("AS-L2 no-face rejected", r.status_code == 422, f"status={r.status_code} body={r.text[:120]}")

        # AS-L3 — ENTRY happy path, source=selfie
        r = c.post(f"{BACKEND}/attendance/selfie-checkin", headers=eh,
                   data={"event_type": "ENTRY"}, files=frames)
        d = r.json().get("data") or {}
        check("AS-L3 ENTRY recorded source=selfie",
              r.status_code == 200 and str(d.get("source", "")).lower() == "selfie" and d.get("check_in"),
              f"status={r.status_code} source={d.get('source')} check_in={d.get('check_in')}")

        # AS-L4 — optional EXIT records check_out
        r = c.post(f"{BACKEND}/attendance/selfie-checkin", headers=eh,
                   data={"event_type": "EXIT"}, files=frames)
        d = r.json().get("data") or {}
        check("AS-L4 optional EXIT records check_out",
              r.status_code == 200 and d.get("check_out"), f"status={r.status_code} check_out={d.get('check_out')}")

        # AS-L5 — duplicate ENTRY blocked (cooldown / sequence)
        r = c.post(f"{BACKEND}/attendance/selfie-checkin", headers=eh,
                   data={"event_type": "ENTRY"}, files=frames)
        err = r.json().get("error", "").lower()
        check("AS-L5 duplicate ENTRY blocked",
              r.status_code == 422 and ("cooldown" in err or "sequence" in err), f"status={r.status_code} err={err}")

        # AS-L6 — flag & audit: an audit_logs row exists for this selfie event
        logs = c.get(f"{BACKEND}/system/audit-logs",
                     headers=ah, params={"table_name": "attendance_events", "per_page": 100}).json()["data"]
        mine = [l for l in logs if (l.get("after_value") or {}).get("method") == "selfie"
                and str(l.get("performed_by_id")) == str(emp_id)]
        sample = mine[0]["after_value"] if mine else {}
        check("AS-L6 flag&audit row written",
              len(mine) >= 1 and "from_office_lan" in sample and "similarity" in sample,
              f"rows={len(mine)} sample={sample}")
    finally:
        # Self-clean: soft-delete the throwaway employee.
        c.request("DELETE", f"{BACKEND}/employees/{emp_id}", headers=ah)

    print(f"\nALL SELFIE LIVENESS AUDITS PASSED ({len(passed)}/7)")


if __name__ == "__main__":
    main()
