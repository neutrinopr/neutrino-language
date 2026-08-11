#!/usr/bin/env python3
"""Generate a deterministic complete domain-pack v2 manifest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "validators"))
import verify_domain_pack as verifier  # noqa: E402


def build(spec: dict, bundle: dict, pack_root: Path) -> dict:
    allowed = {
        "packId",
        "translatorPins",
        "requiredContracts",
        "optionalContracts",
        "payloads",
    }
    unknown = sorted(set(spec) - allowed)
    if unknown:
        raise ValueError(f"pack spec has unknown fields: {unknown}")
    rows = []
    for row in spec["payloads"]:
        path = row.get("path")
        if verifier.normalized_payload_path(path) != path:
            raise ValueError(f"payload path is not normalized: {path!r}")
        source = pack_root / path
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"payload is not a regular file: {path!r}")
        output = dict(row)
        output["sha256"] = verifier.file_sha256(source)
        rows.append(output)
    rows.sort(key=lambda row: row["path"])
    paths = [row["path"] for row in rows]
    if len(paths) != len(set(paths)):
        raise ValueError("payload paths must be unique")
    manifest = {
        "kind": "neutrino.domain-pack",
        "schemaVersion": 2,
        "packId": spec["packId"],
        "targetsBundle": {
            "bundleId": bundle["bundleId"],
            "bundleVersion": bundle["bundleVersion"],
            "bundleDigest": bundle["bundleDigest"],
        },
        "payloads": rows,
    }
    for key in ("translatorPins", "requiredContracts", "optionalContracts"):
        if key in spec:
            manifest[key] = spec[key]
    manifest["packDigest"] = verifier.canonical_pack_digest(manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--pack-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        manifest = build(spec, bundle, args.pack_root.resolve())
        rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"domain-pack generation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
