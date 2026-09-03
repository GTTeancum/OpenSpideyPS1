#!/usr/bin/env python3
"""Prove all twenty SM1 costumes through the live COSTUME VIEWER.

The route and every menu input are injected inside the recompiled game process.
The validator refuses to start if SpiderMan.exe is already running and launches
exactly one instance for the complete roster.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXE = ROOT / "spiderman" / "port" / "bin" / "Release" / "net10.0" / "SpiderMan.exe"
DEFAULT_BATCH = ROOT / "dreamcast" / "converted" / "all-characters"
DEFAULT_OUTPUT = ROOT / "proof_render" / "costume-system" / "viewer-all20"

ROSTER = (
    ("Spider-Man", "spidey.psx"),
    ("Spider-Man 2099", "sp2099.psx"),
    ("Symbiote Spider-Man", "spsymbi.psx"),
    ("Captain Universe", "spuniv.psx"),
    ("Spidey Unlimited", "spunlim.psx"),
    ("Amazing Bag Man", "spbagman.psx"),
    ("Scarlet Spidey", "spscar.psx"),
    ("Ben Reilly", "spreilly.psx"),
    ("Quick Change Spidey", "spquick.psx"),
    ("Peter Parker", "sppark.psx"),
    ("Spider-Phoenix", "sp2phoenix.psx"),
    ("Prodigy", "sp2prodigy.psx"),
    ("Dusk", "sp2dusk.psx"),
    ("Insulated Spider-Man", "sp2insulated.psx"),
    ("Alex Ross Spider-Man", "sp2rossred.psx"),
    ("Alex Ross White Spider-Man", "sp2rosswhite.psx"),
    ("Venom Earth-X", "sp2venomx.psx"),
    ("Negative Zone Spider-Man", "sp2negative.psx"),
    ("Battle-Damaged Spider-Man", "sp2battle.psx"),
    ("Spider-Man (Web Wings)", "sp2default.psx"),
)

ROUTE = (
    "title.bmr+120:start:12",
    "title.bmr+300:right:12",
    "title.bmr+500:down:12",
    "title.bmr+700:down:12",
    "title.bmr+900:cross:12",
    "title.bmr+1200:cross:12",
)
FIRST_CAPTURE = 1450
FIRST_ADVANCE = 1600
STEP_INTERVAL = 500
CROSS_DELAY = 150
POST_SELECT_CAPTURE = 350


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=600)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_script() -> str:
    steps = list(ROUTE)
    for index in range(1, len(ROSTER)):
        advance = FIRST_ADVANCE + (index - 1) * STEP_INTERVAL
        steps.append(f"title.bmr+{advance}:down:12")
        steps.append(f"title.bmr+{advance + CROSS_DELAY}:cross:12")
    return ";".join(steps)


def shot_offsets() -> list[int]:
    return [FIRST_CAPTURE] + [
        FIRST_ADVANCE + (index - 1) * STEP_INTERVAL + POST_SELECT_CAPTURE
        for index in range(1, len(ROSTER))
    ]


def ensure_one_process() -> None:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq SpiderMan.exe", "/FO", "CSV", "/NH"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode == 0 and re.search(r'"SpiderMan\.exe"', result.stdout, re.I):
        raise RuntimeError("refusing to launch while another SpiderMan.exe process exists")


def verify_capture(path: Path) -> dict[str, Any]:
    with Image.open(path) as opened:
        opened.load()
        image = opened.convert("RGB")
        extrema = image.getextrema()
        colors = image.getcolors(maxcolors=image.width * image.height)
    if image.size != (1280, 960):
        raise ValueError(f"unexpected capture size {image.size}: {path}")
    dynamic_range = max(high - low for low, high in extrema)
    color_count = len(colors) if colors is not None else image.width * image.height
    if dynamic_range < 32 or color_count < 64:
        raise ValueError(
            f"capture is not a reviewable rendered frame "
            f"(range={dynamic_range}, colors={color_count}): {path}"
        )
    return {
        "size": list(image.size),
        "dynamicRange": dynamic_range,
        "colorCount": color_count,
        "sha256": sha256(path),
    }


def main() -> None:
    args = parse_args()
    exe = args.exe.resolve()
    batch = args.batch.resolve()
    output = args.output.resolve()
    if not exe.is_file():
        raise FileNotFoundError(exe)
    for _, model in ROSTER:
        if not (batch / model).is_file():
            raise FileNotFoundError(batch / model)

    ensure_one_process()
    output.mkdir(parents=True, exist_ok=True)
    for pattern in ("frame_*.png", "costume_*.png"):
        for old in output.glob(pattern):
            old.unlink()

    offsets = shot_offsets()
    exit_offset = offsets[-1] + 250
    env = {key: value for key, value in os.environ.items() if not key.startswith("SPIDEY_")}
    env.pop("RECOMP_RENDER_SCALE", None)
    env.update(
        {
            "RECOMP_RENDER_SCALE": "4",
            "SPIDEY_ASSET_DIR": str(batch),
            "SPIDEY_BOOT_SKIP_UNTIL": "title.bmr",
            "SPIDEY_CHEATS": "everything,viewers",
            "SPIDEY_HZ": "60",
            "SPIDEY_SCRIPT": build_script(),
            "SPIDEY_SHOTS": ",".join(f"title.bmr+{offset}" for offset in offsets),
            "SPIDEY_SHOT_DIR": str(output),
            "SPIDEY_EXIT": f"title.bmr+{exit_offset}",
            "SPIDEY_LOG_DIR": str(output),
            "SPIDEY_STALL_EXIT": "1",
            "SPIDEY_TRACE_WAD": "1",
        }
    )
    pack_root = batch / "packs"
    if pack_root.is_dir():
        env["RECOMP_ASSET_PACK_DIR"] = str(pack_root)

    try:
        result = subprocess.run(
            [str(exe)],
            cwd=exe.parent,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=args.timeout,
            check=False,
        )
        console = result.stdout or ""
        return_code: int | None = result.returncode
        timed_out = False
    except subprocess.TimeoutExpired as error:
        console = (
            error.stdout
            if isinstance(error.stdout, str)
            else (error.stdout or b"").decode(errors="replace")
        )
        return_code = None
        timed_out = True
    (output / "console.log").write_text(console, encoding="utf-8")

    reloads = re.findall(
        r"\[costume\] viewer actor reload slot (\d+): ([^\r\n]+\.psx)",
        console,
        re.I,
    )
    initially_loaded = [
        model.lower()
        for model in re.findall(
            r"\[costume\] viewer actor already loaded: ([^\r\n]+\.psx)",
            console,
            re.I,
        )
    ]
    actual_models = [model.lower() for _, model in reloads]
    expected_initial = ROSTER[0][1].lower()
    expected_models = [model.lower() for _, model in ROSTER[1:]]
    slots = [int(slot) for slot, _ in reloads]

    resolved_frames: list[int] = []
    capture_errors: list[str] = []
    captures: list[dict[str, Any]] = []
    resolved = [
        int(frame)
        for frame in re.findall(
            r"\[capture\] 'title\.bmr' at frame \d+: archive shot resolved to frame (\d+)",
            console,
            re.I,
        )
    ]
    if len(resolved) != len(ROSTER):
        capture_errors.append(
            f"expected {len(ROSTER)} title-anchored shots, found {len(resolved)}"
        )
    else:
        resolved_frames = resolved

    for index, (display_name, model) in enumerate(ROSTER):
        try:
            if index >= len(resolved_frames) or resolved_frames[index] < 0:
                raise ValueError("shot anchor did not resolve")
            source = output / f"frame_{resolved_frames[index]:05d}.png"
            metrics = verify_capture(source)
            proof = output / f"costume_{index:02d}_{Path(model).stem}.png"
            shutil.copy2(source, proof)
            captures.append(
                {
                    "index": index,
                    "displayName": display_name,
                    "model": model,
                    "asset": str(batch / model),
                    "assetSha256": sha256(batch / model),
                    "frame": resolved_frames[index],
                    "path": str(proof),
                    **metrics,
                }
            )
        except Exception as error:
            capture_errors.append(f"{index:02d} {display_name}: {error}")

    bad_markers = [
        marker for marker in (
            "Unhandled exception",
            "watchdog: STALLED",
            "MISSED -- overlay not resident",
            "costume viewer model slot moved",
        ) if marker.lower() in console.lower()
    ]
    clean_exit = f"[capture] exit at frame" in console
    initial_resident = initially_loaded == [expected_initial]
    same_slot = len(slots) == len(ROSTER) - 1 and len(set(slots)) == 1
    status = (
        "pass"
        if not timed_out
        and return_code == 0
        and clean_exit
        and not bad_markers
        and initial_resident
        and actual_models == expected_models
        and same_slot
        and not capture_errors
        and len(captures) == len(ROSTER)
        else "fail"
    )
    report = {
        "schemaVersion": 1,
        "status": status,
        "inputMethod": "process-local SPIDEY_SCRIPT controller state",
        "gameProcessCount": 1,
        "processPolicy": "one SpiderMan.exe for the complete twenty-entry run",
        "viewerTransition": "unload/reload stable spidey cache slot; no retail texture-only overlay",
        "rosterCount": len(ROSTER),
        "initialResidentModel": initially_loaded[0] if initial_resident else None,
        "reloadCount": len(reloads),
        "reloadModels": actual_models,
        "stableCacheSlot": slots[0] if same_slot else None,
        "captureCount": len(captures),
        "captureErrors": capture_errors,
        "badMarkers": bad_markers,
        "returnCode": return_code,
        "timedOut": timed_out,
        "cleanExit": clean_exit,
        "captures": captures,
        "consoleLog": str(output / "console.log"),
    }
    report_path = output / "runtime-validation.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"{status.upper()}: {len(reloads)}/{len(ROSTER) - 1} stable-slot model reloads "
        f"after the resident initial actor; "
        f"{len(captures)}/{len(ROSTER)} native captures"
    )
    if not initial_resident:
        print(f"expected resident initial actor: {expected_initial}")
        print("actual resident actors: " + ", ".join(initially_loaded))
    if actual_models != expected_models:
        print("expected reloads: " + ", ".join(expected_models))
        print("actual reloads:   " + ", ".join(actual_models))
    for error in capture_errors:
        print("capture failure: " + error)
    print(f"report: {report_path}")
    if status != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
