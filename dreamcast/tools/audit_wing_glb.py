"""Audit wing topology, UVs, texture pixels, and material semantics in GLBs."""

from __future__ import annotations

import argparse
from collections import Counter
from io import BytesIO
import json
from pathlib import Path
import struct
from typing import Any

from PIL import Image


WING_MATERIAL_PREFIX = "tex_dc38d248"
COMPONENT_FORMATS = {
    5120: "b",
    5121: "B",
    5122: "h",
    5123: "H",
    5125: "I",
    5126: "f",
}
TYPE_WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="SM2 donor/costume GLB")
    parser.add_argument("--output", required=True, help="converted static proof GLB")
    parser.add_argument("--report")
    return parser.parse_args()


def load_glb(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    if data[:4] != b"glTF":
        raise RuntimeError(f"not a binary glTF: {path}")
    document: dict[str, Any] | None = None
    binary = b""
    cursor = 12
    while cursor < len(data):
        length, chunk_type = struct.unpack_from("<II", data, cursor)
        cursor += 8
        payload = data[cursor : cursor + length]
        cursor += length
        if chunk_type == 0x4E4F534A:
            document = json.loads(payload.decode("utf-8"))
        elif chunk_type == 0x004E4942:
            binary = payload
    if document is None:
        raise RuntimeError(f"GLB has no JSON chunk: {path}")
    return document, binary


def accessor_values(document: dict[str, Any], binary: bytes, index: int) -> list[tuple[Any, ...]]:
    accessor = document["accessors"][index]
    view = document["bufferViews"][accessor["bufferView"]]
    component_type = accessor["componentType"]
    component_format = COMPONENT_FORMATS[component_type]
    width = TYPE_WIDTHS[accessor["type"]]
    packed_size = struct.calcsize("<" + component_format * width)
    stride = view.get("byteStride", packed_size)
    offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    return [
        struct.unpack_from("<" + component_format * width, binary, offset + row * stride)
        for row in range(accessor["count"])
    ]


def wing_primitive(document: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, Any]]:
    material_index = next(
        (
            index
            for index, material in enumerate(document.get("materials", []))
            if material.get("name", "").casefold().startswith(WING_MATERIAL_PREFIX)
        ),
        None,
    )
    if material_index is None:
        raise RuntimeError("GLB lacks the DC38D248 wing material")
    primitives = [
        primitive
        for mesh in document.get("meshes", [])
        for primitive in mesh.get("primitives", [])
        if primitive.get("material") == material_index
    ]
    if len(primitives) != 1:
        raise RuntimeError(f"expected one wing primitive, found {len(primitives)}")
    return material_index, document["materials"][material_index], primitives[0]


def uv_topology(document: dict[str, Any], binary: bytes, primitive: dict[str, Any]) -> dict[str, Any]:
    uvs = accessor_values(document, binary, primitive["attributes"]["TEXCOORD_0"])
    raw_indices = accessor_values(document, binary, primitive["indices"])
    indices = [int(value[0]) for value in raw_indices]
    triangles = []
    for offset in range(0, len(indices), 3):
        triangle = tuple(
            (round(float(uvs[index][0]), 7), round(float(uvs[index][1]), 7))
            for index in indices[offset : offset + 3]
        )
        triangles.append(triangle)
    canonical = [tuple(sorted(triangle)) for triangle in triangles]
    return {
        "vertexCount": len(uvs),
        "triangleCount": len(triangles),
        "uniqueUvCoordinates": sorted({uv for triangle in triangles for uv in triangle}),
        "uniqueUvTriangles": sorted(set(canonical)),
        "uvTriangleMultiplicity": {
            repr(triangle): count for triangle, count in sorted(Counter(canonical).items())
        },
    }


def material_pixels(
    document: dict[str, Any], binary: bytes, material: dict[str, Any]
) -> tuple[tuple[int, int], list[tuple[int, int, int, int]]]:
    texture_info = material.get("pbrMetallicRoughness", {}).get("baseColorTexture")
    if texture_info is None:
        raise RuntimeError("wing material has no base-color texture")
    texture = document["textures"][texture_info["index"]]
    image = document["images"][texture["source"]]
    view = document["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    payload = binary[start : start + view["byteLength"]]
    with Image.open(BytesIO(payload)) as decoded:
        rgba = decoded.convert("RGBA")
        pixels = (
            list(rgba.get_flattened_data())
            if hasattr(rgba, "get_flattened_data")
            else list(rgba.getdata())
        )
        return rgba.size, pixels


def summarize(path: Path) -> tuple[dict[str, Any], list[tuple[int, int, int, int]]]:
    document, binary = load_glb(path)
    _, material, primitive = wing_primitive(document)
    size, pixels = material_pixels(document, binary, material)
    alpha_histogram = Counter(pixel[3] for pixel in pixels)
    return (
        {
            "path": str(path.resolve()),
            "material": material.get("name"),
            "doubleSided": bool(material.get("doubleSided", False)),
            "alphaMode": material.get("alphaMode", "OPAQUE"),
            "alphaCutoff": material.get("alphaCutoff"),
            "textureSize": list(size),
            "alphaHistogram": {str(alpha): count for alpha, count in sorted(alpha_histogram.items())},
            **uv_topology(document, binary, primitive),
        },
        pixels,
    )


def main() -> None:
    args = parse_args()
    source_summary, source_pixels = summarize(Path(args.source))
    output_summary, output_pixels = summarize(Path(args.output))
    checks = {
        "uvCoordinatesExact": source_summary["uniqueUvCoordinates"]
        == output_summary["uniqueUvCoordinates"],
        "uvTrianglesExact": source_summary["uniqueUvTriangles"]
        == output_summary["uniqueUvTriangles"],
        "textureDimensionsExact": source_summary["textureSize"] == output_summary["textureSize"],
        "texturePixelsExact": source_pixels == output_pixels,
        "fourUniqueOutputTriangles": output_summary["triangleCount"] == 4,
        "outputDoubleSided": output_summary["doubleSided"],
    }
    report = {"source": source_summary, "output": output_summary, "checks": checks}
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered + "\n", encoding="utf-8")
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise SystemExit(f"wing audit failed: {', '.join(failed)}")


if __name__ == "__main__":
    main()
