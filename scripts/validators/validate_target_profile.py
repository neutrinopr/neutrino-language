#!/usr/bin/env python3
"""M5 WP4 () — neutrino.target-profile validation.

A target profile declares which semantic FEATURES a rendering target supports; the canonical
spec's targetRequirements are matched against it before rendering (scripts/gates/check_spec_legality.py).
This gate validates the profile's SHAPE fail-closed so the matcher can trust it.

The normative shape is docs/schemas/target-profile.schema.json; this stdlib validator mirrors it
(CI runs the script, not a JSON-Schema library) AND enforces the beyond-schema invariants:

  - profileId matches <family>.<name>.v<major> and its v<major> equals profileVersion (AD3: the
    two identity fields cannot drift);
  - supportedFeatures and unsupportedConstructs are disjoint (a feature cannot be both).

Diagnostics are machine-readable {code, severity, message} under the stable `profile.*` family
(shared failure-taxonomy direction, ), sorted. Exit 0 ok / 1 violations / 2 usage.

  validate_target_profile.py FILE [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

SCHEMA_VERSION = 1
PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\.v([0-9]+)$")
FEATURE_RE = re.compile(r"^[a-z][a-z_]*:[a-z][a-z0-9_]*$")
RUNTIME_FAMILIES = {"on_chain", "relational", "off_chain"}
EXEC_MODES = {"deterministic", "simulated", "real"}
FALLBACK = {"fail_closed", "advisory"}
FIELDS = {"schemaVersion", "kind", "profileId", "profileVersion", "target", "runtimeFamily",
          "executionMode", "supportedFeatures", "unsupportedConstructs", "fallbackPolicy"}
# Optional capability-spec contract pin (R3/) — allowed but not required by the SHAPE validator;
# scripts/gates/check_artifact_pins.py enforces its presence + VALUE against the emitted contract version.
# semanticProfile () is the optional semantic-realization capability block (features + limits +
# its own pinned contract version); its VALUE-level version pin is enforced by the C++ plan-legality gate.
OPTIONAL_FIELDS = {"capabilitySpecVersion", "semanticProfile"}
CAPABILITY_SPEC_VERSION_RE = re.compile(r"^v[0-9]+$")
LIMIT_FIELDS = {"maxExpressionDepth", "maxEffects", "maxEffectGroups", "maxAttestations", "maxComputes",
                "maxOperationSteps"}
# The CLOSED  semantic-requirement registry is loaded from the ONE
# authoritative artifact — docs/semantic-feature-vocabulary.json, emitted by
# `neutrino-translate --semantic-feature-vocabulary` from neutrino::
# knownSemanticFeatures() and byte-matched against the compiler by CI. NO
# hand-copied table: a semanticProfile.features entry outside this set is a
# typo/future feature and fails closed, and the set cannot drift from the C++.
SEMANTIC_VOCABULARY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..",
    "docs", "semantic-feature-vocabulary.json")


def load_semantic_vocabulary(path: str = SEMANTIC_VOCABULARY):
    """Load the closed vocabulary artifact -> (features frozenset, semanticProfileVersion).
    Fail-closed: a missing/malformed artifact raises rather than silently allowing
    every feature (an empty registry would wrongly reject all — a present-but-bogus
    one would wrongly accept)."""
    with open(path, encoding="utf-8") as fh:
        v = json.load(fh)
    feats, ver = v.get("features"), v.get("semanticProfileVersion")
    if (v.get("kind") != "neutrino.semantic-feature-vocabulary"
            or not isinstance(feats, list) or not all(isinstance(f, str) for f in feats)
            or not isinstance(ver, int) or isinstance(ver, bool)):
        raise ValueError(f"malformed semantic-feature vocabulary artifact: {path}")
    return frozenset(feats), ver


SEMANTIC_FEATURE_REGISTRY, SEMANTIC_PROFILE_VERSION = load_semantic_vocabulary()


def _pos_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def _nonneg_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _validate_semantic_profile(sp, out: list) -> None:
    """Mirror the schema's semanticProfile block (): version + features + limits."""
    if not isinstance(sp, dict):
        out.append(diag("profile.schema", "semanticProfile must be a JSON object"))
        return
    for k in sorted(set(sp) - {"version", "features", "limits"}):
        out.append(diag("profile.unknown_field", f"semanticProfile.{k} is not a known field"))
    if not _pos_int(sp.get("version")):
        out.append(diag("profile.schema", "semanticProfile.version must be a positive integer"))
    elif sp.get("version") != SEMANTIC_PROFILE_VERSION:
        # The version PINS the published closed-vocabulary contract; a different
        # value cannot match it (unknown/drifted version fails closed, mirroring
        # the C++ plan-legality gate).
        out.append(diag("profile.profile_version_mismatch",
                        f"semanticProfile.version {sp['version']} != the published "
                        f"semanticProfileVersion {SEMANTIC_PROFILE_VERSION}"))
    feats = _feature_array(sp, "features", out)
    # Advertised semantic features must be in the CLOSED registry (typo/future guard).
    for f in sorted(feats - SEMANTIC_FEATURE_REGISTRY):
        out.append(diag("profile.unknown_semantic_feature",
                        f"semanticProfile.features '{f}' is not in the closed  registry"))
    lim = sp.get("limits")
    if not isinstance(lim, dict):
        out.append(diag("profile.schema", "semanticProfile.limits must be a JSON object"))
    else:
        for k in sorted(set(lim) - LIMIT_FIELDS):
            out.append(diag("profile.unknown_field", f"semanticProfile.limits.{k} is not a known limit"))
        for k in sorted(LIMIT_FIELDS - set(lim)):
            out.append(diag("profile.missing_field", f"semanticProfile.limits missing '{k}'"))
        for k in sorted(LIMIT_FIELDS & set(lim)):
            if not _nonneg_int(lim[k]):
                out.append(diag("profile.schema", f"semanticProfile.limits.{k} must be a non-negative integer"))


def diag(code: str, message: str, severity: str = "error") -> dict:
    return {"code": code, "severity": severity, "message": message}


def _s(v) -> bool:
    return isinstance(v, str) and v != ""


def _feature_array(prof, key: str, out: list) -> set:
    v = prof.get(key)
    if not isinstance(v, list):
        out.append(diag("profile.schema", f"{key} must be an array"))
        return set()
    seen = set()
    for i, f in enumerate(v):
        if not (_s(f) and FEATURE_RE.match(f)):
            out.append(diag("profile.bad_feature", f"{key}[{i}]: '{f}' is not a <dimension>:<value> feature"))
        elif f in seen:
            out.append(diag("profile.schema", f"{key}: duplicate feature '{f}'"))
        else:
            seen.add(f)
    return seen


def validate(prof) -> list:
    out: list = []
    if not isinstance(prof, dict):
        return [diag("profile.schema", "top-level must be a JSON object")]

    for k in sorted(set(prof) - FIELDS - OPTIONAL_FIELDS):
        out.append(diag("profile.unknown_field", f"unknown field '{k}'"))
    for k in sorted(FIELDS - set(prof)):
        out.append(diag("profile.missing_field", f"missing '{k}'"))
    if "capabilitySpecVersion" in prof and not (
            _s(prof.get("capabilitySpecVersion")) and CAPABILITY_SPEC_VERSION_RE.match(prof["capabilitySpecVersion"])):
        out.append(diag("profile.schema", "capabilitySpecVersion must match ^v[0-9]+$"))
    if "semanticProfile" in prof:
        _validate_semantic_profile(prof["semanticProfile"], out)

    if prof.get("schemaVersion") != SCHEMA_VERSION:
        out.append(diag("profile.schema_version", f"schemaVersion must be {SCHEMA_VERSION}"))
    if prof.get("kind") != "neutrino.target-profile":
        out.append(diag("profile.schema", "kind must be 'neutrino.target-profile'"))
    if not _s(prof.get("target")):
        out.append(diag("profile.schema", "target must be a non-empty string"))
    if prof.get("runtimeFamily") not in RUNTIME_FAMILIES:
        out.append(diag("profile.schema", f"runtimeFamily must be one of {sorted(RUNTIME_FAMILIES)}"))
    if prof.get("executionMode") not in EXEC_MODES:
        out.append(diag("profile.schema", f"executionMode must be one of {sorted(EXEC_MODES)}"))
    if prof.get("fallbackPolicy") not in FALLBACK:
        out.append(diag("profile.schema", f"fallbackPolicy must be one of {sorted(FALLBACK)}"))

    # profileId format + version cross-check (AD3).
    pid = prof.get("profileId")
    pid_version = None
    if _s(pid):
        m = PROFILE_ID_RE.match(pid)
        if not m:
            out.append(diag("profile.bad_profile_id", f"profileId '{pid}' must match <family>.<name>.v<major>"))
        else:
            pid_version = int(m.group(1))
    else:
        out.append(diag("profile.bad_profile_id", "profileId must be a non-empty string"))
    pv = prof.get("profileVersion")
    if not (isinstance(pv, int) and not isinstance(pv, bool) and pv >= 1):
        out.append(diag("profile.schema", "profileVersion must be a positive integer"))
    elif pid_version is not None and pid_version != pv:
        out.append(diag("profile.profile_version_mismatch",
                        f"profileVersion {pv} != profileId version v{pid_version}"))

    supported = _feature_array(prof, "supportedFeatures", out)
    unsupported = _feature_array(prof, "unsupportedConstructs", out)
    both = supported & unsupported
    for f in sorted(both):
        out.append(diag("profile.conflicting_feature",
                        f"'{f}' is in both supportedFeatures and unsupportedConstructs"))

    return sorted(out, key=lambda d: (d["code"], d["message"]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a neutrino target profile")
    ap.add_argument("file", help="path to a target-profile.json")
    ap.add_argument("--out", help="output dir for profile.report.json + diagnostics.json")
    args = ap.parse_args()

    prof = None
    try:
        prof = json.load(open(args.file, encoding="utf-8"))
        diagnostics = validate(prof)
    except (OSError, ValueError) as exc:
        diagnostics = [diag("profile.io", f"cannot read target profile: {exc}")]

    ok = not [d for d in diagnostics if d.get("severity") == "error"]
    report = {"ok": ok, "file": os.path.basename(args.file),
              "profileId": prof.get("profileId") if isinstance(prof, dict) else None,
              "diagnostics": diagnostics}
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        json.dump(report, open(os.path.join(args.out, "profile.report.json"), "w"), indent=2, sort_keys=True)
        json.dump({"ok": ok, "diagnostics": diagnostics},
                  open(os.path.join(args.out, "diagnostics.json"), "w"), indent=2, sort_keys=True)

    json.dump({"ok": ok, "diagnostics": diagnostics}, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
