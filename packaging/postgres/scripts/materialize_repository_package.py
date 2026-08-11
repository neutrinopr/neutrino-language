#!/usr/bin/env python3
"""/: materialize the PostgreSQL backend into a verified package tree.

The PostgreSQL analogue of packaging/solidity/scripts/check_clean_clone.py's
--materialize-package path. It writes the build tree's installed-layout
discovery root so ordinary build-tree consumers traverse the SAME
descriptor/startup/protocol seam an installed package would, rather than a
special in-process path that only exists during development.

Descriptor construction mirrors Solidity's field for field, including the
manifestDigest-over-canonical-form-minus-itself convention, so the two packages
present one discovery contract rather than two dialects.
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENTRY_RELATIVE = "bin/neutrino-postgres-backend"
TARGET_IDENTITY = "postgres"
TARGET_PROFILE_IDENTITY = "target.postgres.v1"


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def package_descriptor(binary: Path, package: Path) -> dict:
    entry = package / ENTRY_RELATIVE
    entry.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binary, entry)
    entry.chmod(0o755)
    profile = json.loads(
        (ROOT / "examples/target-profiles/postgres.target-profile.json").read_text()
    )
    descriptor = {
        "apiVersion": 1,
        "capabilities": ["emit", "stream"],
        "closure": [
            {
                "byteLen": entry.stat().st_size,
                "path": ENTRY_RELATIVE,
                "sha256": digest(entry.read_bytes()),
            }
        ],
        "compatibilityBounds": {
            "coreProtocol": {
                "max": {"major": 1, "minor": 0},
                "min": {"major": 1, "minor": 0},
            },
            "projectionSchema": {"max": 5, "min": 5},
        },
        "entry": ENTRY_RELATIVE,
        "kind": "neutrino.backend-package/1",
        #  is a publication/license gate: the identity is NAMED as pending
        # rather than defaulted to a licence nobody ratified.
        "licenseIdentity": "pending:",
        "profileSummary": profile,
        "protocolMajor": 1,
        "protocolMinor": 0,
        "targetIdentity": TARGET_IDENTITY,
        "targetProfileIdentity": TARGET_PROFILE_IDENTITY,
    }
    # The digest covers the canonical form WITHOUT itself, so a consumer can
    # recompute it; adding it before hashing would be a fixed point.
    descriptor["manifestDigest"] = digest(canonical(descriptor))
    (package / "backend-package.json").write_bytes(canonical(descriptor))
    return descriptor


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materialize-package", action="store_true", required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--package-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    if not args.binary.is_file():
        print(f"[] backend binary not found: {args.binary}", file=sys.stderr)
        return 1
    args.package_dir.mkdir(parents=True, exist_ok=True)
    descriptor = package_descriptor(args.binary, args.package_dir)
    print(
        f"[] materialized {TARGET_IDENTITY} package at {args.package_dir} "
        f"({descriptor['manifestDigest']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
