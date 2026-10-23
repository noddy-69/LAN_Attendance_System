# Anti-spoofing (liveness) models

Drop **MiniFASNet ONNX** model files in this folder to enable **passive liveness**
(rejecting printed-photo / phone-screen attacks) on selfie check-in — and, when
`FACE_ANTISPOOF_ENABLED=true`, on the cameras too.

This folder is **bind-mounted** into the face-service container at
`/opt/insightface/antispoof` (see `docker-compose.yml`). The service loads **every
`*.onnx`** here at start-up and ensembles them.

## Expected files

The filename must encode the crop **scale** and **input size** as
`<scale>_<h>x<w>_<name>.onnx` (the loader parses this). The two complementary
80×80 models from the **Silent-Face / minivision** project are:

| Filename | Scale | Input |
|---|---|---|
| `2.7_80x80_MiniFASNetV2.onnx`   | 2.7 | 80×80 |
| `4.0_80x80_MiniFASNetV1SE.onnx` | 4.0 | 80×80 |

One model alone works; both ensembled is more robust.

## How to populate it

**Step 1 — get the two ONNX files.** They aren't bundled (third-party). Produce them
once from the official Silent-Face PyTorch weights with the vendor converter:

```bash
pip install torch onnx
git clone https://github.com/minivision-ai/Silent-Face-Anti-Spoofing
python vendor/convert-minifasnet.py --repo ./Silent-Face-Anti-Spoofing
# -> writes 2.7_80x80_MiniFASNetV2.onnx and 4.0_80x80_MiniFASNetV1SE.onnx into this folder
```

**Step 2 — (or) install ONNX files you already have**, then restart the face service:

```powershell
.\setup-antispoof.ps1 -FromDir "C:\path\to\onnx-models"     # Windows
```
```bash
./setup-antispoof.sh --from-dir /path/to/onnx-models        # Ubuntu
```

(`setup-antispoof` can also auto-download if you fill a trusted URL + SHA-256 in its
manifest. The converter already writes straight into this folder, so after running it
you only need `docker compose restart face-recognition`.)

## Delivery note

In a packaged delivery (`dist/`), these ONNX models are **already bundled** —
`vendor/package.ps1` copies them from the vendor store (`vendor/antispoof-models/`,
produced once by `vendor/convert-minifasnet.py`). This in-repo runtime folder is kept
**empty** on purpose so the automated test suite (which exercises the pipeline with stock
photos — which any real anti-spoof model correctly rejects) stays valid.

> **Acceptance test (do once with a real webcam):** because anti-spoofing can only be
> judged with a *live* camera, verify a genuine selfie is accepted after install. If real
> staff are wrongly rejected in poor light, lower `FACE_ANTISPOOF_THRESHOLD` or set
> `SELFIE_ANTISPOOF_ENABLED=false`.

## Notes

- The ONNX models are **third-party** and are **not bundled** with this software.
  Produce them with `vendor/convert-minifasnet.py` (above), or host your own verified
  copy and pin the URL + SHA-256 in the helper.
- **Empty folder = liveness fails open** for the passive check — but the **active
  head-movement liveness** on selfie check-in still applies regardless.
- After adding/removing files, restart the face service so it reloads:
  `docker compose restart face-recognition`.
- Verify it's active: a selfie check-in's `/verify-selfie` response then reports
  `"antispoof_active": true`.
