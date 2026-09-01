#!/usr/bin/env python3
"""Capture all nineteen SM2 Spider-Man costumes on compatible Dreamcast actors.

Every run is a separate, sequential SpiderMan2 process. Costume selection and menu
input stay inside the game process through SPIDEY_COSTUME and SPIDEY_SCRIPT; no host
keyboard, mouse, or controller input is generated.
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
DEFAULT_EXE = (
    ROOT / "spiderman2" / "port" / "bin" / "Release" / "net10.0" / "SpiderMan2.exe"
)
DEFAULT_ASSETS = ROOT / "dreamcast" / "converted" / "sm2-spider-man-runtime"
DEFAULT_OUTPUT = DEFAULT_ASSETS / "runtime-menu-proof"
COSTUME_COUNT = 19
SPECIAL_ACTORS = {13: "spidey-slot13.psx", 17: "spidey-slot17.psx"}
SPECIAL_TEXTURES = {13: "sp_tex13-dc.psx", 17: "sp_tex17-dc.psx"}
# A process-local START pulse repeats only until title.bmr loads. The
# archive-anchored START leaves the title screen, and CROSS then enters the actual main menu, which
# loads charlite.dat and renders CONTINUE / NEW GAME / OPTIONS with live 3D Spidey.
# Deliberately omit the later CROSS used by gameplay routes so the test stays there.
INPUT_SCRIPT = "title.bmr+80:start:10;title.bmr+200:cross:10"
BOOT_SKIP_ANCHOR = "title.bmr"
SHOT_ANCHOR = "charlite.dat"
SHOT_OFFSETS = (300, 400, 500, 600, 700)
SHOT_SPECS = tuple(f"{SHOT_ANCHOR}+{offset}" for offset in SHOT_OFFSETS)
SHOT_SPEC = ",".join(SHOT_SPECS)
EXIT_FRAME = 1800

# Exact, actor-free regions of the retail main-menu chrome at the required 4x
# rasterizer scale.  Resolution, dynamic range, and color count reject many bad
# captures but do not positively identify a screen: a scaled FMV can satisfy all
# three.  These four labels cannot be present in an intro/title movie, and keeping
# them outside the center actor band makes the proof independent of costume/pose.
MENU_REGION_SIGNATURES = {
    "continueLabel": {
        "bounds": (120, 100, 410, 235),
        "sha256": "6eb22af08b4a54b8261cc0ec615ffee4e84830c1497b0878125f7ea250ccf04a",
    },
    "trainingLabel": {
        "bounds": (875, 100, 1150, 235),
        "sha256": "e84eace92c323d39324fbaa2a2f079b72901c4b97299142fa8502116a5945f8b",
    },
    "optionsLabel": {
        "bounds": (150, 735, 420, 850),
        "sha256": "a3048b48ba0dad95196aa7c58f5850f38444d5d9d50c2577915b4c49f8be71ca",
    },
    "galleryLabel": {
        "bounds": (880, 735, 1140, 850),
        "sha256": "d91729c9610cdd886062c9482ea30b387245bc56a5976707d2bbd737d97d24a9",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--slots",
        default=",".join(str(slot) for slot in range(COSTUME_COUNT)),
        help="comma-separated slots from 0 through 18",
    )
    parser.add_argument("--render-scale", type=int, default=4)
    parser.add_argument("--exit-frame", type=int, default=EXIT_FRAME)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--reuse-captures",
        action="store_true",
        help="validate existing console logs and frames without launching the game",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_no_game_process() -> None:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq SpiderMan2.exe", "/FO", "CSV", "/NH"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode == 0 and re.search(
        r'"SpiderMan2\.exe"', result.stdout, re.IGNORECASE
    ):
        raise RuntimeError("refusing to launch while another SpiderMan2.exe process exists")


def run_game(
    exe: Path,
    assets: Path,
    slot_root: Path,
    slot: int,
    render_scale: int,
    exit_frame: int,
    timeout: int,
) -> tuple[str, str]:
    ensure_no_game_process()
    for pattern in (
        "frame_*.png",
        "sm2_spider_man_slot*_menu_close*.png",
        "menu_sequence_contact.png",
        "console.log",
        "spidey.log",
    ):
        for generated in slot_root.glob(pattern):
            generated.unlink()
    run_token = uuid.uuid4().hex
    env = {key: value for key, value in os.environ.items() if not key.startswith("SPIDEY_")}
    env.pop("RECOMP_RENDER_SCALE", None)
    env.pop("RECOMP_ASSET_PACK_DIR", None)
    env.update(
        {
            "RECOMP_RENDER_SCALE": str(render_scale),
            "RECOMP_VALIDATE_MODEL_GEOMETRY": "1",
            "RECOMP_TRACE_MODEL_STITCHES": "1",
            "SPIDEY_ASSET_DIR": str(assets),
            "SPIDEY_COSTUME": str(slot),
            "SPIDEY_BOOT_SKIP_UNTIL": BOOT_SKIP_ANCHOR,
            "SPIDEY_HZ": "60",
            "SPIDEY_RUN_TOKEN": run_token,
            "SPIDEY_SCRIPT": INPUT_SCRIPT,
            "SPIDEY_SHOTS": SHOT_SPEC,
            "SPIDEY_SHOT_DIR": str(slot_root),
            "SPIDEY_EXIT": str(exit_frame),
            "SPIDEY_LOG_DIR": str(slot_root),
            "SPIDEY_STALL_EXIT": "1",
            "SPIDEY_TRACE_GAME": "1",
            "SPIDEY_TRACE_WAD": "1",
        }
    )
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
    except subprocess.TimeoutExpired as error:
        console = (
            error.stdout
            if isinstance(error.stdout, str)
            else (error.stdout or b"").decode(errors="replace")
        )
        (slot_root / "console.log").write_text(console, encoding="utf-8")
        raise RuntimeError(f"slot {slot:02d} timed out after {timeout}s") from error
    (slot_root / "console.log").write_text(console, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"slot {slot:02d} exited {result.returncode}")
    return console, run_token


def run_token_from_console(console: str) -> str:
    matches = re.findall(r"\[capture\] run-token ([0-9a-f]{32})", console)
    if len(matches) != 1:
        raise RuntimeError(
            "runtime evidence predates the exclusive fresh-run gate; capture it again"
        )
    return matches[0]


def resolved_shot_frames(console: str) -> list[int]:
    matches = re.findall(
        rf"\[capture\] '{re.escape(SHOT_ANCHOR)}' load #\d+ at frame (\d+): "
        r"shot resolved to frame (\d+)",
        console,
    )
    by_offset = {
        int(shot) - int(load): int(shot)
        for load, shot in matches
        if int(shot) - int(load) in SHOT_OFFSETS
    }
    missing = [offset for offset in SHOT_OFFSETS if offset not in by_offset]
    if missing or len(matches) != len(SHOT_OFFSETS):
        raise RuntimeError(
            f"expected the complete {SHOT_SPEC} menu sequence; "
            f"missing offsets {missing}, found {matches}"
        )
    return [by_offset[offset] for offset in SHOT_OFFSETS]


def validate_image(path: Path, render_scale: int) -> dict[str, Any]:
    with Image.open(path) as opened:
        opened.load()
        image = opened.convert("RGB")
        size = image.size
        extrema = image.getextrema()
        colors = image.getcolors(maxcolors=image.width * image.height)
    expected_size = (320 * render_scale, 240 * render_scale)
    if size != expected_size:
        raise RuntimeError(
            f"{path} is {size}; expected the live 3D menu at {expected_size}. "
            "A 320x240 24-bit capture is still the title/FMV path."
        )
    dynamic_range = max(high - low for low, high in extrema)
    color_count = len(colors) if colors is not None else image.width * image.height
    if dynamic_range < 32 or color_count < 64:
        raise RuntimeError(
            f"{path} does not resemble a rendered frame "
            f"(range={dynamic_range}, colors={color_count})"
        )
    return {
        "path": str(path),
        "size": list(size),
        "capturePath": "full internal-resolution live 3D rasterizer readback",
        "dynamicRange": dynamic_range,
        "colorCount": color_count,
        "sha256": sha256(path),
    }


def validate_main_menu_signature(path: Path) -> list[dict[str, Any]]:
    """Positively identify the live 3D main menu, failing closed on any mismatch."""
    with Image.open(path) as opened:
        opened.load()
        image = opened.convert("RGB")
        results = []
        for name, expected in MENU_REGION_SIGNATURES.items():
            bounds = expected["bounds"]
            digest = hashlib.sha256(image.crop(bounds).tobytes()).hexdigest()
            results.append(
                {
                    "name": name,
                    "bounds": list(bounds),
                    "sha256": digest,
                    "expectedSha256": expected["sha256"],
                    "matches": digest == expected["sha256"],
                }
            )
    mismatches = [result["name"] for result in results if not result["matches"]]
    if mismatches:
        raise RuntimeError(
            f"{path} is not the verified live 3D main menu; "
            f"menu chrome mismatched at {', '.join(mismatches)}"
        )
    return results


def validate_slot(
    assets: Path,
    slot_root: Path,
    slot: int,
    console: str,
    render_scale: int,
    exit_frame: int,
    run_token: str,
) -> dict[str, Any]:
    actor_name = SPECIAL_ACTORS.get(slot, "spidey.psx")
    actor_size = (assets / actor_name).stat().st_size
    texture_name = f"sp_tex{slot:02d}.psx"
    texture_source = SPECIAL_TEXTURES.get(slot, texture_name)
    texture_size = (assets / texture_source).stat().st_size
    markers = {
        "requested": f"[costume] requested slot {slot:02d} ({texture_name})" in console,
        "selected": (
            f"[costume] selected retail loader slot {slot:02d} -> {texture_name}" in console
        ),
        "modelOverride": bool(
            re.search(
                (
                    rf"\[loose-wad\] override spidey\.psx: {actor_size} bytes"
                    if slot not in SPECIAL_ACTORS
                    else rf"\[loose-wad\] override (?:spbagdc|spparkdc)\.psx"
                    rf" <- {re.escape(actor_name)}: {actor_size} bytes"
                ),
                console,
                re.IGNORECASE,
            )
            and (
                slot not in SPECIAL_ACTORS
                or f"[costume] active actor slot {slot:02d}" in console
            )
        ),
        "textureOverride": bool(
            re.search(
                rf"\[loose-wad\] override {re.escape(texture_name)}"
                rf"(?: <- {re.escape(texture_source)})?: {texture_size} bytes",
                console,
                re.IGNORECASE,
            )
        ),
        "mainMenuAssets": "charlite.dat" in console,
        "cleanExit": f"[capture] exit at frame {exit_frame}" in console,
        "freshRunToken": (
            f"[capture] run-token {run_token}" in console
            and console.count("[capture] run-token ") == 1
        ),
        "bootSkipBoundary": (
            f"[capture] boot-skip completed at '{BOOT_SKIP_ANCHOR}' load" in console
        ),
    }
    title_load = re.search(
        r"\[capture\] 'title\.bmr' load #1 at frame (\d+): step resolved",
        console,
    )
    markers["introMovieSkipped"] = bool(
        title_load and int(title_load.group(1)) < 1000
    )
    runtime_log_path = slot_root / "spidey.log"
    runtime_log = (
        runtime_log_path.read_text(encoding="utf-8", errors="replace")
        if runtime_log_path.is_file()
        else ""
    )
    if slot in SPECIAL_ACTORS:
        markers["hostTexturePack"] = bool(
            re.search(
                r"\[assets\] game=SLUS-01378 packs=[1-9]\d* .*"
                r"sm2-spider-man-runtime\\packs",
                runtime_log,
                re.IGNORECASE,
            )
        )
    if slot == 13:
        markers["bagmanNestedShellDepth"] = (
            "[dc-model] Bag-Man nested shell: inner=86 outer=93 ot-bias=128"
            in console
        )
    bad_markers = [
        marker
        for marker in ("Unhandled exception", "watchdog: STALLED", "MISSED -- overlay not resident")
        if marker.lower() in console.lower()
    ]
    frames = resolved_shot_frames(console)
    captures = [
        validate_image(slot_root / f"frame_{frame:05d}.png", render_scale)
        for frame in frames
    ]
    for frame, capture in zip(frames, captures, strict=True):
        capture["native3d16BitMarker"] = bool(
            re.search(
                rf"\[capture\].*frame_{frame:05d}\.png \d+x\d+ "
                r"\(live-3d 16bpp display aspect\)",
                console,
            )
        )
        if not capture["native3d16BitMarker"]:
            raise RuntimeError(
                f"slot {slot:02d} frame {frame} was not freshly captured from the "
                "native 16-bit 3D menu path"
            )
    for capture in captures:
        capture["mainMenuSignature"] = validate_main_menu_signature(Path(capture["path"]))
    markers["mainMenuVisualSignature"] = all(
        all(region["matches"] for region in capture["mainMenuSignature"])
        for capture in captures
    )

    closeups: list[dict[str, Any]] = []
    thumbnails: list[Image.Image] = []
    for offset, capture in zip(SHOT_OFFSETS, captures, strict=True):
        source = Path(capture["path"])
        closeup = slot_root / (
            f"sm2_spider_man_slot{slot:02d}_menu_close_{offset:03d}.png"
        )
        with Image.open(source) as opened:
            # Exact pixels only. The main-menu actor occupies the central vertical band.
            opened.load()
            width, height = opened.size
            crop = (
                round(width * 0.25),
                round(height * 0.08),
                round(width * 0.75),
                round(height * 0.98),
            )
            opened.crop(crop).save(closeup, format="PNG", optimize=False)
            thumbnail = opened.convert("RGB")
            thumbnail.thumbnail((640, 480), Image.Resampling.LANCZOS)
            thumbnails.append(thumbnail.copy())
        closeups.append(
            {
                "offset": offset,
                "path": str(closeup),
                "cropPolicy": "native capture crop; no scaling or filtering",
                "sha256": sha256(closeup),
            }
        )

    contact_sheet = slot_root / "menu_sequence_contact.png"
    sheet = Image.new("RGB", (640 * len(thumbnails), 480), color=(0, 0, 0))
    for index, thumbnail in enumerate(thumbnails):
        sheet.paste(thumbnail, (index * 640, 0))
    sheet.save(contact_sheet, format="PNG", optimize=False)

    # These checks prove that the requested actor/texture files reached the live
    # 3D menu and produced reviewable evidence.  They intentionally do not call
    # the costume visually correct; geometry, weighting, and UV quality require
    # inspection of the captured frame.
    status = (
        "menu-capture-valid"
        if all(markers.values()) and not bad_markers
        else "menu-capture-invalid"
    )
    return {
        "slot": slot,
        "runToken": run_token,
        "actor": actor_name,
        "textureLibrary": texture_name,
        "textureSource": texture_source,
        "status": status,
        "runtimeMarkers": markers,
        "badMarkers": bad_markers,
        "captureSequence": captures,
        "authoredCloseups": closeups,
        "menuSequenceContactSheet": {
            "path": str(contact_sheet),
            "offsets": list(SHOT_OFFSETS),
            "sha256": sha256(contact_sheet),
        },
        "visualReview": "pending",
        "consoleLog": str(slot_root / "console.log"),
        "runtimeLog": str(runtime_log_path),
    }


def main() -> None:
    args = parse_args()
    if args.render_scale < 1 or args.render_scale > 8:
        raise ValueError("--render-scale must be between 1 and 8")
    slots = [int(value.strip()) for value in args.slots.split(",") if value.strip()]
    if not slots or len(set(slots)) != len(slots):
        raise ValueError("--slots must contain unique values")
    if any(slot < 0 or slot >= COSTUME_COUNT for slot in slots):
        raise ValueError("--slots must select values from 0 through 18")

    exe = args.exe.resolve()
    assets = args.assets.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for slot in slots:
        slot_root = output / f"slot-{slot:02d}"
        slot_root.mkdir(parents=True, exist_ok=True)
        if args.reuse_captures:
            console = (slot_root / "console.log").read_text(encoding="utf-8")
            run_token = run_token_from_console(console)
        else:
            console, run_token = run_game(
                exe,
                assets,
                slot_root,
                slot,
                args.render_scale,
                args.exit_frame,
                args.timeout,
            )
        result = validate_slot(
            assets,
            slot_root,
            slot,
            console,
            args.render_scale,
            args.exit_frame,
            run_token,
        )
        results.append(result)
        print(
            f"{result['status'].upper()} slot {slot:02d} "
            f"{result['textureLibrary']} -> one sequential SpiderMan2 process",
            flush=True,
        )
        if result["status"] != "menu-capture-valid":
            raise RuntimeError(f"slot {slot:02d} failed runtime validation")

    report = {
        "schemaVersion": 3,
        "status": "menu-capture-valid",
        "visualReview": "pending; every menu frame must be inspected before a costume passes",
        "scope": "SM2 Spider-Man costumes only; no NPC or enemy replacements",
        "assets": str(assets),
        "processPolicy": "strictly sequential; never more than one SpiderMan2 process",
        "inputMethod": (
            "process-local costume pre-hook, boot-skip boundary, and SPIDEY_SCRIPT "
            "controller state"
        ),
        "freshEvidencePolicy": (
            "unique per-process run token plus native live-3D 16bpp marker; stale or "
            "FMV captures fail closed"
        ),
        "shotTiming": SHOT_SPEC,
        "environmentPolicy": "retail PS1 SM2 environments are unchanged",
        "renderScaleRequested": args.render_scale,
        "costumeCount": len(results),
        "results": results,
    }
    report_path = output / "runtime-validation.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"MENU CAPTURED: {len(results)}/{len(slots)} selected SM2 Spider-Man costume slots; "
        "visual review still required"
    )
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
