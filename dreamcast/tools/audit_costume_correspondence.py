"""Audit anatomical/topological correspondence between two costume GLBs.

Run under Blender in background mode.  The report is intended to decide
whether UVs can be transferred deterministically instead of surface-projected.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def import_mesh(path: Path) -> bpy.types.Object:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path.resolve()))
    meshes = [
        obj
        for obj in set(bpy.data.objects) - before
        if obj.type == "MESH" and any(mod.type == "ARMATURE" for mod in obj.modifiers)
    ]
    if len(meshes) != 1:
        raise RuntimeError(f"expected one mesh in {path}, found {len(meshes)}")
    return meshes[0]


def dominant_group(obj: bpy.types.Object, vertex_index: int) -> str:
    memberships = obj.data.vertices[vertex_index].groups
    if not memberships:
        return "unweighted"
    strongest = max(memberships, key=lambda member: member.weight)
    return obj.vertex_groups[strongest.group].name


def summarize(obj: bpy.types.Object) -> dict[str, object]:
    groups: dict[str, dict[str, object]] = {}
    for vertex in obj.data.vertices:
        name = dominant_group(obj, vertex.index)
        record = groups.setdefault(name, {"vertices": [], "polygons": set()})
        record["vertices"].append(vertex.index)
    for polygon in obj.data.polygons:
        names = {dominant_group(obj, index) for index in polygon.vertices}
        for name in names:
            if name in groups:
                groups[name]["polygons"].add(polygon.index)

    output_groups: dict[str, object] = {}
    for name, record in sorted(groups.items()):
        indices = record["vertices"]
        points = [obj.data.vertices[index].co for index in indices]
        minimum = [min(point[axis] for point in points) for axis in range(3)]
        maximum = [max(point[axis] for point in points) for axis in range(3)]
        output_groups[name] = {
            "vertexCount": len(indices),
            "polygonCount": len(record["polygons"]),
            "bounds": {"minimum": minimum, "maximum": maximum},
        }
    return {
        "vertexCount": len(obj.data.vertices),
        "loopCount": len(obj.data.loops),
        "polygonCount": len(obj.data.polygons),
        "materialCount": len(obj.data.materials),
        "groups": output_groups,
    }


def normalized(point: Vector, minimum: Vector, maximum: Vector) -> Vector:
    result = Vector()
    for axis in range(3):
        extent = maximum[axis] - minimum[axis]
        result[axis] = 0.5 if abs(extent) < 1e-8 else (point[axis] - minimum[axis]) / extent
    return result


def correspondence(source: bpy.types.Object, target: bpy.types.Object) -> dict[str, object]:
    result: dict[str, object] = {}
    source_names = {dominant_group(source, v.index) for v in source.data.vertices}
    target_names = {dominant_group(target, v.index) for v in target.data.vertices}
    for name in sorted(source_names & target_names):
        source_vertices = [v for v in source.data.vertices if dominant_group(source, v.index) == name]
        target_vertices = [v for v in target.data.vertices if dominant_group(target, v.index) == name]
        source_min = Vector(tuple(min(v.co[a] for v in source_vertices) for a in range(3)))
        source_max = Vector(tuple(max(v.co[a] for v in source_vertices) for a in range(3)))
        target_min = Vector(tuple(min(v.co[a] for v in target_vertices) for a in range(3)))
        target_max = Vector(tuple(max(v.co[a] for v in target_vertices) for a in range(3)))
        source_points = [normalized(v.co, source_min, source_max) for v in source_vertices]
        target_points = [normalized(v.co, target_min, target_max) for v in target_vertices]
        nearest = []
        for target_point in target_points:
            distance, index = min(
                ((target_point - source_point).length, index)
                for index, source_point in enumerate(source_points)
            )
            nearest.append((distance, index))
        result[name] = {
            "sourceVertices": len(source_vertices),
            "targetVertices": len(target_vertices),
            "uniqueNearestSourceVertices": len({index for _, index in nearest}),
            "meanNormalizedDistance": sum(distance for distance, _ in nearest) / len(nearest),
            "maxNormalizedDistance": max(distance for distance, _ in nearest),
        }
    return result


def main() -> None:
    args = parse_args()
    clear_scene()
    source = import_mesh(args.source)
    target = import_mesh(args.target)
    report = {
        "source": summarize(source),
        "target": summarize(target),
        "correspondence": correspondence(source, target),
    }
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output.resolve()}")


if __name__ == "__main__":
    main()
