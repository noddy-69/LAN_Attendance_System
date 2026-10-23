#!/usr/bin/env python3
"""
convert-minifasnet.py -- convert Silent-Face MiniFASNet PyTorch weights (.pth) to
the ONNX files the face service expects for passive liveness / anti-spoofing.

WHY this needs the upstream repo
--------------------------------
The .pth files are *state dicts* -- just the trained weights, not the network
architecture. To export them to ONNX we must first load them into the matching
MiniFASNet nn.Module classes, which live in the third-party
Silent-Face-Anti-Spoofing project (Apache-2.0). This script imports those classes
from your local clone of that repo so the architecture always matches the weights
exactly -- we don't reproduce (and risk mismatching) the model code here.

ONE-TIME SETUP (on your build machine, not the server)
------------------------------------------------------
  pip install torch onnx
  git clone https://github.com/minivision-ai/Silent-Face-Anti-Spoofing
  # the two pretrained .pth files ship in:
  #   Silent-Face-Anti-Spoofing/resources/anti_spoof_models/
  #     2.7_80x80_MiniFASNetV2.pth
  #     4_0_0_80x80_MiniFASNetV1SE.pth

USAGE
-----
  python vendor/convert-minifasnet.py --repo /path/to/Silent-Face-Anti-Spoofing
  # writes 2.7_80x80_MiniFASNetV2.onnx and 4.0_80x80_MiniFASNetV1SE.onnx into
  # ./models/antispoof (the dir bind-mounted into the face service)

The output filenames use the <scale>_<h>x<w>_<Type>.onnx convention that
face-service/src/antispoof.py parses. Preprocessing matches the service: BGR crop,
NCHW, divided by 255 (no mean/std), 3-class output (class 1 = "real").
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import OrderedDict

# Make stdout UTF-8 so PyTorch's exporter progress prints (which include emoji)
# don't crash on the Windows cp1252 console.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass


def get_kernel(h: int, w: int) -> tuple[int, int]:
    """Silent-Face conv6 kernel size for a given input crop (80x80 -> (5, 5))."""
    return (h + 15) // 16, (w + 15) // 16


def parse_model_name(filename: str):
    """
    Parse '2.7_80x80_MiniFASNetV2.pth' or '4_0_0_80x80_MiniFASNetV1SE.pth'
    -> (h, w, model_type, scale). scale is None for 'org_*' models.
    """
    stem = filename
    for ext in (".pth", ".pth.tar"):
        if stem.endswith(ext):
            stem = stem[: -len(ext)]
            break
    parts = stem.split("_")
    # input size is the token of the form HxW
    hw = next((p for p in parts if re.fullmatch(r"\d+x\d+", p)), None)
    if hw is None:
        raise ValueError(f"Cannot find HxW input size in '{filename}'")
    h, w = (int(x) for x in hw.split("x"))
    model_type = parts[-1]
    scale = None if parts[0] == "org" else float(parts[0])
    return h, w, model_type, scale


def main() -> int:
    ap = argparse.ArgumentParser(description="Convert MiniFASNet .pth weights to ONNX.")
    ap.add_argument("--repo", required=True,
                    help="Path to a clone of minivision-ai/Silent-Face-Anti-Spoofing")
    ap.add_argument("--weights", default=None,
                    help="Folder with the .pth files (default: <repo>/resources/anti_spoof_models)")
    ap.add_argument("--out", default=None,
                    help="Output folder (default: <project>/models/antispoof)")
    ap.add_argument("--opset", type=int, default=11)
    args = ap.parse_args()

    try:
        import torch
    except ImportError:
        print("ERROR: PyTorch is not installed. Run:  pip install torch onnx", file=sys.stderr)
        return 2

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        print(f"ERROR: --repo not found: {repo}", file=sys.stderr)
        return 2
    sys.path.insert(0, repo)

    # Import the architecture classes straight from the upstream repo.
    try:
        from src.model_lib.MiniFASNet import (  # type: ignore
            MiniFASNetV1, MiniFASNetV2, MiniFASNetV1SE, MiniFASNetV2SE,
        )
    except Exception as exc:  # pragma: no cover - depends on the user's clone
        print(
            "ERROR: could not import MiniFASNet classes from the repo "
            f"(src/model_lib/MiniFASNet.py). Is --repo a correct clone?\n  {exc}",
            file=sys.stderr,
        )
        return 2

    MODEL_MAPPING = {
        "MiniFASNetV1": MiniFASNetV1,
        "MiniFASNetV2": MiniFASNetV2,
        "MiniFASNetV1SE": MiniFASNetV1SE,
        "MiniFASNetV2SE": MiniFASNetV2SE,
    }

    weights_dir = args.weights or os.path.join(repo, "resources", "anti_spoof_models")
    if not os.path.isdir(weights_dir):
        print(f"ERROR: weights folder not found: {weights_dir}", file=sys.stderr)
        return 2

    # Default output: ./models/antispoof relative to the project root (parent of vendor/).
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = args.out or os.path.join(project_root, "models", "antispoof")
    os.makedirs(out_dir, exist_ok=True)

    pth_files = [f for f in sorted(os.listdir(weights_dir)) if f.endswith(".pth")]
    if not pth_files:
        print(f"ERROR: no .pth files in {weights_dir}", file=sys.stderr)
        return 2

    converted = 0
    for fname in pth_files:
        try:
            h, w, model_type, scale = parse_model_name(fname)
        except ValueError as exc:
            print(f"[skip] {fname}: {exc}")
            continue
        if scale is None:
            print(f"[skip] {fname}: 'org' model has no scale (not used by this service)")
            continue
        if model_type not in MODEL_MAPPING:
            print(f"[skip] {fname}: unknown model type '{model_type}'")
            continue

        model = MODEL_MAPPING[model_type](conv6_kernel=get_kernel(h, w))
        state = torch.load(os.path.join(weights_dir, fname), map_location="cpu")
        # Strip a DataParallel 'module.' prefix if present.
        first = next(iter(state))
        if first.startswith("module."):
            state = OrderedDict((k[7:], v) for k, v in state.items())
        model.load_state_dict(state)
        model.eval()

        # Output name in the <scale>_<h>x<w>_<Type>.onnx form the loader parses.
        out_name = f"{scale}_{h}x{w}_{model_type}.onnx"
        out_path = os.path.join(out_dir, out_name)
        dummy = torch.randn(1, 3, h, w)
        torch.onnx.export(
            model, dummy, out_path,
            input_names=["input"], output_names=["output"],
            opset_version=args.opset,
            dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
        )

        # Fold any external weight file (.onnx.data, produced by the newer exporter)
        # back into a single self-contained .onnx so each model is ONE file to ship.
        try:
            import onnx
            _m = onnx.load(out_path)
            onnx.save_model(_m, out_path, save_as_external_data=False)
            _data = out_path + ".data"
            if os.path.exists(_data):
                os.remove(_data)
        except Exception as _e:
            print(f"[warn] could not inline weights for {out_name}: {_e}")

        print(f"[ok]   {fname}  ->  {out_name}")
        converted += 1

    print(f"\nConverted {converted} model(s) into {out_dir}")
    if converted:
        print("Restart the face service to load them:  docker compose restart face-recognition")
        print("Verify: a selfie check-in's /verify-selfie then reports antispoof_active=true.")
    return 0 if converted else 1


if __name__ == "__main__":
    raise SystemExit(main())
