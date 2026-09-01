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
import uuid

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
BOOT_SKIP_ANCHOR = "title.bmr"
SHOT_SPECS = (
    ("menu", "title.bmr", 450),
    ("gameplay_deployed", "e1m0_t.trg", 1968),
)
EXIT_FRAME = 6000

# Exact actor-free chrome from the authored 8x proof.  These regions positively
# identify the live 3D main menu and active gameplay UI; archive timing, output
# dimensions, and dynamic range are not accepted as substitutes.
MENU_REGION_SIGNATURES = {
    "continueLabel": {
        "bounds": (240, 200, 820, 470),
        "sha256": "4bb6b2f971303c044b26de5131fb64dce43dfbb9134ab12d40b47e01f48233e3",
    },
    "trainingLabel": {
        "bounds": (1750, 200, 2300, 470),
        "sha256": "218af4ab4f35ca1c7b4daa5bb90599b801f3c251024015b0e53a04d47f076549",
    },
    "optionsLabel": {
        "bounds": (300, 1470, 840, 1700),
        "sha256": "b95c398c11f9908e56e7f49d5592449feb75ebc9060279190edf2fb3feb02359",
    },
    "galleryLabel": {
        "bounds": (1760, 1470, 2280, 1700),
        "sha256": "7ceb07dad9087656150b3daa437efe44dc84fe10367ca730477bd465f8ff4436",
    },
}
GAMEPLAY_HUD_REGION_SIGNATURES = {
    "healthIcon": {
        "bounds": (40, 40, 300, 300),
        "sha256": "ced4752623615246be0bbd31d907d7ff9dce193c83524caec5a148a4f8f9f444",
    },
    "healthBar": {
        "bounds": (275, 155, 580, 250),
        "sha256": "afe7451cb967d745ba77a7bf5f65b4fe65374bf65668970e8b5c249925be4dab",
    },
    "webCounter": {
        "bounds": (190, 265, 600, 430),
        "sha256": "8b42359d884aca674552742476395c35e5f3de5e9a73c23c4c78a06503418ec8",
    },
    # The compass arrow rotates with player heading, so hashing its large bounding
    # box rejected genuine gameplay. The web-meter body is opaque, actor-free HUD
    # chrome and remains exact for this no-web-use capture route.
    "webMeterFrame": {
        "bounds": (105, 390, 220, 700),
        "sha256": "9cd6d2d37742c2e54085b285ea499c015fe39ce5878cc2c37ddb747f42adf57c",
    },
}

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


def run_game(
    exe: Path, assets: Path, output: Path, scale: int, timeout: int
) -> tuple[str, str]:
    ensure_no_game_process()
    for pattern in (
        "frame_*.png",
        "sm2_default_*_wings_close.png",
        "console.log",
        "spidey.log",
    ):
        for generated in output.glob(pattern):
            generated.unlink()
    run_token = uuid.uuid4().hex
    env = {key: value for key, value in os.environ.items() if not key.startswith("SPIDEY_")}
    env.pop("RECOMP_RENDER_SCALE", None)
    env.update(
        {
            "RECOMP_RENDER_SCALE": str(scale),
            "RECOMP_VALIDATE_MODEL_GEOMETRY": "1",
            "SPIDEY_ASSET_DIR": str(assets),
            "SPIDEY_BOOT_SKIP_UNTIL": BOOT_SKIP_ANCHOR,
            "SPIDEY_HZ": "60",
            "SPIDEY_RUN_TOKEN": run_token,
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
    return console, run_token


def run_token_from_console(console: str) -> str:
    matches = re.findall(r"\[capture\] run-token ([0-9a-f]{32})", console)
    if len(matches) != 1:
        raise RuntimeError(
            "runtime evidence predates the exclusive fresh-run gate; capture it again"
        )
    return matches[0]


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


def validate_exact_regions(
    path: Path,
    expected_regions: dict[str, dict[str, Any]],
    screen_name: str,
) -> list[dict[str, Any]]:
    with Image.open(path) as opened:
        opened.load()
        image = opened.convert("RGB")
        results = []
        for name, expected in expected_regions.items():
            bounds = expected["bounds"]
            actual = hashlib.sha256(image.crop(bounds).tobytes()).hexdigest()
            results.append(
                {
                    "name": name,
                    "bounds": list(bounds),
                    "sha256": actual,
                    "expectedSha256": expected["sha256"],
                    "matches": actual == expected["sha256"],
                }
            )
    mismatches = [result["name"] for result in results if not result["matches"]]
    if mismatches:
        raise RuntimeError(
            f"{path} is not the verified {screen_name}; exact regions mismatched at "
            + ", ".join(mismatches)
        )
    return results


def main() -> None:
    args = parse_args()
    if args.render_scale != 8:
        raise ValueError(
            "--render-scale must be 8; the authored proof uses exact 8x menu and HUD gates"
        )
    exe = args.exe.resolve()
    assets = args.assets.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.reuse_captures:
        console = (output / "console.log").read_text(encoding="utf-8")
        run_token = run_token_from_console(console)
    else:
        console, run_token = run_game(
            exe, assets, output, args.render_scale, args.timeout
        )

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
        "freshRunToken": (
            f"[capture] run-token {run_token}" in console
            and console.count("[capture] run-token ") == 1
        ),
        "bootSkipBoundary": (
            f"[capture] boot-skip completed at '{BOOT_SKIP_ANCHOR}' load" in console
        ),
    }
    if not all(required_markers.values()):
        raise RuntimeError(f"runtime markers failed: {required_markers}")

    frames = resolved_frames(console)
    expected_size = (320 * args.render_scale, 240 * args.render_scale)
    frame_records = {
        label: validate_frame(output / f"frame_{frame:05d}.png", expected_size)
        for label, frame in frames.items()
    }
    for label, frame in frames.items():
        frame_records[label]["native3d16BitMarker"] = bool(
            re.search(
                rf"\[capture\].*frame_{frame:05d}\.png \d+x\d+ "
                r"\(live-3d 16bpp display aspect\)",
                console,
            )
        )
        if not frame_records[label]["native3d16BitMarker"]:
            raise RuntimeError(
                f"{label} frame {frame} was not freshly captured from the native "
                "16-bit 3D path"
            )
    frame_records["menu"]["mainMenuSignature"] = validate_exact_regions(
        Path(frame_records["menu"]["path"]),
        MENU_REGION_SIGNATURES,
        "live 3D main menu",
    )
    frame_records["gameplay_deployed"]["gameplayHudSignature"] = validate_exact_regions(
        Path(frame_records["gameplay_deployed"]["path"]),
        GAMEPLAY_HUD_REGION_SIGNATURES,
        "active SM2 gameplay HUD",
    )

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
        "schemaVersion": 3,
        "status": "pass",
        "inputMethod": "process-local SPIDEY_SCRIPT controller state",
        "shotTiming": "archive-anchored SPIDEY_SHOTS",
        "assets": str(assets),
        "runToken": run_token,
        "renderScale": args.render_scale,
        "runtimeMarkers": required_markers,
        "captureGate": (
            "fresh per-process token, boot-skip boundary, native live-3D 16bpp "
            "readback, exact actor-free 8x main-menu chrome, and exact 8x active-"
            "gameplay HUD"
        ),
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
