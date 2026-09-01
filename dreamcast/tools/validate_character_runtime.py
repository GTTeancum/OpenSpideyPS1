#!/usr/bin/env python3
"""Launch a minimal level set that exercises every story-loaded DC actor override.

Input is injected only through the recompilation's process-local controller script.
No host keyboard, mouse, or desktop automation is used.  Each child process writes an
isolated log and native GPU screenshots, which are then checked and summarized.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXE = ROOT / "spiderman" / "port" / "bin" / "Release" / "net10.0" / "SpiderMan.exe"
DEFAULT_BATCH = ROOT / "dreamcast" / "converted" / "all-characters"
DEFAULT_OUTPUT = ROOT / "dreamcast" / "converted" / "all-characters-runtime-current"
DEFAULT_TRIGGERS = ROOT / "dreamcast" / "decoded" / "triggers"
DEFAULT_SHOTS = "4300,4400"
DEFAULT_EXIT_FRAME = 4450
DEFAULT_LEVELS = (
    "l1a1",   # blackcat, henchman, spidey, thug
    "l5a3",   # lizman, lizman2, venom, venom2
    "l7a5",   # goldfish, mysterio, softeyes, softspot
    "l2a2",   # jameson, jjjj, scorpion
    "l7a1",   # hostage, sym_base, symbi_02
    "l3a1",   # chopper, police
    "l8a3",   # bc2, sym_dark
    "l8a5",   # carnage, mariner
    "l1a2a",  # torch
    "l2a1",   # henchngt
    "l3a3",   # swat
    "l4a1",   # rhino
    "l6a3",   # lizard
    "l6a4",   # mj
    "l7a3",   # sym_gen
    "l8a2",   # turret
    "l8a4",   # docock
    "l8a6",   # superock
)
INPUT_SCRIPT = (
    "title.bmr+120:start:12;title.bmr+420:cross:12;"
    "title.bmr+720:cross:12;title.bmr+1100:cross:12;"
    "title.bmr+1500:cross:12;title.bmr+1900:cross:12"
)
BOOT_SKIP_ANCHOR = "title.bmr"
RUNTIME_EQUIVALENTS = {
    # Trigger/overlay names are not always model names.  These pairs are the retail
    # game's own resource choices, while every exact file still receives the separate
    # independent decode/reconstruct/render audit.
    "jjjj": {"jjjj", "jameson"},
    "lizman": {"lizman", "lizman2"},
    "thug": {"thug", "henchman", "henchngt"},
}
LEVEL_ASSET_ALIASES = {
    # Retail L1A2a has variant-specific geometry/logic but intentionally shares
    # the L1A2 object archive.
    ("l1a2a", "O"): ("L1A2_O",),
}
LEVEL_SHOT_OVERRIDES = {
    # The final scripted chase reaches the save prompt before frame 2800. These
    # two frames are inside the live Super Ock sequence and show both actors.
    "l8a6": "2400,2450",
}
LEVEL_EXIT_OVERRIDES = {"l8a6": 2500}

# Fixed red-letter mask for the retail GAME OVER heading at the required 4x
# capture size. The background is deliberately ignored: this signature detects
# the overlay over any level scene and prevents a dead player from satisfying a
# weak "16-bit image exists" test.
GAME_OVER_CROP = (480, 180, 800, 320)
GAME_OVER_SAMPLE_SIZE = (64, 28)
GAME_OVER_REFERENCE = bytes.fromhex(
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "03ce667c1f44f9f0064e66601b4cc1b0061e6e78114cf1b006da7e783378f9e0"
    "06defec03378c36006feb6f83f70f36003f2b4f81e70f3200000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
)
GAME_OVER_MAX_HAMMING = 32

SAVE_PROGRESS_CROP = (300, 170, 980, 280)
SAVE_PROGRESS_SAMPLE_SIZE = (96, 16)
SAVE_PROGRESS_REFERENCE = bytes.fromhex(
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000a5240e"
    "c92073399c8ca080008d0000cb40548a0508808000484e104170674a99cc4100"
    "000cc811d440054a8900000000d08e0d14708533a1ccc0000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
)
SAVE_PROGRESS_MAX_HAMMING = 24

# Static blue HUD-chrome mask from a verified live gameplay frame. Only reference
# pixels that belong to the opaque health/web UI are counted, so level scenery in
# the crop cannot create a false mismatch. This is the positive path for levels
# whose retail driver stays inside the outer RunFrame(0) loop.
GAMEPLAY_HUD_CROP = (0, 20, 360, 340)
GAMEPLAY_HUD_SAMPLE_SIZE = (72, 64)
GAMEPLAY_HUD_REFERENCE = bytes.fromhex(
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000400000000000000003fe000000"
    "000000000f83800000000000001900c000000000000032006000000000000064"
    "0070000000000000cc0038000000000000dc003ffffffffc0000f8003fffffff"
    "fe0001f8003fffffffff0001f0003c0000000f0001e0003c000000070001e000"
    "7c000000070001e000fc000000070000e000fc0000000e0001f000ffffffffff"
    "0000f001fffffffffe0000f803fffffffffe00007d03fffffffffc00003f87f0"
    "0000000000001fe7e00000000000001fffc00800000000001fff806e00000000"
    "001fff07ff00000000001fff0ff780000000001fff0ff7c0000000001fff1ef7"
    "e4888000001fff1ffffcd98000001fff1ffffcdb0000001fff1ffffcde000000"
    "1fff1f7ffcf60000001fff0ffbcc760000001fff0fbb80000000001fff07bb00"
    "000000001fff03da00000000001fff00c000000000001fff000000000000001f"
    "ff000000000000001fff000000000000001fff000000000000001fff00000000"
    "0000001fff000000000000001fff000000000000001fff000000000000001bff"
    "000000000000000dfe0000000000000003fc0000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
)
GAMEPLAY_HUD_MIN_COVERAGE = 0.90


def game_over_signature(image: Image.Image) -> dict[str, Any]:
    sampled = image.convert("RGB").crop(GAME_OVER_CROP).resize(
        GAME_OVER_SAMPLE_SIZE,
        Image.Resampling.BOX,
    )
    bits = [
        red > 135 and red > green * 1.45 and red > blue * 1.45
        for red, green, blue in sampled.get_flattened_data()
    ]
    packed = bytes(
        sum((1 if bits[index + bit] else 0) << (7 - bit) for bit in range(8))
        for index in range(0, len(bits), 8)
    )
    distance = sum(
        (actual ^ expected).bit_count()
        for actual, expected in zip(packed, GAME_OVER_REFERENCE)
    )
    matches = distance <= GAME_OVER_MAX_HAMMING
    return {
        "crop": list(GAME_OVER_CROP),
        "sampleSize": list(GAME_OVER_SAMPLE_SIZE),
        "hammingDistance": distance,
        "maximumHammingDistance": GAME_OVER_MAX_HAMMING,
        "matches": matches,
    }


def save_progress_signature(image: Image.Image) -> dict[str, Any]:
    sampled = image.convert("L").crop(SAVE_PROGRESS_CROP).resize(
        SAVE_PROGRESS_SAMPLE_SIZE,
        Image.Resampling.BOX,
    )
    bits = [value >= 128 for value in sampled.get_flattened_data()]
    packed = bytes(
        sum((1 if bits[index + bit] else 0) << (7 - bit) for bit in range(8))
        for index in range(0, len(bits), 8)
    )
    distance = sum(
        (actual ^ expected).bit_count()
        for actual, expected in zip(packed, SAVE_PROGRESS_REFERENCE)
    )
    matches = distance <= SAVE_PROGRESS_MAX_HAMMING
    return {
        "crop": list(SAVE_PROGRESS_CROP),
        "sampleSize": list(SAVE_PROGRESS_SAMPLE_SIZE),
        "hammingDistance": distance,
        "maximumHammingDistance": SAVE_PROGRESS_MAX_HAMMING,
        "matches": matches,
    }


def gameplay_hud_signature(image: Image.Image) -> dict[str, Any]:
    sampled = image.convert("RGB").crop(GAMEPLAY_HUD_CROP).resize(
        GAMEPLAY_HUD_SAMPLE_SIZE,
        Image.Resampling.BOX,
    )
    actual_bits = [
        blue > 60 and blue > red * 1.12 and blue > green * 1.03
        for red, green, blue in sampled.get_flattened_data()
    ]
    reference_bits = [
        bool(byte & (1 << (7 - bit)))
        for byte in GAMEPLAY_HUD_REFERENCE
        for bit in range(8)
    ]
    reference_pixel_count = sum(reference_bits)
    matching_pixel_count = sum(
        actual and expected
        for actual, expected in zip(actual_bits, reference_bits)
    )
    coverage = matching_pixel_count / reference_pixel_count
    return {
        "crop": list(GAMEPLAY_HUD_CROP),
        "sampleSize": list(GAMEPLAY_HUD_SAMPLE_SIZE),
        "matchingReferencePixels": matching_pixel_count,
        "referencePixelCount": reference_pixel_count,
        "coverage": coverage,
        "minimumCoverage": GAMEPLAY_HUD_MIN_COVERAGE,
        "matches": coverage >= GAMEPLAY_HUD_MIN_COVERAGE,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--triggers", type=Path, default=DEFAULT_TRIGGERS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--levels", default=",".join(DEFAULT_LEVELS))
    parser.add_argument(
        "--concurrency",
        type=int,
        choices=(1,),
        default=1,
        help="runtime validation is deliberately restricted to one game process",
    )
    parser.add_argument("--render-scale", type=int, default=4)
    parser.add_argument("--shots", default=DEFAULT_SHOTS)
    parser.add_argument("--exit-frame", type=int, default=DEFAULT_EXIT_FRAME)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--dump-textures",
        action="store_true",
        help="dump complete runtime texture uploads for actor-specific CLUT diagnostics",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse existing clean level results and rerun only missing/failed levels",
    )
    parser.add_argument(
        "--allow-partial-coverage",
        action="store_true",
        help="pass a focused --levels run when every requested level passes",
    )
    parser.add_argument(
        "--continue-on-failure",
        action="store_true",
        help="continue later levels after a failed screen/resource gate (default: stop immediately)",
    )
    return parser.parse_args()


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


def all_story_actor_names(manifest: dict[str, Any], trigger_dir: Path) -> set[str]:
    names = {entry["name"].lower() for entry in manifest["entries"]}
    found: set[str] = set()
    token = {name: re.compile(rf"(?<![a-z0-9_]){re.escape(name)}(?![a-z0-9_])") for name in names}
    for path in trigger_dir.glob("*.json"):
        prefix = path.stem.lower().removesuffix("_t")
        if not re.fullmatch(r"l[1-9]a\d+[a-z]?", prefix):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        found.update(name for name, pattern in token.items() if pattern.search(text))
    return found


def summarize_level(
    level: str,
    level_dir: Path,
    console_path: Path,
    text: str,
    return_code: int | None,
    timed_out: bool,
    exit_frame: int,
    reused: bool,
    render_scale: int,
    shots: str,
) -> dict[str, Any]:
    overrides = sorted(
        {
            match.group(1).lower().removesuffix(".psx")
            for match in re.finditer(r"\[loose-wad\] override ([^:\s]+\.psx):", text, re.I)
        }
    )
    captures = sorted(level_dir.glob("frame_*.png"))
    capture_sizes: dict[str, dict[str, Any]] = {}
    capture_errors: list[str] = []
    expected_size = (320 * render_scale, 240 * render_scale)
    for path in captures:
        try:
            with Image.open(path) as opened:
                opened.load()
                image = opened.convert("RGB")
                size = image.size
                extrema = image.getextrema()
                colors = image.getcolors(maxcolors=image.width * image.height)
            dynamic_range = max(high - low for low, high in extrema)
            color_count = len(colors) if colors is not None else image.width * image.height
            if size != expected_size:
                raise ValueError(f"size {size}, expected live 3D raster {expected_size}")
            if dynamic_range < 32 or color_count < 64:
                raise ValueError(
                    f"not a reviewable rendered frame (range={dynamic_range}, colors={color_count})"
                )
            if not re.search(
                rf"\[capture\].*{re.escape(path.name)} .*"
                r"\(live-3d 16bpp display aspect\)",
                text,
            ):
                raise ValueError("capture lacks native live-3D 16bpp marker")
            state_match = re.search(
                rf"\[capture\].*{re.escape(path.name)} .*"
                r"\(level-runframe-entered=(\d+)\)",
                text,
            )
            active_level_runframe = int(state_match.group(1)) if state_match else 0
            gameplay_hud = gameplay_hud_signature(image)
            game_over = game_over_signature(image)
            save_progress = save_progress_signature(image)
            if game_over["matches"]:
                raise ValueError(
                    "capture is the retail GAME OVER screen "
                    f"(signature distance={game_over['hammingDistance']})"
                )
            if save_progress["matches"]:
                raise ValueError(
                    "capture is the retail SAVE GAME PROGRESS screen "
                    f"(signature distance={save_progress['hammingDistance']})"
                )
            live_gameplay_gate = active_level_runframe > 0 or gameplay_hud["matches"]
            if not live_gameplay_gate:
                raise ValueError(
                    "capture has neither a non-zero level RunFrame entry nor the "
                    "verified gameplay HUD signature "
                    f"(HUD coverage={gameplay_hud['coverage']:.3f})"
                )
            capture_sizes[path.name] = {
                "size": list(size),
                "dynamicRange": dynamic_range,
                "colorCount": color_count,
                "activeLevelRunFrame": active_level_runframe,
                "gameplayHudSignature": gameplay_hud,
                "gameOverSignature": game_over,
                "saveProgressSignature": save_progress,
                "liveGameplayGate": live_gameplay_gate,
            }
        except Exception as error:
            capture_errors.append(f"{path.name}: {error}")
    clean_exit = f"[capture] exit at frame {exit_frame}" in text
    # The default level logs an explicit [level] source -> destination remap,
    # while redirected levels load their requested L/O/G resources directly.
    # The WAD-load line is emitted only after the exact requested asset has
    # resolved, so it is the common authoritative proof for both paths.
    level_asset_proofs: dict[str, str] = {}
    for suffix in ("L", "O", "G"):
        expected_stems = (f"{level.upper()}_{suffix}",) + LEVEL_ASSET_ALIASES.get(
            (level.lower(), suffix), ()
        )
        for stem in expected_stems:
            if re.search(
                rf"(?m)^{re.escape(stem)}\.psx\[wad\]\s+"
                rf"{re.escape(stem)}\.psx\s+<-",
                text,
                re.IGNORECASE,
            ):
                level_asset_proofs[suffix] = f"{stem}.psx"
                break
    level_assets_loaded = len(level_asset_proofs) == 3
    geometry_proof = level_asset_proofs.get("G")
    geometry_log_position = (
        text.lower().find(f"{geometry_proof.lower()}[wad]")
        if geometry_proof
        else -1
    )
    capture_log_positions = [
        text.find(f"[capture] {path}")
        for path in captures
    ]
    expected_capture_count = len([shot for shot in shots.split(",") if shot.strip()])
    level_geometry_capture_gate = (
        geometry_log_position >= 0
        and len(captures) == expected_capture_count
        and all(position > geometry_log_position for position in capture_log_positions)
    )
    bad_markers = [
        marker
        for marker in ("Unhandled exception", "watchdog: STALLED", "MISSED -- overlay not resident")
        if marker.lower() in text.lower()
    ]
    status = (
        "pass"
        if not timed_out
        and return_code == 0
        and clean_exit
        and level_assets_loaded
        and level_geometry_capture_gate
        and captures
        and not capture_errors
        and not bad_markers
        else "fail"
    )
    return {
        "level": level,
        "status": status,
        "returnCode": return_code,
        "timedOut": timed_out,
        "cleanExit": clean_exit,
        "levelAssetsLoaded": level_assets_loaded,
        "levelAssetProofs": level_asset_proofs,
        "levelGeometryCaptureGate": level_geometry_capture_gate,
        "shotSpec": shots,
        "expectedCaptureCount": expected_capture_count,
        "badMarkers": bad_markers,
        "captureErrors": capture_errors,
        "loadedOverrides": overrides,
        "captures": capture_sizes,
        "consoleLog": str(console_path),
        "reused": reused,
    }


def run_level(
    level: str,
    exe: Path,
    batch: Path,
    output: Path,
    render_scale: int,
    shots: str,
    exit_frame: int,
    timeout: int,
    resume: bool,
    dump_textures: bool,
) -> dict[str, Any]:
    level_dir = output / level
    level_dir.mkdir(parents=True, exist_ok=True)
    console_path = level_dir / "console.log"
    if resume and console_path.is_file():
        existing = summarize_level(
            level,
            level_dir,
            console_path,
            console_path.read_text(encoding="utf-8", errors="replace"),
            0,
            False,
            exit_frame,
            True,
            render_scale,
            shots,
        )
        if existing["status"] == "pass":
            return existing

    ensure_no_game_process()
    for old_capture in level_dir.glob("frame_*.png"):
        old_capture.unlink()
    env = {key: value for key, value in os.environ.items() if not key.startswith("SPIDEY_")}
    env.pop("RECOMP_RENDER_SCALE", None)
    env.update(
        {
            "RECOMP_RENDER_SCALE": str(render_scale),
            "SPIDEY_ASSET_DIR": str(batch),
            "SPIDEY_BOOT_SKIP_UNTIL": BOOT_SKIP_ANCHOR,
            "SPIDEY_LEVEL": level,
            "SPIDEY_HZ": "60",
            "SPIDEY_SCRIPT": INPUT_SCRIPT,
            "SPIDEY_SHOTS": shots,
            "SPIDEY_SHOT_DIR": str(level_dir),
            "SPIDEY_EXIT": str(exit_frame),
            "SPIDEY_LOG_DIR": str(level_dir),
            "SPIDEY_STALL_EXIT": "1",
            "SPIDEY_TRACE_GAME": "1",
            "SPIDEY_TRACE_WAD": "1",
            "SPIDEY_CHEATS": "invuln",
        }
    )
    if dump_textures:
        env["SPIDEY_DUMP_TEXTURES"] = "pages"
        env["RECOMP_TEXTURE_DUMP_DIR"] = str(level_dir / "texture-dump")
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
        text = result.stdout or ""
        return_code: int | None = result.returncode
        timed_out = False
    except subprocess.TimeoutExpired as error:
        text = (error.stdout or "") if isinstance(error.stdout, str) else (error.stdout or b"").decode(errors="replace")
        return_code = None
        timed_out = True
    console_path.write_text(text, encoding="utf-8")
    return summarize_level(
        level,
        level_dir,
        console_path,
        text,
        return_code,
        timed_out,
        exit_frame,
        False,
        render_scale,
        shots,
    )


def main() -> None:
    args = parse_args()
    exe = args.exe.resolve()
    batch = args.batch.resolve()
    output = args.output.resolve()
    trigger_dir = args.triggers.resolve()
    manifest_path = (args.manifest or batch / "manifest.json").resolve()
    levels = tuple(item.strip().lower() for item in args.levels.split(",") if item.strip())
    if not levels:
        raise ValueError("--levels produced an empty level set")
    if args.concurrency < 1:
        raise ValueError("--concurrency must be positive")
    if args.render_scale != 4:
        raise ValueError("--render-scale must be 4 for reviewable runtime evidence")
    output.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runtime_target = all_story_actor_names(manifest, trigger_dir)
    print(
        f"launching {len(levels)} levels at concurrency {args.concurrency}; "
        f"runtime target is {len(runtime_target)} story-loaded actors",
        flush=True,
    )

    results: list[dict[str, Any]] = []
    for level in levels:
        level_shots = (
            LEVEL_SHOT_OVERRIDES.get(level, args.shots)
            if args.shots == DEFAULT_SHOTS
            else args.shots
        )
        level_exit_frame = (
            LEVEL_EXIT_OVERRIDES.get(level, args.exit_frame)
            if args.exit_frame == DEFAULT_EXIT_FRAME
            else args.exit_frame
        )
        result = run_level(
            level,
            exe,
            batch,
            output,
            args.render_scale,
            level_shots,
            level_exit_frame,
            args.timeout,
            args.resume,
            args.dump_textures,
        )
        results.append(result)
        print(
            f"{result['status'].upper():4s} {result['level']:6s} "
            f"overrides={len(result['loadedOverrides']):2d} "
            f"captures={len(result['captures']):2d}",
            flush=True,
        )
        if result["status"] != "pass" and not args.continue_on_failure:
            print("stopping matrix at the first failed level", file=sys.stderr, flush=True)
            break

    results.sort(key=lambda item: levels.index(item["level"]))
    loaded = {name for result in results for name in result["loadedOverrides"]}
    covered = {
        target
        for target in runtime_target
        if loaded & RUNTIME_EQUIVALENTS.get(target, {target})
    }
    missing = sorted(runtime_target - covered)
    report = {
        "schemaVersion": 4,
        "manifest": str(manifest_path),
        "batch": str(batch),
        "inputMethod": "process-local SPIDEY_SCRIPT controller state",
        "processPolicy": "strictly sequential; never more than one SpiderMan process",
        "renderScale": args.render_scale,
        "levels": list(levels),
        "levelCount": len(levels),
        "passedLevelCount": sum(result["status"] == "pass" for result in results),
        "runtimeTargetCount": len(runtime_target),
        "runtimeCoveredCount": len(covered),
        "runtimeCoveredActors": sorted(covered),
        "runtimeMissingActors": missing,
        "results": results,
        "coveragePolicy": "requested-levels" if args.allow_partial_coverage else "all-story-actors",
        "captureGate": (
            "boot FMV skip plus requested level-geometry load ordering, native "
            "live-3D 16bpp readback, non-zero level RunFrame or exact gameplay-HUD "
            "signature, and explicit GAME OVER and SAVE GAME PROGRESS rejection; "
            "the retail invulnerability flag prevents idle "
            "validation runs from dying before capture"
        ),
        "status": "pass"
        if all(result["status"] == "pass" for result in results)
        and (args.allow_partial_coverage or not missing)
        else "fail",
    }
    report_path = output / "runtime-validation.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"{report['status'].upper()}: {report['passedLevelCount']}/{report['levelCount']} levels; "
        f"{report['runtimeCoveredCount']}/{report['runtimeTargetCount']} story-loaded actors"
    )
    if missing:
        print("missing runtime actor coverage: " + ", ".join(missing), file=sys.stderr)
    print(f"report: {report_path}")
    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
