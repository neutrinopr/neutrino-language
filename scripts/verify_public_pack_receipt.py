#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate and verify content-addressed receipts for bundled public packs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile


KIND = "neutrino.public-pack-receipt/1"


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def members(pack):
    result = []
    for directory, subdirs, names in os.walk(pack):
        subdirs.sort()
        names.sort()
        for name in names:
            path = Path(directory, name)
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ValueError(f"non-regular pack member: {path}")
            data = path.read_bytes()
            result.append({
                "path": path.relative_to(pack).as_posix(),
                "mode": "100755" if info.st_mode & stat.S_IXUSR else "100644",
                "bytes": len(data),
                "sha256": sha256(data),
            })
    return result


def build_receipt(repo, pack_id):
    manifest = json.loads((repo / "docs/m6-curated-example-corpus.json").read_text())
    coordinate = manifest["packs"][pack_id]
    pack = repo / coordinate["packPath"]
    rows = members(pack)
    payload = {
        "kind": KIND,
        "schemaVersion": 1,
        "packId": pack_id,
        "packPath": coordinate["packPath"],
        "declaredPackDigest": coordinate["packDigest"],
        "coreContractBundleDigest": coordinate["bundleDigest"],
        "contentDigest": "sha256:" + sha256(canonical({"members": rows})),
        "members": rows,
    }
    return {**payload, "receiptIdentity": "sha256:" + sha256(canonical(payload))}


def verify(repo, receipt_path):
    receipt = json.loads(receipt_path.read_text())
    if set(receipt) != {
            "kind", "schemaVersion", "packId", "packPath",
            "declaredPackDigest", "coreContractBundleDigest", "contentDigest",
            "members", "receiptIdentity"}:
        raise ValueError("receipt has unknown or omitted fields")
    if receipt["kind"] != KIND or receipt["schemaVersion"] != 1:
        raise ValueError("unsupported receipt contract")
    expected = build_receipt(repo, receipt["packId"])
    if receipt != expected:
        raise ValueError("receipt does not match the current pack closure")
    return expected


def self_test(repo, receipt_path):
    verified = verify(repo, receipt_path)
    with tempfile.TemporaryDirectory() as tmp:
        mutated = json.loads(json.dumps(verified))
        mutated["members"][0]["sha256"] = "0" * 64
        path = Path(tmp) / "receipt.json"
        path.write_text(json.dumps(mutated, indent=2, sort_keys=True) + "\n")
        try:
            verify(repo, path)
        except ValueError:
            pass
        else:
            raise ValueError("member substitution mutation did not bite")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--pack")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    manifest = json.loads((repo / "docs/m6-curated-example-corpus.json").read_text())
    pack_ids = sorted(manifest["packs"]) if args.all else [args.pack]
    if not all(pack_ids):
        parser.error("use --pack ID or --all")
    for pack_id in pack_ids:
        receipt_path = repo / manifest["packs"][pack_id]["receiptPath"]
        if args.generate:
            receipt_path.write_text(
                json.dumps(build_receipt(repo, pack_id), indent=2, sort_keys=True) + "\n")
        verified = verify(repo, receipt_path)
        if args.self_test:
            self_test(repo, receipt_path)
        print(f"{pack_id}: {verified['receiptIdentity']}")


if __name__ == "__main__":
    main()
