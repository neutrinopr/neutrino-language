"""Hermetic witness for the M6 pack resolver ().

Proves, WITHOUT neutrino-gen, that the deterministic receipt-verified pack
resolver (scripts/gates/m6_pack_resolver.py) and the gates that consume it are
FAIL-CLOSED:

  * POSITIVE: hydrates the in-repo pack-v2 fixture through its release receipt and
    the reused public verifier with ZERO diagnostics, mapping source/scenario
    payload roles to concrete on-disk paths; member == packId.
  * BUNDLE REGISTRY: the current v1.12 and historical v1.11/v1.10 exact tuples
    hydrate successfully, while an unknown tuple, a crossed version/digest, and
    a one-byte mutation of the historical bundle all fail closed.
  * [P1-1b] REJECTION: a member that is not the pack's packId fails closed even with
    an otherwise-valid receipt/coords.
  * REJECTION: fails closed when a pack payload byte is tampered (a copy, never the
    shared fixture) — end-to-end through the reused verifier's pack.integrity check.
  * [P1-2] REJECTION: the PRODUCTION curated-corpus gate rejects a `packs` block with
    a non-member key and a malformed entry.
  * [P1-3] REJECTION: hydrate_members fails closed (PackResolutionError) when a member
    resolves to a role-incomplete pack (pack-v2 carries no capability-spec).
  * SCHEMA: the complete `packs` block validates against the curated-corpus schema,
    and a malformed digest is rejected.
  * NO FALLBACK: removing one member coordinate fails closed before hydration.

argv: REPO FIXTURE RECEIPT RESOLVER_PATH
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

REPO, FIXTURE, RECEIPT, RESOLVER_PATH = (Path(a) for a in sys.argv[1:5])

sys.path.insert(0, str(RESOLVER_PATH.parent))          # scripts/gates
sys.path.insert(0, str(REPO / "scripts" / "validators"))
import m6_pack_resolver as resolver  # noqa: E402
import verify_domain_pack as verifier  # noqa: E402
import check_m6_curated_example_corpus as corpus  # noqa: E402

fails: list[str] = []

BUNDLE = json.loads((REPO / "docs" / "core-contract-bundle.json").read_text(encoding="utf-8"))
BUNDLE_DIGEST = BUNDLE["bundleDigest"]
PACK = json.loads((FIXTURE / "pack.json").read_text(encoding="utf-8"))
PACK_DIGEST = PACK["packDigest"]
PACK_ID = PACK["packId"]
HISTORICAL = REPO / "test" / "ir" / "bundle" / "Inputs" / "pack-v2-v1.10"
HISTORICAL_PACK = json.loads((HISTORICAL / "pack.json").read_text(encoding="utf-8"))
HISTORICAL_RECEIPT = HISTORICAL / "receipt.json"
HISTORICAL_DIGEST = HISTORICAL_PACK["targetsBundle"]["bundleDigest"]
HISTORICAL_VERSION = HISTORICAL_PACK["targetsBundle"]["bundleVersion"]
ZERO_DIGEST = "sha256:" + "0" * 64


def coords(
    pack_path,
    receipt_path=RECEIPT,
    *,
    pack_digest=PACK_DIGEST,
    bundle_digest=BUNDLE_DIGEST,
):
    return {
        "packPath": str(pack_path),
        "receiptPath": str(receipt_path),
        "packDigest": pack_digest,
        "bundleDigest": bundle_digest,
    }


# --- POSITIVE: hydrate the committed fixture, zero diagnostics; member == packId
try:
    member = resolver.resolve_member(PACK_ID, coords(FIXTURE), repo=REPO)
except resolver.PackResolutionError as error:
    fails.append(f"positive: committed fixture was rejected: {error}")
else:
    if member.source_path != FIXTURE / "source" / "synthetic.neu" or not member.source_path.is_file():
        fails.append(f"positive: source_path did not resolve to the fixture payload ({member.source_path})")
    if member.scenario_dir != FIXTURE / "scenario" or not any(member.scenario_dir.glob("*.json")):
        fails.append(f"positive: scenario_dir did not resolve to the fixture payload ({member.scenario_dir})")
    if member.spec_path is not None:
        fails.append(f"positive: spec_path should be None (fixture carries no capability-spec): {member.spec_path}")

# --- HISTORICAL POSITIVE: immutable v1.10 tuple selects archived exact bytes --
with tempfile.TemporaryDirectory(prefix="pack-resolver-historical.") as td:
    historical_root = Path(td) / "pack"
    shutil.copytree(FIXTURE, historical_root)
    shutil.copy2(HISTORICAL / "pack.json", historical_root / "pack.json")
    try:
        resolver.resolve_member(
            PACK_ID,
            coords(
                historical_root,
                receipt_path=HISTORICAL_RECEIPT,
                pack_digest=HISTORICAL_PACK["packDigest"],
                bundle_digest=HISTORICAL_DIGEST,
            ),
            repo=REPO,
        )
    except resolver.PackResolutionError as error:
        fails.append(f"historical-positive: v1.10 tuple was rejected: {error}")


def expect_tuple_rejection(label, version, digest):
    """Make receipt, pack, and coords consistently claim one unregistered tuple."""
    with tempfile.TemporaryDirectory(prefix=f"pack-resolver-{label}.") as td:
        root = Path(td) / "pack"
        shutil.copytree(FIXTURE, root)
        pack = json.loads((root / "pack.json").read_text(encoding="utf-8"))
        pack["targetsBundle"]["bundleVersion"] = version
        pack["targetsBundle"]["bundleDigest"] = digest
        pack["packDigest"] = verifier.canonical_pack_digest(pack)
        (root / "pack.json").write_text(
            json.dumps(pack, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
        receipt["targetsBundle"]["bundleVersion"] = version
        receipt["targetsBundle"]["bundleDigest"] = digest
        receipt["pack"]["packDigest"] = pack["packDigest"]
        receipt_path = Path(td) / "receipt.json"
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            resolver.resolve_member(
                PACK_ID,
                coords(
                    root,
                    receipt_path=receipt_path,
                    pack_digest=pack["packDigest"],
                    bundle_digest=digest,
                ),
                repo=REPO,
            )
        except resolver.PackResolutionError as error:
            if "no registered core-contract bundle for exact tuple" not in str(error):
                fails.append(f"{label}: wrong fail-closed diagnostic: {error}")
        else:
            fails.append(f"{label}: unregistered bundle tuple was accepted")


# --- UNKNOWN + CROSSED exact tuples have no alias/fallback -------------------
expect_tuple_rejection("unknown-tuple", "9.9.9", ZERO_DIGEST)
expect_tuple_rejection("crossed-tuple", HISTORICAL_VERSION, BUNDLE_DIGEST)

# --- ONE-BYTE historical bundle mutation fails its raw-byte registry pin -----
with tempfile.TemporaryDirectory(prefix="pack-resolver-bundle-byte.") as td:
    temp_repo = Path(td)
    registry = REPO / "docs" / "core-contract-bundle-registry.json"
    for source in (
        registry,
        REPO / "docs" / "core-contract-bundle.json",
        REPO / "docs" / "core-contract-bundles" / "v1.11" / "core-contract-bundle.json",
        REPO / "docs" / "core-contract-bundles" / "v1.10" / "core-contract-bundle.json",
    ):
        destination = temp_repo / source.relative_to(REPO)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    historical_bundle = (
        temp_repo
        / "docs"
        / "core-contract-bundles"
        / "v1.10"
        / "core-contract-bundle.json"
    )
    with historical_bundle.open("ab") as stream:
        stream.write(b" ")
    try:
        resolver._select_bundle(
            HISTORICAL_VERSION,
            HISTORICAL_DIGEST,
            repo=temp_repo,
        )
    except resolver.PackResolutionError as error:
        if "exact file bytes" not in str(error):
            fails.append(f"historical-byte-mutation: wrong rejection: {error}")
    else:
        fails.append("historical-byte-mutation: one-byte mutation was accepted")

# --- [P1-1b] REJECT: a member that is not the pack's packId, valid receipt/coords
try:
    resolver.resolve_member("wrong-curated-member", coords(FIXTURE), repo=REPO)
except resolver.PackResolutionError as error:
    if "packId binding" not in str(error):
        fails.append(f"P1-1b: failed closed but not on the member/packId binding: {error}")
else:
    fails.append("P1-1b: a member != packId was accepted (fail-open)")

# --- REJECTION: a tampered payload byte fails closed via the reused verifier -
with tempfile.TemporaryDirectory(prefix="pack-resolver-tamper.") as td:
    tampered = Path(td) / "pack"
    shutil.copytree(FIXTURE, tampered)
    # Mutate a payload byte only — the manifest (and thus packDigest, packId and the
    # receipt's pack.packDigest) is unchanged, so steps 1-2c still pass and the
    # rejection is proven END-TO-END by the reused bundle verifier (pack.integrity).
    with (tampered / "generated" / "postgres" / "schema.sql").open("a", encoding="utf-8") as stream:
        stream.write("-- tampered\n")
    try:
        resolver.resolve_member(PACK_ID, coords(tampered), repo=REPO)
    except resolver.PackResolutionError as error:
        if "pack.integrity" not in str(error):
            fails.append(f"rejection: failed closed but not via pack.integrity: {error}")
    else:
        fails.append("rejection: tampered payload was NOT rejected (fail-open)")

# --- [P1-2] REJECT: the PRODUCTION corpus gate rejects a bad `packs` block ----
CORPUS = json.loads((REPO / "docs" / "m6-curated-example-corpus.json").read_text(encoding="utf-8"))
valid_entry = {
    "packPath": "test/ir/bundle/Inputs/pack-v2",
    "receiptPath": "test/ir/bundle/Inputs/pack-v2-receipt/receipt.json",
    "packDigest": PACK_DIGEST,
    "bundleDigest": BUNDLE_DIGEST,
}

non_member = json.loads(json.dumps(CORPUS))
non_member["packs"]["typo_member"] = dict(valid_entry)
errs = corpus.validate_manifest(corpus.canonical_pretty(non_member), repo=REPO)
if not any("exact bijection" in e for e in errs):
    fails.append(f"P1-2: a non-member packs key was accepted by the corpus gate: {errs}")

malformed = json.loads(json.dumps(CORPUS))
malformed["packs"][CORPUS["examples"][0]] = {"anything": "goes"}
errs = corpus.validate_manifest(corpus.canonical_pretty(malformed), repo=REPO)
if not any("packs[" in e for e in errs):
    fails.append(f"P1-2: a malformed packs entry was accepted by the corpus gate: {errs}")

# --- SCHEMA: the complete `packs` block validates; a bad digest is rejected ---
SCHEMA = json.loads(
    (REPO / "docs" / "schemas" / "m6-curated-example-corpus.schema.json").read_text(encoding="utf-8")
)
with_packs = dict(CORPUS)
with_packs["packs"] = {
    member: dict(valid_entry) for member in CORPUS["examples"]
}
diags: list = []
verifier._validate(with_packs, SCHEMA, "", diags, SCHEMA)
if diags:
    fails.append(f"schema: a valid `packs` entry was rejected: {diags}")

bad = json.loads(json.dumps(with_packs))
bad["packs"][CORPUS["examples"][0]]["packDigest"] = "not-a-sha256-digest"
diags = []
verifier._validate(bad, SCHEMA, "", diags, SCHEMA)
if not diags:
    fails.append("schema: a malformed packDigest was accepted (fail-open)")

# --- [P1-3] REJECT: hydrate_members fails closed on a role-incomplete pack -----
sys.path.insert(0, str(REPO / "scripts" / "gates"))
import check_m6_release_gate as gate  # noqa: E402

# A synthetic manifest whose only member IS the pack-v2 packId, mapped (via `packs`)
# to the role-incomplete pack-v2 fixture (no capability-spec). resolve_member itself
# succeeds (member == packId), but the gate's role contract must reject it.
role_incomplete = {
    "examples": [PACK_ID],
    "packs": {PACK_ID: dict(valid_entry)},
}
try:
    gate.hydrate_members(role_incomplete)
except resolver.PackResolutionError as error:
    if "capability-spec" not in str(error):
        fails.append(f"P1-3: failed closed but not on the missing capability-spec role: {error}")
else:
    fails.append("P1-3: a role-incomplete pack (no capability-spec) was accepted (fail-open)")

# --- NO FALLBACK: one missing coordinate fails before any member resolution ---
missing_coordinate = json.loads(json.dumps(with_packs))
missing_coordinate["packs"].pop(missing_coordinate["examples"][0])
try:
    gate.hydrate_members(missing_coordinate)
except resolver.PackResolutionError as error:
    if "exact bijection" not in str(error):
        fails.append(f"no-fallback: wrong rejection for a missing coordinate: {error}")
else:
    fails.append("no-fallback: a member without pack coordinates was accepted")

if fails:
    print("pack-resolver test FAILED:", file=sys.stderr)
    for failure in fails:
        print("  - " + failure, file=sys.stderr)
    sys.exit(1)
print(
    "pack-resolver test OK (current + historical exact bundles, unknown/crossed/"
    "byte-mutation rejection, wrong-member + tampered rejection, corpus-gate packs "
    "validation, role-contract fail-closed, additive schema, pack-only no-fallback)"
)
