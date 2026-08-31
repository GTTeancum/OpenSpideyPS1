#!/usr/bin/env python3
"""Validate the visible retail wing art and production magenta paint-out."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
CONVERTER = ROOT / "spiderman" / "tools" / "port_dc_character.py"


def load_converter():
    spec = importlib.util.spec_from_file_location("dc_character_converter", CONVERTER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load converter at {CONVERTER}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--visible",
        type=Path,
        default=ROOT / "dreamcast" / "converted" / "sm1-winged-runtime" / "sp_tex00.psx",
    )
    parser.add_argument(
        "--production",
        type=Path,
        default=ROOT / "dreamcast" / "converted" / "sm1-winged-production" / "sp_tex00.psx",
    )
    parser.add_argument(
        "--donor",
        type=Path,
        default=ROOT / "spiderman2" / "extracted" / "wad" / "sp_tex00.psx",
    )
    parser.add_argument(
        "--production-captures",
        type=Path,
        default=ROOT
        / "dreamcast"
        / "converted"
        / "sm1-winged-production"
        / "runtime-magenta-proof",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "dreamcast" / "converted" / "wing-texture-validation.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    converter = load_converter()
    visible = converter.load_ps1_texture_asset(args.visible.resolve(), converter.WING_HASH)
    production = converter.load_ps1_texture_asset(args.production.resolve(), converter.WING_HASH)
    donor = converter.load_ps1_texture_asset(args.donor.resolve(), converter.WING_HASH)
    runtime_frames = {}
    for frame in (4100, 4150, 4200, 4300):
        path = args.production_captures.resolve() / f"frame_{frame:05d}.png"
        with Image.open(path) as image:
            image.load()
            runtime_frames[str(frame)] = {
                "path": str(path),
                "size": list(image.size),
                "format": image.format,
            }

    checks = {
        "visibleDimensionsExact": (visible.width, visible.height) == (64, 64),
        "visiblePaletteExactToDonor": visible.palette == donor.palette,
        "visiblePixelsExactToDonor": visible.payload == donor.payload,
        "productionDimensionsExact": (production.width, production.height) == (64, 64),
        "productionPaletteAllMagentaKey": set(production.palette) == {converter.MAGENTA_555},
        "productionPixelsAllPaletteZero": set(production.payload) == {0},
        "productionRuntimeFramesPresent": len(runtime_frames) == 4
        and all(item["format"] == "PNG" and item["size"] == [2560, 1920] for item in runtime_frames.values()),
    }
    report = {
        "schemaVersion": 1,
        "checks": checks,
        "visible": str(args.visible.resolve()),
        "donor": str(args.donor.resolve()),
        "production": str(args.production.resolve()),
        "productionRuntimeFrames": runtime_frames,
    }
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise SystemExit(f"FAIL: wing texture validation failed: {', '.join(failed)}")
    print(
        "PASS: visible wing payload is donor-exact; production wing payload is "
        "64x64 all-magenta/all-zero paint-out; 4 production runtime frames verified"
    )
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
