#!/usr/bin/env python3
"""Verify authored wing visibility in the SM2 costumes staged for SM1."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import tempfile
from typing import Any

import pack_sm2_costume_to_dc as native_pack


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ACTORS = ROOT / "dreamcast" / "converted" / "all-characters"
DEFAULT_REPORT = (
    ROOT / "dreamcast" / "converted" / "sm1-sm2-costumes" / "wing-policy-audit.json"
)
WING_HASH = 0xDC38D248
MAGENTA_555 = 0x7C1F
COSTUMES = (
    (1, "Spider-Phoenix", "sp2phoenix.psx", "visible"),
    (2, "Prodigy", "sp2prodigy.psx", "transparent"),
    (3, "Dusk", "sp2dusk.psx", "visible"),
    (4, "Insulated", "sp2insulated.psx", "visible"),
    (5, "Alex Ross Red", "sp2rossred.psx", "visible"),
    (6, "Alex Ross White", "sp2rosswhite.psx", "visible"),
    (7, "Venom Earth-X", "sp2venomx.psx", "transparent"),
    (8, "Negative Zone", "sp2negative.psx", "visible"),
    (18, "Battle-Damaged", "sp2battle.psx", "visible"),
    (0, "Spider-Man (Web Wings)", "sp2default.psx", "visible"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actors", type=Path, default=DEFAULT_ACTORS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--multitool", type=Path)
    return parser.parse_args()


def edge(
    a: tuple[float, float], b: tuple[float, float], point: tuple[float, float]
) -> float:
    return (point[0] - a[0]) * (b[1] - a[1]) - (point[1] - a[1]) * (
        b[0] - a[0]
    )


def triangle_texels(
    coordinates: list[tuple[int, int]], width: int, height: int
) -> set[tuple[int, int]]:
    a, b, c = coordinates
    winding = edge(a, b, c)
    if winding == 0:
        return {(u % width, v % height) for u, v in coordinates}
    result: set[tuple[int, int]] = set()
    minimum_u = min(point[0] for point in coordinates)
    maximum_u = max(point[0] for point in coordinates)
    minimum_v = min(point[1] for point in coordinates)
    maximum_v = max(point[1] for point in coordinates)
    for v in range(minimum_v, maximum_v + 1):
        for u in range(minimum_u, maximum_u + 1):
            point = (u + 0.5, v + 0.5)
            weights = (edge(a, b, point), edge(b, c, point), edge(c, a, point))
            if all(value >= 0 for value in weights) or all(
                value <= 0 for value in weights
            ):
                result.add((u % width, v % height))
    result.update((u % width, v % height) for u, v in coordinates)
    return result


def summarize_actor(
    actor: Path, expected: str, multitool: Path, temporary: Path
) -> dict[str, Any]:
    converter = native_pack.load_converter()
    texture = converter.load_ps1_texture_asset(actor, WING_HASH)
    dump = native_pack.dump_mesh(multitool, actor, temporary / f"{actor.stem}.json")
    faces = [
        face
        for mesh in dump["Meshes"]
        for face in mesh["Faces"]
        if face["TextureHash"] == WING_HASH
    ]
    sampled: set[tuple[int, int]] = set()
    for face in faces:
        for slots in native_pack.emitted_slot_orders(face):
            sampled.update(
                triangle_texels(
                    [
                        (
                            int(face["TextureCoordinates"][slot]["U"]),
                            int(face["TextureCoordinates"][slot]["V"]),
                        )
                        for slot in slots
                    ],
                    texture.width,
                    texture.height,
                )
            )
    colors = Counter(
        texture.palette[texture.payload[v * texture.width + u]] for u, v in sampled
    )
    opaque = sum(count for color, count in colors.items() if color != MAGENTA_555)
    actual = "visible" if opaque else "transparent"
    return {
        "actor": str(actor.resolve()),
        "expected": expected,
        "actual": actual,
        "matches": actual == expected,
        "wingMaterial": f"0x{WING_HASH:08X}",
        "wingFaceCount": len(faces),
        "textureSize": [texture.width, texture.height],
        "sampledTexelCount": len(sampled),
        "opaqueSampledTexels": opaque,
        "magentaSampledTexels": colors[MAGENTA_555],
    }


def main() -> None:
    args = parse_args()
    actors = args.actors.resolve()
    multitool = native_pack.resolve_multitool(args.multitool)
    results = []
    with tempfile.TemporaryDirectory(prefix="sm1-wing-policy-audit-") as scratch:
        temporary = Path(scratch)
        for slot, name, filename, expected in COSTUMES:
            result = summarize_actor(actors / filename, expected, multitool, temporary)
            result.update({"slot": slot, "name": name})
            results.append(result)
    checks = {
        "allCostumesPresent": len(results) == len(COSTUMES),
        "allActorsUseElevenWingFaces": all(
            item["wingFaceCount"] == 11 for item in results
        ),
        "allAuthoredStatesMatch": all(item["matches"] for item in results),
        "eightVisible": sum(item["actual"] == "visible" for item in results) == 8,
        "twoTransparent": sum(item["actual"] == "transparent" for item in results)
        == 2,
    }
    report = {
        "schemaVersion": 1,
        "scope": "staged SM1 runtime actors; embedded authored SM2 wing pixels",
        "checks": checks,
        "costumes": results,
        "status": "pass" if all(checks.values()) else "fail",
    }
    rendered = json.dumps(report, indent=2) + "\n"
    report_path = args.report.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not all(checks.values()):
        raise SystemExit("FAIL: staged authored wing policy does not match")
    print("PASS: eight winged suits and two authored wingless suits")
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
