#!/usr/bin/env python3
"""Exercise every SM1 costume slot with its dedicated Dreamcast actor at runtime.

The harness uses only process-local controller state and the recompilation's native
GPU capture path.  It never sends keyboard, mouse, or controller input to Windows.

The default proof stops at the main menu, where the active costume is already rendered
large in 3D.  Gameplay mode remains available for defects that require player motion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
from typing import Any

from PIL import Image

from validate_character_runtime import (
    game_over_signature,
    gameplay_hud_signature,
    save_progress_signature,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXE = ROOT / "spiderman" / "port" / "bin" / "Release" / "net10.0" / "SpiderMan.exe"
DEFAULT_BATCH = ROOT / "dreamcast" / "converted" / "all-characters"
DEFAULT_OUTPUT = ROOT / "dreamcast" / "converted" / "all-characters-costumes-runtime-current"
GAMEPLAY_INPUT_SCRIPT = (
    "title.bmr+120:start:12;title.bmr+420:cross:12;"
    "title.bmr+720:cross:12;title.bmr+1100:cross:12;"
    "title.bmr+1500:cross:12;title.bmr+1900:cross:12"
)
MENU_INPUT_SCRIPT = "title.bmr+120:start:12"
BOOT_SKIP_ANCHOR = "title.bmr"
PROOF_DEFAULTS = {
    "menu": {
        "shots": (
            "menu.spidey+180,menu.spidey+330,menu.spidey+480,"
            "menu.spidey+630,menu.spidey+780,menu.spidey+930,"
            "menu.spidey+1080"
        ),
        "exitFrame": 1800,
        "inputScript": MENU_INPUT_SCRIPT,
    },
    "gameplay": {
        "shots": "4300,4400",
        "exitFrame": 4450,
        "inputScript": GAMEPLAY_INPUT_SCRIPT,
    },
}
# Exact actor-free portions of SM1's live 3D main-menu chrome at 4x internal
# resolution.  Image dimensions and color statistics cannot distinguish a
# scaled FMV from the menu; these labels positively identify the required screen.
MENU_REGION_SIGNATURES = {
    "continueLabel": {
        "bounds": (120, 100, 410, 235),
        "sha256": "fd276d1b8a0dc3abcd7d342ba8c3f07391816fca3b0879e58a3787078aab9f1a",
    },
    "trainingLabel": {
        "bounds": (875, 100, 1150, 235),
        "sha256": "9e2e7f0552a9a96fc17f7bd6aba699aa68b8e518b1c03dc4e8d97a9a43afba22",
    },
    "optionsLabel": {
        "bounds": (150, 735, 420, 850),
        "sha256": "a7375d678f324b7d5dc7519c015fd229459bfcb6983b390cfedf2a9acc5c8fce",
    },
    "galleryLabel": {
        "bounds": (880, 735, 1140, 850),
        "sha256": "d16b68d3e19d451d4f0c87d9f2930997a993ba1127a3064e50db34bc51265c77",
    },
}
COSTUMES = (
    ("spiderman", "spidey.psx", "sp_tex00.psx", "sp_tex00.psx"),
    ("2099", "sp2099.psx", "sp_tex01.psx", "sp_tex01.psx"),
    ("symbiote", "spsymbi.psx", "sp_tex02.psx", "sp_tex02.psx"),
    ("captain", "spuniv.psx", "sp_tex03.psx", "sp_tex03.psx"),
    ("unlimited", "spunlim.psx", "sp_tex04.psx", "sp_tex04.psx"),
    ("bagman", "spbagman.psx", "sp_tex05.psx", "sp_tex05.psx"),
    ("scarlet", "spscar.psx", "sp_tex06.psx", "sp_tex06.psx"),
    ("benreilly", "spreilly.psx", "sp_tex07.psx", "sp_tex07.psx"),
    ("quickchange", "spquick.psx", "sp_tex08.psx", "sp_tex08.psx"),
    ("peterparker", "sppark.psx", "sp_tex09.psx", "sp_tex09.psx"),
    ("spiderphoenix", "sp2phoenix.psx", "sp_tex00.psx", None),
    ("prodigy", "sp2prodigy.psx", "sp_tex00.psx", None),
    ("dusk", "sp2dusk.psx", "sp_tex00.psx", None),
    ("insulated", "sp2insulated.psx", "sp_tex00.psx", None),
    ("alexrossred", "sp2rossred.psx", "sp_tex00.psx", None),
    ("alexrosswhite", "sp2rosswhite.psx", "sp_tex00.psx", None),
    ("venomearthx", "sp2venomx.psx", "sp_tex00.psx", None),
    ("negativezone", "sp2negative.psx", "sp_tex00.psx", None),
    ("battledamaged", "sp2battle.psx", "sp_tex00.psx", None),
    ("spidermanwinged", "sp2default.psx", "sp_tex00.psx", None),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=DEFAULT_EXE)
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--level", default="l1a1")
    parser.add_argument(
        "--slots",
        default=",".join(str(slot) for slot in range(len(COSTUMES))),
        help="comma-separated costume slots to test",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="must be 1; parallel game instances are intentionally forbidden",
    )
    parser.add_argument("--render-scale", type=int, default=4)
    parser.add_argument(
        "--widescreen",
        action="store_true",
        help="enable SM1's 16:9 gameplay presentation and validate 16:9 captures",
    )
    parser.add_argument(
        "--proof-mode",
        choices=tuple(PROOF_DEFAULTS),
        default="menu",
        help="menu is the fast stable 3D costume proof; gameplay tests player motion",
    )
    parser.add_argument("--shots", help="capture frames (defaults depend on --proof-mode)")
    parser.add_argument("--exit-frame", type=int, help="exit frame (defaults depend on --proof-mode)")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument(
        "--dump-textures",
        action="store_true",
        help="dump complete texture uploads for host-GPU replacement-pack authoring",
    )
    parser.add_argument("--prims", help="capture-frame primitive dump for diagnostics")
    return parser.parse_args()


def verify_capture(path: Path, expected_size: tuple[int, int]) -> dict[str, Any]:
    with Image.open(path) as image:
        image.load()
        if image.size != expected_size:
            raise ValueError(f"{path} is {image.size}, expected {expected_size}")
        rgb = image.convert("RGB")
        extrema = rgb.getextrema()
        colors = rgb.getcolors(maxcolors=expected_size[0] * expected_size[1])
    dynamic_range = max(channel[1] - channel[0] for channel in extrema)
    color_count = len(colors) if colors is not None else expected_size[0] * expected_size[1]
    if dynamic_range < 32 or color_count < 64:
        raise ValueError(
            f"{path} does not resemble a rendered game frame "
            f"(range={dynamic_range}, colors={color_count})"
        )
    return {
        "size": list(expected_size),
        "dynamicRange": dynamic_range,
        "colorCount": color_count,
    }


def ensure_no_game_process() -> None:
    result = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq SpiderMan.exe", "/FO", "CSV", "/NH"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode == 0 and re.search(
        r'"SpiderMan\.exe"', result.stdout, re.IGNORECASE
    ):
        raise RuntimeError("refusing to launch while another SpiderMan.exe process exists")


def model_mesh_signatures(path: Path) -> set[tuple[int, int, int]]:
    """Return stable (mesh, vertex, face) identities for one v4 actor."""
    data = path.read_bytes()
    version, magic = struct.unpack_from("<HH", data, 0)
    if (version, magic) != (4, 2):
        raise ValueError(f"{path} is v{version} magic {magic:04X}, expected v4 magic 0002")
    object_count = struct.unpack_from("<I", data, 8)[0]
    mesh_count_offset = 12 + object_count * 36
    mesh_count = struct.unpack_from("<I", data, mesh_count_offset)[0]
    pointer_table = mesh_count_offset + 4
    signatures = set()
    for mesh_index in range(mesh_count):
        pointer = struct.unpack_from("<I", data, pointer_table + mesh_index * 4)[0]
        vertex_count = struct.unpack_from("<H", data, pointer + 2)[0]
        face_count = struct.unpack_from("<H", data, pointer + 6)[0]
        signatures.add((mesh_index, vertex_count, face_count))
    return signatures


def validate_main_menu_signature(path: Path) -> list[dict[str, Any]]:
    """Positively identify SM1's live 3D main menu, failing closed."""
    with Image.open(path) as opened:
        opened.load()
        image = opened.convert("RGB")
        results = []
        for name, expected in MENU_REGION_SIGNATURES.items():
            bounds = expected["bounds"]
            digest = hashlib.sha256(image.crop(bounds).tobytes()).hexdigest()
            results.append(
                {
                    "name": name,
                    "bounds": list(bounds),
                    "sha256": digest,
                    "expectedSha256": expected["sha256"],
                    "matches": digest == expected["sha256"],
                }
            )
    mismatches = [result["name"] for result in results if not result["matches"]]
    if mismatches:
        raise ValueError(
            f"{path} is not the verified live 3D main menu; "
            f"menu chrome mismatched at {', '.join(mismatches)}"
        )
    return results


def run_costume(
    slot: int,
    name: str,
    model: str,
    requested_texture: str,
    source_texture: str | None,
    exe: Path,
    batch: Path,
    output: Path,
    level: str | None,
    proof_mode: str,
    input_script: str,
    render_scale: int,
    widescreen: bool,
    shots: str,
    exit_frame: int,
    timeout: int,
    dump_textures: bool,
    prims: str | None,
) -> dict[str, Any]:
    ensure_no_game_process()
    costume_dir = output / f"{slot:02d}-{name}"
    costume_dir.mkdir(parents=True, exist_ok=True)
    for old_capture in costume_dir.glob("frame_*.png"):
        old_capture.unlink()

    env = {key: value for key, value in os.environ.items() if not key.startswith("SPIDEY_")}
    env.pop("RECOMP_RENDER_SCALE", None)
    env.update(
        {
            "RECOMP_RENDER_SCALE": str(render_scale),
            "SPIDEY_ASSET_DIR": str(batch),
            "SPIDEY_BOOT_SKIP_UNTIL": BOOT_SKIP_ANCHOR,
            "SPIDEY_COSTUME": str(slot),
            "SPIDEY_HZ": "60",
            "SPIDEY_SCRIPT": input_script,
            "SPIDEY_SHOTS": shots,
            "SPIDEY_SHOT_DIR": str(costume_dir),
            "SPIDEY_EXIT": str(exit_frame),
            "SPIDEY_LOG_DIR": str(costume_dir),
            "SPIDEY_STALL_EXIT": "1",
            "SPIDEY_TRACE_GAME": "1",
            "SPIDEY_TRACE_WAD": "1",
            "RECOMP_VALIDATE_MODEL_GEOMETRY": "1",
        }
    )
    if widescreen:
        env["SPIDEY_WIDE"] = "1"
    if level is not None:
        env["SPIDEY_LEVEL"] = level
        # Idle proof runs must not die before the requested deformation window.
        env["SPIDEY_CHEATS"] = "invuln"
    if dump_textures:
        dump_root = costume_dir / "texture-dump"
        env["SPIDEY_DUMP_TEXTURES"] = "pages"
        env["RECOMP_TEXTURE_DUMP_DIR"] = str(dump_root)
    if prims:
        env["SPIDEY_PRIMS"] = prims
    try:
        result = subprocess.run(
            [str(exe)],
            cwd=exe.parent,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        console = result.stdout or ""
        return_code: int | None = result.returncode
        timed_out = False
    except subprocess.TimeoutExpired as error:
        console = (
            (error.stdout or "")
            if isinstance(error.stdout, str)
            else (error.stdout or b"").decode(errors="replace")
        )
        return_code = None
        timed_out = True
    console_path = costume_dir / "console.log"
    console_path.write_text(console, encoding="utf-8")

    expected_texture = requested_texture
    markers = {
        "selection": f"[costume] {name} (index {slot})" in console,
        "modelOverride": bool(
            re.search(
                rf"\[loose-wad\] override spidey\.psx(?: <- {re.escape(model)})?:",
                console,
                re.IGNORECASE,
            )
        ),
        "cleanExit": f"[capture] exit at frame {exit_frame}" in console,
    }
    # The recomp costume hook reloads the selected self-contained actor and skips
    # retail's separate sp_tex overlay. Static texture-pack auditing verifies the
    # embedded records; requiring a companion load here rejects the actual path.
    markers["embeddedTexturePath"] = bool(
        re.search(
            r"\[costume\] viewer actor (?:reload slot \d+:|already loaded:)",
            console,
        )
    )
    if proof_mode == "menu":
        title_load = re.search(
            r"\[capture\] 'title\.bmr'(?: load #\d+)? at frame (\d+): step resolved",
            console,
        )
        markers["introMovieSkipped"] = bool(
            title_load and int(title_load.group(1)) < 1000
        )
        model_shots = re.findall(
            r"\[capture\] 'menu\.spidey' at frame (\d+): "
            r"title-shell model shot resolved to frame (\d+)",
            console,
        )
        markers["liveMenuModelGate"] = (
            len(model_shots) == len([shot for shot in shots.split(",") if shot.strip()])
            and len({int(frame) for _, frame in model_shots}) == len(model_shots)
        )
    audit_console = console
    if proof_mode == "gameplay":
        construction = re.search(
            rf"\[costume\] ability config {re.escape(name)} <- ", console
        )
        if construction is not None:
            audit_console = console[construction.start() :]
    player_meshes = model_mesh_signatures(batch / model)
    head_audits = [
        (int(invalid), int(span))
        for mesh, vertices, faces, invalid, span in re.findall(
            r"\[model-mesh-audit\].*?mesh=(\d+).*?vertices=(\d+).*?faces=(\d+)"
            r".*?invalid=(\d+).*?max-span=(\d+)",
            audit_console,
        )
        if (int(mesh), int(vertices), int(faces)) in player_meshes
    ]
    markers["headGeometry"] = bool(head_audits) and all(
        invalid == 0 and span <= 80 for invalid, span in head_audits
    )
    if slot != 0:
        markers["modelAlias"] = (
            f"[costume] Dreamcast asset spidey.psx <- {model}".lower() in console.lower()
        )
    if slot >= 10 and source_texture is not None:
        markers["textureAlias"] = (
            f"[costume] Dreamcast asset {requested_texture} <- {source_texture}".lower()
            in console.lower()
        )

    expected_height = 240 * render_scale
    expected_size = (
        (round(expected_height * 16 / 9), expected_height)
        if widescreen
        else (320 * render_scale, expected_height)
    )
    markers["modernRenderer"] = "[Gpu] backend: Gl45" in console
    markers["widescreen"] = (
        "[wide] aspect 1.778" in console if widescreen else True
    )
    captures: dict[str, Any] = {}
    capture_error: str | None = None
    level_asset_proofs: dict[str, str] = {}
    try:
        captures = {
            path.name: verify_capture(path, expected_size)
            for path in sorted(costume_dir.glob("frame_*.png"))
        }
        if len(captures) != len([shot for shot in shots.split(",") if shot.strip()]):
            raise ValueError(f"expected {shots} captures, found {sorted(captures)}")
        if proof_mode == "menu":
            for capture_name in captures:
                if not re.search(
                    rf"\[capture\].*{re.escape(capture_name)} .*"
                    r"\(live-3d 16bpp display aspect\)",
                    console,
                ):
                    raise ValueError(
                        f"{capture_name} lacks the native live-3D 16bpp capture marker"
                    )
            for capture_name, capture in captures.items():
                capture["mainMenuSignature"] = validate_main_menu_signature(
                    costume_dir / capture_name
                )
            markers["mainMenuVisualSignature"] = all(
                all(region["matches"] for region in capture["mainMenuSignature"])
                for capture in captures.values()
            )
        else:
            for capture_name, capture in captures.items():
                if not re.search(
                    rf"\[capture\].*{re.escape(capture_name)} .*"
                    r"\(live-3d 16bpp display aspect\)",
                    console,
                ):
                    raise ValueError(
                        f"{capture_name} lacks the native live-3D 16bpp capture marker"
                    )
                state_match = re.search(
                    rf"\[capture\].*{re.escape(capture_name)} .*"
                    r"\(level-runframe-entered=(\d+)\)",
                    console,
                )
                active_level_runframe = int(state_match.group(1)) if state_match else 0
                with Image.open(costume_dir / capture_name) as opened:
                    opened.load()
                    image = opened.convert("RGB")
                gameplay_hud = gameplay_hud_signature(image)
                game_over = game_over_signature(image)
                save_progress = save_progress_signature(image)
                if game_over["matches"]:
                    raise ValueError(
                        f"{capture_name} is the retail GAME OVER screen "
                        f"(signature distance={game_over['hammingDistance']})"
                    )
                if save_progress["matches"]:
                    raise ValueError(
                        f"{capture_name} is the retail SAVE GAME PROGRESS screen "
                        f"(signature distance={save_progress['hammingDistance']})"
                    )
                live_gameplay_gate = active_level_runframe > 0 or gameplay_hud["matches"]
                if not live_gameplay_gate:
                    raise ValueError(
                        f"{capture_name} has neither a non-zero level RunFrame entry nor "
                        "the verified gameplay HUD signature "
                        f"(HUD coverage={gameplay_hud['coverage']:.3f})"
                    )
                capture.update(
                    {
                        "activeLevelRunFrame": active_level_runframe,
                        "gameplayHudSignature": gameplay_hud,
                        "gameOverSignature": game_over,
                        "saveProgressSignature": save_progress,
                        "liveGameplayGate": live_gameplay_gate,
                    }
                )

            assert level is not None
            for suffix in ("L", "O", "G"):
                stem = f"{level.upper()}_{suffix}"
                if re.search(
                    rf"(?m)^{re.escape(stem)}\.psx\[wad\]\s+"
                    rf"{re.escape(stem)}\.psx\s+<-",
                    console,
                    re.IGNORECASE,
                ):
                    level_asset_proofs[suffix] = f"{stem}.psx"
            markers["levelAssetsLoaded"] = len(level_asset_proofs) == 3
            geometry_proof = level_asset_proofs.get("G")
            geometry_log_position = (
                console.lower().find(f"{geometry_proof.lower()}[wad]")
                if geometry_proof
                else -1
            )
            capture_log_positions = [
                console.find(f"[capture] {costume_dir / capture_name}")
                for capture_name in captures
            ]
            markers["levelGeometryCaptureGate"] = (
                geometry_log_position >= 0
                and all(position > geometry_log_position for position in capture_log_positions)
            )
            markers["liveGameplayGate"] = all(
                capture["liveGameplayGate"] for capture in captures.values()
            )
            # Player construction is the authoritative gameplay gate. The model
            # parser's pointer-identity diagnostic follows the title-shell actor;
            # gameplay instantiates Spider-Man through a copied actor structure, so
            # requiring that diagnostic again rejects valid gameplay captures. The
            # post-constructor ability hook runs only after func_80047DF8 completes
            # successfully and names the independently selected costume profile.
            player_construct = re.search(
                rf"\[costume\] ability config {re.escape(name)} <- ",
                console,
            )
            markers["levelPlayerConstructionGate"] = (
                geometry_log_position >= 0
                and player_construct is not None
                and player_construct.start() > geometry_log_position
                and all(
                    capture_position > player_construct.start()
                    for capture_position in capture_log_positions
                )
            )
    except (OSError, ValueError) as error:
        capture_error = str(error)

    bad_markers = [
        marker
        for marker in ("Unhandled exception", "watchdog: STALLED", "MISSED -- overlay not resident")
        if marker.lower() in console.lower()
    ]
    valid_status = (
        "menu-capture-valid" if proof_mode == "menu" else "gameplay-capture-valid"
    )
    status = (
        valid_status
        if not timed_out
        and return_code == 0
        and all(markers.values())
        and captures
        and capture_error is None
        and not bad_markers
        else "capture-invalid"
    )
    return {
        "slot": slot,
        "costume": name,
        "dreamcastModel": model,
        "textureLibrary": expected_texture,
        "textureSource": source_texture or "embedded resolved runtime pages",
        "proofMode": proof_mode,
        "status": status,
        "returnCode": return_code,
        "timedOut": timed_out,
        "markers": markers,
        "headGeometryAudit": {
            "sampleCount": len(head_audits),
            "invalidFaceIndexCount": max((invalid for invalid, _ in head_audits), default=None),
            "maxFaceSpan": max((span for _, span in head_audits), default=None),
            "maxAllowedFaceSpan": 80,
        },
        "badMarkers": bad_markers,
        "captureError": capture_error,
        "levelAssetProofs": level_asset_proofs,
        "captures": captures,
        "consoleLog": str(console_path),
    }


def main() -> None:
    args = parse_args()
    exe = args.exe.resolve()
    batch = args.batch.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.concurrency != 1:
        raise ValueError("--concurrency must be exactly 1; parallel game instances are forbidden")
    if args.proof_mode == "menu" and args.render_scale != 4:
        raise ValueError("menu proof requires --render-scale 4 for its exact visual signature")
    slots = tuple(int(value.strip()) for value in args.slots.split(",") if value.strip())
    if not slots or any(slot < 0 or slot >= len(COSTUMES) for slot in slots):
        raise ValueError(
            f"--slots must select one or more values from 0 through {len(COSTUMES) - 1}"
        )
    proof_defaults = PROOF_DEFAULTS[args.proof_mode]
    shots = args.shots or proof_defaults["shots"]
    exit_frame = args.exit_frame or proof_defaults["exitFrame"]
    input_script = proof_defaults["inputScript"]
    level = args.level if args.proof_mode == "gameplay" else None

    results: list[dict[str, Any]] = []
    valid_status = (
        "menu-capture-valid" if args.proof_mode == "menu" else "gameplay-capture-valid"
    )
    for slot, (name, model, requested_texture, source_texture) in enumerate(COSTUMES):
        if slot not in slots:
            continue
        result = run_costume(
            slot,
            name,
            model,
            requested_texture,
            source_texture,
            exe,
            batch,
            output,
            level,
            args.proof_mode,
            input_script,
            args.render_scale,
            args.widescreen,
            shots,
            exit_frame,
            args.timeout,
            args.dump_textures,
            args.prims,
        )
        results.append(result)
        print(
            f"{result['status'].upper()} slot {result['slot']:02d} "
            f"{result['costume']:12s} -> {result['dreamcastModel']}",
            flush=True,
        )
    results.sort(key=lambda item: item["slot"])
    passed = sum(result["status"] == valid_status for result in results)
    report = {
        "schemaVersion": 3,
        "batch": str(batch),
        "proofMode": args.proof_mode,
        "level": level,
        "widescreen": args.widescreen,
        "rendererPolicy": "Gl45 modern backend; always-on perspective correction",
        "inputMethod": "process-local SPIDEY_COSTUME and SPIDEY_SCRIPT",
        "inputScript": input_script,
        "environmentPolicy": "retail SM1 level and environment assets remain unchanged",
        "costumeCount": len(results),
        "passedCostumeCount": passed,
        "results": results,
        "status": valid_status if passed == len(slots) else "capture-invalid",
        "visualReview": "pending; every frame must be inspected before a model passes",
        "captureGate": (
            "title.bmr followed by LoadPsx(spidey), native live-3D 16bpp readback, "
            "and four exact main-menu chrome regions"
            if args.proof_mode == "menu"
            else "requested retail level L/O/G assets loaded before every capture, native "
            "live-3D 16bpp readback, non-zero level RunFrame or exact gameplay-HUD "
            "signature, and explicit GAME OVER and SAVE GAME PROGRESS rejection"
        ),
        "processPolicy": "strictly sequential; never more than one SpiderMan process",
    }
    report_path = output / "runtime-validation.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{report['status'].upper()}: {passed}/{len(slots)} selected costume model slots")
    print(f"report: {report_path}")
    if report["status"] != valid_status:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
