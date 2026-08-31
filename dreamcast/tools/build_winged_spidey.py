#!/usr/bin/env python3
"""Build the wing-capable Dreamcast SM1 Spider-Man binary.

This is intentionally a thin, auditable entry point over
``spiderman/tools/port_dc_character.py``. It does not invent a Blender mesh.
It copies SM2's seven native wing primitives, their UV payloads and normals,
and preserves their native type-2 stitch weighting. Donor attachment sources
are copied verbatim into the corresponding DC body parts, including normals.
Two recipient-specific, double-sided seam triangles extend those authored
membranes to the denser Dreamcast armpit surface without changing body faces.

All inputs are loose files. BIN/CUE/GDI media is neither accepted nor opened.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys


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
        "--model",
        type=Path,
        default=ROOT / "dreamcast" / "extracted" / "SPIDEY.PSX",
    )
    parser.add_argument(
        "--textures",
        type=Path,
        default=ROOT / "dreamcast" / "decoded" / "textures" / "SPIDEY",
    )
    parser.add_argument(
        "--wing-donor",
        type=Path,
        default=ROOT / "spiderman2" / "extracted" / "wad" / "spidey.psx",
    )
    parser.add_argument(
        "--output-model",
        type=Path,
        default=ROOT / "dreamcast" / "converted" / "sm1-winged-runtime" / "spidey.psx",
    )
    parser.add_argument(
        "--output-textures",
        type=Path,
        default=ROOT / "dreamcast" / "converted" / "sm1-winged-runtime" / "sp_tex00.psx",
    )
    parser.add_argument(
        "--texture-scale",
        type=int,
        default=1,
        help="DC dimension divisor; 1 preserves the original Dreamcast texture resolution",
    )
    parser.add_argument(
        "--visible-wing-proof",
        action="store_true",
        help=(
            "replace only the normally transparent wing texture with the retail SM2 "
            "black/white artwork for in-game attachment and mapping proof"
        ),
    )
    parser.add_argument(
        "--wing-texture-donor",
        type=Path,
        default=ROOT / "spiderman2" / "extracted" / "wad" / "sp_tex00.psx",
        help="loose SM2 default texture library supplying the real black/white wing art",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    converter = load_converter()
    model = converter.parse_model(args.model.resolve())
    donor = converter.load_wing_templates(args.wing_donor.resolve())
    proof_asset = (
        converter.load_ps1_texture_asset(args.wing_texture_donor.resolve(), converter.WING_HASH)
        if args.visible_wing_proof
        else None
    )
    character = converter.build_character(
        model,
        args.textures.resolve(),
        args.texture_scale,
        donor,
        args.visible_wing_proof,
        proof_asset,
    )
    texture_library = converter.build_texture_library(
        model,
        args.textures.resolve(),
        args.texture_scale,
        True,
        args.visible_wing_proof,
        proof_asset,
    )

    args.output_model.parent.mkdir(parents=True, exist_ok=True)
    args.output_textures.parent.mkdir(parents=True, exist_ok=True)
    args.output_model.write_bytes(character)
    args.output_textures.write_bytes(texture_library)
    print(
        f"wrote donor-preserving, DC-seam-fitted winged model {args.output_model.resolve()} "
        f"({len(character):,} bytes, sha256 {converter.sha256(character)})"
    )
    print(
        f"wrote {'visible proof' if args.visible_wing_proof else 'magenta-key'} "
        f"texture library {args.output_textures.resolve()} "
        f"({len(texture_library):,} bytes, sha256 {converter.sha256(texture_library)})"
    )


if __name__ == "__main__":
    main()
