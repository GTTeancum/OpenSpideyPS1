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

from PIL import Image


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

FNV_OFFSET = 1469598103934665603
FNV_PRIME = 1099511628211
MAGENTA_555 = 0x7C1F

# SM1's costume selector always asks for spidey.psx plus sp_tex00..09.  Dreamcast
# ships one high-detail actor per slot, so the runtime aliases the model request
# and this batch supplies a same-slot texture companion authored from that actor.
COSTUME_MODELS = (
    ("spiderman", "SPIDEY"),
    ("2099", "SP2099"),
    ("symbiote", "SPSYMBI"),
    ("captain", "SPUNIV"),
    ("unlimited", "SPUNLIM"),
    ("bagman", "SPBAGMAN"),
    ("scarlet", "SPSCAR"),
    ("benreilly", "SPREILLY"),
    ("quickchange", "SPQUICK"),
    ("peterparker", "SPPARK"),
)

# These Dreamcast actors contain platform-specific animation/lighting metadata
# that SM1's v4 runtime cannot consume verbatim. Reorder the high-detail meshes
# by stable mesh name and pair them with the matching retail SM1 skeleton. The
# Dreamcast geometry, UVs, material hashes, and original-resolution textures stay
# in use; only SM1-native object/hierarchy/animation semantics come from donors.
SM1_SKELETON_DONORS = {
    "JAMESON": "jameson.psx",
    "JJVIEWER": "jjviewer.psx",
    "PARKER": "parker.psx",
    "SCORPION": "scorpion.psx",
}
FULL_SM1_SKELETON_DONORS = {"SCORPION"}


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


def image_digest(path: Path) -> str:
    with Image.open(path) as image:
        image = image.convert("RGBA")
    rgba = image.convert("RGBA")
    return hashlib.sha256(
        struct.pack("<II", rgba.width, rgba.height) + rgba.tobytes()
    ).hexdigest()


def fnv1a64(data: bytes) -> int:
    value = FNV_OFFSET
    for byte in data:
        value = ((value ^ byte) * FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return value


def replacement_key(
    width: int,
    height: int,
    palette: tuple[int, ...],
    payload: bytes,
) -> str:
    """Return the host-texture key produced by the runtime for this PS1 upload."""
    if width & 1 or len(payload) < width * height:
        raise ValueError(f"host replacement key requires an even {width}x{height} 8-bit texture")
    indices = payload[: width * height]
    index_hash = fnv1a64(struct.pack("<BHH", 8, width, height) + indices)

    # SM1's texture loader treats the magenta key as transparent zero and sets
    # STP on every visible CLUT entry before the palette reaches VRAM. This
    # transformation was verified against native runtime page dumps.
    clut_bytes = bytearray()
    for index in sorted(set(indices)):
        color = palette[index]
        runtime_color = 0 if color == MAGENTA_555 else color | 0x8000
        clut_bytes.extend((index, runtime_color & 0xFF, runtime_color >> 8))
    clut_hash = fnv1a64(bytes(clut_bytes))
    return f"{index_hash:016x}_{clut_hash:016x}"


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
        help=(
            "compact PS1-VRAM compatibility divisor; original Dreamcast PNGs are "
            "always emitted separately for 1:1 host-GPU rendering"
        ),
    )
    parser.add_argument(
        "--playable-animation-donor",
        type=Path,
        default=ROOT / "spiderman" / "extracted" / "wad" / "spidey.psx",
        help="PS1-native 0x2C animation bank used by all playable Dreamcast meshes",
    )
    parser.add_argument(
        "--preserve-dc-playable-animations",
        action="store_true",
        help="diagnostic fallback: retain each Dreamcast costume's embedded animation bank",
    )
    parser.add_argument(
        "--sm1-skeleton-models",
        type=Path,
        default=ROOT / "spiderman" / "extracted" / "wad",
        help="retail SM1 actor directory used for explicit compatibility skeleton donors",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    converter = load_converter()
    models_root = args.dc_models.resolve()
    textures_root = args.dc_textures.resolve()
    output_root = args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    pack_root = output_root / "packs" / "dreamcast-sm1-actors"
    pack_texture_root = pack_root / "textures"
    pack_texture_root.mkdir(parents=True, exist_ok=True)
    for stale in pack_texture_root.glob("*.png"):
        stale.unlink()

    # Remove only stale files that this script itself produced before the
    # audited non-actor exclusions were introduced.
    for name in NON_ACTOR_ANIMATED:
        stale = output_root / f"{name.lower()}.psx"
        if stale.is_file():
            stale.unlink()

    wing_templates = converter.load_wing_templates(args.wing_donor.resolve())
    playable_animation_donor = args.playable_animation_donor.resolve()
    playable_animation = None
    if not args.preserve_dc_playable_animations:
        playable_animation = converter.tagged_chunk_payload(
            playable_animation_donor.read_bytes(), 0x2C
        )
    sm1_skeleton_root = args.sm1_skeleton_models.resolve()
    skeleton_donor_paths = {
        name: sm1_skeleton_root / filename
        for name, filename in SM1_SKELETON_DONORS.items()
    }
    skeleton_donors = {
        name: converter.parse_skeleton_donor(path)
        for name, path in skeleton_donor_paths.items()
    }
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
    converted_models: dict[str, Any] = {}
    host_textures: list[dict[str, Any]] = []
    host_texture_sources: dict[str, str] = {}
    palette_cache_id_owners: dict[int, tuple[str, int, str]] = {}
    for name, source, model in actors:
        destination = output_root / f"{name.lower()}.psx"
        texture_dir = textures_root / name
        try:
            wings = wing_templates if name == "SPIDEY" else None
            tagged_chunks = None
            skeleton_donor = None
            if name in PLAYABLE and playable_animation is not None:
                tagged_chunks = converter.rewrite_tagged_chunks(
                    model.tagged_chunks,
                    {0x2C: playable_animation},
                )
            if name in FULL_SM1_SKELETON_DONORS:
                skeleton_donor = skeleton_donors[name]
            elif name in skeleton_donors:
                tagged_chunks = skeleton_donors[name].tagged_chunks
            converted = converter.build_character(
                model,
                texture_dir,
                args.texture_scale,
                wings,
                tagged_chunks=tagged_chunks,
                skeleton_donor=skeleton_donor,
            )
            destination.write_bytes(converted)
            converted_models[name] = model
            palette_cache_ids = converter.generated_palette_cache_ids(
                model,
                wings is not None,
            )
            model_source_digest = hashlib.sha256(model.data).hexdigest()
            for texture_index, palette_cache_id in palette_cache_ids.items():
                owner = palette_cache_id_owners.get(palette_cache_id)
                # Every material in one converted actor intentionally shares a
                # compatibility CLUT. Some named variants are also byte-identical
                # aliases (BC2/BLACKCAT and VENOM/VENOM2). A cache id may therefore
                # repeat only when it came from the exact same source model.
                if owner is not None and owner[2] != model_source_digest:
                    raise ValueError(
                        f"global palette-cache id 0x{palette_cache_id:08X} collides "
                        f"between {owner[0]} texture {owner[1]} and "
                        f"{name} texture {texture_index}"
                    )
                palette_cache_id_owners[palette_cache_id] = (
                    name,
                    texture_index,
                    model_source_digest,
                )
            dimensions = converter.scaled_dimensions(model, args.texture_scale, False)
            actor_assets = converter.quantize_actor_textures(
                model,
                texture_dir,
                dimensions,
            )
            for texture in model.textures:
                source_png = converter.find_texture_png(texture_dir, texture)
                width, height = dimensions[texture.index]
                palette, payload = actor_assets[texture.index]
                key = replacement_key(width, height, palette, payload)
                source_signature = image_digest(source_png)
                existing_signature = host_texture_sources.get(key)
                if existing_signature is not None and existing_signature != source_signature:
                    raise ValueError(
                        f"host texture key collision {key} between distinct Dreamcast images"
                    )
                host_texture_sources[key] = source_signature
                pack_destination = pack_texture_root / f"{key}.png"
                if not pack_destination.is_file():
                    shutil.copy2(source_png, pack_destination)
                host_textures.append(
                    {
                        "actor": name,
                        "textureIndex": texture.index,
                        "source": str(source_png),
                        "compatibilitySize": [width, height],
                        "hostSize": [texture.width, texture.height],
                        "runtimeKey": key,
                        "output": str(pack_destination),
                        "sha256": source_signature,
                    }
                )
            spline_alias_asset = converter.quantize_scorpion_spline_alias(
                model,
                texture_dir,
                dimensions,
                actor_assets,
            )
            if spline_alias_asset is not None:
                source_texture, runtime_index, palette, payload = spline_alias_asset
                source_png = converter.find_texture_png(texture_dir, source_texture)
                width, height = dimensions[runtime_index]
                key = replacement_key(width, height, palette, payload)
                source_signature = image_digest(source_png)
                existing_signature = host_texture_sources.get(key)
                if existing_signature is not None and existing_signature != source_signature:
                    raise ValueError(
                        f"host texture key collision {key} between distinct Dreamcast images"
                    )
                host_texture_sources[key] = source_signature
                pack_destination = pack_texture_root / f"{key}.png"
                if not pack_destination.is_file():
                    shutil.copy2(source_png, pack_destination)
                host_textures.append(
                    {
                        "actor": name,
                        "textureIndex": runtime_index,
                        "source": str(source_png),
                        "compatibilitySize": [width, height],
                        "hostSize": [source_texture.width, source_texture.height],
                        "runtimeKey": key,
                        "output": str(pack_destination),
                        "sha256": source_signature,
                        "role": "SM1 procedural spline runtime alias",
                        "sourceTextureIndex": source_texture.index,
                    }
                )
            vertices, normals, faces = model_totals(model)
            entries.append(
                {
                    "name": name,
                    "category": category(name),
                    "sourceVersion": 6,
                    "action": "converted_v6_to_v4",
                    "skeletonPolicy": (
                        "SM1-native object order, hierarchy, and animation; "
                        "Dreamcast meshes and textures"
                        if name in FULL_SM1_SKELETON_DONORS
                        else (
                            "Dreamcast object and mesh order; SM1-native hierarchy "
                            "and animation metadata"
                            if name in skeleton_donors
                            else "Dreamcast-native"
                        )
                    ),
                    "skeletonDonor": (
                        str(skeleton_donor_paths[name])
                        if name in skeleton_donors
                        else None
                    ),
                    "source": str(source),
                    "output": str(destination),
                    "objects": model.object_count,
                    "meshes": model.mesh_count,
                    "vertices": vertices,
                    "normals": normals,
                    "faces": faces,
                    "textures": (
                        len(model.textures)
                        + int(spline_alias_asset is not None)
                        + int(name == "SPIDEY")
                    ),
                    "paletteCacheIds": {
                        str(texture_index): f"0x{palette_cache_id:08X}"
                        for texture_index, palette_cache_id in sorted(palette_cache_ids.items())
                    },
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

    costume_companions: list[dict[str, Any]] = []
    for slot, (costume_name, model_name) in enumerate(COSTUME_MODELS):
        destination = output_root / f"sp_tex{slot:02d}.psx"
        try:
            model = converted_models[model_name]
            texture_dir = textures_root / model_name
            companion = converter.build_texture_library(
                model,
                texture_dir,
                args.texture_scale,
                model_name == "SPIDEY",
            )
            destination.write_bytes(companion)
            costume_companions.append(
                {
                    "slot": slot,
                    "costume": costume_name,
                    "model": model_name,
                    "output": str(destination),
                    "bytes": destination.stat().st_size,
                    "sha256": digest(destination),
                    "status": "written",
                }
            )
            print(
                f"textures  {costume_name:12s} -> {destination.name} "
                f"({destination.stat().st_size:,} bytes)"
            )
        except Exception as error:
            failures.append(
                {
                    "name": f"sp_tex{slot:02d}",
                    "source": model_name,
                    "error": str(error),
                }
            )
            print(f"FAILED    sp_tex{slot:02d} {error}", file=sys.stderr)

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
    pack_manifest = {
        "formatVersion": 1,
        "id": "dreamcast-sm1-actors",
        "name": "Dreamcast SM1 Actor Textures",
        "version": "1",
        "description": (
            "Original-resolution Dreamcast character textures rendered by the host GPU; "
            "compact PS1 uploads remain identifiers only."
        ),
        "priority": 100,
        "game": {"id": "SLUS-00875", "strict": True},
    }
    (pack_root / "pack.json").write_text(
        json.dumps(pack_manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    host_texture_manifest = {
        "schemaVersion": 1,
        "pack": str(pack_root),
        "compatibilityTextureScaleDivisor": args.texture_scale,
        "hostTexturePolicy": "original Dreamcast dimensions and RGBA pixels",
        "mappingCount": len(host_textures),
        "uniqueRuntimeKeyCount": len(host_texture_sources),
        "entries": host_textures,
    }
    (pack_root / "texture-manifest.json").write_text(
        json.dumps(host_texture_manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schemaVersion": 1,
        "sourceKind": "loose Dreamcast extraction",
        "targetKind": "loose PS1 SM1 WAD overrides",
        "textureScaleDivisor": args.texture_scale,
        "textureScalePurpose": "compact emulated-VRAM identity; not host render resolution",
        "hostTexturePack": str(pack_root),
        "hostTextureMappingCount": len(host_textures),
        "hostTextureUniqueKeyCount": len(host_texture_sources),
        "playableAnimationPolicy": (
            "preserve Dreamcast embedded banks"
            if args.preserve_dc_playable_animations
            else "PS1-native shared Spider-Man 0x2C bank"
        ),
        "playableAnimationDonor": (
            None
            if args.preserve_dc_playable_animations
            else str(playable_animation_donor)
        ),
        "animatedHierarchyRule": "(tag 0x2A or 0x2C) and tag HIER/0x52454948",
        "excludedAnimatedModels": NON_ACTOR_ANIMATED,
        "costumeModelAliases": [
            {
                "slot": slot,
                "costume": costume,
                "requestedModel": "spidey.psx",
                "dreamcastModel": f"{model.lower()}.psx",
                "textureLibrary": f"sp_tex{slot:02d}.psx",
            }
            for slot, (costume, model) in enumerate(COSTUME_MODELS)
        ],
        "costumeTextureCompanions": costume_companions,
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
