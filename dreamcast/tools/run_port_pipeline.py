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


def main() -> None:
    args = parse_args()
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
        "verify visible wing parity",
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
    stages["captureVisibleWings"] = run("capture default wings in game", capture_command)

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
        "verify production wing parity",
        [python, str(TOOLS / "verify_wing_parity.py"), "--ported", str(PRODUCTION / "spidey.psx")],
    )
    stages["validateWingTextures"] = run(
        "validate visible and production wing textures",
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

    if not args.skip_runtime:
        runtime_command = [
            python,
            str(TOOLS / "validate_character_runtime.py"),
            "--concurrency",
            str(args.runtime_concurrency),
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
    if not args.skip_runtime:
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

    report = {
        "schemaVersion": 1,
        "status": "pass",
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
            "runtimeValidation": str((CONVERTED / "all-characters-runtime-current" / "runtime-validation.json").resolve()),
            "sm1CostumeRuntimeValidation": str((CONVERTED / "all-characters-costumes-runtime-current" / "runtime-validation.json").resolve()),
            "characterViewerRuntimeValidation": str((CONVERTED / "all-characters-viewer-runtime-current" / "runtime-validation.json").resolve()),
            "hostagefViewerProbe": str((HOSTAGEF_PROOF / "runtime-validation.json").resolve()),
            "symbioteViewerProbe": str((SYMBIOTE_PROOF / "runtime-validation.json").resolve()),
            "jamesonScorpionGameplayValidation": str((JAMESON_SCORPION_PROOF / "runtime-validation.json").resolve()),
            "sm2DcActorMap": str((CONVERTED / "sm2-dc-actor-map.json").resolve()),
            "costumeValidation": str((COSTUME_ROOT / "validation.json").resolve()),
            "sm2DefaultRuntimeModel": digest(SM2_DEFAULT_RUNTIME / "spidey.psx"),
            "sm2DefaultRuntimeTextures": digest(SM2_DEFAULT_RUNTIME / "sp_tex00.psx"),
            "sm2DefaultPackReport": str((SM2_DEFAULT_RUNTIME / "pack-report.json").resolve()),
            "sm2DefaultRuntimeValidation": str((SM2_DEFAULT_RUNTIME / "runtime-wing-proof" / "runtime-validation.json").resolve()),
            "sm2DefaultMenuWingProof": str((SM2_DEFAULT_RUNTIME / "runtime-wing-proof" / "sm2_default_menu_wings_close.png").resolve()),
            "sm2DefaultGameplayWingProof": str((SM2_DEFAULT_RUNTIME / "runtime-wing-proof" / "sm2_default_gameplay_wings_close.png").resolve()),
            "sm2SpiderManCostumePack": str((SM2_COSTUME_RUNTIME / "costume-pack.json").resolve()),
            "sm2SpiderManCostumeRuntimeValidation": str((SM2_COSTUME_RUNTIME / "runtime-menu-proof" / "runtime-validation.json").resolve()),
            "sm2SpiderManCostumeReview": str((ROOT / "dreamcast" / "manifests" / "sm2-spider-man-costume-review.json").resolve()),
        },
    }
    report_path = CONVERTED / "port-pipeline-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nPASS: complete Dreamcast character port pipeline\nreport: {report_path}")


if __name__ == "__main__":
    main()
