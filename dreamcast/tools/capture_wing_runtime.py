#!/usr/bin/env python3
"""Capture proof-only SM1 renders of normally transparent wing geometry.

SM1 does not ship with visible wings: its production texture is the magenta,
zero-alpha paint-out. This diagnostic variant makes the retained geometry
visible only to audit seams, UVs, winding, and animation ownership. Visible
production wings belong to SM2 and are captured by capture_sm2_default_runtime.

Input is injected only through the recompilation's process-local controller
script.  This tool never generates host keyboard, mouse, or window input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXE = ROOT / "spiderman" / "port" / "bin" / "Release" / "net10.0" / "SpiderMan.exe"
DEFAULT_ASSETS = ROOT / "dreamcast" / "converted" / "sm1-winged-runtime"
DEFAULT_OUTPUT = DEFAULT_ASSETS / "runtime-wing-seam-proof"
SHOTS = (4000, 4050, 4100, 4150, 4200, 4300, 4400, 4500, 4600, 4700, 4800, 4900, 5000)
EXIT_FRAME = 5050
INPUT_SCRIPT = (
    "title.bmr+120:start:12;title.bmr+420:cross:12;"
    "title.bmr+720:cross:12;title.bmr+1100:cross:12;"
    "title.bmr+1500:cross:12;title.bmr+1900:cross:12"
)
BOOT_SKIP_ANCHOR = "title.bmr"
PROOFS = {
    "proof_front_wings.png": (4100, (350, 1050, 1450, 1700)),
    "proof_rear_wings.png": (4150, (900, 700, 1900, 1530)),
    "proof_side_wings.png": (4800, (850, 700, 1900, 1700)),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--render-scale",
        type=int,
        default=8,
        help="internal 320x240 raster scale; 8 yields 2560x1920 proof frames",
    )
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument(
        "--reuse-captures",
        action="store_true",
        help="validate and recrop existing native frames without launching the game",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(exe: Path, assets: Path, output: Path, scale: int, timeout: int) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("SPIDEY_")}
    env.pop("RECOMP_RENDER_SCALE", None)
    env.update(
        {
            "RECOMP_RENDER_SCALE": str(scale),
            "SPIDEY_ASSET_DIR": str(assets),
            "SPIDEY_BOOT_SKIP_UNTIL": BOOT_SKIP_ANCHOR,
            "SPIDEY_LEVEL": "l1a1",
            "SPIDEY_HZ": "60",
            "SPIDEY_SCRIPT": INPUT_SCRIPT,
            "SPIDEY_SHOTS": ",".join(map(str, SHOTS)),
            "SPIDEY_SHOT_DIR": str(output),
            "SPIDEY_EXIT": str(EXIT_FRAME),
            "SPIDEY_LOG_DIR": str(output),
            "SPIDEY_STALL_EXIT": "1",
            "SPIDEY_TRACE_GAME": "1",
            "SPIDEY_TRACE_WAD": "1",
        }
    )
    result = subprocess.run(
        [str(exe)],
        cwd=exe.parent,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    console = result.stdout or ""
    (output / "console.log").write_text(console, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"game exited {result.returncode}; see {output / 'console.log'}")
    if f"[capture] exit at frame {EXIT_FRAME}" not in console:
        raise RuntimeError(f"game did not record the requested clean exit at frame {EXIT_FRAME}")
    return console


def validate_frame(path: Path, expected_size: tuple[int, int]) -> dict[str, object]:
    with Image.open(path) as image:
        image.load()
        if image.format != "PNG":
            raise RuntimeError(f"not a PNG: {path}")
        size = image.size
    if size != expected_size:
        raise RuntimeError(f"unexpected capture size for {path}: {size}, expected {expected_size}")
    return {"path": str(path.resolve()), "size": list(size), "sha256": sha256(path)}


def main() -> None:
    args = parse_args()
    exe = args.exe.resolve()
    assets = args.assets.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.render_scale < 1 or args.render_scale > 8:
        raise ValueError("--render-scale must be between 1 and 8")
    if not args.reuse_captures:
        console = capture(exe, assets, output, args.render_scale, args.timeout)
        for required in ("spidey.psx", "sp_tex00.psx"):
            if f"override {required}:" not in console.casefold():
                raise RuntimeError(f"runtime did not load the loose {required} override")

    # This level presents a 320x240 display after the runtime's 4:3 aspect
    # correction.  The prior 640x480 multiplier accidentally described scale
    # 8 while reporting scale 4, and rejected correctly captured frames.
    expected_size = (320 * args.render_scale, 240 * args.render_scale)
    frames = {
        str(frame): validate_frame(output / f"frame_{frame:05d}.png", expected_size)
        for frame in SHOTS
    }
    proofs: dict[str, dict[str, object]] = {}
    crop_scale = args.render_scale / 8.0
    for name, (frame, canonical_box) in PROOFS.items():
        box = tuple(round(value * crop_scale) for value in canonical_box)
        source = output / f"frame_{frame:05d}.png"
        destination = output / name
        with Image.open(source) as image:
            crop = image.crop(box)
            crop.save(destination)
        proofs[name] = {
            "path": str(destination.resolve()),
            "sourceFrame": frame,
            "crop": list(box),
            "size": list(crop.size),
            "sha256": sha256(destination),
        }

    report = {
        "schemaVersion": 1,
        "inputMethod": "process-local SPIDEY_SCRIPT controller state",
        "level": "l1a1",
        "assets": str(assets),
        "renderScale": args.render_scale,
        "nativeFrameCount": len(frames),
        "frames": frames,
        "authoredProofs": proofs,
    }
    report_path = output / "wing-runtime-proof.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"PASS: {len(frames)} native in-game frames at {expected_size[0]}x{expected_size[1]}; "
        f"{len(proofs)} exact close-up crops"
    )
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
