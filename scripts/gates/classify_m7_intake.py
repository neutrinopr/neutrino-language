#!/usr/bin/env python3
""" M6→M7 intake seam S0 — classify a source-neutral domain-semantics artifact
against the frozen M7 intake profile.

THE SEAM. The `neutrino.l2-domain-semantics` v3 artifact (schemaVersion 3, hashed by
domainSemanticsHash) is the SOLE compiler-facing M7 intake contract. v3 is v2's
reduction graph PLUS a required, hashed intakeVersioning object; v2 is retained
UNCHANGED as the legacy compatibility baseline and is REFUSED by this seam. A future
M7 ontology/query adapter replaces only the PRODUCER of this artifact; everything
downstream (the  L2→L1 reduction, the normalized CoordinationPlan, the
domain-blind projection core, the backends) is unchanged and never learns that an
ontology existed. This classifier is the admission boundary: it accepts an artifact
iff it is a valid v3 artifact, its three version axes exactly match the live
vocabulary + the profile's reduction-semantics pin, AND every executable reduction
anchors to a capability in the ONE authoritative closed L1/CoordinationPlan
vocabulary. See docs/process/M7_INTAKE_SEAM.md and docs/m7-intake-profile.json.

Layering (why this is thin, not a second overlapping model):
  - Base v3 contract (validate_l2_domain_semantics_v3.py, which wraps the shared
    v2 logic): shape, one identifier namespace, endpoint resolution, descriptive/
    executable restriction, per-concept traceability, accepted provenance for
    behaviour-driving edges, hash, and the required intakeVersioning object. REUSED
    verbatim — not reimplemented, not forked from v2.
  - M7 ADMISSION ADDITIONS (what the base validator deliberately does NOT check,
    because v3 lets a domain declare its own l1Features as free strings):
      * closed-vocabulary anchoring — every EXECUTABLE reduction endpoint is a
        member of docs/semantic-feature-vocabulary.json (the closed namespace
        emitted from neutrino::knownSemanticFeatures()), loaded from the profile's
        declared source;
      * version binding — intakeVersioning.{semanticProfileVersion,
        reductionSemanticsVersion} exactly match the live vocabulary + the
        profile's reduction-semantics pin, so a bumped vocabulary/reducer rejects a
        stale artifact rather than reinterpreting it;
      * versioned + hash-anchored source provenance for every executable edge;
      * unambiguous mapping — a concept→capability executable pair declared once;
      * schema/version negotiation — only v3 is admitted; legacy v2 and unknown
        envelopes fail closed, never crash.
  The classifier introduces NO capability names of its own and NO domain/backend
  identity into capability selection; the namespace is the closed vocabulary by
  reference. Descriptive records cannot affect execution — they never cross into
  the executable capability set the reduction consumes.

Fail-closed. Every admission failure is a stable `intake.*` code (defined in the
profile's admissionDiagnostics, NOT the compiler taxonomy — the taxonomy must
byte-match the C++ compiler and this is a stdlib admission gate). A malformed
profile or artifact fails closed with a code, never a traceback.

Usage:
  classify_m7_intake.py --artifact FILE [--profile FILE]   # classify (prints report JSON)
  classify_m7_intake.py --selftest                         # positive+negative selftest
  classify_m7_intake.py --probe NAME --artifact FILE       # tamper NAME, assert fail-closed
"""
import argparse
import copy
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, os.path.join(_REPO, "scripts", "domain"))
sys.path.insert(0, os.path.join(_REPO, "scripts", "validators"))

import validate_l2_domain_semantics_v2 as v2  # noqa: E402  (shared KIND / relations / hash helpers)
import validate_l2_domain_semantics_v3 as v3  # noqa: E402  (the admitted M7 intake contract)
from validate_target_profile import load_semantic_vocabulary  # noqa: E402

DEFAULT_PROFILE = os.path.join(_REPO, "docs", "m7-intake-profile.json")
REPORT_KIND = "neutrino.m7-intake-admission-report"

# The classifier's stable, self-contained admission diagnostic codes. These are
# ALSO declared in the profile's admissionDiagnostics; assert_codes_match_profile()
# proves the two never drift (the profile is the published contract, this is its
# executable form).
CODES = (
    "intake.profile_invalid",
    "intake.unsupported_schema_version",
    "intake.vocabulary_unresolvable",
    "intake.artifact_invalid",
    "intake.vocabulary_drift",
    "intake.stale_vocabulary",
    "intake.stale_reducer",
    "intake.unregistered_capability",
    "intake.unversioned_mapping",
    "intake.provenance_incomplete",
    "intake.ambiguous_mapping",
)


def _diag(code, message):
    assert code in CODES, f"unregistered intake code {code!r}"
    return {"code": code, "message": message}


def load_profile(path):
    """Load + shape-check the intake profile. Fail-closed (raise) on malformed:
    an empty/bogus profile must not silently admit everything."""
    with open(path, encoding="utf-8") as fh:
        p = json.load(fh)
    ic = p.get("intakeContract") or {}
    cn = p.get("capabilityNamespace") or {}
    rs = p.get("reductionSemantics") or {}
    if (p.get("kind") != "neutrino.m7-intake-profile"
            or p.get("schemaVersion") != 1
            or ic.get("artifactKind") != v2.KIND
            or ic.get("artifactSchemaVersion") != v3.SCHEMA_VERSION
            or ic.get("hashField") != "domainSemanticsHash"
            or cn.get("kind") != "neutrino.semantic-feature-vocabulary"
            or not isinstance(cn.get("source"), str) or not cn.get("source")
            or not _is_positive_int(cn.get("semanticProfileVersion"))
            or not _is_positive_int(rs.get("version"))
            or list(p.get("executableRelations") or []) != list(v2.EXECUTABLE_RELATIONS)
            or not isinstance(p.get("admissionDiagnostics"), list)):
        raise ValueError(f"malformed M7 intake profile: {path}")
    return p


def _is_positive_int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def resolve_profile_vocabulary(profile):
    """P1-2: load the CLOSED vocabulary from the EXACT repo-relative source the
    profile declares (not the validator's default), verify its kind + pinned
    version, and fail closed on a missing / unsafe (absolute or `..`-escaping) /
    drifted reference. Raises ValueError so a bad reference is a stable
    non-admission (intake.vocabulary_unresolvable), never a silent default-load."""
    source = profile["capabilityNamespace"]["source"]
    if os.path.isabs(source) or os.path.normpath(source) != source or source.startswith(".."):
        raise ValueError(f"unsafe capabilityNamespace.source {source!r}")
    resolved = os.path.normpath(os.path.join(_REPO, source))
    if os.path.commonpath([resolved, _REPO]) != _REPO or not os.path.isfile(resolved):
        raise ValueError(f"capabilityNamespace.source does not resolve to a repo file: {source!r}")
    # load_semantic_vocabulary already fails closed on a wrong kind / malformed artifact.
    vocabulary, spv = load_semantic_vocabulary(resolved)
    if spv != profile["capabilityNamespace"]["semanticProfileVersion"]:
        raise ValueError(
            f"capabilityNamespace.source semanticProfileVersion {spv} != profile pin "
            f"{profile['capabilityNamespace']['semanticProfileVersion']}")
    return vocabulary, spv


def _executable_edges(artifact):
    return [r for r in artifact["reductions"] if r["relation"] in v2.EXECUTABLE_RELATIONS]


def classify(artifact, profile, vocabulary, spv):
    """Return an admission report dict. `admitted` is True iff diagnostics is empty.
    Ordering is deterministic (sorted) so the report is byte-reproducible."""
    diags = []

    # (0) Schema/version negotiation. The M7 seam admits v3 ONLY (schemaVersion 3);
    # v2 remains byte-valid but is the LEGACY compatibility baseline, not an M7
    # intake choice, so it fails closed here with a clear code — never a crash.
    if (not isinstance(artifact, dict)
            or artifact.get("kind") != v2.KIND
            or artifact.get("schemaVersion") != v3.SCHEMA_VERSION):
        got_v = artifact.get("schemaVersion") if isinstance(artifact, dict) else None
        legacy = " (v2 is the legacy compatibility baseline; the producer must emit v3)" if got_v == v2.SCHEMA_VERSION else ""
        diags.append(_diag(
            "intake.unsupported_schema_version",
            f"intake admits only ({v2.KIND}, schemaVersion {v3.SCHEMA_VERSION}); "
            f"got ({artifact.get('kind') if isinstance(artifact, dict) else '<non-object>'}, "
            f"schemaVersion {got_v}){legacy}"))
        return _report(artifact, spv, diags, [], [])

    # (1) Vocabulary pin. The closed namespace this profile references must be the
    # one on disk (version-negotiated), else a drifted vocabulary could silently
    # widen or narrow the admitted capability set.
    if spv != profile["capabilityNamespace"]["semanticProfileVersion"]:
        diags.append(_diag(
            "intake.vocabulary_drift",
            f"closed vocabulary semanticProfileVersion {spv} != profile pin "
            f"{profile['capabilityNamespace']['semanticProfileVersion']}"))
        return _report(artifact, spv, diags, [], [])

    # (2) Base v3 contract — REUSED verbatim (shape/identity/endpoint/classification/
    # provenance/hash + REQUIRED intakeVersioning). A base failure is surfaced as a
    # single wrapping intake code, so the seam has one fail-closed vocabulary.
    base = v3.validate(artifact)
    if base:
        for b in base:
            diags.append(_diag("intake.artifact_invalid", f"base v3 contract: {b}"))
        return _report(artifact, spv, diags, [], [])

    # (2b) Version binding () — three explicit axes: envelope schemaVersion (0),
    # capability-vocabulary + reduction-semantics (here). The artifact self-declares
    # both in intakeVersioning (required + hashed by base v3), and each must EXACTLY
    # match the live vocabulary + the profile's reduction-semantics pin, so a bumped
    # vocabulary/reducer rejects a stale artifact rather than reinterpreting it.
    iv = artifact["intakeVersioning"]  # base v3 guarantees presence + int fields
    if iv["semanticProfileVersion"] != spv:
        diags.append(_diag(
            "intake.stale_vocabulary",
            f"artifact was produced under capability-vocabulary version "
            f"{iv['semanticProfileVersion']}, but the live vocabulary is {spv}"))
    rs_pin = profile["reductionSemantics"]["version"]
    if iv["reductionSemanticsVersion"] != rs_pin:
        diags.append(_diag(
            "intake.stale_reducer",
            f"artifact was produced under reduction-semantics version "
            f"{iv['reductionSemanticsVersion']}, but the profile pins {rs_pin}"))
    if any(d["code"] in ("intake.stale_vocabulary", "intake.stale_reducer") for d in diags):
        return _report(artifact, spv, diags, [], [])

    # --- M7 admission additions over the base contract ---
    prov_by_subject = {}
    for p in artifact["provenance"]:
        if p["status"] == "accepted":
            prov_by_subject.setdefault(p["subject"], p)

    exec_caps = set()
    seen_pairs = {}  # (from,to) -> lossiness, to catch contradictory/duplicate mappings
    for r in _executable_edges(artifact):
        rid, frm, to = r["id"], r["from"], r["to"]

        # (3) closed-vocabulary anchoring — the endpoint is a REGISTERED generic L1
        # capability, not a domain-local free string. This is the gap the base v2
        # validator leaves open (it only checks the endpoint is a declared local
        # l1Feature). Domain/backend identity plays NO part in this selection.
        if to not in vocabulary:
            diags.append(_diag(
                "intake.unregistered_capability",
                f"executable reduction '{rid}' targets '{to}', which is not a capability "
                f"in the closed vocabulary (semanticProfileVersion {spv})"))
        else:
            exec_caps.add(to)

        # (4) versioned + hash-anchored source provenance. accepted status is a base
        # invariant; M7 additionally requires the source VERSION and the projection
        # HASH so a future ontology source/query-set/projection is version- and
        # hash-anchored with no new schema (see §"provenance model" in the doc).
        pr = prov_by_subject.get(rid)
        if pr is None or not pr.get("standardVersion"):
            diags.append(_diag(
                "intake.unversioned_mapping",
                f"executable reduction '{rid}' has no versioned accepted provenance "
                f"(standardVersion missing)"))
        if pr is None or not pr.get("excerptHash"):
            diags.append(_diag(
                "intake.provenance_incomplete",
                f"executable reduction '{rid}' has no projection-hash-anchored provenance "
                f"(excerptHash missing)"))

        # (5) unambiguous mapping — a concept→capability executable pair declared
        # more than once (or with contradictory fidelity) leaves it undetermined
        # which record governs. The base contract allows this (distinct edge ids).
        if (frm, to) in seen_pairs:
            diags.append(_diag(
                "intake.ambiguous_mapping",
                f"executable mapping ('{frm}' -> '{to}') is declared more than once "
                f"(lossiness {seen_pairs[(frm, to)]!r} then {r['lossiness']!r})"))
        else:
            seen_pairs[(frm, to)] = r["lossiness"]

    # Descriptive records: every concept NOT reached by an executable edge, plus
    # every non-executable reduction endpoint. Reported for inspection; they can
    # never enter exec_caps, so they cannot affect execution.
    exec_from = {r["from"] for r in _executable_edges(artifact)}
    descriptive = sorted(c["name"] for c in artifact["concepts"] if c["name"] not in exec_from)

    return _report(artifact, spv, diags, sorted(exec_caps), descriptive)


def _report(artifact, spv, diags, exec_caps, descriptive):
    diags = sorted(diags, key=lambda d: (CODES.index(d["code"]), d["message"]))
    return {
        "kind": REPORT_KIND,
        "schemaVersion": 1,
        "admitted": not diags,
        "domain": artifact.get("domain") if isinstance(artifact, dict) else None,
        "artifactHash": artifact.get("domainSemanticsHash") if isinstance(artifact, dict) else None,
        "capabilityNamespace": {"semanticProfileVersion": spv},
        "executableCapabilities": exec_caps,
        "descriptiveRecords": descriptive,
        "diagnostics": diags,
    }


def classify_file(artifact_path, profile_path=DEFAULT_PROFILE):
    profile = load_profile(profile_path)
    with open(artifact_path, encoding="utf-8") as fh:
        artifact = json.load(fh)
    try:
        vocabulary, spv = resolve_profile_vocabulary(profile)  # P1-2: from the profile's declared source
    except (ValueError, OSError) as ex:
        return _report(artifact, None, [_diag("intake.vocabulary_unresolvable", str(ex))], [], [])
    return classify(artifact, profile, vocabulary, spv)


# --------------------------------------------------------------------------- #
# Probe interface — the fail-closed proof. Each probe tampers the admitted
# reference fixture in exactly the way that should trip ONE admission code, and
# asserts the classifier rejects with that code. Mirrors the  gate pattern.
# --------------------------------------------------------------------------- #
def _rehash(artifact):
    """Re-sign so the hash check passes and the SEMANTIC mutation is what bites
    (never a stale-hash false-positive)."""
    artifact["domainSemanticsHash"] = v2._hash_of(v2._canonical_body(artifact))
    return artifact


def _probe_unregistered_capability(a):
    a["l1Features"].append({"name": "effect:teleport", "kind": "primitive"})
    a["reductions"][0]["to"] = "effect:teleport"
    return _rehash(a)


def _probe_unversioned_mapping(a):
    rid = _executable_edges(a)[0]["id"]
    for p in a["provenance"]:
        if p["subject"] == rid and p["status"] == "accepted":
            p.pop("standardVersion", None)
    return _rehash(a)


def _probe_provenance_incomplete(a):
    rid = _executable_edges(a)[0]["id"]
    for p in a["provenance"]:
        if p["subject"] == rid and p["status"] == "accepted":
            p.pop("excerptHash", None)
    return _rehash(a)


def _probe_ambiguous_mapping(a):
    e = _executable_edges(a)[0]
    dup = dict(e)
    dup["id"] = e["id"] + "_dup"
    dup["lossiness"] = "lossy_preserved" if e["lossiness"] == "lossless" else "lossless"
    a["reductions"].append(dup)
    a["provenance"].append({"subject": dup["id"], "source": "s", "status": "accepted",
                            "standardVersion": "1.0.0", "excerptHash": "0" * 64})
    return _rehash(a)


def _probe_descriptive_drives_executable(a):
    # A descriptive concept driving an executable edge -> base l2v2.classification,
    # surfaced as intake.artifact_invalid (the seam refuses it before capability
    # selection). Proves descriptive records cannot become executable.
    frm = _executable_edges(a)[0]["from"]
    for c in a["concepts"]:
        if c["name"] == frm:
            c["classification"] = "descriptive"
    return _rehash(a)


def _probe_unsupported_schema_version(a):
    a["schemaVersion"] = 4  # an unknown/future envelope is not admitted (only v3 is)
    return _rehash(a)


def _probe_legacy_v2(a):
    # A byte-valid LEGACY v2 artifact (no intakeVersioning) is refused by the M7
    # profile — v2 is the compatibility baseline, not an M7 intake choice.
    a["schemaVersion"] = 2
    a.pop("intakeVersioning", None)
    return _rehash(a)


def _probe_stale_vocabulary(a):
    a["intakeVersioning"]["semanticProfileVersion"] = 99  # != live vocabulary
    return _rehash(a)


def _probe_stale_reducer(a):
    a["intakeVersioning"]["reductionSemanticsVersion"] = 99  # != profile pin
    return _rehash(a)


def _probe_mixed_version(a):
    # A mixed tuple (both axes drifted differently) is rejected — the seam checks
    # the FULL (vocabulary, reducer) tuple, not one axis.
    a["intakeVersioning"] = {"semanticProfileVersion": 99, "reductionSemanticsVersion": 88}
    return _rehash(a)


def _probe_tampered_hash(a):
    # A stale hash (no re-sign) -> base hash check -> intake.artifact_invalid.
    a["domainSemanticsHash"] = "0" * 64
    return a


def _profile_bad_vocabulary_source(p):
    # P1-2: the profile's declared capabilityNamespace.source no longer resolves.
    p["capabilityNamespace"]["source"] = "does/not/exist.json"
    return p


# Each probe tampers the reference fixture (target "artifact") or the profile
# (target "profile") in exactly the way that should trip ONE admission code.
PROBES = {
    "unregistered-capability": ("intake.unregistered_capability", _probe_unregistered_capability, "artifact"),
    "unversioned-mapping": ("intake.unversioned_mapping", _probe_unversioned_mapping, "artifact"),
    "provenance-incomplete": ("intake.provenance_incomplete", _probe_provenance_incomplete, "artifact"),
    "ambiguous-mapping": ("intake.ambiguous_mapping", _probe_ambiguous_mapping, "artifact"),
    "descriptive-drives-executable": ("intake.artifact_invalid", _probe_descriptive_drives_executable, "artifact"),
    "unsupported-schema-version": ("intake.unsupported_schema_version", _probe_unsupported_schema_version, "artifact"),
    "legacy-v2-rejected": ("intake.unsupported_schema_version", _probe_legacy_v2, "artifact"),
    "stale-vocabulary": ("intake.stale_vocabulary", _probe_stale_vocabulary, "artifact"),
    "stale-reducer": ("intake.stale_reducer", _probe_stale_reducer, "artifact"),
    "mixed-version": ("intake.stale_vocabulary", _probe_mixed_version, "artifact"),
    "tampered-hash": ("intake.artifact_invalid", _probe_tampered_hash, "artifact"),
    "bad-vocabulary-source": ("intake.vocabulary_unresolvable", _profile_bad_vocabulary_source, "profile"),
}


def run_probe(name, artifact_path, profile_path=DEFAULT_PROFILE):
    expect_code, mutate, target = PROBES[name]
    profile = load_profile(profile_path)
    with open(artifact_path, encoding="utf-8") as fh:
        base = json.load(fh)
    if target == "profile":
        # Write the tampered profile and classify the UNCHANGED fixture against it.
        bad = mutate(copy.deepcopy(profile))
        bad_path = os.path.join(os.path.dirname(os.path.abspath(artifact_path)), f"._probe_{name}.profile.json")
        try:
            with open(bad_path, "w", encoding="utf-8") as fh:
                json.dump(bad, fh)
            report = classify_file(artifact_path, bad_path)
        finally:
            if os.path.exists(bad_path):
                os.remove(bad_path)
    else:
        vocabulary, spv = resolve_profile_vocabulary(profile)
        report = classify(mutate(copy.deepcopy(base)), profile, vocabulary, spv)
    codes = {d["code"] for d in report["diagnostics"]}
    if report["admitted"] or expect_code not in codes:
        return (False, f"probe {name}: expected fail-closed with {expect_code}; "
                       f"admitted={report['admitted']} codes={sorted(codes)}")
    return (True, f"probe {name}: fail-closed with {expect_code}")


def assert_codes_match_profile(profile_path=DEFAULT_PROFILE):
    """The classifier's CODES tuple equals the profile's admissionDiagnostics —
    neither the published contract nor its executable form may drift."""
    profile = load_profile(profile_path)
    declared = {d["code"] for d in profile["admissionDiagnostics"]}
    if declared != set(CODES):
        return (False, f"admissionDiagnostics drift: profile-only {sorted(declared - set(CODES))}, "
                       f"classifier-only {sorted(set(CODES) - declared)}")
    return (True, "admissionDiagnostics match")


def selftest():
    fixture = os.path.join(_REPO, "examples", "m7-intake",
                           "ontology_shaped_milestone_acceptance.l2v3.json")
    fails = []
    ok, msg = assert_codes_match_profile()
    if not ok:
        fails.append(msg)
    report = classify_file(fixture)
    if not report["admitted"]:
        fails.append(f"reference fixture rejected: {report['diagnostics']}")
    if not report["executableCapabilities"]:
        fails.append("reference fixture admitted with no executable capabilities")
    for name in PROBES:
        ok, msg = run_probe(name, fixture)
        if not ok:
            fails.append(msg)
    if fails:
        for f in fails:
            print(f"[intake.selftest] {f}", file=sys.stderr)
        return 1
    print(f"ok (selftest): reference fixture admitted; {len(PROBES)} probes fail closed")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Classify a domain-semantics artifact against the M7 intake seam.")
    ap.add_argument("--artifact")
    ap.add_argument("--profile", default=DEFAULT_PROFILE)
    ap.add_argument("--probe", choices=sorted(PROBES))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.probe:
        # Repo tamper-probe convention (): a probe "fails as expected" by
        # exiting NONZERO and printing probe-failed-as-expected:<name> when the
        # tamper is correctly caught fail-closed. If the tamper slips through, exit
        # 0 so the meta-gate sees returncode==0 and flags the probe as broken.
        artifact = args.artifact or os.path.join(
            _REPO, "examples", "m7-intake", "ontology_shaped_milestone_acceptance.l2v3.json")
        ok, msg = run_probe(args.probe, artifact, args.profile)
        if ok:
            print(f"probe-failed-as-expected:{args.probe}")
            return 1
        print(f"probe unexpectedly passed: {msg}")
        return 0
    if not args.artifact:
        print("one of --artifact / --selftest / --probe is required", file=sys.stderr)
        return 2

    try:
        report = classify_file(args.artifact, args.profile)
    except (ValueError, OSError, json.JSONDecodeError) as ex:
        # Fail closed: a malformed profile/artifact is a stable non-admission, not a crash.
        print(json.dumps({"kind": REPORT_KIND, "admitted": False,
                          "diagnostics": [{"code": "intake.profile_invalid", "message": str(ex)}]},
                         indent=2, sort_keys=True))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["admitted"] else 1


if __name__ == "__main__":
    sys.exit(main())
