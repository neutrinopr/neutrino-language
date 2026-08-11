#!/usr/bin/env python3
"""Validate a neutrino.l2-domain-semantics v3 artifact ().

v3 is the M7-intake domain-semantics contract: IDENTICAL to v2's executable
reduction graph and cross-record contract, plus a REQUIRED `intakeVersioning`
object binding the artifact to the capability-vocabulary (semanticProfileVersion)
and reduction-semantics (reductionSemanticsVersion) contract versions it was
produced under. v2 is retained UNCHANGED as the legacy compatibility baseline
(a distinct /v2 contract id); this validator SHARES all logic with the v2
validator — it only flips the envelope (schemaVersion 3 + required intakeVersioning).

  validate_l2_domain_semantics_v3.py --artifact FILE     # validate (shape+semantics+hash)
  validate_l2_domain_semantics_v3.py --canonicalize FILE # re-emit canonical bytes (round-trip)
  validate_l2_domain_semantics_v3.py --selftest          # embedded non-vacuity checks
Exit 0 ok / 1 violations / 2 usage.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_l2_domain_semantics_v2 as base  # noqa: E402

KIND = base.KIND
SCHEMA_VERSION = 3


def validate(obj):
    """The v3 contract = v2's shared shape/semantics/hash with schemaVersion 3 and
    a required intakeVersioning object."""
    return base.validate(obj, schema_version=SCHEMA_VERSION, require_intake=True)


def canonicalize(obj):
    """Same canonical-bytes discipline as v2 (sorted keys, records sorted by full
    canonical form, hash over the compact body with the hash removed)."""
    return base.canonicalize(obj)


def _selftest():
    b = {
        "kind": KIND, "schemaVersion": 3, "domain": "d", "version": "1.0.0",
        "implements": "c", "coverage": "partial",
        "l1Features": [{"name": "f", "kind": "primitive"}],
        "concepts": [{"name": "x", "kind": "state", "classification": "executable"}],
        "reductions": [{"id": "e", "from": "x", "to": "f", "relation": "expands",
                        "lossiness": "lossless"}],
        "failureModes": [], "invariants": [],
        "provenance": [{"subject": "e", "source": "s", "status": "accepted"}],
        "intakeVersioning": {"semanticProfileVersion": 3, "reductionSemanticsVersion": 1},
    }
    b["domainSemanticsHash"] = base._hash_of(base._canonical_body(b))
    fails = []
    if validate(b):
        fails.append(f"valid v3 artifact rejected: {validate(b)}")
    # A v2-shaped artifact (schemaVersion 2, no intakeVersioning) is NOT a v3.
    v2shape = copy.deepcopy(b)
    v2shape.pop("intakeVersioning")
    v2shape["schemaVersion"] = 2
    v2shape["domainSemanticsHash"] = base._hash_of(base._canonical_body(v2shape))
    if not validate(v2shape):
        fails.append("v3 validator accepted a v2-shaped artifact (missing intakeVersioning)")

    def rehashed(fn):
        d = copy.deepcopy(b)
        fn(d)
        d["domainSemanticsHash"] = base._hash_of(base._canonical_body(d))
        return d

    for name, fn in [
        ("missing intakeVersioning", lambda d: d.pop("intakeVersioning")),
        ("intake unknown field", lambda d: d["intakeVersioning"].update({"x": 1})),
        ("intake non-int", lambda d: d["intakeVersioning"].update({"semanticProfileVersion": "3"})),
        ("wrong schemaVersion", lambda d: d.update({"schemaVersion": 2})),
        # the shared cross-record contract still bites under v3:
        ("descriptive executable", lambda d: d["concepts"][0].update({"classification": "descriptive"})),
        ("missing accepted provenance", lambda d: d.update({"provenance": []})),
    ]:
        if not validate(rehashed(fn)):
            fails.append(f"v3 mutation not caught (even re-hashed): {name}")

    # intakeVersioning is covered by the hash: mutating it without re-signing bites.
    stale = copy.deepcopy(b)
    stale["intakeVersioning"]["reductionSemanticsVersion"] = 9
    if not any("hash" in d for d in validate(stale)):
        fails.append("intakeVersioning is not covered by domainSemanticsHash")

    if fails:
        for f in fails:
            print(f"[l2v3.selftest] {f}", file=sys.stderr)
        return 1
    print("ok (selftest)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--artifact")
    g.add_argument("--canonicalize")
    g.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    path = args.artifact or args.canonicalize
    text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    obj = json.loads(text)
    if args.canonicalize:
        sys.stdout.write(canonicalize(obj))
        return 0
    diags = validate(obj)
    for d in diags:
        print(d, file=sys.stderr)
    return 1 if diags else 0


if __name__ == "__main__":
    sys.exit(main())
