#!/usr/bin/env python3
"""Launch a minimal level set that exercises every story-loaded DC actor override.

Input is injected only through the recompilation's process-local controller script.
No host keyboard, mouse, or desktop automation is used.  Each child process writes an
isolated log and native GPU screenshots, which are then checked and summarized.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
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
RUNTIME_EQUIVALENTS = {
    # Trigger/overlay names are not always model names.  These pairs are the retail
    # game's own resource choices, while every exact file still receives the separate
    # independent decode/reconstruct/render audit.
    "jjjj": {"jjjj", "jameson"},
    "lizman": {"lizman", "lizman2"},
    "thug": {"thug", "henchman", "henchngt"},
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
    parser.add_argument("--render-scale", type=int, default=1)
    parser.add_argument("--shots", default="4300,4400")
    parser.add_argument("--exit-frame", type=int, default=4450)
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
    return parser.parse_args()


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
) -> dict[str, Any]:
    overrides = sorted(
        {
            match.group(1).lower().removesuffix(".psx")
            for match in re.finditer(r"\[loose-wad\] override ([^:\s]+\.psx):", text, re.I)
        }
    )
    captures = sorted(level_dir.glob("frame_*.png"))
    capture_sizes: dict[str, list[int]] = {}
    for path in captures:
        with Image.open(path) as image:
            image.verify()
            capture_sizes[path.name] = [image.width, image.height]
    clean_exit = f"[capture] exit at frame {exit_frame}" in text
    bad_markers = [
        marker
        for marker in ("Unhandled exception", "watchdog: STALLED", "MISSED -- overlay not resident")
        if marker.lower() in text.lower()
    ]
    status = (
        "pass"
        if not timed_out and return_code == 0 and clean_exit and captures and not bad_markers
        else "fail"
    )
    return {
        "level": level,
        "status": status,
        "returnCode": return_code,
        "timedOut": timed_out,
        "cleanExit": clean_exit,
        "badMarkers": bad_markers,
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
        )
        if existing["status"] == "pass":
            return existing

    env = {key: value for key, value in os.environ.items() if not key.startswith("SPIDEY_")}
    env.pop("RECOMP_RENDER_SCALE", None)
    env.update(
        {
            "RECOMP_RENDER_SCALE": str(render_scale),
            "SPIDEY_ASSET_DIR": str(batch),
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
        level, level_dir, console_path, text, return_code, timed_out, exit_frame, False
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
    output.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    runtime_target = all_story_actor_names(manifest, trigger_dir)
    print(
        f"launching {len(levels)} levels at concurrency {args.concurrency}; "
        f"runtime target is {len(runtime_target)} story-loaded actors"
    )

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(
                run_level,
                level,
                exe,
                batch,
                output,
                args.render_scale,
                args.shots,
                args.exit_frame,
                args.timeout,
                args.resume,
                args.dump_textures,
            ): level
            for level in levels
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(
                f"{result['status'].upper():4s} {result['level']:6s} "
                f"overrides={len(result['loadedOverrides']):2d} "
                f"captures={len(result['captures']):2d}"
            )

    results.sort(key=lambda item: levels.index(item["level"]))
    loaded = {name for result in results for name in result["loadedOverrides"]}
    covered = {
        target
        for target in runtime_target
        if loaded & RUNTIME_EQUIVALENTS.get(target, {target})
    }
    missing = sorted(runtime_target - covered)
    report = {
        "schemaVersion": 1,
        "manifest": str(manifest_path),
        "batch": str(batch),
        "inputMethod": "process-local SPIDEY_SCRIPT controller state",
        "levels": list(levels),
        "levelCount": len(levels),
        "passedLevelCount": sum(result["status"] == "pass" for result in results),
        "runtimeTargetCount": len(runtime_target),
        "runtimeCoveredCount": len(covered),
        "runtimeCoveredActors": sorted(covered),
        "runtimeMissingActors": missing,
        "results": results,
        "coveragePolicy": "requested-levels" if args.allow_partial_coverage else "all-story-actors",
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
