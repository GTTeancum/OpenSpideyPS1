#!/usr/bin/env python3
"""Capture the native SM2 Default-suit Dreamcast actor and close wing proofs.

The game receives input only through its process-local controller harness.  Shot
timing is anchored to archive loads, so menu and gameplay proof poses remain
stable when wall-clock pacing shifts their absolute frame numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXE = ROOT / "spiderman2" / "port" / "bin" / "Release" / "net10.0" / "SpiderMan2.exe"
DEFAULT_ASSETS = (
    ROOT / "dreamcast" / "converted" / "sm2-costume-tests" / "runtime" / "default"
)
DEFAULT_OUTPUT = DEFAULT_ASSETS / "runtime-wing-proof"
INPUT_SCRIPT = (
    "title.bmr+80:start:10;title.bmr+280:cross:10;"
    "title.bmr+480:cross:10;title.bmr+700:cross:10;"
    "e1m0_t.trg+1200:cross:8;e1m0_t.trg+1500:cross:8;"
    "e1m0_t.trg+1800:cross:8"
)
SHOT_SPECS = (
    ("menu", "title.bmr", 450),
    ("gameplay_motion", "e1m0_t.trg", 1568),
    ("gameplay_deployed", "e1m0_t.trg", 1968),
)
EXIT_FRAME = 6000

# Canonical scale-8 display-aspect coordinates.  Cropping never modifies source
# pixels; these proofs retain the native 2560x1920 capture density.
PROOF_SPECS = (
    (
        "sm2_default_menu_wings_close.png",
        "menu",
        (800, 500, 1900, 1250),
        "main-menu front upper body",
    ),
    (
        "sm2_default_gameplay_wings_close.png",
        "gameplay_deployed",
        (940, 600, 1720, 1240),
        "in-game animated rear upper body",
    ),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--render-scale", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument(
        "--reuse-captures",
        action="store_true",
        help="validate and reauthor an existing run without launching the game",
    )
    return parser.parse_args()


def ensure_no_game_process() -> None:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq SpiderMan2.exe", "/FO", "CSV", "/NH"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode == 0 and re.search(r'"SpiderMan2\.exe"', result.stdout, re.IGNORECASE):
        raise RuntimeError("refusing to launch while another SpiderMan2.exe process exists")


def run_game(exe: Path, assets: Path, output: Path, scale: int, timeout: int) -> str:
    ensure_no_game_process()
    for capture in output.glob("frame_*.png"):
        capture.unlink()
    env = {key: value for key, value in os.environ.items() if not key.startswith("SPIDEY_")}
    env.pop("RECOMP_RENDER_SCALE", None)
    env.update(
        {
            "RECOMP_RENDER_SCALE": str(scale),
            "RECOMP_VALIDATE_MODEL_GEOMETRY": "1",
            "SPIDEY_ASSET_DIR": str(assets),
            "SPIDEY_HZ": "60",
            "SPIDEY_SCRIPT": INPUT_SCRIPT,
            "SPIDEY_SHOTS": ",".join(
                f"{anchor}+{offset}" for _, anchor, offset in SHOT_SPECS
            ),
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
    return console


def resolved_frames(console: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for label, anchor, offset in SHOT_SPECS:
        pattern = re.compile(
            rf"\[capture\] '{re.escape(anchor)}' load #\d+ at frame (\d+): "
            rf"shot resolved to frame (\d+)"
        )
        candidates = [
            (int(load_frame), int(shot_frame))
            for load_frame, shot_frame in pattern.findall(console)
        ]
        expected = [shot for load, shot in candidates if shot - load == offset]
        if len(expected) != 1:
            raise RuntimeError(
                f"expected one resolved {label} shot for {anchor}+{offset}, found {candidates}"
            )
        result[label] = expected[0]
    return result


def validate_frame(path: Path, expected_size: tuple[int, int]) -> dict[str, Any]:
    with Image.open(path) as image:
        image.load()
        if image.size != expected_size:
            raise RuntimeError(f"{path} is {image.size}, expected {expected_size}")
        extrema = image.convert("RGB").getextrema()
    dynamic_range = max(high - low for low, high in extrema)
    if dynamic_range < 32:
        raise RuntimeError(f"{path} is not a rendered game frame (range={dynamic_range})")
    return {
        "path": str(path.resolve()),
        "size": list(expected_size),
        "dynamicRange": dynamic_range,
        "sha256": sha256(path),
    }


def main() -> None:
    args = parse_args()
    if args.render_scale < 1 or args.render_scale > 8:
        raise ValueError("--render-scale must be between 1 and 8")
    exe = args.exe.resolve()
    assets = args.assets.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.reuse_captures:
        console = (output / "console.log").read_text(encoding="utf-8")
    else:
        console = run_game(exe, assets, output, args.render_scale, args.timeout)

    model_bytes = (assets / "spidey.psx").stat().st_size
    texture_bytes = (assets / "sp_tex00.psx").stat().st_size
    required_markers = {
        "modelOverride": bool(
            re.search(
                rf"\[loose-wad\] override spidey\.psx: {model_bytes} bytes",
                console,
                re.IGNORECASE,
            )
        ),
        "textureOverride": bool(
            re.search(
                rf"\[loose-wad\] override sp_tex00\.psx: {texture_bytes} bytes",
                console,
                re.IGNORECASE,
            )
        ),
        "cleanExit": f"[capture] exit at frame {EXIT_FRAME}" in console,
    }
    if not all(required_markers.values()):
        raise RuntimeError(f"runtime markers failed: {required_markers}")

    frames = resolved_frames(console)
    expected_size = (320 * args.render_scale, 240 * args.render_scale)
    frame_records = {
        label: validate_frame(output / f"frame_{frame:05d}.png", expected_size)
        for label, frame in frames.items()
    }

    scale = args.render_scale / 8.0
    proofs: dict[str, dict[str, Any]] = {}
    for name, source_label, canonical_crop, view in PROOF_SPECS:
        crop = tuple(round(value * scale) for value in canonical_crop)
        source = output / f"frame_{frames[source_label]:05d}.png"
        destination = output / name
        with Image.open(source) as image:
            closeup = image.crop(crop)
            closeup.save(destination, format="PNG", optimize=False)
        proofs[name] = {
            "view": view,
            "path": str(destination.resolve()),
            "sourceFrame": frames[source_label],
            "cropLeftTopRightBottom": list(crop),
            "pixelPolicy": "native capture crop; no scaling or filtering",
            "size": list(closeup.size),
            "sha256": sha256(destination),
        }

    report = {
        "schemaVersion": 1,
        "status": "pass",
        "inputMethod": "process-local SPIDEY_SCRIPT controller state",
        "shotTiming": "archive-anchored SPIDEY_SHOTS",
        "assets": str(assets),
        "renderScale": args.render_scale,
        "runtimeMarkers": required_markers,
        "frames": frame_records,
        "authoredProofs": proofs,
    }
    report_path = output / "runtime-validation.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"PASS: native SM2 Default DC actor at {expected_size[0]}x{expected_size[1]}; "
        f"{len(proofs)} exact close-up wing proofs"
    )
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
