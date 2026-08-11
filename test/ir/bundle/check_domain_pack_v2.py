"""Exercise the complete external domain-pack v2 contract."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

REPO, FIXTURE, SPEC_PATH, VERIFIER_PATH, GENERATOR_PATH = map(Path, sys.argv[1:6])
sys.path.insert(0, str(VERIFIER_PATH.parent))
sys.path.insert(0, str(GENERATOR_PATH.parent))
import make_domain_pack as generator  # noqa: E402
import verify_domain_pack as verifier  # noqa: E402

BUNDLE_PATH = REPO / "docs/core-contract-bundle.json"
BUNDLE = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
fails = []


def rendered(value):
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def resign(pack):
    pack["packDigest"] = verifier.canonical_pack_digest(pack)


def verify(root):
    diags = []
    verifier.verify(BUNDLE_PATH, REPO, root / "pack.json", root, diags)
    return diags


def expect(root, code, name):
    diags = verify(root)
    if not any(code in diag for diag in diags):
        fails.append(f"{name}: expected {code}, got {diags}")


with tempfile.TemporaryDirectory(prefix="domain-pack-v2.") as td:
    scratch = Path(td)

    generated = generator.build(SPEC, BUNDLE, FIXTURE)
    committed = (FIXTURE / "pack.json").read_text(encoding="utf-8")
    if rendered(generated) != committed:
        fails.append("deterministic generator does not byte-match committed pack.json")
    if rendered(generator.build(SPEC, BUNDLE, FIXTURE)) != rendered(generated):
        fails.append("pack generation is not byte-deterministic")
    if verify(FIXTURE):
        fails.append(f"committed v2 fixture rejected: {verify(FIXTURE)}")

    missing = scratch / "missing"
    shutil.copytree(FIXTURE, missing)
    (missing / "source/synthetic.neu").unlink()
    expect(missing, "[pack.completeness]", "missing payload")

    extra = scratch / "extra"
    shutil.copytree(FIXTURE, extra)
    (extra / "unlisted.txt").write_text("extra\n", encoding="utf-8")
    expect(extra, "[pack.completeness]", "extra payload")

    altered = scratch / "altered"
    shutil.copytree(FIXTURE, altered)
    with (altered / "generated/postgres/schema.sql").open("a", encoding="utf-8") as stream:
        stream.write("-- tampered\n")
    expect(altered, "[pack.integrity]", "altered payload")

    duplicate = scratch / "duplicate"
    shutil.copytree(FIXTURE, duplicate)
    pack = json.loads((duplicate / "pack.json").read_text(encoding="utf-8"))
    row = copy.deepcopy(pack["payloads"][0])
    row["role"] = "duplicate-role"
    pack["payloads"].insert(1, row)
    resign(pack)
    (duplicate / "pack.json").write_text(rendered(pack), encoding="utf-8")
    expect(duplicate, "[pack.completeness]", "duplicate payload path")

    unordered = scratch / "unordered"
    shutil.copytree(FIXTURE, unordered)
    pack = json.loads((unordered / "pack.json").read_text(encoding="utf-8"))
    pack["payloads"].reverse()
    resign(pack)
    (unordered / "pack.json").write_text(rendered(pack), encoding="utf-8")
    expect(unordered, "[pack.completeness]", "unordered payload inventory")

    traversal = scratch / "traversal"
    shutil.copytree(FIXTURE, traversal)
    pack = json.loads((traversal / "pack.json").read_text(encoding="utf-8"))
    pack["payloads"][0]["path"] = "../outside"
    resign(pack)
    (traversal / "pack.json").write_text(rendered(pack), encoding="utf-8")
    expect(traversal, "[pack.path]", "path traversal")

    symlink = scratch / "symlink"
    shutil.copytree(FIXTURE, symlink)
    outside = scratch / "outside.sql"
    outside.write_text("SELECT 1;\n", encoding="utf-8")
    target = symlink / "generated/postgres/schema.sql"
    target.unlink()
    os.symlink(outside, target)
    expect(symlink, "[pack.path]", "symlink escape")

    identity = scratch / "identity"
    shutil.copytree(FIXTURE, identity)
    pack = json.loads((identity / "pack.json").read_text(encoding="utf-8"))
    pack["packId"] = "tampered-without-resigning"
    (identity / "pack.json").write_text(rendered(pack), encoding="utf-8")
    expect(identity, "[pack.integrity]", "pack identity")

    opaque = scratch / "opaque"
    shutil.copytree(FIXTURE, opaque)
    (opaque / "scenario/happy_path.json").write_text("not JSON\n", encoding="utf-8")
    pack = generator.build(SPEC, BUNDLE, opaque)
    (opaque / "pack.json").write_text(rendered(pack), encoding="utf-8")
    if verify(opaque):
        fails.append(f"opaque JSON payload was decoded instead of byte-verified: {verify(opaque)}")

    semantic = scratch / "semantic"
    shutil.copytree(FIXTURE, semantic)
    policy_path = semantic / "artifacts/policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["mode"] = "not-a-valid-mode"
    policy_path.write_text(rendered(policy), encoding="utf-8")
    pack = generator.build(SPEC, BUNDLE, semantic)
    (semantic / "pack.json").write_text(rendered(pack), encoding="utf-8")
    expect(semantic, "[pack.schema]", "contract-backed semantic payload")

    required = scratch / "required"
    shutil.copytree(FIXTURE, required)
    pack = json.loads((required / "pack.json").read_text(encoding="utf-8"))
    pack["payloads"][0].pop("contract")
    resign(pack)
    (required / "pack.json").write_text(rendered(pack), encoding="utf-8")
    expect(required, "[pack.missing_required]", "required contract accounting")

if fails:
    print("domain-pack v2 test FAILED:", file=sys.stderr)
    for failure in fails:
        print("  - " + failure, file=sys.stderr)
    sys.exit(1)
print("domain-pack v2 test OK")
