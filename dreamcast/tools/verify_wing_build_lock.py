#!/usr/bin/env python3
"""Verify exact private inputs and generated winged-Spidey outputs against a safe lockfile."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = ROOT / "dreamcast" / "manifests" / "winged-spidey-lock.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument(
        "--inputs-only",
        action="store_true",
        help="check the private extracted inputs without requiring generated outputs",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_entries(kind: str, entries: list[dict[str, Any]]) -> int:
    checked = 0
    failures: list[str] = []
    for entry in entries:
        relative = Path(entry["path"])
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"missing {kind}: {relative.as_posix()}")
            continue
        actual_size = path.stat().st_size
        if actual_size != entry["bytes"]:
            failures.append(
                f"size mismatch {relative.as_posix()}: {actual_size} != {entry['bytes']}"
            )
            continue
        actual_hash = sha256(path)
        if actual_hash.casefold() != entry["sha256"].casefold():
            failures.append(
                f"sha256 mismatch {relative.as_posix()}: {actual_hash} != {entry['sha256']}"
            )
            continue
        checked += 1
    if failures:
        raise RuntimeError("\n".join(failures))
    return checked


def main() -> None:
    args = parse_args()
    lock_path = args.lock.resolve()
    document = json.loads(lock_path.read_text(encoding="utf-8"))
    if document.get("schemaVersion") != 1:
        raise ValueError(f"unsupported wing lock schema in {lock_path}")
    input_count = verify_entries("input", document["inputs"])
    output_count = 0
    if not args.inputs_only:
        output_count = verify_entries("output", document["outputs"])
    detail = "inputs only" if args.inputs_only else f"{output_count} generated outputs"
    print(
        f"PASS: wing build lock matches {input_count} private inputs and {detail}; "
        f"lock: {lock_path}"
    )


if __name__ == "__main__":
    main()
