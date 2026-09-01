#!/usr/bin/env python3
"""Run the reproducible Dreamcast-character port, proof, and validation pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "dreamcast" / "tools"
CONVERTED = ROOT / "dreamcast" / "converted"
VISIBLE = CONVERTED / "sm1-winged-runtime"
PRODUCTION = CONVERTED / "sm1-winged-production"
JAMESON_SCORPION_PROOF = CONVERTED / "jameson-scorpion-runtime-alias-gameplay-proof"
HOSTAGEF_PROOF = CONVERTED / "hostagef-viewer-probe"
SYMBIOTE_PROOF = CONVERTED / "symbiote-compatible-viewer-probe"
COSTUME_ROOT = CONVERTED / "sm2-costume-tests"
SM2_DEFAULT_RUNTIME = COSTUME_ROOT / "runtime" / "default"
SM2_COSTUME_RUNTIME = CONVERTED / "sm2-spider-man-runtime"
SM1_REVIEW_QUEUE = ROOT / "dreamcast" / "manifests" / "sm1-model-review.json"
SM1_COSTUME_REVIEW = ROOT / "dreamcast" / "manifests" / "sm1-costume-menu-review.json"
SM1_RUNTIME_VISUAL_REVIEW = ROOT / "dreamcast" / "manifests" / "sm1-runtime-visual-review.json"
SM2_COSTUME_REVIEW = ROOT / "dreamcast" / "manifests" / "sm2-spider-man-costume-review.json"
SM1_STORY_LEVEL_COUNT = 18
COSTUMES = {
    "default": ("sp_tex00.glb", "DEFAULT_DC_WINGED_TPOSE.glb"),
    "dusk": ("sp_tex03.glb", "DUSK_DC_WINGED_TPOSE.glb"),
    "prodigy": ("sp_tex02.glb", "PRODIGY_DC_WINGED_TPOSE.glb"),
    "ricochet": ("sp_tex08.glb", "RICOCHET_DC_WINGED_TPOSE.glb"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--blender", type=Path)
    parser.add_argument("--multitool", type=Path)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-costume-build", action="store_true")
    parser.add_argument("--skip-static-tools", action="store_true")
    parser.add_argument("--skip-runtime", action="store_true")
    parser.add_argument(
        "--use-existing-runtime-evidence",
        action="store_true",
        help=(
            "do not launch game processes; hash/audit the existing runtime reports "
            "and their literal visual-review manifests"
        ),
    )
    parser.add_argument("--resume-runtime", action="store_true")
    parser.add_argument("--reuse-wing-captures", action="store_true")
    parser.add_argument(
        "--runtime-concurrency",
        type=int,
        choices=(1,),
        default=1,
        help="runtime proofs are deliberately restricted to one game process",
    )
    return parser.parse_args()


def resolve_blender(explicit: Path | None) -> Path:
    candidates = [
        explicit,
        Path(os.environ["BLENDER"]) if os.environ.get("BLENDER") else None,
        Path(r"C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"),
        Path(found) if (found := shutil.which("blender")) else None,
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError("Blender was not found; pass --blender or set BLENDER")


def resolve_multitool(explicit: Path | None) -> Path:
    candidates = [
        explicit,
        Path(os.environ["NEVERSOFT_MULTITOOL"])
        if os.environ.get("NEVERSOFT_MULTITOOL")
        else None,
        Path(found) if (found := shutil.which("NeversoftMultitool")) else None,
        Path(found_exe) if (found_exe := shutil.which("NeversoftMultitool.exe")) else None,
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "NeversoftMultitool was not found; pass --multitool, set "
        "NEVERSOFT_MULTITOOL, or use --skip-static-tools with existing proofs"
    )


def run(stage: str, command: list[str], acceptable: tuple[int, ...] = (0,)) -> dict[str, Any]:
    print(f"\n[{stage}]", flush=True)
    print(subprocess.list2cmdline(command), flush=True)
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = result.stdout or ""
    print(output, end="")
    if result.returncode not in acceptable:
        raise RuntimeError(f"{stage} exited {result.returncode}")
    return {"status": "pass", "returnCode": result.returncode, "outputTail": output[-2000:]}


def digest(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": str(path.resolve()),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def audit_sm1_review_queue() -> dict[str, Any]:
    """Keep confirmed defects distinct from unresolved user visual review."""
    payload = json.loads(SM1_REVIEW_QUEUE.read_text(encoding="utf-8"))
    actors = payload.get("actors")
    if not isinstance(actors, dict) or not actors:
        raise ValueError(f"{SM1_REVIEW_QUEUE} has no actor review records")

    invalid = [
        actor
        for actor, review in actors.items()
        if not isinstance(review, dict)
        or not isinstance(review.get("blocksClearance"), bool)
    ]
    if invalid:
        raise ValueError(
            "SM1 review records need an explicit boolean blocksClearance: "
            + ", ".join(sorted(invalid))
        )

    blocked = sorted(
        actor for actor, review in actors.items() if review["blocksClearance"]
    )
    technical_defects = sorted(
        actor
        for actor, review in actors.items()
        if review["blocksClearance"]
        and review.get("status") == "technical-defect-confirmed"
    )
    return {
        "status": (
            "technical-defect-confirmed"
            if technical_defects
            else ("user-review-required" if blocked else "pass")
        ),
        "manifest": str(SM1_REVIEW_QUEUE.resolve()),
        "actorCount": len(actors),
        "blockerCount": len(blocked),
        "blockedActors": blocked,
        "technicalDefects": technical_defects,
        "policy": (
            "Automated conversion/runtime success cannot clear a user-reported "
            "visual failure or an explicit user-review hold."
        ),
    }


def audit_costume_review_manifest(
    name: str,
    manifest_path: Path,
    runtime_report_path: Path,
    expected_costume_count: int,
    allowed_blockers: set[str],
) -> dict[str, Any]:
    errors: list[str] = []
    payload: dict[str, Any] = {}
    if not manifest_path.is_file():
        errors.append("review manifest is missing")
    else:
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise TypeError("root is not an object")
            payload = loaded
        except Exception as error:
            errors.append(f"invalid review manifest: {error}")

    costumes = payload.get("costumes", []) if payload else []
    if len(costumes) != expected_costume_count:
        errors.append(
            f"review contains {len(costumes)} costumes, expected {expected_costume_count}"
        )
    manifest_blockers = set(payload.get("completionBlockers", []))
    if not manifest_blockers.issubset(allowed_blockers):
        errors.append(
            "unexpected costume review blockers: "
            + ", ".join(sorted(manifest_blockers - allowed_blockers))
        )
    unreviewed = [
        str(costume.get("slot"))
        for costume in costumes
        if "manual-visual-pass" not in str(costume.get("status", ""))
        and not costume.get("blocksClearance")
    ]
    if unreviewed:
        errors.append("costume slots lack manual review: " + ", ".join(unreviewed))

    expected_hash = payload.get("runtimeReportSha256")
    actual_hash = (
        hashlib.sha256(runtime_report_path.read_bytes()).hexdigest()
        if runtime_report_path.is_file()
        else None
    )
    if actual_hash is None:
        errors.append("reviewed runtime report is missing")
    elif expected_hash != actual_hash:
        errors.append("runtime report hash no longer matches the reviewed evidence")

    return {
        "name": name,
        "status": "pass" if not errors else "fail",
        "manifest": str(manifest_path.resolve()),
        "runtimeReport": str(runtime_report_path.resolve()),
        "expectedRuntimeReportSha256": expected_hash,
        "actualRuntimeReportSha256": actual_hash,
        "costumeCount": len(costumes),
        "allowedUserBlockers": sorted(allowed_blockers),
        "errors": errors,
        "completionBlockers": [] if not errors else [f"{name}:stale-or-incomplete-review"],
    }


def audit_sm1_runtime_visual_review() -> dict[str, Any]:
    """Hash-lock literal frame review to the runtime reports it inspected."""
    errors: list[str] = []
    payload: dict[str, Any] = {}
    try:
        loaded = json.loads(SM1_RUNTIME_VISUAL_REVIEW.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise TypeError("root is not an object")
        payload = loaded
    except Exception as error:
        errors.append(f"invalid or missing review manifest: {error}")

    expected = {
        "story": CONVERTED / "all-characters-runtime-current" / "runtime-validation.json",
        "viewer": CONVERTED / "all-characters-viewer-runtime-current" / "runtime-validation.json",
        "hostagef": HOSTAGEF_PROOF / "runtime-validation.json",
        "symbiote": SYMBIOTE_PROOF / "runtime-validation.json",
        "jamesonScorpion": JAMESON_SCORPION_PROOF / "runtime-validation.json",
    }
    report_reviews = payload.get("reports", {}) if payload else {}
    report_results: list[dict[str, Any]] = []
    for name, runtime_path in expected.items():
        review = report_reviews.get(name, {})
        actual_hash = (
            hashlib.sha256(runtime_path.read_bytes()).hexdigest()
            if runtime_path.is_file()
            else None
        )
        expected_hash = review.get("runtimeReportSha256")
        reviewed_count = review.get("reviewedFrameCount")
        actual_count = None
        if runtime_path.is_file():
            try:
                runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
                if "captureCount" in runtime:
                    actual_count = runtime.get("captureCount")
                else:
                    actual_count = sum(
                        len(result.get("captures", {}))
                        for result in runtime.get("results", [])
                    )
            except Exception as error:
                errors.append(f"{name} runtime report is invalid: {error}")
        item_errors: list[str] = []
        if not review:
            item_errors.append("review entry is missing")
        if actual_hash is None:
            item_errors.append("runtime report is missing")
        elif expected_hash != actual_hash:
            item_errors.append("runtime report hash no longer matches reviewed evidence")
        if actual_count != reviewed_count:
            item_errors.append(
                f"reviewed frame count {reviewed_count!r} does not match runtime count {actual_count!r}"
            )
        if "review-complete" not in str(review.get("status", "")):
            item_errors.append("review status is incomplete")
        errors.extend(f"{name}: {message}" for message in item_errors)
        report_results.append(
            {
                "name": name,
                "runtimeReport": str(runtime_path.resolve()),
                "expectedRuntimeReportSha256": expected_hash,
                "actualRuntimeReportSha256": actual_hash,
                "reviewedFrameCount": reviewed_count,
                "actualFrameCount": actual_count,
                "status": "pass" if not item_errors else "fail",
                "errors": item_errors,
            }
        )

    preserved_holds = set(payload.get("preservedUserHolds", []))
    review_queue = json.loads(SM1_REVIEW_QUEUE.read_text(encoding="utf-8"))
    expected_holds = {
        actor
        for actor, review in review_queue.get("actors", {}).items()
        if review.get("blocksClearance") is True and "costume" not in review
    }
    if preserved_holds != expected_holds:
        errors.append(
            "preserved user holds do not match the runtime review queue: "
            + ", ".join(sorted(preserved_holds ^ expected_holds))
        )
    return {
        "status": "pass" if not errors else "fail",
        "manifest": str(SM1_RUNTIME_VISUAL_REVIEW.resolve()),
        "reports": report_results,
        "preservedUserHolds": sorted(preserved_holds),
        "errors": errors,
        "completionBlockers": [] if not errors else ["SM1-runtime:stale-or-incomplete-review"],
    }


def audit_runtime_report(
    name: str,
    path: Path,
    expected_status: str,
    minimum_schema: int,
    fresh_after: Path,
    requirements: tuple[tuple[str, bool], ...],
) -> dict[str, Any]:
    errors: list[str] = []
    payload: dict[str, Any] = {}
    if not path.is_file():
        errors.append("report is missing")
    else:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise TypeError("root is not an object")
            payload = loaded
        except Exception as error:
            errors.append(f"invalid JSON: {error}")

    if payload:
        schema = payload.get("schemaVersion")
        if not isinstance(schema, int) or schema < minimum_schema:
            errors.append(f"schemaVersion {schema!r} is below {minimum_schema}")
        if payload.get("status") != expected_status:
            errors.append(
                f"status {payload.get('status')!r} is not {expected_status!r}"
            )
        errors.extend(message for message, condition in requirements if not condition)
        if not fresh_after.is_file():
            errors.append(f"freshness input is missing: {fresh_after}")
        elif path.stat().st_mtime_ns < fresh_after.stat().st_mtime_ns:
            errors.append(f"report predates {fresh_after.name}")

    return {
        "name": name,
        "path": str(path.resolve()),
        "expectedStatus": expected_status,
        "freshAfter": str(fresh_after.resolve()),
        "status": "pass" if not errors else "fail",
        "errors": errors,
    }


def audit_runtime_evidence(runtime_executed: bool) -> dict[str, Any]:
    """Fail closed when runtime stages were skipped, stale, or structurally invalid."""
    required_stage_names = [
        "validateStoryRuntime",
        "validateSm1CostumeRuntime",
        "validateCharacterViewerRuntime",
        "validateHostagefViewerProbe",
        "validateSymbioteViewerProbe",
        "validateJamesonScorpionGameplayRuntime",
        "captureSm2DefaultNative",
        "validateSm2SpiderManCostumesRuntime",
    ]
    if not runtime_executed:
        return {
            "status": "runtime-not-run",
            "runtimeExecuted": False,
            "completionBlockers": [f"runtime:{name}" for name in required_stage_names],
            "reports": [],
            "policy": "Skipped runtime work can never produce a technical pass.",
        }

    actor_manifest = CONVERTED / "all-characters" / "manifest.json"
    sm2_default_pack = SM2_DEFAULT_RUNTIME / "pack-report.json"
    sm2_costume_pack = SM2_COSTUME_RUNTIME / "costume-pack.json"

    story_path = CONVERTED / "all-characters-runtime-current" / "runtime-validation.json"
    story = json.loads(story_path.read_text(encoding="utf-8")) if story_path.is_file() else {}
    sm1_costume_path = (
        CONVERTED / "all-characters-costumes-runtime-current" / "runtime-validation.json"
    )
    sm1_costume = (
        json.loads(sm1_costume_path.read_text(encoding="utf-8"))
        if sm1_costume_path.is_file()
        else {}
    )
    viewer_path = (
        CONVERTED / "all-characters-viewer-runtime-current" / "runtime-validation.json"
    )
    viewer = json.loads(viewer_path.read_text(encoding="utf-8")) if viewer_path.is_file() else {}
    hostagef_path = HOSTAGEF_PROOF / "runtime-validation.json"
    hostagef = json.loads(hostagef_path.read_text(encoding="utf-8")) if hostagef_path.is_file() else {}
    symbiote_path = SYMBIOTE_PROOF / "runtime-validation.json"
    symbiote = json.loads(symbiote_path.read_text(encoding="utf-8")) if symbiote_path.is_file() else {}
    jameson_scorpion_path = JAMESON_SCORPION_PROOF / "runtime-validation.json"
    jameson_scorpion = (
        json.loads(jameson_scorpion_path.read_text(encoding="utf-8"))
        if jameson_scorpion_path.is_file()
        else {}
    )
    sm2_default_path = SM2_DEFAULT_RUNTIME / "runtime-wing-proof" / "runtime-validation.json"
    sm2_default = (
        json.loads(sm2_default_path.read_text(encoding="utf-8"))
        if sm2_default_path.is_file()
        else {}
    )
    sm2_costumes_path = SM2_COSTUME_RUNTIME / "runtime-menu-proof" / "runtime-validation.json"
    sm2_costumes = (
        json.loads(sm2_costumes_path.read_text(encoding="utf-8"))
        if sm2_costumes_path.is_file()
        else {}
    )

    reports = [
        audit_runtime_report(
            "SM1 story actor matrix",
            story_path,
            "pass",
            4,
            actor_manifest,
            (
                ("renderScale is not 4", story.get("renderScale") == 4),
                ("story level matrix is incomplete", story.get("levelCount") == SM1_STORY_LEVEL_COUNT),
                (
                    "story actor coverage is incomplete",
                    story.get("runtimeCoveredCount") == story.get("runtimeTargetCount"),
                ),
                (
                    "one-process policy is missing",
                    story.get("processPolicy")
                    == "strictly sequential; never more than one SpiderMan process",
                ),
                (
                    "one or more story captures lacks the live level-geometry gate",
                    all(
                        result.get("levelGeometryCaptureGate") is True
                        for result in story.get("results", [])
                    )
                    and len(story.get("results", [])) == SM1_STORY_LEVEL_COUNT,
                ),
                (
                    "one or more story captures is not positively gated as live gameplay",
                    all(
                        capture.get("liveGameplayGate") is True
                        and capture.get("gameOverSignature", {}).get("matches") is False
                        and capture.get("saveProgressSignature", {}).get("matches") is False
                        for result in story.get("results", [])
                        for capture in result.get("captures", {}).values()
                    )
                    and sum(
                        len(result.get("captures", {}))
                        for result in story.get("results", [])
                    ) == SM1_STORY_LEVEL_COUNT * 2,
                ),
            ),
        ),
        audit_runtime_report(
            "SM1 costume menu",
            sm1_costume_path,
            "menu-capture-valid",
            3,
            actor_manifest,
            (
                ("proofMode is not menu", sm1_costume.get("proofMode") == "menu"),
                ("costume matrix is incomplete", sm1_costume.get("costumeCount") == 10),
                (
                    "one or more costumes lacks a valid menu signature",
                    all(
                        result.get("status") == "menu-capture-valid"
                        and result.get("markers", {}).get("liveMenuModelGate") is True
                        and result.get("markers", {}).get("mainMenuVisualSignature") is True
                        for result in sm1_costume.get("results", [])
                    )
                    and len(sm1_costume.get("results", [])) == 10,
                ),
            ),
        ),
        audit_runtime_report(
            "SM1 Character Viewer roster",
            viewer_path,
            "pass",
            3,
            actor_manifest,
            (
                ("renderScale is not 4", viewer.get("renderScale") == 4),
                ("viewer roster is incomplete", viewer.get("rosterCount") == 26),
                (
                    "viewer captures are incomplete",
                    viewer.get("captureCount") == viewer.get("rosterCount"),
                ),
                (
                    "one or more captures lacks the Character Viewer screen gate",
                    all(
                        capture.get("viewerTitleSignature", {}).get("matches") is True
                        for capture in viewer.get("captures", [])
                    )
                    and len(viewer.get("captures", [])) == 26,
                ),
            ),
        ),
        audit_runtime_report(
            "SM1 HOSTAGEF viewer probe",
            hostagef_path,
            "pass",
            3,
            actor_manifest,
            (
                ("renderScale is not 4", hostagef.get("renderScale") == 4),
                ("HOSTAGEF probe alias is missing", bool(hostagef.get("probe"))),
                (
                    "HOSTAGEF captures lack the Character Viewer screen gate",
                    all(
                        capture.get("viewerTitleSignature", {}).get("matches") is True
                        for capture in hostagef.get("captures", [])
                    )
                    and bool(hostagef.get("captures")),
                ),
            ),
        ),
        audit_runtime_report(
            "SM1 SYMBIOTE viewer probe",
            symbiote_path,
            "pass",
            3,
            actor_manifest,
            (
                ("renderScale is not 4", symbiote.get("renderScale") == 4),
                ("SYMBIOTE probe alias is missing", bool(symbiote.get("probe"))),
                (
                    "SYMBIOTE captures lack the Character Viewer screen gate",
                    all(
                        capture.get("viewerTitleSignature", {}).get("matches") is True
                        for capture in symbiote.get("captures", [])
                    )
                    and bool(symbiote.get("captures")),
                ),
            ),
        ),
        audit_runtime_report(
            "SM1 Jameson/Scorpion gameplay",
            jameson_scorpion_path,
            "pass",
            4,
            actor_manifest,
            (
                ("renderScale is not 4", jameson_scorpion.get("renderScale") == 4),
                ("focused gameplay level is not L2A2", jameson_scorpion.get("levels") == ["l2a2"]),
                (
                    "focused gameplay lacks the live level-geometry gate",
                    all(
                        result.get("levelGeometryCaptureGate") is True
                        for result in jameson_scorpion.get("results", [])
                    )
                    and len(jameson_scorpion.get("results", [])) == 1,
                ),
                (
                    "focused gameplay is not positively gated as live gameplay",
                    all(
                        capture.get("liveGameplayGate") is True
                        and capture.get("gameOverSignature", {}).get("matches") is False
                        and capture.get("saveProgressSignature", {}).get("matches") is False
                        for result in jameson_scorpion.get("results", [])
                        for capture in result.get("captures", {}).values()
                    )
                    and bool(jameson_scorpion.get("results")),
                ),
            ),
        ),
        audit_runtime_report(
            "SM2 default Spider-Man wings",
            sm2_default_path,
            "pass",
            3,
            sm2_default_pack,
            (
                ("renderScale is not the authored 8x proof", sm2_default.get("renderScale") == 8),
                (
                    "SM2 Default menu frame lacks the exact live-menu gate",
                    len(
                        sm2_default.get("frames", {})
                        .get("menu", {})
                        .get("mainMenuSignature", [])
                    )
                    == 4
                    and all(
                        region.get("matches") is True
                        and region.get("sha256") == region.get("expectedSha256")
                        for region in sm2_default.get("frames", {})
                        .get("menu", {})
                        .get("mainMenuSignature", [])
                    ),
                ),
                (
                    "SM2 Default gameplay frame lacks the exact active-HUD gate",
                    len(
                        sm2_default.get("frames", {})
                        .get("gameplay_deployed", {})
                        .get("gameplayHudSignature", [])
                    )
                    == 4
                    and all(
                        region.get("matches") is True
                        and region.get("sha256") == region.get("expectedSha256")
                        for region in sm2_default.get("frames", {})
                        .get("gameplay_deployed", {})
                        .get("gameplayHudSignature", [])
                    ),
                ),
                (
                    "SM2 Default proof includes an ungated scene frame",
                    set(sm2_default.get("frames", {}))
                    == {"menu", "gameplay_deployed"},
                ),
                (
                    "SM2 Default proof lacks fresh native 16-bit 3D captures",
                    all(
                        frame.get("native3d16BitMarker") is True
                        for frame in sm2_default.get("frames", {}).values()
                    )
                    and bool(sm2_default.get("frames")),
                ),
            ),
        ),
        audit_runtime_report(
            "SM2 Spider-Man costume menu",
            sm2_costumes_path,
            "menu-capture-valid",
            3,
            sm2_costume_pack,
            (
                ("renderScaleRequested is not 4", sm2_costumes.get("renderScaleRequested") == 4),
                ("SM2 Spider-Man costume matrix is incomplete", sm2_costumes.get("costumeCount") == 19),
                (
                    "one or more SM2 costumes lacks a valid menu signature",
                    all(
                        result.get("status") == "menu-capture-valid"
                        and result.get("runtimeMarkers", {}).get("mainMenuVisualSignature") is True
                        and result.get("runtimeMarkers", {}).get("freshRunToken") is True
                        and result.get("runtimeMarkers", {}).get("bootSkipBoundary") is True
                        and all(
                            capture.get("native3d16BitMarker") is True
                            for capture in result.get("captureSequence", [])
                        )
                        for result in sm2_costumes.get("results", [])
                    )
                    and len(sm2_costumes.get("results", [])) == 19,
                ),
            ),
        ),
    ]
    blockers = [f"runtime:{report['name']}" for report in reports if report["status"] != "pass"]
    return {
        "status": "pass" if not blockers else "fail",
        "runtimeExecuted": True,
        "completionBlockers": blockers,
        "reports": reports,
        "policy": "Runtime evidence must be current, structurally complete, and reviewable at 4x or higher.",
    }


def main() -> None:
    args = parse_args()
    if args.skip_runtime and args.use_existing_runtime_evidence:
        raise ValueError(
            "--skip-runtime and --use-existing-runtime-evidence are mutually exclusive"
        )
    execute_runtime = not args.skip_runtime and not args.use_existing_runtime_evidence
    python = str(Path(args.python).resolve())
    blender = None if args.skip_costume_build else resolve_blender(args.blender)
    multitool = (
        None
        if args.skip_static_tools and args.skip_costume_build
        else resolve_multitool(args.multitool)
    )
    stages: dict[str, Any] = {}

    if not args.skip_build:
        stages["buildVisibleWings"] = run(
            "build visible default wings",
            [
                python,
                str(TOOLS / "build_winged_spidey.py"),
                "--visible-wing-proof",
                "--output-model",
                str(VISIBLE / "spidey.psx"),
                "--output-textures",
                str(VISIBLE / "sp_tex00.psx"),
            ],
        )
    stages["verifyVisibleWingParity"] = run(
        "verify proof-only SM1 visible-wing parity",
        [python, str(TOOLS / "verify_wing_parity.py"), "--ported", str(VISIBLE / "spidey.psx")],
    )
    capture_command = [
        python,
        str(TOOLS / "capture_wing_runtime.py"),
        "--assets",
        str(VISIBLE),
        "--output",
        str(VISIBLE / "runtime-wing-seam-proof"),
    ]
    if args.reuse_wing_captures:
        capture_command.append("--reuse-captures")
    stages["captureVisibleWings"] = run(
        "capture proof-only visible wings in the SM1 diagnostic harness",
        capture_command,
    )

    if not args.skip_build:
        stages["buildProductionWings"] = run(
            "build production magenta-key wings",
            [
                python,
                str(TOOLS / "build_winged_spidey.py"),
                "--output-model",
                str(PRODUCTION / "spidey.psx"),
                "--output-textures",
                str(PRODUCTION / "sp_tex00.psx"),
            ],
        )
    stages["verifyWingBuildLock"] = run(
        "verify reproducible wing build lock",
        [python, str(TOOLS / "verify_wing_build_lock.py")],
    )
    stages["verifyProductionWingParity"] = run(
        "verify shipping SM1 zero-alpha wing-capable geometry parity",
        [python, str(TOOLS / "verify_wing_parity.py"), "--ported", str(PRODUCTION / "spidey.psx")],
    )
    stages["validateWingTextures"] = run(
        "validate proof-only visible and shipping SM1 transparent wing textures",
        [python, str(TOOLS / "validate_wing_textures.py")],
    )

    if not args.skip_build:
        stages["portAllCharacters"] = run(
            "port every Dreamcast actor", [python, str(TOOLS / "port_all_characters.py")]
        )
    stages["auditCharacterTexturePack"] = run(
        "audit compact actor pages and full-resolution texture pack",
        [python, str(TOOLS / "audit_character_texture_pack.py")],
    )
    stages["auditSm1SkeletonAdaptations"] = run(
        "audit SM1-native skeleton adaptations for Dreamcast actor meshes",
        [python, str(TOOLS / "audit_sm1_skeleton_adaptations.py")],
    )
    static_command = [python, str(TOOLS / "validate_all_characters.py")]
    if args.skip_static_tools:
        static_command.append("--skip-tools")
    else:
        static_command.extend(["--multitool", str(multitool)])
    stages["validateAllCharacters"] = run("validate every converted actor", static_command)

    if execute_runtime:
        runtime_command = [
            python,
            str(TOOLS / "validate_character_runtime.py"),
            "--concurrency",
            str(args.runtime_concurrency),
            "--render-scale",
            "4",
        ]
        if args.resume_runtime:
            runtime_command.append("--resume")
        stages["validateStoryRuntime"] = run("validate story actor runtime matrix", runtime_command)
        stages["validateSm1CostumeRuntime"] = run(
            "validate all SM1 costume models on the 3D main menu",
            [
                python,
                str(TOOLS / "validate_sm1_costume_models_runtime.py"),
                "--concurrency",
                "1",
                "--render-scale",
                "4",
                "--proof-mode",
                "menu",
            ],
        )
        stages["validateCharacterViewerRuntime"] = run(
            "validate the complete selectable SM1 Character Viewer roster",
            [
                python,
                str(TOOLS / "validate_character_viewer_runtime.py"),
                "--render-scale",
                "4",
            ],
        )
        stages["validateHostagefViewerProbe"] = run(
            "validate the otherwise unrouted SM1 HOSTAGEF actor",
            [
                python,
                str(TOOLS / "validate_character_viewer_runtime.py"),
                "--probe-model",
                "hostagef",
                "--probe-slot",
                "parker",
                "--output",
                str(HOSTAGEF_PROOF),
                "--render-scale",
                "4",
            ],
        )
        stages["validateSymbioteViewerProbe"] = run(
            "validate the otherwise unrouted SM1 SYMBIOTE actor",
            [
                python,
                str(TOOLS / "validate_character_viewer_runtime.py"),
                "--probe-model",
                "symbiote",
                "--probe-slot",
                "symbi_02",
                "--output",
                str(SYMBIOTE_PROOF),
                "--render-scale",
                "4",
            ],
        )
        stages["validateJamesonScorpionGameplayRuntime"] = run(
            "validate Jameson lighting and Scorpion's procedural tail in L2A2",
            [
                python,
                str(TOOLS / "validate_character_runtime.py"),
                "--levels",
                "l2a2",
                "--concurrency",
                "1",
                "--render-scale",
                "4",
                "--shots",
                "4200,4225,4250,4275,4300,4325,4350,4375,4400,4425,4450",
                "--exit-frame",
                "4500",
                "--output",
                str(JAMESON_SCORPION_PROOF),
                "--allow-partial-coverage",
            ],
        )

    stages["auditSm1ActorCoverage"] = run(
        "audit complete Dreamcast-to-SM1 actor coverage",
        [python, str(TOOLS / "audit_sm1_actor_coverage.py")],
    )

    base_glb = COSTUME_ROOT / "base" / "glb" / "spidey_dc_winged_hd.glb"
    for name, (source_file, output_file) in COSTUMES.items():
        port_root = COSTUME_ROOT / "ports" / name
        source_glb = COSTUME_ROOT / "variants-glb" / source_file
        output_glb = port_root / output_file
        if not args.skip_costume_build:
            transfer_command = [
                str(blender),
                "--background",
                "--python",
                str(TOOLS / "transfer_sm2_costume_to_dc.py"),
                "--",
                "--source",
                str(source_glb),
                "--target",
                str(base_glb),
                "--output",
                str(output_glb),
                "--textures-output",
                str(port_root / "textures"),
                "--name",
                name.upper(),
            ]
            if name == "default":
                transfer_command.extend(
                    ["--mapping-output", str(port_root / "native-face-map.json")]
                )
            stages[f"buildCostume:{name}"] = run(
                f"build {name} T-pose costume",
                transfer_command,
            )
        stages[f"auditCostume:{name}"] = run(
            f"audit {name} wings",
            [
                python,
                str(TOOLS / "audit_wing_glb.py"),
                "--source",
                str(source_glb),
                "--output",
                str(output_glb),
                "--report",
                str(port_root / "wing-audit.json"),
            ],
        )
        if not args.skip_costume_build:
            stages[f"renderCostume:{name}"] = run(
                f"render {name} T-pose review",
                [
                    str(multitool),
                    "glb-render",
                    str(output_glb),
                    "-o",
                    str(port_root / "renders"),
                    "--preset",
                    "object-review",
                    "--size",
                    "1024",
                ],
            )
            stages[f"renderCostumeWings:{name}"] = run(
                f"render {name} wing close-ups",
                [
                    str(blender),
                    "--background",
                    "--python",
                    str(TOOLS / "render_wing_closeups.py"),
                    "--",
                    "--input",
                    str(output_glb),
                    "--output-dir",
                    str(port_root / "wing-closeups"),
                    "--prefix",
                    name,
                    "--width",
                    "1800",
                    "--height",
                    "1200",
                ],
            )
    stages["validateCostumes"] = run(
        "validate selected SM2 costumes", [python, str(TOOLS / "validate_sm2_costumes.py")]
    )
    if not args.skip_costume_build:
        stages["packSm2DefaultNative"] = run(
            "pack mapped SM2 Default textures into a native Dreamcast-mesh actor",
            [
                python,
                str(TOOLS / "pack_sm2_costume_to_dc.py"),
                "--multitool",
                str(multitool),
            ],
        )
        stages["buildSm2SpiderManCostumePack"] = run(
            "build the complete 19-slot SM2 Dreamcast Spider-Man pack",
            [python, str(TOOLS / "build_sm2_spider_man_costume_pack.py")],
        )
    if execute_runtime:
        sm2_capture_command = [
            python,
            str(TOOLS / "capture_sm2_default_runtime.py"),
        ]
        if args.reuse_wing_captures:
            sm2_capture_command.append("--reuse-captures")
        stages["captureSm2DefaultNative"] = run(
            "capture native SM2 Default Dreamcast actor in one game process",
            sm2_capture_command,
        )
        sm2_costume_command = [
            python,
            str(TOOLS / "validate_sm2_spider_man_costumes_runtime.py"),
            "--render-scale",
            "4",
        ]
        if args.reuse_wing_captures:
            sm2_costume_command.append("--reuse-captures")
        stages["validateSm2SpiderManCostumesRuntime"] = run(
            "validate all 19 SM2 Spider-Man slots on the live 3D menu, sequentially",
            sm2_costume_command,
        )

    # Generate the mapping report after the native pack and runtime proof so its
    # per-actor status reflects current evidence rather than intended work.
    stages["mapSm2DcActors"] = run(
        "map PS1 SM2 character actors to compatible Dreamcast SM1 actors",
        [python, str(TOOLS / "map_sm2_dc_actors.py")],
    )
    stages["auditSm2PlayerPortCoverage"] = run(
        "audit complete SM2 player port and explicit retail fallbacks",
        [python, str(TOOLS / "audit_sm2_player_port_coverage.py")],
    )

    review_gate = audit_sm1_review_queue()
    stages["auditSm1ReviewQueue"] = review_gate
    sm1_costume_review = audit_costume_review_manifest(
        "SM1-costumes",
        SM1_COSTUME_REVIEW,
        CONVERTED / "all-characters-costumes-runtime-current" / "runtime-validation.json",
        10,
        {"SPQUICK"},
    )
    stages["auditSm1CostumeReview"] = sm1_costume_review
    sm1_runtime_visual_review = audit_sm1_runtime_visual_review()
    stages["auditSm1RuntimeVisualReview"] = sm1_runtime_visual_review
    sm2_costume_review = audit_costume_review_manifest(
        "SM2-Spider-Man-costumes",
        SM2_COSTUME_REVIEW,
        SM2_COSTUME_RUNTIME / "runtime-menu-proof" / "runtime-validation.json",
        19,
        set(),
    )
    stages["auditSm2CostumeReview"] = sm2_costume_review
    runtime_gate = audit_runtime_evidence(not args.skip_runtime)
    stages["auditRuntimeEvidence"] = runtime_gate

    runtime_blockers = runtime_gate["completionBlockers"]
    technical_defects = review_gate["technicalDefects"]
    review_blockers = (
        review_gate["blockedActors"]
        + sm1_costume_review["completionBlockers"]
        + sm1_runtime_visual_review["completionBlockers"]
        + sm2_costume_review["completionBlockers"]
    )
    completion_blockers = runtime_blockers + review_blockers
    if runtime_gate["status"] == "runtime-not-run":
        pipeline_status = "incomplete-runtime-validation"
    elif runtime_gate["status"] != "pass":
        pipeline_status = "runtime-validation-failed"
    elif technical_defects:
        pipeline_status = "technical-defect-confirmed"
    elif review_blockers:
        pipeline_status = "technical-pass-user-review-required"
    else:
        pipeline_status = "pass"

    report = {
        "schemaVersion": 2,
        "status": pipeline_status,
        "completionBlockers": completion_blockers,
        "runtimeValidationExecuted": execute_runtime,
        "existingRuntimeEvidenceAudited": args.use_existing_runtime_evidence,
        "wingOwnershipPolicy": {
            "sm1Shipping": (
                "wing-capable geometry retained with a magenta/all-zero-alpha "
                "texture; visually wingless"
            ),
            "sm1VisibleHarness": (
                "diagnostic seam/UV/weighting proof only; not a shipping appearance"
            ),
            "sm2Shipping": "visible black/white web wings in menu and gameplay",
        },
        "stages": stages,
        "artifacts": {
            "visibleModel": digest(VISIBLE / "spidey.psx"),
            "visibleTextures": digest(VISIBLE / "sp_tex00.psx"),
            "productionModel": digest(PRODUCTION / "spidey.psx"),
            "productionTextures": digest(PRODUCTION / "sp_tex00.psx"),
            "wingTextureValidation": str((CONVERTED / "wing-texture-validation.json").resolve()),
            "wingRuntimeProof": str((VISIBLE / "runtime-wing-seam-proof" / "wing-runtime-proof.json").resolve()),
            "allCharacterManifest": str((CONVERTED / "all-characters" / "manifest.json").resolve()),
            "actorTexturePackAudit": str((CONVERTED / "all-characters" / "packs" / "dreamcast-sm1-actors" / "texture-audit.json").resolve()),
            "skeletonAdaptationAudit": str((CONVERTED / "all-characters" / "skeleton-adaptation-audit.json").resolve()),
            "allCharacterValidation": str((CONVERTED / "all-characters-validation-current" / "validation.json").resolve()),
            "sm1ActorCoverageAudit": str((CONVERTED / "sm1-dc-actor-coverage.json").resolve()),
            "runtimeValidation": str((CONVERTED / "all-characters-runtime-current" / "runtime-validation.json").resolve()),
            "sm1CostumeRuntimeValidation": str((CONVERTED / "all-characters-costumes-runtime-current" / "runtime-validation.json").resolve()),
            "characterViewerRuntimeValidation": str((CONVERTED / "all-characters-viewer-runtime-current" / "runtime-validation.json").resolve()),
            "hostagefViewerProbe": str((HOSTAGEF_PROOF / "runtime-validation.json").resolve()),
            "symbioteViewerProbe": str((SYMBIOTE_PROOF / "runtime-validation.json").resolve()),
            "jamesonScorpionGameplayValidation": str((JAMESON_SCORPION_PROOF / "runtime-validation.json").resolve()),
            "sm2DcActorMap": str((CONVERTED / "sm2-dc-actor-map.json").resolve()),
            "sm2PlayerPortCoverageAudit": str((CONVERTED / "sm2-player-port-coverage.json").resolve()),
            "costumeValidation": str((COSTUME_ROOT / "validation.json").resolve()),
            "sm2DefaultRuntimeModel": digest(SM2_DEFAULT_RUNTIME / "spidey.psx"),
            "sm2DefaultRuntimeTextures": digest(SM2_DEFAULT_RUNTIME / "sp_tex00.psx"),
            "sm2DefaultPackReport": str((SM2_DEFAULT_RUNTIME / "pack-report.json").resolve()),
            "sm2DefaultRuntimeValidation": str((SM2_DEFAULT_RUNTIME / "runtime-wing-proof" / "runtime-validation.json").resolve()),
            "sm2DefaultMenuWingProof": str((SM2_DEFAULT_RUNTIME / "runtime-wing-proof" / "sm2_default_menu_wings_close.png").resolve()),
            "sm2DefaultGameplayWingProof": str((SM2_DEFAULT_RUNTIME / "runtime-wing-proof" / "sm2_default_gameplay_wings_close.png").resolve()),
            "sm2SpiderManCostumePack": str((SM2_COSTUME_RUNTIME / "costume-pack.json").resolve()),
            "sm2SpiderManCostumeRuntimeValidation": str((SM2_COSTUME_RUNTIME / "runtime-menu-proof" / "runtime-validation.json").resolve()),
            "sm2SpiderManCostumeReview": str(SM2_COSTUME_REVIEW.resolve()),
            "sm1CostumeMenuReview": str(SM1_COSTUME_REVIEW.resolve()),
            "sm1RuntimeVisualReview": str(SM1_RUNTIME_VISUAL_REVIEW.resolve()),
            "sm1ModelReview": str(SM1_REVIEW_QUEUE.resolve()),
        },
    }
    report_path = CONVERTED / "port-pipeline-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if pipeline_status == "pass":
        summary = "PASS: complete Dreamcast character port pipeline"
    elif pipeline_status == "incomplete-runtime-validation":
        summary = "INCOMPLETE: runtime validation was skipped"
    elif pipeline_status == "runtime-validation-failed":
        summary = "FAIL: required runtime evidence is missing, stale, or invalid"
    elif pipeline_status == "technical-defect-confirmed":
        summary = "FAIL: CONFIRMED TECHNICAL DEFECT: " + ", ".join(technical_defects)
    else:
        summary = (
            "TECHNICAL PASS; USER REVIEW REQUIRED: "
            + ", ".join(review_blockers)
        )
    print(f"\n{summary}\nreport: {report_path}")
    if pipeline_status in {"runtime-validation-failed", "technical-defect-confirmed"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
