#!/usr/bin/env python3
"""Run SM1's costume persistence, unlock-migration, and ability self-test.

The assertions execute against live PSMemory inside one recompiled game process.
No host input or window automation is used.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXE = (
    ROOT / "spiderman" / "port" / "bin" / "Release" / "net10.0" / "SpiderMan.exe"
)
DEFAULT_ASSETS = ROOT / "dreamcast" / "converted" / "all-characters"
DEFAULT_OUTPUT = ROOT / "proof_render" / "costume-system" / "state-self-test"
PASS_LINE = (
    "[costume-self-test] PASS 9 paired unlock migrations; "
    "20 persistent selections; 20 independent ability configs; "
    "Peter donor count 0; default ability trio only"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=60)
    return parser.parse_args()


def ensure_one_process() -> None:
    probe = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "@(Get-Process SpiderMan -ErrorAction SilentlyContinue).Count",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if probe.returncode != 0:
        raise RuntimeError(probe.stderr.strip() or "could not inspect SpiderMan processes")
    if int(probe.stdout.strip() or "0") != 0:
        raise RuntimeError("refusing to launch while SpiderMan.exe is already running")


def main() -> None:
    args = parse_args()
    exe = args.exe.resolve()
    assets = args.assets.resolve()
    output = args.output.resolve()
    if not exe.is_file():
        raise FileNotFoundError(exe)
    if not assets.is_dir():
        raise FileNotFoundError(assets)
    ensure_one_process()
    output.mkdir(parents=True, exist_ok=True)

    env = {key: value for key, value in os.environ.items() if not key.startswith("SPIDEY_")}
    env.update(
        {
            "SPIDEY_ASSET_DIR": str(assets),
            "SPIDEY_COSTUME_SELF_TEST": "1",
            "SPIDEY_EXIT": "120",
            "SPIDEY_LOG_DIR": str(output),
            "SPIDEY_STALL_EXIT": "1",
        }
    )
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
    (output / "console.log").write_text(console, encoding="utf-8")

    ability_lines = re.findall(r"^\[costume\] ability config .+$", console, re.MULTILINE)
    markers = {
        "liveMemorySelfTest": PASS_LINE in console,
        "allTwentyAbilityWrites": len(ability_lines) == 20,
        "cleanExit": "[capture] exit at frame 120" in console,
        "singleProcessPolicy": True,
    }
    status = "pass" if result.returncode == 0 and all(markers.values()) else "fail"
    report = {
        "schemaVersion": 1,
        "status": status,
        "exe": str(exe),
        "assets": str(assets),
        "returnCode": result.returncode,
        "markers": markers,
        "abilityWriteCount": len(ability_lines),
        "assertions": {
            "pairedUnlockMigrations": 9,
            "persistentSelections": 20,
            "independentAbilityConfigurations": 20,
            "peterParkerImportedAbilityDonors": 0,
            "defaultAbilityImportedCopies": [18, 19],
            "defaultUnlockedSlots": [0, 19],
        },
    }
    report_path = output / "runtime-validation.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{status.upper()}: SM1 costume live-memory state self-test")
    print(f"report: {report_path}")
    if status != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
