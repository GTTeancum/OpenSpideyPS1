#!/usr/bin/env python3
"""Port every Dreamcast SM1 actor model into PS1 SM1's loose-WAD format.

The actor census is format-driven: a Dreamcast v6 container is an actor when it
contains both a skeletal animation chunk (0x2A or 0x2C) and a HIER chunk.  This
captures playable variants, viewer/cutscene duplicates, NPCs, enemies and bosses
without relying on a hand-picked display-name list.  A small explicit set of
v3/v4 actor components is also copied because those files already use native PS1
containers on the Dreamcast disc.

Inputs are loose files created by the one-time extraction process.  This script
never accepts or opens BIN/CUE/GDI media.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONVERTER_PATH = ROOT / "spiderman" / "tools" / "port_dc_character.py"
ANIMATION_TAGS = {0x2A, 0x2C}
HIER_TAG = 0x52454948

# These dedicated entity files appear beside the v6 actors but already ship in
# PS1 v3/v4 form.  Some are byte-identical to SM1 PS1, while the SP_ALT and
# SOFTSPT2/3 files are Dreamcast-only additions.  Keeping them in the manifest
# makes the scope exhaustive and the no-op compatibility cases visible.
NATIVE_ACTOR_COMPONENTS = (
    "CHOPPER",
    "CLAW",
    "COPCAR",
    "GOLDFISH",
    "JJJJ",
    "SOFTEYES",
    "SOFTSPOT",
    "SOFTSPT2",
    "SOFTSPT3",
    "SP_ALT01",
    "SP_ALT02",
    "SP_ALT04",
    "SP_ALT05",
    "TURRET",
)

PLAYABLE = {
    "PARKER",
    "SP2099",
    "SPARMOR",
    "SPBAGMAN",
    "SPIDEY",
    "SPPARK",
    "SPQUICK",
    "SPREILLY",
    "SPSCAR",
    "SPSYMBI",
    "SPUNIV",
    "SPUNLIM",
    "SP_ALT01",
    "SP_ALT02",
    "SP_ALT04",
    "SP_ALT05",
}
NPCS = {
    "BC2",
    "BLACKCAT",
    "CAPTAIN",
    "DAREDEVL",
    "HOSTAGE",
    "HOSTAGEF",
    "JAMESON",
    "JJJJ",
    "JJVIEWER",
    "MARINER",
    "MJ",
    "MJVIEWER",
    "PARKER",
    "POLICE",
    "PUNISHER",
    "SWAT",
}
SUPPORT = {"CONTROL", "FIRE", "GOLDFISH", "SYM_BASE", "SYM_GEN", "VMU"}

# These files satisfy the raw chunk rule but are not characters: CONTROL is the
# Dreamcast controller shown by the menu, FIRE is an effect mesh, and VMU is the
# memory-card model.  Record them as audited exclusions instead of allowing the
# structural heuristic to silently broaden "all characters" into UI/effects.
NON_ACTOR_ANIMATED = {
    "CONTROL": "animated menu controller model",
    "FIRE": "animated fire effect",
    "VMU": "animated Visual Memory Unit model",
}


def load_converter():
    spec = importlib.util.spec_from_file_location("dc_character_converter", CONVERTER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load converter at {CONVERTER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def chunk_tags(model: Any) -> list[int]:
    tags: list[int] = []
    cursor = model.meta_top
    while True:
        tag = struct.unpack_from("<I", model.data, cursor)[0]
        if tag == 0xFFFFFFFF:
            return tags
        size = struct.unpack_from("<I", model.data, cursor + 4)[0]
        tags.append(tag)
        cursor += 8 + size


def category(name: str) -> str:
    if name in PLAYABLE:
        return "playable"
    if name in NPCS:
        return "npc_or_ally"
    if name in SUPPORT:
        return "actor_support"
    return "enemy_or_boss"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model_totals(model: Any) -> tuple[int, int, int]:
    vertices = normals = faces = 0
    for pointer in model.mesh_pointers:
        vertex_count, normal_count, face_count = struct.unpack_from("<HHH", model.data, pointer + 2)
        vertices += vertex_count
        normals += normal_count
        faces += face_count
    return vertices, normals, faces


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dc-models", type=Path, default=ROOT / "dreamcast" / "extracted")
    parser.add_argument("--dc-textures", type=Path, default=ROOT / "dreamcast" / "decoded" / "textures")
    parser.add_argument("--output", type=Path, default=ROOT / "dreamcast" / "converted" / "all-characters")
    parser.add_argument(
        "--wing-donor",
        type=Path,
        default=ROOT / "spiderman2" / "extracted" / "wad" / "spidey.psx",
    )
    parser.add_argument(
        "--texture-scale",
        type=int,
        default=4,
        help="DC dimension divisor; 4 matches the aggregate native SM1 actor texture budget",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    converter = load_converter()
    models_root = args.dc_models.resolve()
    textures_root = args.dc_textures.resolve()
    output_root = args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    # Remove only stale files that this script itself produced before the
    # audited non-actor exclusions were introduced.
    for name in NON_ACTOR_ANIMATED:
        stale = output_root / f"{name.lower()}.psx"
        if stale.is_file():
            stale.unlink()

    wing_templates = converter.load_wing_templates(args.wing_donor.resolve())
    actors: list[tuple[str, Path, Any]] = []
    scan_errors: list[dict[str, str]] = []
    for source in sorted(models_root.glob("*.PSX")):
        try:
            model = converter.parse_model(source)
        except ValueError as error:
            # v3/v4 files are handled by the explicit native-component pass.
            if "expected Dreamcast v6" not in str(error):
                scan_errors.append({"source": str(source), "error": str(error)})
            continue
        tags = set(chunk_tags(model))
        if tags & ANIMATION_TAGS and HIER_TAG in tags:
            name = source.stem.upper()
            if name not in NON_ACTOR_ANIMATED:
                actors.append((name, source, model))

    entries: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for name, source, model in actors:
        destination = output_root / f"{name.lower()}.psx"
        texture_dir = textures_root / name
        try:
            wings = wing_templates if name == "SPIDEY" else None
            converted = converter.build_character(model, texture_dir, args.texture_scale, wings)
            destination.write_bytes(converted)
            if name == "SPIDEY":
                companion = converter.build_texture_library(
                    model,
                    texture_dir,
                    args.texture_scale,
                    True,
                )
                (output_root / "sp_tex00.psx").write_bytes(companion)
            vertices, normals, faces = model_totals(model)
            entries.append(
                {
                    "name": name,
                    "category": category(name),
                    "sourceVersion": 6,
                    "action": "converted_v6_to_v4",
                    "source": str(source),
                    "output": str(destination),
                    "objects": model.object_count,
                    "meshes": model.mesh_count,
                    "vertices": vertices,
                    "normals": normals,
                    "faces": faces,
                    "textures": len(model.textures) + int(name == "SPIDEY"),
                    "wingCapable": name == "SPIDEY",
                    "bytes": destination.stat().st_size,
                    "sha256": digest(destination),
                    "status": "written",
                }
            )
            print(f"converted {name:12s} -> {destination.name} ({destination.stat().st_size:,} bytes)")
        except Exception as error:  # continue so the manifest exposes every failure
            failures.append({"name": name, "source": str(source), "error": str(error)})
            print(f"FAILED    {name:12s} {error}", file=sys.stderr)

    for name in NATIVE_ACTOR_COMPONENTS:
        source = models_root / f"{name}.PSX"
        destination = output_root / f"{name.lower()}.psx"
        try:
            data = source.read_bytes()
            version, magic = struct.unpack_from("<HH", data, 0)
            if version not in (3, 4) or magic != 2:
                raise ValueError(f"expected native v3/v4 magic 0002, got v{version} magic {magic:04X}")
            shutil.copy2(source, destination)
            entries.append(
                {
                    "name": name,
                    "category": category(name),
                    "sourceVersion": version,
                    "action": "copied_native_ps1_container",
                    "source": str(source),
                    "output": str(destination),
                    "wingCapable": False,
                    "bytes": destination.stat().st_size,
                    "sha256": digest(destination),
                    "status": "written",
                }
            )
            print(f"copied    {name:12s} -> {destination.name} ({destination.stat().st_size:,} bytes)")
        except Exception as error:
            failures.append({"name": name, "source": str(source), "error": str(error)})
            print(f"FAILED    {name:12s} {error}", file=sys.stderr)

    entries.sort(key=lambda entry: entry["name"])
    manifest = {
        "schemaVersion": 1,
        "sourceKind": "loose Dreamcast extraction",
        "targetKind": "loose PS1 SM1 WAD overrides",
        "textureScaleDivisor": args.texture_scale,
        "animatedHierarchyRule": "(tag 0x2A or 0x2C) and tag HIER/0x52454948",
        "excludedAnimatedModels": NON_ACTOR_ANIMATED,
        "actorCount": len(entries),
        "convertedV6Count": sum(entry["action"] == "converted_v6_to_v4" for entry in entries),
        "nativeContainerCount": sum(
            entry["action"] == "copied_native_ps1_container" for entry in entries
        ),
        "scanErrors": scan_errors,
        "failures": failures,
        "entries": entries,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(
        f"manifest: {manifest_path} ({len(entries)} actors, "
        f"{len(failures)} failures, {len(scan_errors)} scan errors)"
    )
    if failures or scan_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
