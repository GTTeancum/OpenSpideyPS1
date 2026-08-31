#!/usr/bin/env python3
"""Independently decode, reconstruct, render, and audit the full DC actor batch.

The converter and this validator deliberately use different readers.  Conversion
is handled by ``port_dc_character.py``; validation is delegated to Neversoft
Multitool and then checked here by parsing the emitted GLB containers and opening
every decoded/rendered PNG.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BATCH = ROOT / "dreamcast" / "converted" / "all-characters"
DEFAULT_OUTPUT = ROOT / "dreamcast" / "converted" / "all-characters-validation-current"
RENDER_VIEWS = ("front_left", "front_right", "rear_left", "rear_right", "top")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, default=DEFAULT_BATCH)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--multitool",
        type=Path,
        help="NeversoftMultitool executable; defaults to NEVERSOFT_MULTITOOL or PATH",
    )
    parser.add_argument(
        "--skip-tools",
        action="store_true",
        help="audit existing decoded GLBs/PNGs without invoking Neversoft Multitool",
    )
    parser.add_argument("--render-size", type=int, default=512)
    return parser.parse_args()


def find_multitool(explicit: Path | None) -> Path:
    candidates = [
        str(explicit) if explicit else None,
        os.environ.get("NEVERSOFT_MULTITOOL"),
        shutil.which("NeversoftMultitool"),
        shutil.which("NeversoftMultitool.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise FileNotFoundError(
        "NeversoftMultitool was not found; pass --multitool, set "
        "NEVERSOFT_MULTITOOL, or use --skip-tools with existing validation output"
    )


def run_tool(command: list[str], acceptable_returncodes: tuple[int, ...] = (0,)) -> str:
    print("+ " + subprocess.list2cmdline(command))
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode not in acceptable_returncodes:
        raise RuntimeError(
            f"command exited {result.returncode}: {subprocess.list2cmdline(command)}"
        )
    return result.stdout + result.stderr


def load_glb(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 20:
        raise ValueError(f"truncated GLB: {path}")
    magic, version, declared_length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or version != 2 or declared_length != len(data):
        raise ValueError(
            f"invalid GLB header for {path}: magic={magic!r} version={version} "
            f"declared={declared_length} actual={len(data)}"
        )
    chunk_length, chunk_type = struct.unpack_from("<II", data, 12)
    if chunk_type != 0x4E4F534A or 20 + chunk_length > len(data):
        raise ValueError(f"missing GLB JSON chunk: {path}")
    return json.loads(data[20 : 20 + chunk_length].decode("utf-8").rstrip(" \t\r\n\0"))


def triangle_count(document: dict[str, Any], path: Path) -> int:
    accessors = document.get("accessors", [])
    meshes = document.get("meshes", [])
    if not meshes:
        raise ValueError(f"GLB has no meshes: {path}")
    triangles = 0
    primitives = 0
    for mesh in meshes:
        for primitive in mesh.get("primitives", []):
            mode = primitive.get("mode", 4)
            if mode != 4:
                raise ValueError(f"GLB primitive is not TRIANGLES (mode {mode}): {path}")
            accessor_index = primitive.get("indices")
            if accessor_index is None:
                accessor_index = primitive.get("attributes", {}).get("POSITION")
            if accessor_index is None or accessor_index >= len(accessors):
                raise ValueError(f"GLB primitive lacks a valid index/position accessor: {path}")
            count = int(accessors[accessor_index].get("count", 0))
            if count <= 0 or count % 3:
                raise ValueError(f"GLB primitive has invalid triangle element count {count}: {path}")
            triangles += count // 3
            primitives += 1
    if not primitives or not triangles:
        raise ValueError(f"GLB contains no triangles: {path}")
    return triangles


def verify_png(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        size = image.size
        image.verify()
    if size[0] <= 0 or size[1] <= 0:
        raise ValueError(f"PNG has invalid dimensions {size}: {path}")
    return size


def main() -> None:
    args = parse_args()
    batch = args.batch.resolve()
    manifest_path = (args.manifest or batch / "manifest.json").resolve()
    output = args.output.resolve()
    glb_dir = output / "glb"
    texture_dir = output / "textures"
    render_dir = output / "renders"
    output.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("entries", [])
    expected_models = {Path(entry["output"]).stem.lower() for entry in entries}
    if len(expected_models) != manifest.get("actorCount"):
        raise ValueError("manifest actorCount does not match its unique output names")
    expected_psx = expected_models | {"sp_tex00"}

    tool_logs: dict[str, str] = {}
    if not args.skip_tools:
        multitool = find_multitool(args.multitool)
        tool_logs["textures"] = run_tool(
            [
                str(multitool),
                "psx",
                str(batch),
                "-o",
                str(texture_dir),
                "--subdirs",
                "--no-dds",
            ]
        )
        tool_logs["meshes"] = run_tool(
            [str(multitool), "psx-mesh", str(batch), "-o", str(glb_dir), "--format", "glb"],
            # The batch intentionally includes sp_tex00.psx, a texture-only companion.
            # Multitool reports that expected non-mesh input with exit code 1.  The exact
            # GLB name-set check below still catches any actor that failed reconstruction.
            acceptable_returncodes=(0, 1),
        )
        tool_logs["renders"] = run_tool(
            [
                str(multitool),
                "glb-render",
                str(glb_dir),
                "-o",
                str(render_dir),
                "--preset",
                "object-review",
                "--size",
                str(args.render_size),
            ]
        )

    glbs = {path.stem.lower(): path for path in glb_dir.glob("*.glb")}
    if set(glbs) != expected_models:
        raise ValueError(
            f"GLB set mismatch; missing={sorted(expected_models - set(glbs))} "
            f"extra={sorted(set(glbs) - expected_models)}"
        )
    per_model_triangles = {name: triangle_count(load_glb(path), path) for name, path in glbs.items()}

    texture_sets = {path.name.lower(): path for path in texture_dir.iterdir() if path.is_dir()}
    if set(texture_sets) != expected_psx:
        raise ValueError(
            f"decoded texture set mismatch; missing={sorted(expected_psx - set(texture_sets))} "
            f"extra={sorted(set(texture_sets) - expected_psx)}"
        )
    decoded_pngs = sorted(path for directory in texture_sets.values() for path in directory.glob("*.png"))
    if not decoded_pngs:
        raise ValueError("independent texture decoder produced no PNGs")
    for path in decoded_pngs:
        verify_png(path)

    expected_renders = {
        f"{name}_{view}" for name in expected_models for view in RENDER_VIEWS
    }
    renders = {path.stem.lower(): path for path in render_dir.glob("*.png")}
    if set(renders) != expected_renders:
        raise ValueError(
            f"render set mismatch; missing={sorted(expected_renders - set(renders))} "
            f"extra={sorted(set(renders) - expected_renders)}"
        )
    for path in renders.values():
        verify_png(path)

    report = {
        "schemaVersion": 1,
        "manifest": str(manifest_path),
        "batch": str(batch),
        "independentReader": "NeversoftMultitool",
        "actorCount": len(expected_models),
        "glbCount": len(glbs),
        "triangleCount": sum(per_model_triangles.values()),
        "decodedTextureCount": len(decoded_pngs),
        "renderCount": len(renders),
        "viewsPerActor": list(RENDER_VIEWS),
        "perModelTriangles": dict(sorted(per_model_triangles.items())),
        "status": "pass",
    }
    report_path = output / "validation.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"PASS: {report['actorCount']} actors; {report['glbCount']} GLBs; "
        f"{report['triangleCount']:,} triangles; {report['decodedTextureCount']} textures; "
        f"{report['renderCount']} review renders"
    )
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
