#!/usr/bin/env python3
"""Exercise every SM1 costume slot with its dedicated Dreamcast actor at runtime.

The harness uses only process-local controller state and the recompilation's native
GPU capture path.  It never sends keyboard, mouse, or controller input to Windows.

The default proof stops at the main menu, where the active costume is already rendered
large in 3D.  Gameplay mode remains available for defects that require player motion.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXE = ROOT / "spiderman" / "port" / "bin" / "Release" / "net10.0" / "SpiderMan.exe"
DEFAULT_BATCH = ROOT / "dreamcast" / "converted" / "all-characters"
DEFAULT_OUTPUT = ROOT / "dreamcast" / "converted" / "all-characters-costumes-runtime-current"
GAMEPLAY_INPUT_SCRIPT = (
    "title.bmr+120:start:12;title.bmr+420:cross:12;"
    "title.bmr+720:cross:12;title.bmr+1100:cross:12;"
    "title.bmr+1500:cross:12;title.bmr+1900:cross:12"
)
MENU_INPUT_SCRIPT = "title.bmr+120:start:12"
PROOF_DEFAULTS = {
    "menu": {
        "shots": "2450,2600,2750,2900,3050,3200,3350",
        "exitFrame": 3400,
        "inputScript": MENU_INPUT_SCRIPT,
    },
    "gameplay": {
        "shots": "4300,4400",
        "exitFrame": 4450,
        "inputScript": GAMEPLAY_INPUT_SCRIPT,
    },
}
COSTUMES = (
    ("spiderman", "spidey.psx"),
    ("2099", "sp2099.psx"),
    ("symbiote", "spsymbi.psx"),
    ("captain", "spuniv.psx"),
    ("unlimited", "spunlim.psx"),
    ("bagman", "spbagman.psx"),
    ("scarlet", "spscar.psx"),
    ("benreilly", "spreilly.psx"),
    ("quickchange", "spquick.psx"),
    ("peterparker", "sppark.psx"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--level", default="l1a1")
    parser.add_argument(
        "--slots",
        default="0,1,2,3,4,5,6,7,8,9",
        help="comma-separated costume slots to test",
    )
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--render-scale", type=int, default=2)
    parser.add_argument(
        "--proof-mode",
        choices=tuple(PROOF_DEFAULTS),
        default="menu",
        help="menu is the fast stable 3D costume proof; gameplay tests player motion",
    )
    parser.add_argument("--shots", help="capture frames (defaults depend on --proof-mode)")
    parser.add_argument("--exit-frame", type=int, help="exit frame (defaults depend on --proof-mode)")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument(
        "--dump-textures",
        action="store_true",
        help="dump complete texture uploads for host-GPU replacement-pack authoring",
    )
    return parser.parse_args()


def verify_capture(path: Path, expected_size: tuple[int, int]) -> dict[str, Any]:
    with Image.open(path) as image:
        image.load()
        if image.size != expected_size:
            raise ValueError(f"{path} is {image.size}, expected {expected_size}")
        rgb = image.convert("RGB")
        extrema = rgb.getextrema()
        colors = rgb.getcolors(maxcolors=expected_size[0] * expected_size[1])
    dynamic_range = max(channel[1] - channel[0] for channel in extrema)
    color_count = len(colors) if colors is not None else expected_size[0] * expected_size[1]
    if dynamic_range < 32 or color_count < 64:
        raise ValueError(
            f"{path} does not resemble a rendered game frame "
            f"(range={dynamic_range}, colors={color_count})"
        )
    return {
        "size": list(expected_size),
        "dynamicRange": dynamic_range,
        "colorCount": color_count,
    }


def run_costume(
    slot: int,
    name: str,
    model: str,
    exe: Path,
    batch: Path,
    output: Path,
    level: str | None,
    proof_mode: str,
    input_script: str,
    render_scale: int,
    shots: str,
    exit_frame: int,
    timeout: int,
    dump_textures: bool,
) -> dict[str, Any]:
    costume_dir = output / f"{slot:02d}-{name}"
    costume_dir.mkdir(parents=True, exist_ok=True)
    for old_capture in costume_dir.glob("frame_*.png"):
        old_capture.unlink()

    env = {key: value for key, value in os.environ.items() if not key.startswith("SPIDEY_")}
    env.pop("RECOMP_RENDER_SCALE", None)
    env.update(
        {
            "RECOMP_RENDER_SCALE": str(render_scale),
            "SPIDEY_ASSET_DIR": str(batch),
            "SPIDEY_COSTUME": str(slot),
            "SPIDEY_HZ": "60",
            "SPIDEY_SCRIPT": input_script,
            "SPIDEY_SHOTS": shots,
            "SPIDEY_SHOT_DIR": str(costume_dir),
            "SPIDEY_EXIT": str(exit_frame),
            "SPIDEY_LOG_DIR": str(costume_dir),
            "SPIDEY_STALL_EXIT": "1",
            "SPIDEY_TRACE_GAME": "1",
            "SPIDEY_TRACE_WAD": "1",
            "RECOMP_VALIDATE_MODEL_GEOMETRY": "1",
        }
    )
    if level is not None:
        env["SPIDEY_LEVEL"] = level
    if dump_textures:
        dump_root = costume_dir / "texture-dump"
        env["SPIDEY_DUMP_TEXTURES"] = "pages"
        env["RECOMP_TEXTURE_DUMP_DIR"] = str(dump_root)
    try:
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
        return_code: int | None = result.returncode
        timed_out = False
    except subprocess.TimeoutExpired as error:
        console = (
            (error.stdout or "")
            if isinstance(error.stdout, str)
            else (error.stdout or b"").decode(errors="replace")
        )
        return_code = None
        timed_out = True
    console_path = costume_dir / "console.log"
    console_path.write_text(console, encoding="utf-8")

    expected_texture = f"sp_tex{slot:02d}.psx"
    markers = {
        "selection": f"[costume] {name} (index {slot})" in console,
        "modelOverride": bool(
            re.search(
                rf"\[loose-wad\] override spidey\.psx(?: <- {re.escape(model)})?:",
                console,
                re.IGNORECASE,
            )
        ),
        "textureOverride": bool(
            re.search(
                rf"\[loose-wad\] override {re.escape(expected_texture)}:",
                console,
                re.IGNORECASE,
            )
        ),
        "cleanExit": f"[capture] exit at frame {exit_frame}" in console,
    }
    head_audits = [
        (int(invalid), int(span))
        for invalid, span in re.findall(
            r"\[model-head-audit\].*?invalid=(\d+).*?max-span=(\d+)",
            console,
        )
    ]
    markers["headGeometry"] = bool(head_audits) and all(
        invalid == 0 and span <= 80 for invalid, span in head_audits
    )
    if slot != 0:
        markers["modelAlias"] = (
            f"[costume] Dreamcast model spidey.psx <- {model}".lower() in console.lower()
        )

    expected_size = (320 * render_scale, 240 * render_scale)
    captures: dict[str, Any] = {}
    capture_error: str | None = None
    try:
        captures = {
            path.name: verify_capture(path, expected_size)
            for path in sorted(costume_dir.glob("frame_*.png"))
        }
        if len(captures) != len([shot for shot in shots.split(",") if shot.strip()]):
            raise ValueError(f"expected {shots} captures, found {sorted(captures)}")
    except (OSError, ValueError) as error:
        capture_error = str(error)

    bad_markers = [
        marker
        for marker in ("Unhandled exception", "watchdog: STALLED", "MISSED -- overlay not resident")
        if marker.lower() in console.lower()
    ]
    status = (
        "pass"
        if not timed_out
        and return_code == 0
        and all(markers.values())
        and captures
        and capture_error is None
        and not bad_markers
        else "fail"
    )
    return {
        "slot": slot,
        "costume": name,
        "dreamcastModel": model,
        "textureLibrary": expected_texture,
        "proofMode": proof_mode,
        "status": status,
        "returnCode": return_code,
        "timedOut": timed_out,
        "markers": markers,
        "headGeometryAudit": {
            "sampleCount": len(head_audits),
            "invalidFaceIndexCount": max((invalid for invalid, _ in head_audits), default=None),
            "maxFaceSpan": max((span for _, span in head_audits), default=None),
            "maxAllowedFaceSpan": 80,
        },
        "badMarkers": bad_markers,
        "captureError": capture_error,
        "captures": captures,
        "consoleLog": str(console_path),
    }


def main() -> None:
    args = parse_args()
    exe = args.exe.resolve()
    batch = args.batch.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.concurrency < 1:
        raise ValueError("--concurrency must be positive")
    slots = tuple(int(value.strip()) for value in args.slots.split(",") if value.strip())
    if not slots or any(slot < 0 or slot >= len(COSTUMES) for slot in slots):
        raise ValueError("--slots must select one or more values from 0 through 9")
    proof_defaults = PROOF_DEFAULTS[args.proof_mode]
    shots = args.shots or proof_defaults["shots"]
    exit_frame = args.exit_frame or proof_defaults["exitFrame"]
    input_script = proof_defaults["inputScript"]
    level = args.level if args.proof_mode == "gameplay" else None

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(
                run_costume,
                slot,
                name,
                model,
                exe,
                batch,
                output,
                level,
                args.proof_mode,
                input_script,
                args.render_scale,
                shots,
                exit_frame,
                args.timeout,
                args.dump_textures,
            ): (slot, name)
            for slot, (name, model) in enumerate(COSTUMES)
            if slot in slots
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(
                f"{result['status'].upper():4s} slot {result['slot']:02d} "
                f"{result['costume']:12s} -> {result['dreamcastModel']}"
            )

    results.sort(key=lambda item: item["slot"])
    passed = sum(result["status"] == "pass" for result in results)
    report = {
        "schemaVersion": 1,
        "batch": str(batch),
        "proofMode": args.proof_mode,
        "level": level,
        "inputMethod": "process-local SPIDEY_COSTUME and SPIDEY_SCRIPT",
        "inputScript": input_script,
        "environmentPolicy": "retail SM1 level and environment assets remain unchanged",
        "costumeCount": len(results),
        "passedCostumeCount": passed,
        "results": results,
        "status": "pass" if passed == len(slots) else "fail",
    }
    report_path = output / "runtime-validation.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{report['status'].upper()}: {passed}/{len(slots)} selected costume model slots")
    print(f"report: {report_path}")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
