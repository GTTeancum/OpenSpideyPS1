#!/usr/bin/env python3
"""Prove the complete Dreamcast-to-SM1 actor coverage disposition.

This audit closes the gap between an exhaustive converted-source census and the
smaller set of models that retail SM1 can reach naturally.  It independently
rescans the Dreamcast containers, locks natural story/viewer/costume routes to
their reviewed runtime reports, verifies the two explicit viewer probes and the
byte-identical CLAW no-op, and rejects any unclassified batch entry.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "dreamcast" / "tools"
DC_SOURCE = ROOT / "dreamcast" / "extracted"
SM1_WAD = ROOT / "spiderman" / "extracted" / "wad"
BATCH = ROOT / "dreamcast" / "converted" / "all-characters"
MANIFEST = BATCH / "manifest.json"
STORY_REPORT = ROOT / "dreamcast" / "converted" / "all-characters-runtime-current" / "runtime-validation.json"
VIEWER_REPORT = ROOT / "dreamcast" / "converted" / "all-characters-viewer-runtime-current" / "runtime-validation.json"
COSTUME_REPORT = ROOT / "dreamcast" / "converted" / "all-characters-costumes-runtime-current" / "runtime-validation.json"
HOSTAGEF_REPORT = ROOT / "dreamcast" / "converted" / "hostagef-viewer-probe" / "runtime-validation.json"
SYMBIOTE_REPORT = ROOT / "dreamcast" / "converted" / "symbiote-compatible-viewer-probe" / "runtime-validation.json"
RUNTIME_REVIEW = ROOT / "dreamcast" / "manifests" / "sm1-runtime-visual-review.json"
COSTUME_REVIEW = ROOT / "dreamcast" / "manifests" / "sm1-costume-menu-review.json"
OUTPUT = ROOT / "dreamcast" / "converted" / "sm1-dc-actor-coverage.json"

EXPECTED_COUNTS = {
    "batch": 65,
    "convertedV6": 51,
    "native": 14,
    "naturalRouteUnion": 52,
    "explicitProbe": 2,
    "retailByteIdentical": 1,
    "dreamcastOnlySupplemental": 10,
}
PROBES = {
    "hostagef": (HOSTAGEF_REPORT, "hostagef"),
    "symbiote": (SYMBIOTE_REPORT, "symbiote"),
}
DREAMCAST_ONLY_SUPPLEMENTAL = {
    "copcar",
    "lizman2t",
    "lizmant",
    "softspt2",
    "softspt3",
    "sp_alt01",
    "sp_alt02",
    "sp_alt04",
    "sp_alt05",
    "sparmor",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def load_port_module():
    path = TOOLS / "port_all_characters.py"
    spec = importlib.util.spec_from_file_location("sm1_port_all_characters", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def scan_dreamcast_actor_names(port_module: Any, errors: list[str]) -> set[str]:
    converter = port_module.load_converter()
    names: set[str] = set()
    for source in sorted(DC_SOURCE.glob("*.PSX")):
        try:
            model = converter.parse_model(source)
        except ValueError as error:
            if "expected Dreamcast v6" not in str(error):
                errors.append(f"Dreamcast source scan failed for {source.name}: {error}")
            continue
        tags = set(port_module.chunk_tags(model))
        name = source.stem.upper()
        if (
            tags & port_module.ANIMATION_TAGS
            and port_module.HIER_TAG in tags
            and name not in port_module.NON_ACTOR_ANIMATED
        ):
            names.add(name.lower())
    for name in port_module.NATIVE_ACTOR_COMPONENTS:
        source = DC_SOURCE / f"{name}.PSX"
        require(errors, source.is_file(), f"missing native Dreamcast actor component {source}")
        if source.is_file():
            names.add(name.lower())
    return names


def verify_locked_report(
    errors: list[str],
    report_path: Path,
    expected_hash: str,
    label: str,
) -> None:
    require(errors, report_path.is_file(), f"missing {label} report {report_path}")
    if report_path.is_file():
        actual = digest(report_path)
        require(
            errors,
            actual.lower() == expected_hash.lower(),
            f"{label} report hash changed: {actual} != {expected_hash}",
        )


def main() -> None:
    errors: list[str] = []
    manifest = load_json(MANIFEST)
    runtime_review = load_json(RUNTIME_REVIEW)
    costume_review = load_json(COSTUME_REVIEW)
    port_module = load_port_module()

    entries = manifest.get("entries", [])
    actors = {entry["name"].lower(): entry for entry in entries}
    scanned = scan_dreamcast_actor_names(port_module, errors)
    require(errors, set(actors) == scanned, "converted manifest does not exactly match the Dreamcast actor rescan")
    require(errors, len(actors) == EXPECTED_COUNTS["batch"], f"expected 65 actors, found {len(actors)}")
    require(
        errors,
        manifest.get("convertedV6Count") == EXPECTED_COUNTS["convertedV6"],
        f"expected 51 converted v6 actors, found {manifest.get('convertedV6Count')}",
    )
    require(
        errors,
        manifest.get("nativeContainerCount") == EXPECTED_COUNTS["native"],
        f"expected 14 native containers, found {manifest.get('nativeContainerCount')}",
    )
    require(errors, not manifest.get("scanErrors"), "actor conversion manifest contains scan errors")
    require(errors, not manifest.get("failures"), "actor conversion manifest contains failures")

    for name, entry in actors.items():
        output = Path(entry["output"])
        require(errors, output.is_file(), f"missing converted actor output {output}")
        if output.is_file():
            require(
                errors,
                digest(output).lower() == entry["sha256"].lower(),
                f"converted actor hash changed for {name}",
            )

    story = load_json(STORY_REPORT)
    story_review = runtime_review["reports"]["story"]
    verify_locked_report(errors, STORY_REPORT, story_review["runtimeReportSha256"], "story")
    require(errors, story.get("status") == "pass", f"story runtime status is {story.get('status')}")
    require(
        errors,
        story.get("levelCount") == story.get("passedLevelCount") == 18,
        "story runtime does not pass all 18 required levels",
    )
    require(
        errors,
        story.get("runtimeTargetCount") == story.get("runtimeCoveredCount") == 34,
        "story runtime does not cover all 34 requested actors",
    )
    require(errors, not story.get("runtimeMissingActors"), "story runtime has missing actors")
    story_names = set(story.get("runtimeCoveredActors", []))
    require(errors, story_names <= set(actors), "story runtime names an actor outside the converted batch")

    viewer = load_json(VIEWER_REPORT)
    viewer_review = runtime_review["reports"]["viewer"]
    verify_locked_report(errors, VIEWER_REPORT, viewer_review["runtimeReportSha256"], "viewer")
    require(errors, viewer.get("status") == "pass", f"viewer runtime status is {viewer.get('status')}")
    require(
        errors,
        viewer.get("rosterCount") == viewer.get("loadedModelCount") == viewer.get("overrideCount") == viewer.get("captureCount") == 26,
        "viewer runtime does not prove all 26 selectable actors",
    )
    for key in ("missingLoads", "missingOverrides", "captureErrors", "badMarkers"):
        require(errors, not viewer.get(key), f"viewer runtime contains {key}")
    viewer_names = {capture["model"].lower() for capture in viewer.get("captures", [])}
    require(errors, viewer_names <= set(actors), "viewer runtime names an actor outside the converted batch")

    costumes = load_json(COSTUME_REPORT)
    verify_locked_report(
        errors,
        COSTUME_REPORT,
        costume_review["runtimeReportSha256"],
        "costume menu",
    )
    require(
        errors,
        costumes.get("status") == "menu-capture-valid",
        f"costume runtime status is {costumes.get('status')}",
    )
    require(
        errors,
        costumes.get("costumeCount") == costumes.get("passedCostumeCount") == 10,
        "costume runtime does not prove all ten selectable SM1 slots",
    )
    costume_names = {
        Path(result["dreamcastModel"]).stem.lower()
        for result in costumes.get("results", [])
    }
    manifest_costume_names = {
        Path(alias["dreamcastModel"]).stem.lower()
        for alias in manifest.get("costumeModelAliases", [])
    }
    require(errors, costume_names == manifest_costume_names, "costume runtime and conversion aliases disagree")
    require(errors, costume_names <= set(actors), "costume runtime names an actor outside the converted batch")

    routes: dict[str, list[str]] = {name: [] for name in actors}
    for route, names in (("story", story_names), ("viewer", viewer_names), ("costume", costume_names)):
        for name in names:
            routes[name].append(route)
    natural_names = {name for name, actor_routes in routes.items() if actor_routes}
    require(
        errors,
        len(natural_names) == EXPECTED_COUNTS["naturalRouteUnion"],
        f"expected 52 naturally routed actors, found {len(natural_names)}",
    )

    probe_names: set[str] = set()
    for name, (report_path, expected_source) in PROBES.items():
        report = load_json(report_path)
        review_record = runtime_review["reports"][name]
        verify_locked_report(errors, report_path, review_record["runtimeReportSha256"], name)
        require(errors, report.get("status") == "pass", f"{name} probe status is {report.get('status')}")
        require(
            errors,
            report.get("probe", {}).get("sourceModel", "").lower() == expected_source,
            f"{name} probe used the wrong source model",
        )
        require(
            errors,
            report.get("probe", {}).get("temporaryAliasRemoved") is True,
            f"{name} probe did not remove its temporary alias",
        )
        for key in ("missingLoads", "missingOverrides", "captureErrors", "badMarkers"):
            require(errors, not report.get(key), f"{name} probe contains {key}")
        probe_names.add(name)
    require(errors, len(probe_names) == EXPECTED_COUNTS["explicitProbe"], "explicit probe count changed")

    claw_paths = [DC_SOURCE / "CLAW.PSX", SM1_WAD / "claw.psx", BATCH / "claw.psx"]
    for path in claw_paths:
        require(errors, path.is_file(), f"missing CLAW parity input {path}")
    claw_hashes = {digest(path) for path in claw_paths if path.is_file()}
    require(errors, len(claw_hashes) == 1, "Dreamcast, retail SM1, and output CLAW are not byte-identical")

    for name in DREAMCAST_ONLY_SUPPLEMENTAL:
        require(errors, name in actors, f"missing Dreamcast-only supplemental actor {name}")
        require(errors, not (SM1_WAD / f"{name}.psx").exists(), f"{name} is not Dreamcast-only; retail SM1 contains it")
    require(
        errors,
        len(DREAMCAST_ONLY_SUPPLEMENTAL) == EXPECTED_COUNTS["dreamcastOnlySupplemental"],
        "Dreamcast-only supplemental count changed",
    )

    classified = natural_names | probe_names | {"claw"} | DREAMCAST_ONLY_SUPPLEMENTAL
    unclassified = sorted(set(actors) - classified)
    overlapping_special = sorted(
        (probe_names | {"claw"} | DREAMCAST_ONLY_SUPPLEMENTAL) & natural_names
    )
    require(errors, not unclassified, f"unclassified Dreamcast actors: {', '.join(unclassified)}")
    require(errors, not overlapping_special, f"special actor classifications overlap natural routes: {', '.join(overlapping_special)}")
    require(errors, len(classified) == len(actors), "actor dispositions do not cover the full batch")

    actor_dispositions: list[dict[str, Any]] = []
    for name in sorted(actors):
        if name in natural_names:
            disposition = "natural-retail-sm1-route"
        elif name in probe_names:
            disposition = "explicit-compatible-viewer-probe"
        elif name == "claw":
            disposition = "retail-sm1-byte-identical"
        else:
            disposition = "dreamcast-only-supplemental-not-installed-as-alias"
        actor_dispositions.append(
            {
                "actor": name,
                "disposition": disposition,
                "routes": routes[name],
                "sourceVersion": actors[name]["sourceVersion"],
                "action": actors[name]["action"],
                "outputSha256": actors[name]["sha256"],
            }
        )

    report = {
        "schemaVersion": 1,
        "status": "pass" if not errors else "fail",
        "policy": "Every Dreamcast SM1 actor has a proved retail route, explicit probe/no-op, or verified Dreamcast-only disposition; environments are out of scope.",
        "counts": {
            "dreamcastActorBatch": len(actors),
            "convertedV6": manifest.get("convertedV6Count"),
            "nativeContainers": manifest.get("nativeContainerCount"),
            "naturalRetailSm1RouteUnion": len(natural_names),
            "storyActors": len(story_names),
            "viewerActors": len(viewer_names),
            "costumeActors": len(costume_names),
            "explicitCompatibleProbes": len(probe_names),
            "retailByteIdentical": 1,
            "dreamcastOnlySupplemental": len(DREAMCAST_ONLY_SUPPLEMENTAL),
            "unclassified": len(unclassified),
        },
        "lockedEvidence": {
            "storyRuntime": str(STORY_REPORT),
            "viewerRuntime": str(VIEWER_REPORT),
            "costumeRuntime": str(COSTUME_REPORT),
            "hostagefProbe": str(HOSTAGEF_REPORT),
            "symbioteProbe": str(SYMBIOTE_REPORT),
            "clawSha256": next(iter(claw_hashes), None),
        },
        "actors": actor_dispositions,
        "errors": errors,
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(
        "PASS: 65 Dreamcast actors fully classified; 52 natural SM1 routes, "
        "2 compatible probes, 1 byte-identical no-op, 10 Dreamcast-only supplemental"
    )
    print(f"report: {OUTPUT}")


if __name__ == "__main__":
    main()
