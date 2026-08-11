#!/usr/bin/env python3
"""Validate a Neutrino agreement-identity artifact ().

The artifact (docs/schemas/agreement-identity.schema.json) is the portable
semantic-agreement identity: the domain-separated agreementHash over the
capability-spec's canonical semantic bytes + a versioned agreement envelope. This
validator is BOTH the producer-side shape gate AND the reference consumer check.
CI/admission run THIS validator (not a JSON-Schema library), so it must FULLY
mirror the schema — a partial mirror would admit a malformed identity contract
(recurring lesson).

  1. SHAPE — well-formed: required fields + no unknown fields at every object
     level + the type/const/pattern of every field, so a truncated / typoed /
     unknown-version artifact fails closed.
  2. INTEGRITY (--verify-hashes CAPABILITY_SPEC) — recompute, from the paired
     capability-spec, the canonical semantic bytes (verifying that spec's own
     capabilityHash) and the envelope bytes, then the length-framed
     domain-separated preimage, and check that capabilityHash + agreementHash
     match. A tampered spec, a moved field boundary, or a forged digest fails
     closed. The recompute is standalone (matches the C++ core byte-for-byte).

Standard library only. Exit 0 ok / 1 invalid (fail closed) / 2 usage.

  validate_agreement_identity.py --artifact A [--verify-hashes CAPABILITY_SPEC]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys

# Mirrors the schema $defs + VersionInfo.h constants (single source of the wire
# contract for THIS validator). A drift check ties these to the schema.
HEX64 = r"^[0-9a-f]{64}$"
SEMVER = r"^[0-9]+\.[0-9]+\.[0-9]+$"
DOMAIN = "neutrino.agreement.v1"
KIND = "neutrino.agreement-identity"
ENVELOPE_VERSION = 1
# The semantic-language version(s) this release can interpret (mirrors
# VersionInfo.h kSemanticLanguageVersion + the schema enum). A PORTABLE identity
# authored at an unknown version must fail closed here — a consumer must never
# accept an identity whose semantic-language version it cannot interpret.
KNOWN_LANGUAGE_VERSIONS = {"0.1.0"}
TOP_FIELDS = {"kind", "domain", "semanticLanguageVersion", "capabilityHash",
              "envelope", "identity"}
ENVELOPE_FIELDS = {"schemaVersion", "consentPolicy", "amendmentPolicy",
                   "clauseSemanticIds"}
IDENTITY_FIELDS = {"agreementHash"}
# The non-semantic keys stripped to recover the capability-spec semantic core
# (identical to the C++ canonicalCapabilitySpecBytesFromSpec).
NON_SEMANTIC = {"kind", "schemaVersion", "identity", "sourceMap",
                "targetRequirements"}


def _compact(v) -> bytes:
    # Matches the C++ compactJson / Python json.dumps(sort_keys, separators).
    return json.dumps(v, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _frame(b: bytes) -> bytes:
    return struct.pack(">Q", len(b)) + b


def _no_unknown(obj: dict, allowed: set, prefix: str, errs: list) -> None:
    for k in obj:
        if k not in allowed:
            errs.append(f"unknown field {prefix}.{k}")


def _require(obj: dict, allowed: set, prefix: str, errs: list) -> None:
    for k in sorted(allowed - set(obj)):
        errs.append(f"{prefix}: missing '{k}'")


import re


def validate_shape(a, errs: list) -> None:
    if not isinstance(a, dict):
        errs.append("artifact is not a JSON object")
        return
    _require(a, TOP_FIELDS, "artifact", errs)
    _no_unknown(a, TOP_FIELDS, "artifact", errs)
    if a.get("kind") != KIND:
        errs.append(f"kind must be {KIND!r}")
    if a.get("domain") != DOMAIN:
        errs.append(f"domain must be {DOMAIN!r} (unknown domain)")
    slv = a.get("semanticLanguageVersion")
    if not isinstance(slv, str) or not re.match(SEMVER, slv):
        errs.append("semanticLanguageVersion must be a MAJOR.MINOR.PATCH string")
    elif slv not in KNOWN_LANGUAGE_VERSIONS:
        errs.append(f"semanticLanguageVersion {slv!r} is not a known semantic-"
                    "language version (unknown version — fail closed)")
    if not isinstance(a.get("capabilityHash"), str) or \
            not re.match(HEX64, a.get("capabilityHash", "")):
        errs.append("capabilityHash must be a 64-char lowercase hex string")

    env = a.get("envelope")
    if not isinstance(env, dict):
        errs.append("envelope must be an object")
    else:
        _require(env, ENVELOPE_FIELDS, "envelope", errs)
        _no_unknown(env, ENVELOPE_FIELDS, "envelope", errs)
        if env.get("schemaVersion") != ENVELOPE_VERSION:
            errs.append(f"envelope.schemaVersion must be {ENVELOPE_VERSION} "
                        "(unknown envelope version)")
        for pol in ("consentPolicy", "amendmentPolicy"):
            if env.get(pol) is not None and not isinstance(env.get(pol), dict):
                errs.append(f"envelope.{pol} must be an object or null")
        cl = env.get("clauseSemanticIds")
        if not isinstance(cl, list) or \
                any(not isinstance(x, str) or not x for x in cl):
            errs.append("envelope.clauseSemanticIds must be an array of "
                        "non-empty strings")

    ident = a.get("identity")
    if not isinstance(ident, dict):
        errs.append("identity must be an object")
    else:
        _require(ident, IDENTITY_FIELDS, "identity", errs)
        _no_unknown(ident, IDENTITY_FIELDS, "identity", errs)
        if not isinstance(ident.get("agreementHash"), str) or \
                not re.match(HEX64, ident.get("agreementHash", "")):
            errs.append("identity.agreementHash must be a 64-char lowercase hex "
                        "string")


def canonical_capability_bytes(spec, errs: list):
    """Recover + verify the capability-spec's canonical semantic bytes."""
    if not isinstance(spec, dict):
        errs.append("capability-spec is not a JSON object")
        return None
    core = {k: v for k, v in spec.items() if k not in NON_SEMANTIC}
    b = _compact(core)
    declared = (spec.get("identity") or {}).get("capabilityHash")
    if not declared:
        errs.append("capability-spec has no identity.capabilityHash")
        return None
    if hashlib.sha256(b).hexdigest() != declared:
        errs.append("capability-spec capabilityHash mismatch — its semantic "
                    "core does not hash to the declared identity (tampered)")
        return None
    return b


def verify_hashes(a, spec, errs: list) -> None:
    cap = canonical_capability_bytes(spec, errs)
    if cap is None:
        return
    if a.get("capabilityHash") != hashlib.sha256(cap).hexdigest():
        errs.append("capabilityHash does not match the paired capability-spec")
    env_bytes = _compact(a["envelope"])
    preimage = (_frame(DOMAIN.encode()) +
                _frame(a["semanticLanguageVersion"].encode()) +
                _frame(cap) + _frame(env_bytes))
    if a.get("identity", {}).get("agreementHash") != \
            hashlib.sha256(preimage).hexdigest():
        errs.append("agreementHash does not recompute — inauthentic identity")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", required=True)
    ap.add_argument("--verify-hashes", metavar="CAPABILITY_SPEC", default=None)
    args = ap.parse_args()

    errs: list = []
    try:
        with open(args.artifact, encoding="utf-8") as f:
            artifact = json.load(f)
    except (OSError, ValueError) as exc:
        print(f"[] agreement-identity INVALID: cannot read "
              f"{args.artifact}: {exc}", file=sys.stderr)
        return 1

    validate_shape(artifact, errs)
    if not errs and args.verify_hashes:
        try:
            with open(args.verify_hashes, encoding="utf-8") as f:
                spec = json.load(f)
        except (OSError, ValueError) as exc:
            print(f"[] agreement-identity INVALID: cannot read "
                  f"capability-spec {args.verify_hashes}: {exc}", file=sys.stderr)
            return 1
        verify_hashes(artifact, spec, errs)

    if errs:
        print("[] agreement-identity INVALID:", file=sys.stderr)
        for e in errs:
            print("    " + e, file=sys.stderr)
        return 1
    print("[] agreement-identity OK: shape valid" +
          (" + hashes verified" if args.verify_hashes else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
