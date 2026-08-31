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
COSTUME_ROOT = CONVERTED / "sm2-costume-tests"
COSTUMES = {
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
    parser.add_argument("--runtime-concurrency", type=int, default=3)
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
    multitool = None if args.skip_static_tools else resolve_multitool(args.multitool)
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

    base_glb = COSTUME_ROOT / "base" / "glb" / "spidey_dc_winged_hd.glb"
    for name, (source_file, output_file) in COSTUMES.items():
        port_root = COSTUME_ROOT / "ports" / name
        source_glb = COSTUME_ROOT / "variants-glb" / source_file
        output_glb = port_root / output_file
        if not args.skip_costume_build:
            stages[f"buildCostume:{name}"] = run(
                f"build {name} T-pose costume",
                [
                    str(blender),
                    "--background",
                    "--python",
                    str(TOOLS / "bake_sm2_costume_to_dc.py"),
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
                ],
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
            "wingRuntimeProof": str((VISIBLE / "runtime-wing-real-proof" / "wing-runtime-proof.json").resolve()),
            "allCharacterManifest": str((CONVERTED / "all-characters" / "manifest.json").resolve()),
            "allCharacterValidation": str((CONVERTED / "all-characters-validation-current" / "validation.json").resolve()),
            "runtimeValidation": str((CONVERTED / "all-characters-runtime-current" / "runtime-validation.json").resolve()),
            "costumeValidation": str((COSTUME_ROOT / "validation.json").resolve()),
        },
    }
    report_path = CONVERTED / "port-pipeline-report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nPASS: complete Dreamcast character port pipeline\nreport: {report_path}")


if __name__ == "__main__":
    main()
