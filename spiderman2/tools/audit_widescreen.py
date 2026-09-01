#!/usr/bin/env python3
"""Run the SM2 widescreen coverage audit, one native game process at a time.

Each level is cold-booted through the real menus, redirected by SPIDEY_LEVEL, and
captured on four consecutive stationary gameplay samples. SPIDEY_WIDE_DEBUG paints
the game's background clear magenta, making any part of the frame that world geometry
did not cover explicit. The JSON report records every image in order; magenta is a
review flag rather than an automatic failure because open sky can legitimately expose
the clear colour.

Examples:
    python tools/audit_widescreen.py --levels e1m0,e1m1
    python tools/audit_widescreen.py --native-43 --levels e1m4,e2m3
    python tools/audit_widescreen.py --resume
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


STORY_LEVELS = (
    "e1m0", "e1m1", "e1m2", "e1m3", "e1m4",
    "e2m1", "e2m2", "e2m3",
    "e3m0", "e3m1", "e3m2", "e3m3",
    "e4m1", "e4m2",
    "e5m1", "e5m2", "e5m3", "e5m4", "e5m5", "e5m6",
    "e6m1", "e6m2", "e6m3", "e6m4",
)

SHOT_OFFSETS = (1900, 1960, 2020, 2080)
EXIT_OFFSET = 2160


def game_running() -> bool:
    if os.name != "nt":
        return False
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq SpiderMan2.exe", "/NH"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return "SpiderMan2.exe" in result.stdout


def image_metrics(path: Path) -> dict:
    with Image.open(path) as image:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    height, width = rgb.shape[:2]
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
            "SPIDEY_SHOTS": ",".join(f"{anchor}+{offset}" for offset in SHOT_OFFSETS),
            "SPIDEY_SCRIPT": ";".join(
                (
                    "title.bmr+80:start:10",
                    "title.bmr+280:cross:10",
                    "title.bmr+480:cross:10",
                    "title.bmr+700:cross:10",
                    f"{anchor}+1200:cross:8",
                    f"{anchor}+1500:cross:8",
                    f"{anchor}+1800:cross:8",
                )
            ),
            "SPIDEY_EXIT": f"{anchor}+{EXIT_OFFSET}",
        }
    )
    if magenta_debug:
        env["SPIDEY_WIDE_DEBUG"] = "1"
    if coverage_view:
        env["SPIDEY_WIDE_COVERAGE_VIEW"] = "1"
    if coverage_trace:
        env["SPIDEY_WIDE_COVERAGE_TRACE"] = "1"
    if not completed_view:
        env["SPIDEY_WIDE_RAW_GAPS"] = "1"
    if native_43:
        env["SPIDEY_WIDE"] = "0"
    else:
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
    if len(images) != len(SHOT_OFFSETS):
        failures.append(f"expected {len(SHOT_OFFSETS)} captures, found {len(images)}")
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
        "level": level,
        "presentation": (
            "4:3 control" if native_43 else f"{target_aspect:.6f}:1 widescreen"
        ),
        "coverage_mode": "completed" if completed_view else "raw gaps",
        "magenta_debug": magenta_debug,
        "fxaa": fxaa,
        "render_scale": render_scale,
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
    levels: list[str],
    results: list[dict],
    native_43: bool,
    target_aspect: float,
    completed_view: bool,
    magenta_debug: bool,
    fxaa: bool,
    render_scale: int,
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
                "method": (
                    "native in-process presented captures; stationary gameplay; "
                    f"{'4:3 control' if native_43 else f'{target_aspect:.6f}:1 widescreen'}; "
                    f"{'completed side bands' if completed_view else 'raw gaps'}; "
                    f"magenta diagnostic {'on' if magenta_debug else 'off'}; "
                    f"FXAA {'on' if fxaa else 'off'}; {render_scale}x internal scale"
                ),
                "requested_levels": levels,
                "shot_offsets": SHOT_OFFSETS,
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
    default_exe = root / "spiderman2" / "port" / "bin" / "Release" / "net10.0" / "SpiderMan2.exe"
    default_output = default_exe.parent / "proof_render" / "sm2_widescreen_audit_all"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, default=default_exe)
    parser.add_argument("--output", type=Path, default=default_output)
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
    parser.add_argument("--timeout", type=int, default=110, help="per-level timeout in seconds")
    args = parser.parse_args()
    if not 4.0 / 3.0 < args.aspect < 3.0:
        raise SystemExit("--aspect must be greater than 4:3 and less than 3.0")
    if not 1 <= args.render_scale <= 8:
        raise SystemExit("--render-scale must be between 1 and 8")

    exe = args.exe.resolve()
    output_root = args.output.resolve()
    report_path = output_root / "report.json"
    levels = list(STORY_LEVELS if not args.levels else (x.strip().lower() for x in args.levels.split(",") if x.strip()))
    if not exe.is_file():
        raise SystemExit(f"game executable not found: {exe}")
    if game_running():
        raise SystemExit("SpiderMan2.exe is already running; refusing to start the audit")
    output_root.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    if args.resume and report_path.is_file():
        old = json.loads(report_path.read_text(encoding="utf-8"))
        results = [item for item in old.get("results", []) if item.get("level") in levels and item.get("status") != "fail"]
    complete = {item["level"] for item in results}

    for index, level in enumerate(levels, 1):
        if level in complete:
            print(f"[{index}/{len(levels)}] {level}: retained", flush=True)
            continue
        if game_running():
            raise SystemExit("SpiderMan2.exe appeared during the audit; refusing a concurrent launch")
        result = run_level(
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
        )
        results = [item for item in results if item["level"] != level]
        results.append(result)
        results.sort(key=lambda item: levels.index(item["level"]))
        write_report(
            report_path,
            levels,
            results,
            args.native_43,
            args.aspect,
            args.completed_view,
            not args.no_magenta,
            args.fxaa,
            args.render_scale,
        )
        print(
            f"[{index}/{len(levels)}] {level}: {result['status']} "
            f"({len(result['images'])} frames, {result['elapsed_seconds']:.1f}s, "
            f"magenta={len(result['magenta_review_frames'])})",
            flush=True,
        )

    write_report(
        report_path,
        levels,
        results,
        args.native_43,
        args.aspect,
        args.completed_view,
        not args.no_magenta,
        args.fxaa,
        args.render_scale,
    )
    failed = [item["level"] for item in results if item["status"] == "fail"]
    review = [item["level"] for item in results if item["status"] == "review"]
    print(f"report: {report_path}")
    print(f"summary: pass={len(results) - len(failed) - len(review)} review={len(review)} fail={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
