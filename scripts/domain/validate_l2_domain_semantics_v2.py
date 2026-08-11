#!/usr/bin/env python3
"""Validate a neutrino.l2-domain-semantics v2 artifact ().

The SETTLED domain-semantics contract, version 2: the machine-emitted
(neutrino-emit --kind=domain-semantics) executable reduction graph over the
generic l2 meta-model. It SUPERSEDES the v1 hand-authored descriptive form (same
kind neutrino.l2-domain-semantics, schemaVersion 2); v1 is retained as the legacy
descriptive artifact (validate_l2_domain_semantics.py, schemaVersion 1) pending
migration; neutrino.domain-dialect stays the vocabulary/source artifact only.

FAIL-CLOSED, standard library only. This is a faithful re-ingest of the artifact,
not a JSON checksum: it enforces (a) the schema shape, (b) the SAME cross-record
contract the C++ DomainOp::verify() enforces — one global identifier namespace,
reduction endpoint resolution, per-concept supported traceability, the
descriptive/executable restriction, accepted provenance for behaviour-driving
edges, provenance subject resolution, and invariant failure-mode references —
and (c) the domainSemanticsHash (recomputed over the canonical form with the
hash removed). A recomputed hash never makes a semantically invalid graph valid.

  validate_l2_domain_semantics_v2.py --artifact FILE     # validate (shape+semantics+hash)
  validate_l2_domain_semantics_v2.py --canonicalize FILE # re-emit canonical bytes (round-trip)
  validate_l2_domain_semantics_v2.py --selftest          # embedded non-vacuity checks
Exit 0 ok / 1 violations / 2 usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys

KIND = "neutrino.l2-domain-semantics"
SCHEMA_VERSION = 2
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

TOP_REQUIRED = ["kind", "schemaVersion", "domain", "version", "implements",
                "l1Features", "concepts", "reductions", "failureModes",
                "invariants", "provenance", "domainSemanticsHash"]
# `imports` is OPTIONAL for schemaVersion-2 back-compatibility: a pre- v2
# artifact (no imports field) stays valid and keeps its original hash preimage
# (an absent imports field is not part of it); absent means [].
TOP_OPTIONAL = ["coverage", "imports"]
ARRAYS = ("l1Features", "concepts", "reductions", "failureModes", "invariants",
          "provenance", "imports")

L1_RELATIONS = ("expands", "discharges", "protects")
EXECUTABLE_RELATIONS = ("expands", "discharges")
SUPPORTED_LOSSINESS = ("lossless", "lossy_preserved")


def _fail(diags, code, msg):
    diags.append(f"[{code}] {msg}")


def _nonempty_str(v):
    return isinstance(v, str) and len(v) > 0


def _check_object(diags, obj, path, required, spec):
    if not isinstance(obj, dict):
        _fail(diags, "l2v2.shape", f"{path} is not an object")
        return
    for f in required:
        if f not in obj:
            _fail(diags, "l2v2.shape", f"{path} is missing required '{f}'")
    for k, v in obj.items():
        if k not in spec:
            _fail(diags, "l2v2.shape", f"{path} has unknown property '{k}'")
            continue
        kind = spec[k]
        if kind == "str":
            if not _nonempty_str(v):
                _fail(diags, "l2v2.shape", f"{path}.{k} must be a non-empty string")
        elif kind == "sha256":
            if not (_nonempty_str(v) and SHA256.match(v)):
                _fail(diags, "l2v2.shape", f"{path}.{k} is not a 64-char lowercase sha256")
        elif kind == "semver":
            if not (_nonempty_str(v) and SEMVER.match(v)):
                _fail(diags, "l2v2.shape", f"{path}.{k} is not a semantic version")
        elif kind.startswith("enum:"):
            allowed = kind[len("enum:"):].split("|")
            if v not in allowed:
                _fail(diags, "l2v2.shape",
                      f"{path}.{k} '{v}' is not one of {'/'.join(allowed)}")


def _check_array(diags, root, field, required, spec):
    arr = root.get(field)
    if not isinstance(arr, list):
        _fail(diags, "l2v2.shape", f"{field} must be an array")
        return
    for i, item in enumerate(arr):
        _check_object(diags, item, f"{field}[{i}]", required, spec)


def validate_shape(obj, diags, *, schema_version=SCHEMA_VERSION, require_intake=False):
    # v2 (default): intakeVersioning is not an allowed top field. v3 (,
    # require_intake=True): schemaVersion 3 and a REQUIRED, shape-checked
    # intakeVersioning object. The cross-record contract below is IDENTICAL — v2
    # and v3 share it, they do not fork.
    required = TOP_REQUIRED + (["intakeVersioning"] if require_intake else [])
    allowed = set(required) | set(TOP_OPTIONAL)
    for f in required:
        if f not in obj:
            _fail(diags, "l2v2.shape", f"missing required '{f}'")
    for k in obj:
        if k not in allowed:
            _fail(diags, "l2v2.shape", f"unknown top-level property '{k}'")
    if obj.get("kind") != KIND:
        _fail(diags, "l2v2.identity", f"kind must be '{KIND}'")
    if obj.get("schemaVersion") != schema_version:
        _fail(diags, "l2v2.identity", f"schemaVersion must be {schema_version}")
    for f in ("domain", "implements"):
        if not _nonempty_str(obj.get(f)):
            _fail(diags, "l2v2.shape", f"{f} must be a non-empty string")
    if not (_nonempty_str(obj.get("version")) and SEMVER.match(obj["version"])):
        _fail(diags, "l2v2.shape", "version is not a semantic version")
    if "coverage" in obj and obj["coverage"] not in ("full", "partial"):
        _fail(diags, "l2v2.shape", "coverage is not one of full/partial")
    if not (_nonempty_str(obj.get("domainSemanticsHash")) and SHA256.match(obj["domainSemanticsHash"])):
        _fail(diags, "l2v2.shape", "domainSemanticsHash is not a 64-char lowercase sha256")
    _check_array(diags, obj, "l1Features", ["name", "kind"],
                 {"name": "str", "kind": "enum:primitive|obligation"})
    _check_array(diags, obj, "concepts", ["name", "kind", "classification"],
                 {"name": "str", "kind": "enum:state|action|concept",
                  "classification": "enum:executable|descriptive"})
    _check_array(diags, obj, "reductions", ["id", "from", "to", "relation", "lossiness"],
                 {"id": "str", "from": "str", "to": "str",
                  "relation": "enum:expands|discharges|protects|failure",
                  "lossiness": "enum:lossless|lossy_preserved|unsupported"})
    _check_array(diags, obj, "failureModes", ["name"],
                 {"name": "str", "compensation": "str"})
    _check_array(diags, obj, "invariants", ["name", "predicate"],
                 {"name": "str", "predicate": "str", "onFailure": "str"})
    _check_array(diags, obj, "provenance", ["subject", "source", "status"],
                 {"subject": "str", "source": "str",
                  "status": "enum:proposed|accepted|rejected",
                  "standardVersion": "str", "excerptHash": "sha256", "reviewer": "str"})
    if "imports" in obj:
        _check_array(diags, obj, "imports", ["capability", "version"],
                     {"capability": "str", "version": "semver"})
    # intakeVersioning (, v3 only): a required object with exactly the two
    # positive-int contract-version axes. Mirrors the C++ validateShape and the v3
    # schema. Absent under v2 (rejected above as an unknown top field).
    if require_intake and "intakeVersioning" in obj:
        iv = obj["intakeVersioning"]
        if not isinstance(iv, dict):
            _fail(diags, "l2v2.shape", "intakeVersioning must be an object")
        else:
            for k in iv:
                if k not in ("semanticProfileVersion", "reductionSemanticsVersion"):
                    _fail(diags, "l2v2.shape", f"intakeVersioning has an unknown property '{k}'")
            for f in ("semanticProfileVersion", "reductionSemanticsVersion"):
                v = iv.get(f)
                if not (isinstance(v, int) and not isinstance(v, bool) and v >= 1):
                    _fail(diags, "l2v2.shape", f"intakeVersioning.{f} must be a positive integer")


def validate_semantics(obj, diags):
    """The SAME cross-record contract the C++ DomainOp::verify() enforces."""
    l1 = {f["name"] for f in obj["l1Features"]}
    concepts = {c["name"]: c for c in obj["concepts"]}
    fmodes = {f["name"] for f in obj["failureModes"]}
    edges = {r["id"] for r in obj["reductions"]}

    # (1) One global identifier namespace across concept / edge / l1_feature /
    #     failure_mode — a reference resolves to exactly one record.
    seen = {}
    for what, items, key in (("concept", obj["concepts"], "name"),
                             ("reduction edge", obj["reductions"], "id"),
                             ("L1 feature", obj["l1Features"], "name"),
                             ("failure mode", obj["failureModes"], "name")):
        for it in items:
            nm = it[key]
            if nm in seen:
                _fail(diags, "l2v2.identity",
                      f"{what} identifier '{nm}' collides with another record")
            seen[nm] = what

    # (2) Endpoint resolution + descriptive/executable restriction + traceability.
    traced = set()
    for r in obj["reductions"]:
        frm, to, rel, loss = r["from"], r["to"], r["relation"], r["lossiness"]
        if frm not in concepts:
            _fail(diags, "l2v2.reference", f"reduction edge from undeclared concept '{frm}'")
        if rel == "failure":
            if to not in fmodes:
                _fail(diags, "l2v2.reference", f"failure edge targets undeclared failure mode '{to}'")
        elif to not in l1:
            _fail(diags, "l2v2.reference", f"reduction edge targets undeclared L1 feature '{to}'")
        if rel in EXECUTABLE_RELATIONS and concepts.get(frm, {}).get("classification") == "descriptive":
            _fail(diags, "l2v2.classification",
                  f"descriptive concept '{frm}' cannot drive an executable {rel} reduction")
        if rel in L1_RELATIONS and loss in SUPPORTED_LOSSINESS and frm in concepts:
            traced.add(frm)
    for cname in concepts:
        if cname not in traced:
            _fail(diags, "l2v2.traceability",
                  f"concept '{cname}' has no supported reduction to a declared L1 feature")

    # (3) Provenance: subjects resolve; every behaviour-driving edge is accepted.
    accepted = {p["subject"] for p in obj["provenance"] if p["status"] == "accepted"}
    for p in obj["provenance"]:
        if p["subject"] not in concepts and p["subject"] not in edges:
            _fail(diags, "l2v2.reference",
                  f"provenance subject '{p['subject']}' resolves to no declared concept or edge")
    for r in obj["reductions"]:
        if r["relation"] in EXECUTABLE_RELATIONS and r["id"] not in accepted:
            _fail(diags, "l2v2.provenance",
                  f"executable reduction edge '{r['id']}' has no accepted provenance")

    # (4) Invariant on_failure resolves.
    for inv in obj["invariants"]:
        of = inv.get("onFailure")
        if of is not None and of not in fmodes:
            _fail(diags, "l2v2.reference",
                  f"invariant on_failure references undeclared failure mode '{of}'")

    # (5) A domain may import a given capability at most once (importing two
    # versions of it is contradictory) — mirrors DomainOp::verify.
    seen_imports = set()
    for imp in obj.get("imports", []):
        cap = imp["capability"]
        if cap in seen_imports:
            _fail(diags, "l2v2.identity",
                  f"duplicate import of capability '{cap}'")
        seen_imports.add(cap)


def _canonical_body(obj):
    """The hash-preimage body: arrays sorted by full canonical form, hash removed."""
    body = {k: v for k, v in obj.items() if k != "domainSemanticsHash"}
    for a in ARRAYS:
        if isinstance(body.get(a), list):
            body[a] = sorted(body[a], key=lambda r: json.dumps(
                r, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    return body


def _hash_of(body):
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def validate(obj, *, schema_version=SCHEMA_VERSION, require_intake=False):
    # Default (schema_version=2, require_intake=False) is the v2 contract,
    # byte-identical to before . The v3 validator calls with (3, True); every
    # other check — cross-record semantics + hash — is shared, not forked.
    diags = []
    if not isinstance(obj, dict):
        return ["[l2v2.shape] artifact root is not an object"]
    validate_shape(obj, diags, schema_version=schema_version, require_intake=require_intake)
    # Run the cross-record contract only once the shape holds, so field accesses
    # are well-typed.
    if not diags:
        validate_semantics(obj, diags)
    if _nonempty_str(obj.get("domainSemanticsHash")) and SHA256.match(obj["domainSemanticsHash"]):
        recomputed = _hash_of(_canonical_body(obj))
        if recomputed != obj["domainSemanticsHash"]:
            _fail(diags, "l2v2.hash",
                  f"domainSemanticsHash {obj['domainSemanticsHash']} != recomputed {recomputed}")
    return diags


def canonicalize(obj):
    """Re-emit the artifact in canonical form — byte-identical to the direct-IR
    emission for a valid, already-canonical artifact (the round-trip proof)."""
    body = _canonical_body(obj)
    out = dict(body)
    out["domainSemanticsHash"] = _hash_of(body)
    return json.dumps(out, indent=2, sort_keys=True) + "\n"


def _selftest():
    base = {
        "kind": KIND, "schemaVersion": SCHEMA_VERSION, "domain": "d", "version": "1.0.0",
        "implements": "c", "coverage": "partial",
        "l1Features": [{"name": "f", "kind": "primitive"}],
        "concepts": [{"name": "x", "kind": "state", "classification": "executable"}],
        "reductions": [{"id": "e", "from": "x", "to": "f", "relation": "expands",
                        "lossiness": "lossless"}],
        "failureModes": [], "invariants": [],
        "provenance": [{"subject": "e", "source": "s", "status": "accepted"}],
        "imports": [{"capability": "coordinate.other", "version": "1.0.0"}],
    }
    base["domainSemanticsHash"] = _hash_of(_canonical_body(base))
    fails = []
    if validate(base):
        fails.append(f"valid artifact rejected: {validate(base)}")
    # canonicalize is idempotent: re-canonicalizing its own output is a no-op.
    once = canonicalize(base)
    if once != canonicalize(json.loads(once)):
        fails.append("canonicalize is not idempotent")

    import copy

    def rehashed(fn):
        d = copy.deepcopy(base)
        fn(d)
        d["domainSemanticsHash"] = _hash_of(_canonical_body(d))  # re-sign
        return d

    # Each semantic mutation must be caught EVEN WITH a valid recomputed hash.
    cases = [
        ("unknown top field", lambda d: d.update({"sneaky": 1})),
        ("bad kind", lambda d: d.update({"kind": "neutrino.l2-domain-semantics-sidecar"})),
        ("bad schemaVersion", lambda d: d.update({"schemaVersion": 1})),
        ("dangling from", lambda d: d["reductions"][0].update({"from": "missing"})),
        ("dangling to", lambda d: d["reductions"][0].update({"to": "missing"})),
        ("descriptive executable", lambda d: d["concepts"][0].update({"classification": "descriptive"})),
        ("missing accepted provenance", lambda d: d.update({"provenance": []})),
        ("dangling provenance subject",
         lambda d: d["provenance"].append({"subject": "ghost", "source": "s", "status": "accepted"})),
        ("duplicate identity",
         lambda d: d["concepts"].append({"name": "e", "kind": "state", "classification": "executable"})),
        ("bad onFailure",
         lambda d: d["invariants"].append({"name": "inv", "predicate": "p", "onFailure": "ghost"})),
        ("untraced concept",
         lambda d: d["reductions"][0].update({"lossiness": "unsupported"})),
        ("import bad version",
         lambda d: d["imports"].append({"capability": "coordinate.z", "version": "v1"})),
        ("import unknown field",
         lambda d: d["imports"][0].update({"sneaky": 1})),
        ("duplicate import",
         lambda d: d["imports"].append({"capability": "coordinate.other", "version": "2.0.0"})),
    ]
    for name, fn in cases:
        if not validate(rehashed(fn)):
            fails.append(f"mutation not caught (even re-hashed): {name}")

    # A stale hash (no re-sign) is caught by the hash check.
    stale = copy.deepcopy(base)
    stale["domainSemanticsHash"] = "0" * 64
    if not any("hash" in d for d in validate(stale)):
        fails.append("stale hash not caught")

    if fails:
        for f in fails:
            print(f"[l2v2.selftest] {f}", file=sys.stderr)
        return 1
    print("ok (selftest)")
    return 0


def _load(path):
    text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    return json.loads(text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", help="validate the sidecar JSON ('-' for stdin)")
    ap.add_argument("--canonicalize", help="re-emit canonical bytes for the sidecar JSON")
    ap.add_argument("--selftest", action="store_true", help="run embedded non-vacuity checks")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    target = args.artifact or args.canonicalize
    if not target:
        ap.error("one of --artifact / --canonicalize / --selftest is required")
    try:
        obj = _load(target)
    except OSError as e:
        print(f"[l2v2.io] cannot read artifact: {e}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"[l2v2.shape] artifact is not valid JSON: {e}", file=sys.stderr)
        return 1
    if args.canonicalize:
        sys.stdout.write(canonicalize(obj))
        return 0
    diags = validate(obj)
    if diags:
        for d in diags:
            print(d, file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
