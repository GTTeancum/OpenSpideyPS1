#!/usr/bin/env python3
"""Map PS1 SM2 actors to structurally compatible Dreamcast SM1 actors.

This parses the loose PSX containers directly, records the texture-remapping
state for each compatible actor, and names the original-SM2 fallbacks.  A model
is promoted from pending only when its native packed actor and runtime evidence
validate.  Level/environment files are never considered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SM2_WAD = ROOT / "spiderman2" / "extracted" / "wad"
DEFAULT_DC_BATCH = ROOT / "dreamcast" / "converted" / "all-characters"
DEFAULT_OUTPUT = ROOT / "dreamcast" / "converted" / "sm2-dc-actor-map.json"
HIER = 0x52454948
ANIMATION_TAGS = (0x2A, 0x2C)

# Character actors in the SM2 loose WAD.  Animated props (generators, drones,
# shields, bombs, vehicles, effects, and menu models) are intentionally outside
# this roster.  Variants remain separate because their SM2 textures can differ.
SM2_ACTORS = (
    "beast",
    "daazeve",
    "electro",
    "gelectro",
    "hamhead",
    "hamhead2",
    "hamthug",
    "henchman",
    "hgoon",
    "hostage",
    "hostage2",
    "lizard",
    "lizman",
    "lizman2",
    "mercthug",
    "mj",
    "musguard",
    "parker",
    "rogue",
    "samurai",
    "sandman",
    "sandman2",
    "selectro",
    "shocker",
    "spidey",
    "spiral",
    "symbi_02",
    "thug",
    "xavier",
    "yrdguard",
)

# A different retail name is only promoted to a candidate when the relationship
# is semantically known.  Structural ranking is still recorded for every actor,
# but never silently turns a coincidental score into a replacement decision.
KNOWN_ALIASES = {
    # HOSTAGE2 is an SM2 texture/model variant of the same male hostage rig;
    # its complete mesh-name set and hierarchy match HOSTAGE exactly.
    "hostage2": "hostage",
}

# The current SM2 upgrade scope is deliberately player-only. Structural matches
# remain useful audit evidence, but are not an instruction to replace NPCs or
# enemies; every non-Spider-Man actor stays on its retail SM2 model and textures.
PORT_TARGETS = {"spidey": "spidey"}

MAPPING_PROOFS = {
    "spidey": {
        "sourceTextureModel": "sp_tex00.glb",
        "dcMappedModel": "sm2-costume-tests/ports/default/DEFAULT_DC_WINGED_TPOSE.glb",
        "staticValidation": "sm2-costume-tests/validation.json",
        "nativeActor": "sm2-costume-tests/runtime/default/spidey.psx",
        "nativeTextures": "sm2-costume-tests/runtime/default/sp_tex00.psx",
        "packReport": "sm2-costume-tests/runtime/default/pack-report.json",
        "runtimeValidation": (
            "sm2-costume-tests/runtime/default/runtime-wing-proof/"
            "runtime-validation.json"
        ),
        "runtimeWingProofs": [
            "sm2-costume-tests/runtime/default/runtime-wing-proof/"
            "sm2_default_menu_wings_close.png",
            "sm2-costume-tests/runtime/default/runtime-wing-proof/"
            "sm2_default_gameplay_wings_close.png",
        ],
        "costumePack": "sm2-spider-man-runtime/costume-pack.json",
        "costumeRuntimeValidation": (
            "sm2-spider-man-runtime/runtime-menu-proof/runtime-validation.json"
        ),
        "costumeReview": "dreamcast/manifests/sm2-spider-man-costume-review.json",
        "scope": "native SM2 .psx actor using Dreamcast geometry and original SM2 textures",
    }
}


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_pass_report(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return report if report.get("status") == "pass" else None


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def validate_mapping_proof(name: str) -> tuple[str, dict[str, Any] | None]:
    definition = MAPPING_PROOFS.get(name)
    if definition is None:
        return "exact-name-texture-mapping-pending", None

    proof = dict(definition)
    model = DEFAULT_DC_BATCH.parent / definition["nativeActor"]
    textures = DEFAULT_DC_BATCH.parent / definition["nativeTextures"]
    pack_report = read_pass_report(DEFAULT_DC_BATCH.parent / definition["packReport"])
    runtime_report = read_pass_report(
        DEFAULT_DC_BATCH.parent / definition["runtimeValidation"]
    )
    costume_pack = read_pass_report(
        DEFAULT_DC_BATCH.parent / definition["costumePack"]
    )
    costume_runtime = read_json(
        DEFAULT_DC_BATCH.parent / definition["costumeRuntimeValidation"]
    )
    costume_review = read_json(ROOT / definition["costumeReview"])
    pack_valid = bool(
        pack_report
        and model.is_file()
        and textures.is_file()
        and pack_report.get("outputModelSha256") == sha256(model)
        and pack_report.get("outputTextureSha256") == sha256(textures)
    )
    runtime_valid = bool(
        runtime_report
        and all(runtime_report.get("runtimeMarkers", {}).values())
        and runtime_report.get("inputMethod")
        == "process-local SPIDEY_SCRIPT controller state"
    )
    costume_runtime_results = (
        costume_runtime.get("results", []) if costume_runtime else []
    )
    costume_review_results = (
        costume_review.get("costumes", []) if costume_review else []
    )
    costume_valid = bool(
        costume_pack
        and costume_pack.get("costumeCount") == 19
        and costume_pack.get("environmentPolicy")
        == "retail PS1 SM2 environments are unchanged"
        and costume_runtime
        and costume_runtime.get("status") == "menu-capture-valid"
        and costume_runtime.get("costumeCount") == 19
        and len(costume_runtime_results) == 19
        and all(
            item.get("status") == "menu-capture-valid"
            and all(item.get("runtimeMarkers", {}).values())
            for item in costume_runtime_results
        )
        and costume_review
        and costume_review.get("status") == "runtime-validated-and-manually-reviewed"
        and costume_review.get("runtimeReportSha256")
        == sha256(DEFAULT_DC_BATCH.parent / definition["costumeRuntimeValidation"])
        and len(costume_review_results) == 19
        and all(item.get("status") == "manual-visual-pass" for item in costume_review_results)
    )
    proof_hashes: dict[str, str] = {}
    if runtime_valid:
        authored = runtime_report.get("authoredProofs", {})
        for relative in definition["runtimeWingProofs"]:
            path = DEFAULT_DC_BATCH.parent / relative
            record = authored.get(path.name)
            if not path.is_file() or not record or record.get("sha256") != sha256(path):
                runtime_valid = False
                break
            proof_hashes[relative] = record["sha256"]
    proof["checks"] = {
        "nativePack": pack_valid,
        "oneProcessRuntime": runtime_valid,
        "allNineteenCostumeMenuProofs": costume_valid,
        "runtimeProofHashes": proof_hashes,
    }
    if pack_valid and runtime_valid and costume_valid:
        return "runtime-native-texture-mapping-proven", proof
    return "static-texture-mapping-proven-runtime-psx-pending", proof


def parse_actor(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 16:
        raise ValueError(f"container is too small: {path}")
    version, magic = struct.unpack_from("<HH", data, 0)
    metadata_offset = u32(data, 4)
    object_count = u32(data, 8)
    mesh_count_offset = 12 + object_count * 36
    mesh_count = u32(data, mesh_count_offset)

    chunks: dict[int, bytes] = {}
    cursor = metadata_offset
    while True:
        tag = u32(data, cursor)
        cursor += 4
        if tag == 0xFFFFFFFF:
            break
        size = u32(data, cursor)
        cursor += 4
        end = cursor + size
        if end > len(data):
            raise ValueError(f"tag 0x{tag:08X} extends past EOF in {path}")
        chunks[tag] = data[cursor:end]
        cursor = end

    mesh_names = tuple(u32(data, cursor + index * 4) for index in range(mesh_count))
    cursor += mesh_count * 4
    texture_count = u32(data, cursor)
    cursor += 4
    texture_hashes = tuple(
        u32(data, cursor + index * 4) for index in range(texture_count)
    )
    return {
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "version": version,
        "magic": f"0x{magic:04X}",
        "objectCount": object_count,
        "meshCount": mesh_count,
        "meshNames": mesh_names,
        "textureHashes": texture_hashes,
        "hierarchySha256": (
            hashlib.sha256(chunks[HIER]).hexdigest() if HIER in chunks else None
        ),
        "animationTags": [
            f"0x{tag:02X}" for tag in ANIMATION_TAGS if tag in chunks
        ],
    }


def comparison(sm2: dict[str, Any], dc: dict[str, Any]) -> dict[str, Any]:
    sm2_meshes = set(sm2["meshNames"])
    dc_meshes = set(dc["meshNames"])
    shared_meshes = sm2_meshes & dc_meshes
    union_meshes = sm2_meshes | dc_meshes
    sm2_materials = set(sm2["textureHashes"])
    dc_materials = set(dc["textureHashes"])
    shared_materials = sm2_materials & dc_materials
    mesh_jaccard = len(shared_meshes) / len(union_meshes) if union_meshes else 1.0
    object_delta = abs(sm2["objectCount"] - dc["objectCount"])
    score = mesh_jaccard * 100.0 - object_delta * 2.0
    if sm2_meshes == dc_meshes:
        score += 25.0
    if sm2["objectCount"] == dc["objectCount"]:
        score += 10.0
    return {
        "dcActor": dc["name"],
        "score": round(score, 3),
        "objectCount": dc["objectCount"],
        "objectCountDelta": object_delta,
        "meshCount": dc["meshCount"],
        "sharedMeshNameCount": len(shared_meshes),
        "meshNameJaccard": round(mesh_jaccard, 6),
        "meshNameSetExact": sm2_meshes == dc_meshes,
        "meshNameOrderExact": sm2["meshNames"] == dc["meshNames"],
        "hierarchyExact": (
            sm2["hierarchySha256"] is not None
            and sm2["hierarchySha256"] == dc["hierarchySha256"]
        ),
        "sharedMaterialHashCount": len(shared_materials),
        "sm2MaterialHashCount": len(sm2_materials),
        "dcMaterialHashCount": len(dc_materials),
        "materialHashSetExact": sm2_materials == dc_materials,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sm2-wad", type=Path, default=DEFAULT_SM2_WAD)
    parser.add_argument("--dc-batch", type=Path, default=DEFAULT_DC_BATCH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sm2_wad = args.sm2_wad.resolve()
    dc_batch = args.dc_batch.resolve()
    manifest = json.loads((dc_batch / "manifest.json").read_text(encoding="utf-8"))
    dc_actors: dict[str, dict[str, Any]] = {}
    for item in manifest["entries"]:
        name = item["name"].lower()
        path = dc_batch / f"{name}.psx"
        parsed = parse_actor(path)
        parsed["name"] = name
        parsed["action"] = item["action"]
        dc_actors[name] = parsed

    entries: list[dict[str, Any]] = []
    for name in SM2_ACTORS:
        sm2_path = sm2_wad / f"{name}.psx"
        if not sm2_path.is_file():
            raise FileNotFoundError(sm2_path)
        sm2 = parse_actor(sm2_path)
        ranked = sorted(
            (comparison(sm2, dc) for dc in dc_actors.values()),
            key=lambda item: (-item["score"], item["dcActor"]),
        )
        exact_name = name if name in dc_actors else None
        structural_dc_actor = exact_name or KNOWN_ALIASES.get(name)
        structural_evidence = next(
            (item for item in ranked if item["dcActor"] == structural_dc_actor), None
        )
        mapping_proof: dict[str, Any] | None = None
        if name in PORT_TARGETS:
            selected = PORT_TARGETS[name]
            status, mapping_proof = validate_mapping_proof(name)
            mapping_type = "dreamcast-texture-port"
        else:
            selected = None
            status = "original-sm2-model-explicit-fallback"
            mapping_type = "fallback-sm2-model"

        if exact_name:
            structural_match_type = "exact-name"
        elif structural_dc_actor and structural_dc_actor in dc_actors:
            structural_match_type = "known-alias"
        else:
            structural_match_type = "no-confirmed-dc-counterpart"
        entries.append(
            {
                "sm2Actor": name,
                "sm2": {
                    key: value
                    for key, value in sm2.items()
                    if key not in ("meshNames", "textureHashes")
                },
                "status": status,
                "mappingType": mapping_type,
                "selectedDcActor": selected,
                "structuralMatchType": structural_match_type,
                "structuralDcActor": (
                    structural_dc_actor if structural_dc_actor in dc_actors else None
                ),
                "structuralEvidence": structural_evidence,
                "rankedStructuralCandidates": ranked[:5],
                "texturePolicy": (
                    "map the original PS1 SM2 Spider-Man textures onto the selected DC mesh"
                    if selected
                    else "retain the original PS1 SM2 model and textures"
                ),
                "fallbackReason": (
                    None
                    if selected
                    else (
                        "non-player actor deferred by current player-only upgrade scope"
                        if structural_dc_actor in dc_actors
                        else "no confirmed Dreamcast counterpart"
                    )
                ),
                "mappingProof": mapping_proof,
            }
        )

    report = {
        "schemaVersion": 1,
        "scope": "character actors only; no environments or animated props",
        "sm2Wad": str(sm2_wad),
        "dcBatch": str(dc_batch),
        "actorCount": len(entries),
        "policy": "Dreamcast upgrade is Spider-Man-only; every NPC and enemy retains its retail SM2 assets",
        "dreamcastPortCount": sum(
            item["mappingType"] == "dreamcast-texture-port" for item in entries
        ),
        "structuralExactNameCount": sum(
            item["structuralMatchType"] == "exact-name" for item in entries
        ),
        "structuralKnownAliasCount": sum(
            item["structuralMatchType"] == "known-alias" for item in entries
        ),
        "fallbackCount": sum(item["mappingType"] == "fallback-sm2-model" for item in entries),
        "entries": entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"SM2 actor map: {report['actorCount']} actors; "
        f"{report['dreamcastPortCount']} Dreamcast player port; "
        f"{report['fallbackCount']} explicit SM2 fallbacks"
    )
    print(f"report: {args.output.resolve()}")


if __name__ == "__main__":
    main()
