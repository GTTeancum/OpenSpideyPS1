#!/usr/bin/env python3
"""Run the SM1 or SM2 widescreen audit, one native game process at a time.

Each level is cold-booted through the real menus, redirected by SPIDEY_LEVEL, and
captured on four consecutive stationary gameplay samples. SPIDEY_WIDE_DEBUG paints
the game's background clear magenta, making any part of the frame that world geometry
did not cover explicit. The JSON report records every image in order; magenta is a
review flag rather than an automatic failure because open sky can legitimately expose
the clear colour.

Examples:
    python tools/audit_widescreen.py --game sm1 --levels l1a1,l2a1
    python tools/audit_widescreen.py --game sm2 --native-43 --levels e1m4,e2m3
    python tools/audit_widescreen.py --game sm2 --resume
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

import numpy as np
from PIL import Image


SM1_STORY_LEVELS = (
    "l1a1", "l1a2", "l1a3", "l1a4",
    "l2a1", "l2a2",
    "l3a1", "l3a2", "l3a3",
    "l4a1",
    "l5a1", "l5a2", "l5a3",
    "l6a1", "l6a2",
    "l7a1", "l7a2",
    "l8a1", "l8a2",
    "l9a1", "l9a3",
)

SM2_STORY_LEVELS = (
    "e1m0", "e1m1", "e1m2", "e1m3", "e1m4",
    "e2m1", "e2m2", "e2m3",
    "e3m0", "e3m1", "e3m2", "e3m3",
    "e4m1", "e4m2",
    "e5m1", "e5m2", "e5m3", "e5m4", "e5m5", "e5m6",
    "e6m1", "e6m2", "e6m3", "e6m4",
)

SM1_SHOT_OFFSETS = (2500, 2560, 2620, 2680)
SM2_SHOT_OFFSETS = (1900, 1960, 2020, 2080)

# Venom's pursuit fails if a stationary test waits as long as ordinary SM1 levels.
# Capture after its objective introduction clears but before the chase timeout.
SM1_LEVEL_SHOT_OVERRIDES = {
    "l5a1": (2080, 2120, 2160, 2200),
}


GAME_PROCESS_NAMES = ("SpiderMan.exe", "SpiderMan2.exe")


def running_games() -> list[str]:
    if os.name != "nt":
        return []
    result = subprocess.run(
        ["tasklist", "/NH"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return [name for name in GAME_PROCESS_NAMES if name.lower() in result.stdout.lower()]


def title_script(game: str, anchor: str, shot_offsets: tuple[int, ...]) -> str:
    if game == "sm1":
        shell_steps = (
            "title.bmr+120:start:12",
            "title.bmr+420:cross:12",
            "title.bmr+720:cross:12",
            "title.bmr+1100:cross:12",
            "title.bmr+1500:cross:12",
            "title.bmr+1900:cross:12",
        )
    else:
        shell_steps = (
            "title.bmr+80:start:10",
            "title.bmr+280:cross:10",
            "title.bmr+480:cross:10",
            "title.bmr+700:cross:10",
        )
    # Keep advancing skippable covers and in-engine introductions until shortly
    # before the first capture. SM1 has several sequences that are still letterboxed
    # at +1900; accepting those as gameplay produced false widescreen passes.
    level_steps = tuple(
        f"{anchor}+{offset}:cross:8"
        for offset in range(1200, shot_offsets[0], 300)
    )
    return ";".join(shell_steps + level_steps)


def image_metrics(path: Path) -> dict:
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    height, width = rgb.shape[:2]
    black = np.all(rgb <= 8, axis=2)
    black_per_row = black.mean(axis=1)
    black_top_rows = 0
    for fraction in black_per_row:
        if fraction < 0.98:
            break
        black_top_rows += 1
    black_bottom_rows = 0
    for fraction in black_per_row[::-1]:
        if fraction < 0.98:
            break
        black_bottom_rows += 1
    magenta = (rgb[:, :, 0] >= 248) & (rgb[:, :, 1] <= 7) & (rgb[:, :, 2] >= 248)
    count = int(magenta.sum())
    lower_count = int(magenta[height // 2 :, :].sum())
    if count:
        ys, xs = np.nonzero(magenta)
        bounds = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
    else:
        bounds = None
    return {
        "file": path.name,
        "width": width,
        "height": height,
        "aspect": round(width / height, 6),
        "rgb_stddev": round(float(rgb.std()), 4),
        "black_top_rows": black_top_rows,
        "black_bottom_rows": black_bottom_rows,
        "magenta_pixels": count,
        "magenta_percent": round(count * 100.0 / (width * height), 6),
        "lower_half_magenta_pixels": lower_count,
        "magenta_bounds": bounds,
    }


def parse_span_audit(output: str) -> dict | None:
    matches = re.findall(
        r"span audit: wide accepted (\d+), rejected x/y (\d+)/(\d+)", output
    )
    if not matches:
        return None
    accepted, rejected_x, rejected_y = matches[-1]
    return {
        "wide_accepted": int(accepted),
        "rejected_x": int(rejected_x),
        "rejected_y": int(rejected_y),
    }


def run_level(
    game: str,
    exe: Path,
    output_root: Path,
    level: str,
    timeout: int,
    native_43: bool,
    target_aspect: float,
    completed_view: bool,
    magenta_debug: bool,
    coverage_view: bool,
    coverage_trace: bool,
    fxaa: bool,
    render_scale: int,
    proof_trigger: int | None,
    trace_call: str | None,
    shot_offsets: tuple[int, ...],
) -> dict:
    anchor = f"{level}_t.trg"
    level_dir = output_root / level
    level_dir.mkdir(parents=True, exist_ok=True)
    for old in level_dir.glob("frame_*.png"):
        old.unlink()

    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("SPIDEY_") or key in {"RECOMP_FXAA", "RECOMP_RENDER_SCALE"}:
            env.pop(key, None)

    env.update(
        {
            "SPIDEY_RUN_TOKEN": uuid.uuid4().hex,
            "SPIDEY_BOOT_SKIP_UNTIL": "title.bmr",
            "SPIDEY_HZ": "60",
            "SPIDEY_LEVEL": level,
            "SPIDEY_CAPTURE_PRESENTED": "1",
            "SPIDEY_QUIET": "1",
            "SPIDEY_STALL": "20",
            "SPIDEY_STALL_EXIT": "1",
            "RECOMP_FXAA": "1" if fxaa else "0",
            "RECOMP_RENDER_SCALE": str(render_scale),
            "SPIDEY_SHOT_DIR": str(level_dir),
            "SPIDEY_SHOTS": ",".join(f"{anchor}+{offset}" for offset in shot_offsets),
            "SPIDEY_SCRIPT": title_script(game, anchor, shot_offsets),
            "SPIDEY_EXIT": f"{anchor}+{max(shot_offsets) + 80}",
        }
    )
    if game == "sm1":
        # Bosses can kill a stationary audit target before the four captures. Use the
        # retail flag so the renderer stays in live gameplay rather than GAME OVER.
        env["SPIDEY_CHEATS"] = "invuln"
    if magenta_debug:
        env["SPIDEY_WIDE_DEBUG"] = "1"
    if coverage_view:
        env["SPIDEY_WIDE_COVERAGE_VIEW"] = "1"
    if coverage_trace:
        env["SPIDEY_WIDE_COVERAGE_TRACE"] = "1"
    if proof_trigger is not None:
        env["SPIDEY_PROOF_TRIGGER"] = str(proof_trigger)
    if trace_call:
        env["RECOMP_TRACE_CALL"] = trace_call
    if not completed_view:
        env["SPIDEY_WIDE_RAW_GAPS"] = "1"
    if native_43:
        env["SPIDEY_WIDE"] = "0"
    else:
        # SM1 ships widescreen as an opt-in path. SM2 defaults to widescreen, so leaving
        # SPIDEY_WIDE absent deliberately verifies its production default.
        if game == "sm1":
            env["SPIDEY_WIDE"] = "1"
        env["SPIDEY_WIDE_ASPECT"] = f"{target_aspect:.8f}"

    started = time.monotonic()
    try:
        process = subprocess.run(
            [str(exe)],
            cwd=exe.parent,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        output = process.stdout
        return_code = process.returncode
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or "") + "\n[audit] process timed out\n"
        return_code = -1

    (level_dir / "run.log").write_text(output, encoding="utf-8", errors="replace")
    images = [image_metrics(path) for path in sorted(level_dir.glob("frame_*.png"))]
    failures: list[str] = []
    if return_code != 0:
        failures.append(f"process returned {return_code}")
    if len(images) != len(shot_offsets):
        failures.append(f"expected {len(shot_offsets)} captures, found {len(images)}")
    expected_aspect = 4.0 / 3.0 if native_43 else target_aspect
    expected_label = "4:3" if native_43 else f"{target_aspect:.3f}:1"
    for image in images:
        if abs(image["aspect"] - expected_aspect) > 0.005:
            failures.append(
                f"{image['file']} is not {expected_label} "
                f"({image['width']}x{image['height']})"
            )
        if image["rgb_stddev"] < 5.0:
            failures.append(f"{image['file']} has near-flat output")
        if (
            image["black_top_rows"] >= image["height"] * 0.05
            and image["black_bottom_rows"] >= image["height"] * 0.05
        ):
            failures.append(
                f"{image['file']} is letterboxed/cinematic "
                f"(black rows {image['black_top_rows']} top, "
                f"{image['black_bottom_rows']} bottom)"
            )
    if f"{level.upper()}_G.psx" not in output and f"{level}_G.psx" not in output:
        failures.append("level geometry archive was not loaded")
    if not native_43:
        if "[wide] aspect" not in output:
            failures.append("widescreen patch did not arm")
        if f"[Host] fitting window to {target_aspect:.3f} output" not in output:
            failures.append(
                f"host window was not fitted to the {target_aspect:.3f}:1 "
                "gameplay output"
            )
    elif "[wide] aspect" in output:
        failures.append("widescreen patch armed during the native-4:3 control")

    magenta_frames = [image["file"] for image in images if image["magenta_pixels"]]
    status = "fail" if failures else "review" if magenta_frames else "pass"
    return {
        "game": game,
        "level": level,
        "presentation": (
            "4:3 control" if native_43 else f"{target_aspect:.6f}:1 widescreen"
        ),
        "coverage_mode": "completed" if completed_view else "raw gaps",
        "magenta_debug": magenta_debug,
        "fxaa": fxaa,
        "render_scale": render_scale,
        "shot_offsets": shot_offsets,
        "stationary_protection": "retail invulnerability cheat" if game == "sm1" else None,
        "status": status,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "return_code": return_code,
        "failures": failures,
        "magenta_review_frames": magenta_frames,
        "span_audit": parse_span_audit(output),
        "images": images,
        "log": str(level_dir / "run.log"),
    }


def write_report(
    path: Path,
    game: str,
    levels: list[str],
    results: list[dict],
    native_43: bool,
    target_aspect: float,
    completed_view: bool,
    magenta_debug: bool,
    fxaa: bool,
    render_scale: int,
    shot_offsets: tuple[int, ...],
    level_shot_overrides: dict[str, tuple[int, ...]],
) -> None:
    summary = {
        "pass": sum(item["status"] == "pass" for item in results),
        "review": sum(item["status"] == "review" for item in results),
        "fail": sum(item["status"] == "fail" for item in results),
    }
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "game": game,
                "method": (
                    "native in-process presented captures; stationary gameplay; "
                    f"{'4:3 control' if native_43 else f'{target_aspect:.6f}:1 widescreen'}; "
                    f"{'completed side bands' if completed_view else 'raw gaps'}; "
                    f"magenta diagnostic {'on' if magenta_debug else 'off'}; "
                    f"FXAA {'on' if fxaa else 'off'}; {render_scale}x internal scale; "
                    f"{'retail invulnerability cheat' if game == 'sm1' else 'no stationary protection'}"
                ),
                "requested_levels": levels,
                "shot_offsets": shot_offsets,
                "level_shot_overrides": level_shot_overrides,
                "summary": summary,
                "results": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", choices=("sm1", "sm2"), default="sm2")
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--levels", help="comma-separated level prefixes; default is every story level")
    parser.add_argument("--resume", action="store_true", help="keep completed pass/review results from report.json")
    parser.add_argument(
        "--native-43",
        action="store_true",
        help="run the same diagnostic in native 4:3 as a control",
    )
    parser.add_argument(
        "--aspect",
        type=float,
        default=16.0 / 9.0,
        help="widescreen aspect ratio to audit; default is 16:9",
    )
    parser.add_argument(
        "--completed-view",
        action="store_true",
        help="enable side-band completion instead of the default raw-gap audit",
    )
    parser.add_argument(
        "--no-magenta",
        action="store_true",
        help="disable the magenta clear diagnostic for clean final proofs",
    )
    parser.add_argument(
        "--coverage-view",
        action="store_true",
        help="render the primitive/world coverage mask for diagnostics",
    )
    parser.add_argument(
        "--coverage-trace",
        action="store_true",
        help="log unique large screen-space primitives for coverage diagnostics",
    )
    parser.add_argument(
        "--fxaa",
        action="store_true",
        help="enable production FXAA for presentation proofs",
    )
    parser.add_argument(
        "--render-scale",
        type=int,
        default=2,
        help="internal render scale; diagnostic default is 2",
    )
    parser.add_argument(
        "--proof-trigger",
        type=int,
        help="SM1 only: activate this real trigger record after gameplay initializes",
    )
    parser.add_argument(
        "--trace-call",
        help="count an exact recompiled function address (hex, with or without 0x)",
    )
    parser.add_argument(
        "--shot-offsets",
        help=(
            "four comma-separated capture offsets from the level trigger load; "
            "defaults are later for SM1 so in-engine introductions can finish"
        ),
    )
    parser.add_argument("--timeout", type=int, default=110, help="per-level timeout in seconds")
    args = parser.parse_args()
    if not 4.0 / 3.0 < args.aspect < 3.0:
        raise SystemExit("--aspect must be greater than 4:3 and less than 3.0")
    if not 1 <= args.render_scale <= 8:
        raise SystemExit("--render-scale must be between 1 and 8")
    if args.proof_trigger is not None and args.game != "sm1":
        raise SystemExit("--proof-trigger currently applies only to SM1")
    if args.proof_trigger is not None and args.proof_trigger < 0:
        raise SystemExit("--proof-trigger must be non-negative")

    default_shots = SM1_SHOT_OFFSETS if args.game == "sm1" else SM2_SHOT_OFFSETS
    if args.shot_offsets:
        try:
            shot_offsets = tuple(int(value.strip()) for value in args.shot_offsets.split(","))
        except ValueError as exc:
            raise SystemExit("--shot-offsets must contain integers") from exc
        if len(shot_offsets) != 4 or any(value <= 0 for value in shot_offsets):
            raise SystemExit("--shot-offsets requires exactly four positive offsets")
        if tuple(sorted(shot_offsets)) != shot_offsets or len(set(shot_offsets)) != 4:
            raise SystemExit("--shot-offsets must be unique and ascending")
    else:
        shot_offsets = default_shots
    level_shot_overrides = (
        {}
        if args.shot_offsets or args.game != "sm1"
        else SM1_LEVEL_SHOT_OVERRIDES
    )

    exe_name = "SpiderMan.exe" if args.game == "sm1" else "SpiderMan2.exe"
    game_dir = "spiderman" if args.game == "sm1" else "spiderman2"
    default_exe = root / game_dir / "port" / "bin" / "Release" / "net10.0" / exe_name
    exe = (args.exe or default_exe).resolve()
    default_output = exe.parent / "proof_render" / f"{args.game}_widescreen_audit_all"
    output_root = (args.output or default_output).resolve()
    report_path = output_root / "report.json"
    story_levels = SM1_STORY_LEVELS if args.game == "sm1" else SM2_STORY_LEVELS
    levels = list(story_levels if not args.levels else (x.strip().lower() for x in args.levels.split(",") if x.strip()))
    if not exe.is_file():
        raise SystemExit(f"game executable not found: {exe}")
    running = running_games()
    if running:
        raise SystemExit(f"{', '.join(running)} is already running; refusing to start the audit")
    output_root.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    if args.resume and report_path.is_file():
        old = json.loads(report_path.read_text(encoding="utf-8"))
        expected_presentation = (
            "4:3 control" if args.native_43 else f"{args.aspect:.6f}:1 widescreen"
        )
        compatible = old.get("game") == args.game
        if compatible:
            results = [
                item
                for item in old.get("results", [])
                if item.get("level") in levels
                and item.get("status") != "fail"
                and item.get("presentation") == expected_presentation
                and item.get("coverage_mode")
                == ("completed" if args.completed_view else "raw gaps")
                and item.get("magenta_debug") == (not args.no_magenta)
                and item.get("fxaa") == args.fxaa
                and item.get("render_scale") == args.render_scale
                and item.get("shot_offsets")
                == list(level_shot_overrides.get(item.get("level"), shot_offsets))
                and item.get("stationary_protection")
                == ("retail invulnerability cheat" if args.game == "sm1" else None)
            ]
    complete = {item["level"] for item in results}

    for index, level in enumerate(levels, 1):
        if level in complete:
            print(f"[{index}/{len(levels)}] {level}: retained", flush=True)
            continue
        running = running_games()
        if running:
            raise SystemExit(
                f"{', '.join(running)} appeared during the audit; refusing a concurrent launch"
            )
        level_shot_offsets = level_shot_overrides.get(level, shot_offsets)
        result = run_level(
            args.game,
            exe,
            output_root,
            level,
            args.timeout,
            args.native_43,
            args.aspect,
            args.completed_view,
            not args.no_magenta,
            args.coverage_view,
            args.coverage_trace,
            args.fxaa,
            args.render_scale,
            args.proof_trigger,
            args.trace_call,
            level_shot_offsets,
        )
        results = [item for item in results if item["level"] != level]
        results.append(result)
        results.sort(key=lambda item: levels.index(item["level"]))
        write_report(
            report_path,
            args.game,
            levels,
            results,
            args.native_43,
            args.aspect,
            args.completed_view,
            not args.no_magenta,
            args.fxaa,
            args.render_scale,
            shot_offsets,
            level_shot_overrides,
        )
        print(
            f"[{index}/{len(levels)}] {level}: {result['status']} "
            f"({len(result['images'])} frames, {result['elapsed_seconds']:.1f}s, "
            f"magenta={len(result['magenta_review_frames'])})",
            flush=True,
        )

    write_report(
        report_path,
        args.game,
        levels,
        results,
        args.native_43,
        args.aspect,
        args.completed_view,
        not args.no_magenta,
        args.fxaa,
        args.render_scale,
        shot_offsets,
        level_shot_overrides,
    )
    failed = [item["level"] for item in results if item["status"] == "fail"]
    review = [item["level"] for item in results if item["status"] == "review"]
    print(f"report: {report_path}")
    print(f"summary: pass={len(results) - len(failed) - len(review)} review={len(review)} fail={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
