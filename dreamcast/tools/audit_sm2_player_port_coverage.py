#!/usr/bin/env python3
"""Independently audit the complete player-only Dreamcast upgrade for PS1 SM2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
SM2_WAD = ROOT / "spiderman2" / "extracted" / "wad"
ASSETS = ROOT / "dreamcast" / "converted" / "sm2-spider-man-runtime"
PACK_REPORT = ASSETS / "costume-pack.json"
SPECIAL_REPORT = ASSETS / "special-dc-costumes.json"
SPECIAL_TEXTURE_MANIFEST = ASSETS / "packs" / "dreamcast-sm2-special-costumes" / "texture-manifest.json"
RUNTIME_REPORT = ASSETS / "runtime-menu-proof" / "runtime-validation.json"
REVIEW = ROOT / "dreamcast" / "manifests" / "sm2-spider-man-costume-review.json"
ACTOR_MAP = ROOT / "dreamcast" / "converted" / "sm2-dc-actor-map.json"
DEFAULT_ROOT = ROOT / "dreamcast" / "converted" / "sm2-costume-tests" / "runtime" / "default"
DEFAULT_PACK = DEFAULT_ROOT / "pack-report.json"
DEFAULT_RUNTIME = DEFAULT_ROOT / "runtime-wing-proof" / "runtime-validation.json"
OUTPUT = ROOT / "dreamcast" / "converted" / "sm2-player-port-coverage.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def verify_file_hash(
    errors: list[str], path: Path, expected: str, label: str
) -> None:
    require(errors, path.is_file(), f"missing {label}: {path}")
    if path.is_file():
        actual = digest(path)
        require(
            errors,
            actual.lower() == expected.lower(),
            f"{label} hash changed: {actual} != {expected}",
        )


def verify_default_proof(errors: list[str]) -> dict[str, Any]:
    pack = load_json(DEFAULT_PACK)
    runtime = load_json(DEFAULT_RUNTIME)
    require(errors, pack.get("status") == "pass", "SM2 Default native pack does not pass")
    default_actor = Path(pack["outputModel"])
    default_textures = Path(pack["outputTextureLibrary"])
    verify_file_hash(errors, default_actor, pack["outputModelSha256"], "SM2 Default actor")
    verify_file_hash(
        errors,
        default_textures,
        pack["outputTextureSha256"],
        "SM2 Default texture library",
    )
    require(errors, runtime.get("status") == "pass", "SM2 Default runtime proof does not pass")
    require(errors, runtime.get("schemaVersion") == 2, "SM2 Default runtime proof lacks hardened schema 2 gates")
    require(
        errors,
        runtime.get("inputMethod") == "process-local SPIDEY_SCRIPT controller state",
        "SM2 Default runtime proof did not use process-local input",
    )
    require(
        errors,
        all(runtime.get("runtimeMarkers", {}).values()),
        "SM2 Default runtime proof has a false runtime marker",
    )
    frames = runtime.get("frames", {})
    require(
        errors,
        set(frames) == {"menu", "gameplay_deployed"},
        "SM2 Default proof contains anything other than the gated menu and active gameplay frames",
    )
    menu_signature = frames.get("menu", {}).get("mainMenuSignature", [])
    gameplay_signature = frames.get("gameplay_deployed", {}).get(
        "gameplayHudSignature", []
    )
    require(
        errors,
        len(menu_signature) == 4
        and all(
            region.get("matches") is True
            and region.get("sha256") == region.get("expectedSha256")
            for region in menu_signature
        ),
        "SM2 Default menu frame lacks all four exact menu regions",
    )
    require(
        errors,
        len(gameplay_signature) == 4
        and all(
            region.get("matches") is True
            and region.get("sha256") == region.get("expectedSha256")
            for region in gameplay_signature
        ),
        "SM2 Default gameplay frame lacks all four exact HUD regions",
    )
    for name, record in frames.items():
        verify_file_hash(errors, Path(record["path"]), record["sha256"], f"Default frame {name}")
    for name, record in runtime.get("authoredProofs", {}).items():
        verify_file_hash(errors, Path(record["path"]), record["sha256"], f"Default authored proof {name}")
    return {
        "actorSha256": pack.get("outputModelSha256"),
        "textureSha256": pack.get("outputTextureSha256"),
        "runtimeReportSha256": digest(DEFAULT_RUNTIME),
    }


def verify_costume_pack(errors: list[str]) -> dict[str, Any]:
    pack = load_json(PACK_REPORT)
    require(errors, pack.get("status") == "pass", "SM2 costume pack does not pass")
    require(
        errors,
        pack.get("environmentPolicy") == "retail PS1 SM2 environments are unchanged",
        "SM2 costume pack does not preserve retail environments",
    )
    actor = Path(pack["actor"]["runtimeFile"])
    verify_file_hash(errors, actor, pack["actor"]["sha256"], "shared Dreamcast Spider-Man actor")
    require(errors, pack.get("costumeCount") == 19, "SM2 costume pack does not contain 19 slots")
    costumes = pack.get("costumes", [])
    slots = {entry.get("slot") for entry in costumes}
    require(errors, len(costumes) == 19 and slots == set(range(19)), "SM2 costume slot set is not 0..18")
    face_counts: set[int] = set()
    for entry in costumes:
        slot = entry["slot"]
        staged = Path(entry["runtimeFile"])
        retail = SM2_WAD / f"sp_tex{slot:02d}.psx"
        audit_model = Path(entry["auditModel"])
        verify_file_hash(errors, staged, entry["runtimeSha256"], f"staged SM2 slot {slot:02d}")
        require(errors, retail.is_file(), f"missing retail SM2 texture slot {slot:02d}")
        if staged.is_file() and retail.is_file():
            require(
                errors,
                staged.read_bytes() == retail.read_bytes(),
                f"SM2 slot {slot:02d} is not byte-exact retail texture data",
            )
        require(errors, entry.get("retailByteExact") is True, f"slot {slot:02d} lacks byte-exact flag")
        require(errors, entry.get("status") == "pass", f"slot {slot:02d} pack status is not pass")
        require(
            errors,
            entry.get("textureRecordCount") == entry.get("materialHashCount"),
            f"slot {slot:02d} texture record/hash counts differ",
        )
        verify_file_hash(
            errors,
            audit_model,
            entry["auditModelSha256"],
            f"slot {slot:02d} merged audit model",
        )
        face_counts.add(entry.get("auditFaceCount"))
    require(errors, face_counts == {pack["actor"]["faceCount"]}, "costume audit face counts are inconsistent")
    return {
        "actor": str(actor),
        "actorSha256": pack["actor"]["sha256"],
        "slotCount": len(costumes),
        "byteExactRetailSlotCount": sum(
            Path(entry["runtimeFile"]).is_file()
            and (SM2_WAD / f"sp_tex{entry['slot']:02d}.psx").is_file()
            and Path(entry["runtimeFile"]).read_bytes()
            == (SM2_WAD / f"sp_tex{entry['slot']:02d}.psx").read_bytes()
            for entry in costumes
        ),
    }


def verify_special_costumes(errors: list[str]) -> dict[str, Any]:
    special = load_json(SPECIAL_REPORT)
    require(
        errors,
        special.get("status") == "structural-build-complete; runtime visual review required",
        "special-costume structural report has an unexpected status",
    )
    results = special.get("results", [])
    require(errors, {entry.get("slot") for entry in results} == {13, 17}, "special costume slots are not 13 and 17")
    for entry in results:
        slot = entry["slot"]
        verify_file_hash(errors, Path(entry["actor"]), entry["actorSha256"], f"special actor {slot:02d}")
        verify_file_hash(
            errors,
            Path(entry["textureLibrary"]),
            entry["textureSha256"],
            f"special texture library {slot:02d}",
        )
        require(errors, Path(entry["dreamcastSource"]).is_file(), f"missing special Dreamcast source {slot:02d}")
        require(errors, Path(entry["skeletonDonor"]).is_file(), f"missing special SM2 donor {slot:02d}")
        require(errors, entry.get("withSm2Wings") is False, f"special slot {slot:02d} fabricated generic wings")

    textures = load_json(SPECIAL_TEXTURE_MANIFEST)
    entries = textures.get("entries", [])
    require(
        errors,
        textures.get("mappingCount") == len(entries) == special.get("hostTextureMappingCount") == 21,
        "special costume host texture mapping count is not 21",
    )
    require(
        errors,
        textures.get("uniqueRuntimeKeyCount")
        == special.get("hostTextureUniqueKeyCount")
        == len({entry["runtimeKey"] for entry in entries})
        == 21,
        "special costume host texture keys are not 21 unique mappings",
    )
    for entry in entries:
        source = Path(entry["source"])
        output = Path(entry["output"])
        verify_file_hash(errors, source, entry["sha256"], f"special source texture {entry['runtimeKey']}")
        verify_file_hash(errors, output, entry["sha256"], f"special host texture {entry['runtimeKey']}")
        if source.is_file() and output.is_file():
            with Image.open(source) as source_image, Image.open(output) as output_image:
                require(
                    errors,
                    list(source_image.size) == entry.get("hostSize")
                    and output_image.size == source_image.size,
                    f"special host texture {entry['runtimeKey']} dimensions do not match its Dreamcast source",
                )
        require(
            errors,
            entry.get("hostSize", [0, 0])[0]
            == entry.get("compatibilitySize", [1, 1])[0] * 4
            and entry.get("hostSize", [0, 0])[1]
            == entry.get("compatibilitySize", [1, 1])[1] * 4,
            f"special host texture {entry['runtimeKey']} is not the original 4x Dreamcast source resolution",
        )
    return {"slots": [13, 17], "hostTextureMappings": len(entries)}


def verify_menu_runtime(errors: list[str]) -> dict[str, Any]:
    runtime = load_json(RUNTIME_REPORT)
    review = load_json(REVIEW)
    require(
        errors,
        digest(RUNTIME_REPORT).lower() == review.get("runtimeReportSha256", "").lower(),
        "SM2 runtime report no longer matches the manual-review lock",
    )
    require(errors, runtime.get("status") == "menu-capture-valid", "SM2 menu runtime status is not valid")
    require(errors, runtime.get("costumeCount") == 19, "SM2 menu runtime does not contain 19 slots")
    require(
        errors,
        runtime.get("processPolicy") == "strictly sequential; never more than one SpiderMan2 process",
        "SM2 runtime process policy is not strictly sequential",
    )
    results = runtime.get("results", [])
    require(errors, {entry.get("slot") for entry in results} == set(range(19)), "SM2 runtime slot set is not 0..18")
    capture_count = 0
    for result in results:
        slot = result["slot"]
        require(errors, result.get("status") == "menu-capture-valid", f"SM2 runtime slot {slot:02d} is invalid")
        require(errors, all(result.get("runtimeMarkers", {}).values()), f"SM2 runtime slot {slot:02d} has a false marker")
        require(errors, not result.get("badMarkers"), f"SM2 runtime slot {slot:02d} has bad markers")
        captures = result.get("captureSequence", [])
        require(errors, len(captures) == 5, f"SM2 runtime slot {slot:02d} does not have five captures")
        capture_count += len(captures)
        for capture in captures:
            verify_file_hash(errors, Path(capture["path"]), capture["sha256"], f"SM2 slot {slot:02d} capture")
            signatures = capture.get("mainMenuSignature", [])
            require(
                errors,
                len(signatures) == 4
                and all(
                    signature.get("matches")
                    and signature.get("sha256") == signature.get("expectedSha256")
                    for signature in signatures
                ),
                f"SM2 slot {slot:02d} capture lacks all four exact main-menu signatures",
            )
        expected_actor = f"spidey-slot{slot:02d}.psx" if slot in {13, 17} else "spidey.psx"
        require(errors, result.get("actor") == expected_actor, f"SM2 slot {slot:02d} used {result.get('actor')}")
    review_results = review.get("costumes", [])
    require(
        errors,
        len(review_results) == 19
        and {entry.get("slot") for entry in review_results} == set(range(19))
        and all(entry.get("status") == "manual-visual-pass" for entry in review_results),
        "SM2 manual costume review is incomplete",
    )
    runtime_by_slot = {entry["slot"]: entry for entry in results}
    for entry in review_results:
        slot = entry["slot"]
        evidence_dir = ROOT / entry.get("evidenceDirectory", "")
        require(
            errors,
            evidence_dir.is_dir(),
            f"SM2 review slot {slot:02d} lacks its individual-frame evidence directory",
        )
        capture_parents = {
            Path(capture["path"]).parent.resolve()
            for capture in runtime_by_slot.get(slot, {}).get("captureSequence", [])
        }
        require(
            errors,
            capture_parents == {evidence_dir.resolve()},
            f"SM2 review slot {slot:02d} evidence directory does not own all five locked frames",
        )
    return {"slotCount": len(results), "captureCount": capture_count, "reviewLockSha256": digest(RUNTIME_REPORT)}


def verify_fallback_map(errors: list[str]) -> dict[str, Any]:
    mapping = load_json(ACTOR_MAP)
    require(errors, mapping.get("animatedHierarchyAssetCount") == 81, "SM2 animated inventory is not 81")
    require(errors, mapping.get("actorCount") == 30, "SM2 character actor census is not 30")
    require(errors, mapping.get("dreamcastPortCount") == 1, "SM2 map does not select exactly one Dreamcast port")
    require(errors, mapping.get("fallbackCount") == 29, "SM2 map does not contain 29 character fallbacks")
    require(
        errors,
        mapping.get("animatedNonPlayerComponentFallbackCount") == 51,
        "SM2 map does not contain 51 animated non-player fallbacks",
    )
    require(
        errors,
        mapping.get("totalRetailAnimatedFallbackCount") == 80,
        "SM2 map does not contain 80 total retail animated fallbacks",
    )
    mapped = mapping.get("entries", [])
    player = [entry for entry in mapped if entry.get("mappingType") == "dreamcast-texture-port"]
    require(
        errors,
        len(player) == 1
        and player[0].get("sm2Actor") == "spidey"
        and player[0].get("selectedDcActor") == "spidey"
        and player[0].get("status") == "runtime-native-texture-mapping-proven",
        "SM2 player mapping is not the proved Dreamcast Spider-Man port",
    )
    fallbacks = [entry for entry in mapped if entry.get("mappingType") == "fallback-sm2-model"]
    for entry in fallbacks:
        name = entry["sm2Actor"]
        source = SM2_WAD / f"{name}.psx"
        verify_file_hash(errors, source, entry["sm2"]["sha256"], f"SM2 fallback actor {name}")
        require(
            errors,
            entry.get("status") == "original-sm2-model-explicit-fallback"
            and entry.get("selectedDcActor") is None
            and entry.get("fallbackReason"),
            f"SM2 fallback actor {name} is not explicit",
        )
    components = mapping.get("animatedNonPlayerComponentFallbacks", [])
    for entry in components:
        verify_file_hash(
            errors,
            Path(entry["path"]),
            entry["sha256"],
            f"SM2 animated fallback {entry['sm2Asset']}",
        )
        require(
            errors,
            entry.get("status") == "original-sm2-asset-explicit-fallback",
            f"SM2 animated fallback {entry['sm2Asset']} is not explicit",
        )
    environment_replacements = sorted(
        str(path)
        for path in ASSETS.rglob("*.psx")
        if re.fullmatch(r"l\d+a\w*_[log]\.psx", path.name, re.IGNORECASE)
    )
    require(errors, not environment_replacements, f"SM2 player pack contains environment replacements: {environment_replacements}")
    return {
        "animatedHierarchyAssets": mapping.get("animatedHierarchyAssetCount"),
        "dreamcastPlayerPorts": len(player),
        "retailCharacterFallbacks": len(fallbacks),
        "retailAnimatedComponentFallbacks": len(components),
    }


def main() -> None:
    errors: list[str] = []
    default = verify_default_proof(errors)
    costume_pack = verify_costume_pack(errors)
    require(
        errors,
        costume_pack["actorSha256"] == default["actorSha256"],
        "aggregate SM2 costume actor differs from the proved Default actor",
    )
    special = verify_special_costumes(errors)
    runtime = verify_menu_runtime(errors)
    fallback = verify_fallback_map(errors)
    report = {
        "schemaVersion": 1,
        "status": "pass" if not errors else "fail",
        "scope": "Dreamcast Spider-Man geometry with all 19 retail SM2 texture slots; every other animated retail asset is an explicit fallback and environments remain unchanged",
        "defaultProof": default,
        "costumePack": costume_pack,
        "specialTopologyCostumes": special,
        "runtimeMenuProof": runtime,
        "fallbackCoverage": fallback,
        "errors": errors,
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(
        "PASS: SM2 player-only port covers 19 texture slots on Dreamcast geometry; "
        "29 character and 51 animated-component retail fallbacks are explicit"
    )
    print(f"report: {OUTPUT}")


if __name__ == "__main__":
    main()
