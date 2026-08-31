#!/usr/bin/env python3
"""Validate the selected SM2 costume ports and their authored visual proofs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / "dreamcast" / "converted" / "sm2-costume-tests"
RENDER_VIEWS = ("front_left", "front_right", "rear_left", "rear_right", "top")
CLOSEUP_VIEWS = (
    "front",
    "rear",
    "front_underside",
    "rear_underside",
    "left_oblique",
    "right_oblique",
)
COSTUMES = {
    "default": {
        "glb": "DEFAULT_DC_WINGED_TPOSE.glb",
        "source": "sp_tex00.glb",
        "textureSize": [64, 64],
        "alphaMode": "MASK",
        "alphaHistogram": {"0": 526, "255": 3570},
    },
    "dusk": {
        "glb": "DUSK_DC_WINGED_TPOSE.glb",
        "source": "sp_tex03.glb",
        "textureSize": [32, 32],
        "alphaMode": "OPAQUE",
        "alphaHistogram": {"255": 1024},
    },
    "prodigy": {
        "glb": "PRODIGY_DC_WINGED_TPOSE.glb",
        "source": "sp_tex02.glb",
        "textureSize": [64, 64],
        "alphaMode": "MASK",
        "alphaHistogram": {"0": 4096},
    },
    "ricochet": {
        "glb": "RICOCHET_DC_WINGED_TPOSE.glb",
        "source": "sp_tex08.glb",
        "textureSize": [64, 64],
        "alphaMode": "MASK",
        "alphaHistogram": {"0": 526, "255": 3570},
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_glb(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError(f"not a GLB: {path}")
    version, declared_length = struct.unpack_from("<II", data, 4)
    if version != 2 or declared_length != len(data):
        raise ValueError(
            f"invalid GLB header for {path}: version={version}, "
            f"declared={declared_length}, actual={len(data)}"
        )
    return {"path": str(path.resolve()), "bytes": len(data), "sha256": sha256(path)}


def validate_png(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        image.load()
        if image.format != "PNG":
            raise ValueError(f"not a PNG: {path}")
        width, height = image.size
        mode = image.mode
    return {
        "path": str(path.resolve()),
        "width": width,
        "height": height,
        "mode": mode,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def validate_costume(root: Path, name: str, expected: dict[str, Any]) -> dict[str, Any]:
    costume_root = root / "ports" / name
    audit_path = costume_root / "wing-audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    failed_audit_checks = sorted(key for key, passed in audit["checks"].items() if not passed)
    source_name = Path(audit["source"]["path"]).name
    semantic_checks = {
        "sourceFileExact": source_name.casefold() == expected["source"].casefold(),
        "textureSizeExact": audit["output"]["textureSize"] == expected["textureSize"],
        "alphaModeExact": audit["output"]["alphaMode"] == expected["alphaMode"],
        "alphaHistogramExact": audit["output"]["alphaHistogram"] == expected["alphaHistogram"],
    }

    glb_path = costume_root / expected["glb"]
    glb = validate_glb(glb_path)
    renders = {
        view: validate_png(costume_root / "renders" / f"{glb_path.stem}_{view}.png")
        for view in RENDER_VIEWS
    }
    closeups = {
        view: validate_png(costume_root / "wing-closeups" / f"{name}_{view}.png")
        for view in CLOSEUP_VIEWS
    }
    closeup_dimensions = sorted(
        {(item["width"], item["height"]) for item in closeups.values()}
    )
    proof_checks = {
        "fiveTposeViews": len(renders) == len(RENDER_VIEWS),
        "sixWingCloseups": len(closeups) == len(CLOSEUP_VIEWS),
        "validTposeDimensions": all(
            item["width"] > 0 and item["height"] > 0 for item in renders.values()
        ),
        "consistentCloseupDimensions": len(closeup_dimensions) == 1,
        "closeupsAtLeastHd": all(
            item["width"] >= 1600 and item["height"] >= 1000 for item in closeups.values()
        ),
    }
    checks = {
        "wingAuditPassed": not failed_audit_checks,
        **semantic_checks,
        **proof_checks,
    }
    return {
        "name": name,
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "failedWingAuditChecks": failed_audit_checks,
        "wing": audit["output"],
        "glb": glb,
        "renders": renders,
        "wingCloseups": closeups,
    }


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    entries = [validate_costume(root, name, expected) for name, expected in COSTUMES.items()]
    report = {
        "schemaVersion": 1,
        "root": str(root),
        "costumeCount": len(entries),
        "passedCostumeCount": sum(entry["status"] == "pass" for entry in entries),
        "tposeViewCount": sum(len(entry["renders"]) for entry in entries),
        "wingCloseupCount": sum(len(entry["wingCloseups"]) for entry in entries),
        "entries": entries,
    }
    report_path = (args.report or root / "validation.json").resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    failed = [entry["name"] for entry in entries if entry["status"] != "pass"]
    if failed:
        raise SystemExit(f"FAIL: costume validation failed for {', '.join(failed)}")
    print(
        f"PASS: {len(entries)} costumes; {report['tposeViewCount']} T-pose views; "
        f"{report['wingCloseupCount']} close wing views; exact source UV/texture parity"
    )
    print(f"report: {report_path}")


if __name__ == "__main__":
    main()
