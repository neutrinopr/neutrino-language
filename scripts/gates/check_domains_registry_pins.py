#!/usr/bin/env python3
"""Enforce the in-tree domains/ pack pins against the externalized-domain registry.

When curated packs were hydrated from the private neutrino-domains repository,
content identity was enforced for free by the pinned checkout ref. With the
packs subtree'd into the release tree, `domains/` is an ordinary mutable
directory — this gate restores the pin as an enforced property ( review):

  for every registry row in docs/externalized-domain-registry.json:
    - the pack manifest exists at domains/<packPath>/pack.json;
    - its self-digest (canonical JSON minus packDigest) matches the manifest,
      the registry row, and the pack receipt;
    - every payload file's sha256 matches the manifest inventory;
    - the tree identity (canonical JSON of the ordered {path, sha256}
      inventory) matches the registry row and the receipt;
  and the set of pack directories on disk equals the set of registered packs,
  so an unregistered pack cannot ride in silently.

Fails closed: a missing file, unreadable JSON, or shape surprise is an error,
never a skip. Exit 0 with a per-pack OK summary, exit 1 listing every failure.
"""

import hashlib
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY = os.path.join(REPO, "docs", "externalized-domain-registry.json")
DOMAINS = os.path.join(REPO, "domains")


def canonical_digest(obj):
    return "sha256:" + hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        .encode("utf-8")
    ).hexdigest()


def file_digest(path):
    with open(path, "rb") as stream:
        return "sha256:" + hashlib.sha256(stream.read()).hexdigest()


def load_json(path, errors, what):
    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError) as exc:
        errors.append(f"[{what}] unreadable: {path}: {exc}")
        return None


def check_pack(row, errors):
    pack_id = row.get("id", "<missing-id>")

    def err(msg):
        errors.append(f"[{pack_id}] {msg}")

    pack_path = row.get("packPath")
    receipt_path = row.get("receiptPath")
    if not isinstance(pack_path, str) or not isinstance(receipt_path, str):
        err("registry row lacks packPath/receiptPath strings")
        return
    manifest_file = os.path.join(DOMAINS, pack_path, "pack.json")
    manifest = load_json(manifest_file, errors, pack_id)
    receipt = load_json(os.path.join(DOMAINS, receipt_path), errors, pack_id)
    if manifest is None or receipt is None:
        return

    unsigned = {k: v for k, v in manifest.items() if k != "packDigest"}
    computed_pack_digest = canonical_digest(unsigned)
    for name, recorded in (
        ("manifest", manifest.get("packDigest")),
        ("registry", row.get("packDigest")),
        ("receipt", (receipt.get("pack") or {}).get("packDigest")),
    ):
        if recorded != computed_pack_digest:
            err(f"packDigest in {name} is {recorded}, "
                f"recomputed {computed_pack_digest}")

    payloads = manifest.get("payloads")
    if not isinstance(payloads, list) or not payloads:
        err("manifest payloads missing or empty")
        return
    identities = []
    for payload in payloads:
        rel = payload.get("path") if isinstance(payload, dict) else None
        recorded = payload.get("sha256") if isinstance(payload, dict) else None
        if not isinstance(rel, str) or not isinstance(recorded, str):
            err(f"malformed payload row: {payload!r}")
            continue
        target = os.path.join(DOMAINS, pack_path, rel)
        if not os.path.isfile(target):
            err(f"payload file missing: {pack_path}/{rel}")
            continue
        actual = file_digest(target)
        if actual != recorded:
            err(f"payload {rel} is {actual}, manifest records {recorded}")
        identities.append({"path": rel, "sha256": recorded})

    computed_tree = canonical_digest(identities)
    for name, recorded in (
        ("registry", row.get("treeIdentity")),
        ("receipt", (receipt.get("pack") or {}).get("treeIdentity")),
    ):
        if recorded != computed_tree:
            err(f"treeIdentity in {name} is {recorded}, recomputed {computed_tree}")


def main():
    errors = []
    registry = load_json(REGISTRY, errors, "registry")
    if registry is None:
        print("domains-registry-pins FAILED:\n  - " + "\n  - ".join(errors),
              file=sys.stderr)
        return 1
    rows = registry.get("domains")
    if not isinstance(rows, list) or not rows:
        errors.append("[registry] domains list missing or empty")
        rows = []
    if isinstance(rows, list) and registry.get("registeredCount") != len(rows):
        errors.append(
            f"[registry] registeredCount {registry.get('registeredCount')} != "
            f"row count {len(rows)}")

    registered_dirs = set()
    for row in rows:
        if isinstance(row, dict):
            check_pack(row, errors)
            pack_path = row.get("packPath")
            if isinstance(pack_path, str) and pack_path.startswith("packs/"):
                registered_dirs.add(pack_path.split("/")[1])
        else:
            errors.append(f"[registry] non-object row: {row!r}")

    packs_root = os.path.join(DOMAINS, "packs")
    try:
        on_disk = {entry for entry in os.listdir(packs_root)
                   if os.path.isdir(os.path.join(packs_root, entry))}
    except OSError as exc:
        errors.append(f"[tree] cannot list {packs_root}: {exc}")
        on_disk = registered_dirs
    for extra in sorted(on_disk - registered_dirs):
        errors.append(f"[tree] unregistered pack directory: packs/{extra}")
    for missing in sorted(registered_dirs - on_disk):
        errors.append(f"[tree] registered pack has no directory: packs/{missing}")

    if errors:
        print("domains-registry-pins FAILED:", file=sys.stderr)
        for line in errors:
            print("  - " + line, file=sys.stderr)
        return 1
    print(f"domains-registry-pins OK ({len(rows)} packs: manifests self-digested, "
          "payload bytes match inventories, tree identities match registry and "
          "receipts, disk pack set equals registered set)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
