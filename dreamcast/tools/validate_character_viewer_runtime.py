#!/usr/bin/env python3
"""Exercise the complete SM1 Character Viewer roster with Dreamcast overrides.

Controller input is injected only through the recompilation's process-local
``SPIDEY_SCRIPT`` harness. The validator always launches exactly one game process.
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
import tempfile
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXE = ROOT / "spiderman" / "port" / "bin" / "Release" / "net10.0" / "SpiderMan.exe"
DEFAULT_BATCH = ROOT / "dreamcast" / "converted" / "all-characters"
DEFAULT_OUTPUT = ROOT / "dreamcast" / "converted" / "all-characters-viewer-runtime-current"

# Exact selectable order recovered from SM1's loose charbio.dat and confirmed by
# walking the menu to its lower bound. The fourth entry is the reformed Octavius
# suit, distinct from the later Doctor Octopus boss entry. charbio.dat also holds
# a J. James Jewett record, but the retail menu stops at Sub-Mariner and never
# exposes it as a selectable Character Viewer entry.
ROSTER = (
    ("Spider-Man", "spidey"),
    ("Peter Parker", "parker"),
    ("Black Cat", "blackcat"),
    ("Dr. Otto Octavius", "ock_suit"),
    ("Eddie Brock", "brock"),
    ("Henchman", "henchman"),
    ("Bank Thug", "thug"),
    ("J. Jonah Jameson", "jjviewer"),
    ("Scorpion", "scorpion"),
    ("Daredevil", "daredevl"),
    ("Policeman", "police"),
    ("SWAT Cop", "swat"),
    ("Rhino", "rhino"),
    ("Human Torch", "torch"),
    ("Venom", "venom"),
    ("Lizardman", "lizman2"),
    ("The Lizard", "lizard"),
    ("Mary Jane Parker", "mjviewer"),
    ("Symbiote", "symbi_02"),
    ("Mysterio", "mystview"),
    ("Punisher", "punisher"),
    ("Doctor Octopus", "docock"),
    ("Carnage", "carnage"),
    ("Monster Ock", "superock"),
    ("Captain America", "captain"),
    ("Sub-Mariner", "mariner"),
)

ROUTE = (
    "120:start:12",                 # skip boot FMV; at-or-after input cannot be skipped
    "title.bmr+120:start:12",       # title -> main wheel
    "title.bmr+300:right:12",       # NEW GAME -> RECORDS
    "title.bmr+500:down:12",        # RECORDS -> SPECIAL
    "title.bmr+700:down:12",        # SPECIAL -> GALLERY
    "title.bmr+900:cross:12",       # enter GALLERY
    "title.bmr+1200:cross:12",      # enter selected CHARACTER VIEWER
)
FIRST_ADVANCE = 1600
STEP_INTERVAL = 300
CROSS_DELAY = 150
FIRST_CAPTURE = 3600
ADVANCE_CAPTURE = 4050
MODEL_SHOT_DELAY = 180
VIEWER_TITLE_CROP = (70, 60, 410, 175)
VIEWER_TITLE_SAMPLE_SIZE = (48, 16)
VIEWER_TITLE_REFERENCE = bytes.fromhex(
    "00000000000000000000000000000000000000000000000000000000000000c9"
    "19c633ce01e999e67bde03293b664918030f2bcec11e020f2bca411802493a4e"
    "511001c14a4a701c008040002000000000000000000000000000000000000000"
)
VIEWER_TITLE_MAX_HAMMING = 80


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--render-scale", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--last-model",
        choices=tuple(model for _, model in ROSTER),
        default=ROSTER[-1][1],
        help="stop after this inclusive roster entry (useful for focused proofs)",
    )
    parser.add_argument(
        "--probe-model",
        help=(
            "converted model stem to present through a Character Viewer slot; "
            "the temporary alias is identified explicitly in the report"
        ),
    )
    parser.add_argument(
        "--probe-slot",
        choices=tuple(model for _, model in ROSTER),
        default="parker",
        help="viewer resource name temporarily replaced by --probe-model",
    )
    return parser.parse_args()


def build_script(roster: tuple[tuple[str, str], ...]) -> str:
    steps = list(ROUTE)
    for index in range(1, len(roster)):
        offset = FIRST_ADVANCE + (index - 1) * STEP_INTERVAL
        steps.append(f"title.bmr+{offset}:down:12")
        steps.append(f"title.bmr+{offset + CROSS_DELAY}:cross:12")
    return ";".join(steps)


def capture_frames(roster: tuple[tuple[str, str], ...]) -> list[int]:
    return [FIRST_CAPTURE] + [
        ADVANCE_CAPTURE + index * STEP_INTERVAL
        for index in range(len(roster) - 1)
    ]


def capture_specs(roster: tuple[tuple[str, str], ...]) -> list[str]:
    return [
        f"model.{model}{'#3' if model == 'spidey' else ''}+{MODEL_SHOT_DELAY}"
        for _, model in roster
    ]


def ensure_no_game_process() -> None:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq SpiderMan.exe", "/FO", "CSV", "/NH"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode == 0 and re.search(
        r'"SpiderMan\.exe"', result.stdout, re.IGNORECASE
    ):
        raise RuntimeError("refusing to launch while another SpiderMan.exe process exists")


def viewer_title_signature(image: Image.Image) -> dict[str, Any]:
    sampled = image.convert("L").crop(VIEWER_TITLE_CROP).resize(
        VIEWER_TITLE_SAMPLE_SIZE,
        Image.Resampling.BOX,
    )
    values = list(sampled.get_flattened_data())
    packed = bytes(
        sum((1 if values[index + bit] >= 128 else 0) << (7 - bit) for bit in range(8))
        for index in range(0, len(values), 8)
    )
    distance = sum((actual ^ expected).bit_count() for actual, expected in zip(
        packed,
        VIEWER_TITLE_REFERENCE,
    ))
    if distance > VIEWER_TITLE_MAX_HAMMING:
        raise ValueError(
            f"CHARACTER VIEWER title signature distance {distance} exceeds "
            f"{VIEWER_TITLE_MAX_HAMMING}"
        )
    return {
        "crop": list(VIEWER_TITLE_CROP),
        "sampleSize": list(VIEWER_TITLE_SAMPLE_SIZE),
        "sha256": hashlib.sha256(packed).hexdigest(),
        "hammingDistance": distance,
        "maximumHammingDistance": VIEWER_TITLE_MAX_HAMMING,
        "matches": True,
    }


def verify_capture(path: Path, render_scale: int, console: str) -> dict[str, Any]:
    with Image.open(path) as opened:
        opened.load()
        image = opened.convert("RGB")
        size = image.size
        extrema = image.getextrema()
        colors = image.getcolors(maxcolors=image.width * image.height)
    expected_size = (320 * render_scale, 240 * render_scale)
    if size != expected_size:
        raise ValueError(f"invalid capture dimensions {size}; expected {expected_size}: {path}")
    dynamic_range = max(high - low for low, high in extrema)
    color_count = len(colors) if colors is not None else image.width * image.height
    if dynamic_range < 32 or color_count < 64:
        raise ValueError(
            f"capture is not a reviewable rendered frame "
            f"(range={dynamic_range}, colors={color_count}): {path}"
        )
    if not re.search(
        rf"\[capture\].*{re.escape(path.name)} .*"
        r"\(live-3d 16bpp display aspect\)",
        console,
    ):
        raise ValueError(f"capture lacks native live-3D 16bpp marker: {path}")
    return {
        "size": list(size),
        "dynamicRange": dynamic_range,
        "colorCount": color_count,
        "viewerTitleSignature": viewer_title_signature(image),
    }


def link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def build_probe_batch(batch: Path, destination: Path, source_model: str, slot: str) -> Path:
    source = batch / f"{source_model.lower()}.psx"
    if not source.is_file():
        raise FileNotFoundError(f"probe model not found in batch: {source}")
    for path in batch.iterdir():
        if path.is_file():
            link_or_copy(path, destination / path.name)
    alias = destination / f"{slot}.psx"
    alias.unlink(missing_ok=True)
    link_or_copy(source, alias)
    return source


def main() -> None:
    args = parse_args()
    exe = args.exe.resolve()
    batch = args.batch.resolve()
    output = args.output.resolve()
    if args.render_scale != 4:
        raise ValueError("--render-scale must be 4 for reviewable runtime evidence")
    probe_model = args.probe_model.lower() if args.probe_model else None
    effective_last_model = args.probe_slot if probe_model else args.last_model
    last_index = next(
        index for index, (_, model) in enumerate(ROSTER) if model == effective_last_model
    )
    roster = ROSTER[: last_index + 1]
    output.mkdir(parents=True, exist_ok=True)
    ensure_no_game_process()
    for old_capture in output.glob("frame_*.png"):
        old_capture.unlink()
    console_path = output / "console.log"
    frames = capture_frames(roster)
    shot_specs = capture_specs(roster)
    exit_frame = frames[-1] + 150

    probe_source: Path | None = None
    with tempfile.TemporaryDirectory(prefix="viewer-probe-", dir=output) as temporary:
        runtime_batch = batch
        if probe_model:
            runtime_batch = Path(temporary)
            probe_source = build_probe_batch(
                batch, runtime_batch, probe_model, args.probe_slot
            )

        env = {key: value for key, value in os.environ.items() if not key.startswith("SPIDEY_")}
        env.pop("RECOMP_RENDER_SCALE", None)
        env.update(
            {
                "RECOMP_RENDER_SCALE": str(args.render_scale),
                "SPIDEY_ASSET_DIR": str(runtime_batch),
                "SPIDEY_CHEATS": "viewers",
                "SPIDEY_HZ": "60",
                "SPIDEY_SCRIPT": build_script(roster),
                "SPIDEY_SHOTS": ",".join(shot_specs),
                "SPIDEY_SHOT_DIR": str(output),
                "SPIDEY_EXIT": str(exit_frame),
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
            text = result.stdout or ""
            return_code: int | None = result.returncode
            timed_out = False
        except subprocess.TimeoutExpired as error:
            text = (
                error.stdout
                if isinstance(error.stdout, str)
                else (error.stdout or b"").decode(errors="replace")
            )
            return_code = None
            timed_out = True
    console_path.write_text(text, encoding="utf-8")

    load_calls = {
        match.group(1).lower()
        for match in re.finditer(r'LoadPsx\("([^"\r\n]+)"\)', text, re.I)
    }
    overrides = {
        match.group(1).lower().removesuffix(".psx")
        for match in re.finditer(r"\[loose-wad\] override ([^:\s]+\.psx):", text, re.I)
    }
    expected_models = {model for _, model in roster}
    missing_loads = sorted(expected_models - load_calls)
    missing_overrides = sorted(expected_models - overrides)

    captures: list[dict[str, Any]] = []
    capture_errors: list[str] = []
    resolved_frames: list[int] = []
    for _, model in roster:
        matches = re.findall(
            rf"\[capture\] 'model\.{re.escape(model)}' at frame (\d+): "
            r"model shot resolved to frame (\d+)",
            text,
            re.IGNORECASE,
        )
        if len(matches) != 1:
            capture_errors.append(
                f"{model}: expected one model-anchored shot resolution, found {matches}"
            )
            resolved_frames.append(-1)
        else:
            resolved_frames.append(int(matches[0][1]))
    for (display_name, model), shot_spec, frame in zip(roster, shot_specs, resolved_frames):
        path = output / f"frame_{frame:05d}.png"
        try:
            if frame < 0:
                raise ValueError("model-anchored shot did not resolve")
            capture_metrics = verify_capture(path, args.render_scale, text)
            captures.append(
                {
                    "index": len(captures),
                    "displayName": display_name,
                    "model": model,
                    "frame": frame,
                    "shotAnchor": shot_spec,
                    "path": str(path),
                    **capture_metrics,
                    **(
                        {"sourceModel": probe_model}
                        if probe_model and model == args.probe_slot
                        else {}
                    ),
                }
            )
        except Exception as error:
            capture_errors.append(f"{model}: {error}")

    bad_markers = [
        marker
        for marker in ("Unhandled exception", "watchdog: STALLED", "MISSED -- overlay not resident")
        if marker.lower() in text.lower()
    ]
    clean_exit = f"[capture] exit at frame {exit_frame}" in text
    status = (
        "pass"
        if not timed_out
        and return_code == 0
        and clean_exit
        and not bad_markers
        and not missing_loads
        and not missing_overrides
        and not capture_errors
        and len(captures) == len(roster)
        else "fail"
    )
    report = {
        "schemaVersion": 3,
        "batch": str(batch),
        "probe": (
            {
                "sourceModel": probe_model,
                "sourcePath": str(probe_source),
                "viewerSlot": args.probe_slot,
                "temporaryAliasRemoved": True,
            }
            if probe_model
            else None
        ),
        "inputMethod": "process-local SPIDEY_SCRIPT controller state",
        "gameProcessCount": 1,
        "processPolicy": "strictly sequential; never more than one SpiderMan process",
        "renderScale": args.render_scale,
        "rosterCount": len(roster),
        "loadedModelCount": len(expected_models & load_calls),
        "overrideCount": len(expected_models & overrides),
        "captureCount": len(captures),
        "missingLoads": missing_loads,
        "missingOverrides": missing_overrides,
        "captureErrors": capture_errors,
        "badMarkers": bad_markers,
        "returnCode": return_code,
        "timedOut": timed_out,
        "cleanExit": clean_exit,
        "captureGate": (
            "model-load-anchored native live-3D 16bpp readback plus normalized "
            "CHARACTER VIEWER title signature"
        ),
        "captures": captures,
        "consoleLog": str(console_path),
        "status": status,
    }
    report_path = output / "runtime-validation.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"{status.upper()}: {report['loadedModelCount']}/{len(roster)} viewer loads; "
        f"{report['overrideCount']}/{len(roster)} overrides; "
        f"{report['captureCount']}/{len(roster)} captures"
    )
    if missing_loads:
        print("missing viewer loads: " + ", ".join(missing_loads))
    if missing_overrides:
        print("missing viewer overrides: " + ", ".join(missing_overrides))
    for error in capture_errors:
        print("capture failure: " + error)
    print(f"report: {report_path}")
    if status != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
