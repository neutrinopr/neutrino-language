#!/usr/bin/env python3
""" Slice 2 — M7 reduction conformance for an external domain-semantics artifact.

Ties the admission boundary ( classify_m7_intake) to the  L2->L1 reduction
and the  capability registry, so a source-neutral v3 artifact is a COMPLETE
deterministic input to the verification/reduction boundary — not merely classified.

Given an admitted v3 artifact and a coordination-plan source (a capability-spec or
a `.neu` source), it proves, fail-closed:

  1. ADMISSION — classify_m7_intake admits the artifact (v3, versioned provenance,
     closed-vocabulary anchoring). A rejected artifact never reaches reduction.
  2. REDUCTION — the EXISTING  reducer (neutrino-emit --kind=domain-reduction)
     reduces it against the concrete normalized coordination plan. A successful reduction is the
     coordination-plan cross-check: every executable l1_feature is INDUCED by the plan and of the
     right kind (the reducer fails closed on unknown/uninduced/wrong-kind).
  3. REGISTRY — every reduction endpoint and every declared l1_feature resolves to a
     capability in the published authoritative registry (docs/semantic-capability-
     registry.json), and each declared kind EQUALS the registry's authoritative
     category. So the artifact anchors to the ONE registry, by identity, and a
     mislabelled or unregistered capability fails closed.
  4. PARITY (optional) — with --expect-reduction, the reduction is byte-identical to a
     reference (e.g. the same artifact reduced against the source `.neu` coordination plan, or the
     compiler's own IR), proving the external artifact is a faithful stand-in and the
     spec/source coordination-plan paths agree.

Every failure is a stable `conformance.*` code. A malformed input fails closed with a
code, never a traceback.

Usage:
  check_m7_reduction_conformance.py --artifact F --reduce-against F --neutrino-emit BIN
      [--registry F] [--profile F] [--expect-reduction F]
  check_m7_reduction_conformance.py --selftest
"""
import argparse
import json
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_REPO, "scripts", "validators"))

import classify_m7_intake as intake  # noqa: E402  (the  admission boundary, reused)
import verify_domain_pack as vdp  # noqa: E402  (the shared JSON-schema-subset validator, reused)

DEFAULT_REGISTRY = os.path.join(_REPO, "docs", "semantic-capability-registry.json")
REGISTRY_SCHEMA = os.path.join(_REPO, "docs", "schemas", "semantic-capability-registry.schema.json")
EXECUTABLE_RELATIONS = ("expands", "discharges")

CODES = (
    "conformance.not_admitted",
    "conformance.reduction_failed",
    "conformance.reduction_incomplete",
    "conformance.unregistered_capability",
    "conformance.category_mismatch",
    "conformance.stale_registry",
    "conformance.parity_mismatch",
    "conformance.malformed",
)


def _diag(code, message):
    assert code in CODES, f"unregistered conformance code {code!r}"
    return {"code": code, "message": message}


_BINDING_FIELDS = ("edge", "concept", "feature", "relation")


def _well_formed_binding(b):
    """A reduction binding must be an object with the four required string fields —
    so downstream tuple/feature access can never KeyError on a malformed emitter."""
    return isinstance(b, dict) and all(isinstance(b.get(k), str) for k in _BINDING_FIELDS)


def validate_registry(path, artifact_spv, diags):
    """Establish that the supplied registry is THE governed capability contract,
    pinned to the admitted artifact's semantic-profile version, then return
    {id: category}. Fail-closed (append a diagnostic + return None) on anything
    that is not the governed registry:
      - full shape/invariants via the committed schema (reusing the shared pack
        validator, not a weaker parallel one) — types/patterns/enums/required/
        additionalProperties;
      - the cross-field id split (dimension:value == id) the schema cannot express;
      - NO duplicate capability ids (schema uniqueItems only rejects duplicate
        whole records, not same-id/different-record);
      - semanticProfileVersion EQUAL to the admitted artifact's pin, so a registry
        from a different semantic contract version is refused, not reinterpreted."""
    try:
        with open(path, encoding="utf-8") as fh:
            reg = json.load(fh)
        schema = json.load(open(REGISTRY_SCHEMA, encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        diags.append(_diag("conformance.malformed", f"registry unreadable: {e}"))
        return None
    sdiags = []  # vdp._validate appends preformatted "[code] message" strings
    vdp._validate(reg, schema, "capabilityRegistry", sdiags, schema)
    if sdiags:
        diags.append(_diag("conformance.malformed",
                           f"registry violates its governed schema: {sdiags[0]}"))
        return None
    ids = [c["id"] for c in reg["capabilities"]]
    if len(ids) != len(set(ids)):
        diags.append(_diag("conformance.malformed", "registry has duplicate capability ids"))
        return None
    for c in reg["capabilities"]:
        if c["id"] != f"{c['dimension']}:{c['value']}":
            diags.append(_diag("conformance.malformed",
                               f"registry capability {c['id']!r} dimension/value does not match its id"))
            return None
    if reg.get("semanticProfileVersion") != artifact_spv:
        diags.append(_diag("conformance.stale_registry",
                           f"registry semanticProfileVersion {reg.get('semanticProfileVersion')!r} "
                           f"!= the admitted artifact's {artifact_spv!r}"))
        return None
    return {c["id"]: c["category"] for c in reg["capabilities"]}


def reduce_artifact(neutrino_emit, artifact_path, reduce_against_path):
    """Run the EXISTING  reducer; return (bindings_text, error_or_None)."""
    r = subprocess.run(
        [neutrino_emit, "--kind=domain-reduction", artifact_path,
         "--reduce-against", reduce_against_path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        return None, r.stderr.decode("utf-8", "replace").strip()
    return r.stdout.decode("utf-8", "replace"), None


def conform(artifact_path, registry_path, profile_path, *, neutrino_emit=None,
            reduce_against_path=None, reduction_path=None, expect_reduction_path=None):
    diags = []
    with open(artifact_path, encoding="utf-8") as fh:
        artifact = json.load(fh)

    # (1) Admission — reuse the  classifier verbatim.
    report = intake.classify_file(artifact_path, profile_path)
    if not report["admitted"]:
        for d in report["diagnostics"]:
            diags.append(_diag("conformance.not_admitted",
                               f"admission refused: {d['code']}: {d['message']}"))
        return _result(artifact, diags, None)

    # (2) Reduction — the concrete-coordination-plan cross-check is the reducer.
    # Either run the live  reducer (neutrino-emit) or consume a committed
    # reduction (so the governance gate + tamper probes run in the build-free fast
    # tier while the lit test drives the real binary).
    if reduction_path is not None:
        with open(reduction_path, encoding="utf-8") as fh:
            bindings_text, err = fh.read(), None
    else:
        bindings_text, err = reduce_artifact(neutrino_emit, artifact_path, reduce_against_path)
    if err is not None:
        diags.append(_diag("conformance.reduction_failed",
                           f"reduction against {os.path.basename(reduce_against_path)} failed: {err}"))
        return _result(artifact, diags, None)
    try:
        reduction = json.loads(bindings_text)
    except json.JSONDecodeError as e:
        diags.append(_diag("conformance.malformed", f"reducer output is not JSON: {e}"))
        return _result(artifact, diags, None)

    # (2b) Completeness — a zero exit is NOT proof; the reducer output must be a
    # well-formed projection object whose EXECUTABLE bindings correspond EXACTLY
    # and UNIQUELY to the admitted artifact's executable reduction edges (matching
    # edge/concept/feature/relation). This rejects a fake/regressed emitter that
    # returns empty/partial/extra bindings or a non-object, before any downstream
    # step treats the reduction as authoritative.
    if (not isinstance(reduction, dict)
            or not isinstance(reduction.get("bindings"), list)
            or any(not _well_formed_binding(b) for b in reduction["bindings"])):
        diags.append(_diag("conformance.malformed",
                           "reducer output is not a projection object with well-formed binding "
                           "objects (each requires string edge/concept/feature/relation)"))
        return _result(artifact, diags, None)
    if reduction.get("domain") != artifact.get("domain"):
        diags.append(_diag("conformance.reduction_incomplete",
                           f"reduction domain {reduction.get('domain')!r} != artifact domain "
                           f"{artifact.get('domain')!r}"))
    artifact_exec = {(r.get("id"), r.get("from"), r.get("to"), r.get("relation"))
                     for r in artifact.get("reductions", [])
                     if r.get("relation") in EXECUTABLE_RELATIONS}
    binding_exec = [(b.get("edge"), b.get("concept"), b.get("feature"), b.get("relation"))
                    for b in reduction["bindings"]
                    if b.get("relation") in EXECUTABLE_RELATIONS]
    if len(binding_exec) != len(set(binding_exec)):
        diags.append(_diag("conformance.reduction_incomplete",
                           "the reduction contains duplicate executable bindings"))
    if set(binding_exec) != artifact_exec:
        missing = sorted(artifact_exec - set(binding_exec))
        extra = sorted(set(binding_exec) - artifact_exec)
        diags.append(_diag("conformance.reduction_incomplete",
                           f"executable bindings do not correspond exactly to the artifact's executable "
                           f"edges (missing {missing}, extra {extra})"))

    # (3) Registry cross-check against the GOVERNED registry, pinned to the
    # admitted artifact's semantic-profile version.
    artifact_spv = (artifact.get("intakeVersioning") or {}).get("semanticProfileVersion")
    registry = validate_registry(registry_path, artifact_spv, diags)
    if registry is not None:
        #  (3a) every declared l1_feature is a registered capability whose declared
        #       kind EQUALS the registry's authoritative category.
        for f in artifact.get("l1Features", []):
            name, kind = f.get("name"), f.get("kind")
            if name not in registry:
                diags.append(_diag("conformance.unregistered_capability",
                                   f"l1_feature '{name}' is not in the published capability registry"))
            elif registry[name] != kind:
                diags.append(_diag("conformance.category_mismatch",
                                   f"l1_feature '{name}' declares kind '{kind}' but the registry's "
                                   f"authoritative category is '{registry[name]}'"))
        #  (3b) every EXECUTABLE reduction endpoint resolves to a registered capability.
        for b in reduction["bindings"]:
            if b.get("relation") in EXECUTABLE_RELATIONS and b.get("feature") not in registry:
                diags.append(_diag("conformance.unregistered_capability",
                                   f"executable reduction '{b.get('edge')}' targets '{b.get('feature')}', "
                                   f"not a registered capability"))

    # (4) Parity (optional) — byte-identical to a reference reduction.
    if expect_reduction_path is not None:
        with open(expect_reduction_path, encoding="utf-8") as fh:
            expected = fh.read()
        if bindings_text != expected:
            diags.append(_diag("conformance.parity_mismatch",
                               "the reduction is not byte-identical to the expected reference"))

    return _result(artifact, diags, reduction)


REPORT_KIND = "neutrino.m7-reduction-conformance-report"


def _result(artifact, diags, reduction):
    """The deterministic machine-readable conformance report ( S3): a versioned
    verdict binding the admitted artifact identity/hash + its version axes to the
    reduced executable capabilities and any fail-closed diagnostics. Suitable for
    the S2 governance gate and the  final witness; byte-reproducible (sorted
    keys, deterministic diagnostic ordering)."""
    art = artifact if isinstance(artifact, dict) else {}
    diags = sorted(diags, key=lambda d: (CODES.index(d["code"]), d["message"]))
    # Defensive: consume only well-formed bindings, so a summary can never KeyError
    # on a malformed emitter even if a caller passes an unvalidated reduction.
    caps = sorted({b["feature"] for b in (reduction or {}).get("bindings", [])
                   if _well_formed_binding(b) and b["relation"] in EXECUTABLE_RELATIONS})
    iv = art.get("intakeVersioning")
    iv = iv if isinstance(iv, dict) else {}
    # The THREE  intake axes the  consumer pins are distinct from the
    # report's OWN contract version: `schemaVersion` versions this report;
    # `artifactSchemaVersion` is the admitted artifact's envelope axis (v3).
    return {
        "kind": REPORT_KIND,
        "schemaVersion": 1,
        "conformant": not diags,
        "domain": art.get("domain"),
        "artifactHash": art.get("domainSemanticsHash"),
        "artifactSchemaVersion": art.get("schemaVersion"),
        "semanticProfileVersion": iv.get("semanticProfileVersion"),
        "reductionSemanticsVersion": iv.get("reductionSemanticsVersion"),
        "reducedExecutableCapabilities": caps,
        "diagnostics": diags,
    }


# --------------------------------------------------------------------------- #
# Probe interface () — each probe tampers the committed reference conformance
# case in exactly the way that should trip ONE conformance code, runs the seam
# build-free (consuming the committed reduction), and asserts the fail-closed
# rejection. Mirrors the classify_m7_intake / target-node-registry probe pattern.
# --------------------------------------------------------------------------- #
import copy  # noqa: E402
import tempfile  # noqa: E402
sys.path.insert(0, os.path.join(_REPO, "scripts", "domain"))
import validate_l2_domain_semantics_v2 as v2  # noqa: E402  (re-hash tampered artifacts)

REF_FIXTURE = os.path.join(_REPO, "examples", "m7-intake", "core_document_escrow_external.l2v3.json")
REF_REDUCTION = os.path.join(_REPO, "examples", "m7-intake", "core_document_escrow_external.reduction.json")


def _t_not_admitted(inp):
    for pr in inp["artifact"]["provenance"]:
        pr.pop("standardVersion", None)  # executable edge loses versioned provenance
    inp["artifact"]["domainSemanticsHash"] = v2._hash_of(v2._canonical_body(inp["artifact"]))


def _t_reduction_incomplete(inp):
    inp["reduction"]["bindings"] = [b for b in inp["reduction"]["bindings"]
                                    if b["relation"] not in EXECUTABLE_RELATIONS]


def _t_malformed_binding(inp):
    inp["reduction"]["bindings"] = [{"relation": "expands"}]  # missing required fields


def _t_non_object(inp):
    inp["reduction"] = []  # a JSON array, not a projection object


def _t_stale_registry(inp):
    inp["registry"]["semanticProfileVersion"] = 999


def _t_duplicate_id(inp):
    inp["registry"]["capabilities"].append(dict(inp["registry"]["capabilities"][0]))


def _t_unregistered(inp):
    inp["registry"]["capabilities"] = [c for c in inp["registry"]["capabilities"]
                                       if c["id"] != "effect:debit"]


def _t_category_mismatch(inp):
    for c in inp["registry"]["capabilities"]:
        if c["id"] == "effect:debit":
            c["category"] = "obligation"


def _t_parity_mismatch(inp):
    inp["expect"] = {"bindings": [], "domain": "coordinate.core_document_escrow"}


PROBES = {
    "not-admitted": ("conformance.not_admitted", _t_not_admitted),
    "reduction-incomplete": ("conformance.reduction_incomplete", _t_reduction_incomplete),
    "malformed-binding": ("conformance.malformed", _t_malformed_binding),
    "non-object-reduction": ("conformance.malformed", _t_non_object),
    "stale-registry": ("conformance.stale_registry", _t_stale_registry),
    "duplicate-id": ("conformance.malformed", _t_duplicate_id),
    "unregistered-capability": ("conformance.unregistered_capability", _t_unregistered),
    "category-mismatch": ("conformance.category_mismatch", _t_category_mismatch),
    "parity-mismatch": ("conformance.parity_mismatch", _t_parity_mismatch),
}


def run_probe(name):
    """Repo tamper-probe convention (): exit NONZERO + print
    probe-failed-as-expected:<name> when the tamper is caught fail-closed; exit 0
    (so the meta-gate flags a broken probe) if it slips through."""
    expect_code, mutate = PROBES[name]
    inp = {"artifact": json.load(open(REF_FIXTURE, encoding="utf-8")),
           "reduction": json.load(open(REF_REDUCTION, encoding="utf-8")),
           "registry": json.load(open(DEFAULT_REGISTRY, encoding="utf-8")),
           "expect": None}
    mutate(inp)
    with tempfile.TemporaryDirectory(prefix="m7-conformance-probe.") as td:
        ap = os.path.join(td, "artifact.json")
        rp = os.path.join(td, "reduction.json")
        gp = os.path.join(td, "registry.json")
        json.dump(inp["artifact"], open(ap, "w"))
        json.dump(inp["reduction"], open(rp, "w"))
        json.dump(inp["registry"], open(gp, "w"))
        ep = None
        if inp["expect"] is not None:
            ep = os.path.join(td, "expect.json")
            open(ep, "w").write(json.dumps(inp["expect"], indent=2, sort_keys=True))
        try:
            report = conform(ap, gp, intake.DEFAULT_PROFILE, reduction_path=rp,
                             expect_reduction_path=ep)
        except Exception as ex:  # noqa: BLE001  a probe must never crash the seam
            print(f"probe {name} crashed instead of failing closed: {ex}")
            return 0
    codes = {d["code"] for d in report["diagnostics"]}
    if report["conformant"] or expect_code not in codes:
        print(f"probe {name} unexpectedly passed: conformant={report['conformant']} codes={sorted(codes)}")
        return 0
    print(f"probe-failed-as-expected:{name}")
    return 1


def main():
    ap = argparse.ArgumentParser(description="M7 external-artifact reduction conformance ( S2/S3).")
    ap.add_argument("--artifact")
    ap.add_argument("--reduce-against")
    ap.add_argument("--neutrino-emit")
    ap.add_argument("--reduction", help="a committed reduction (bindings) to consume "
                                        "instead of running the reducer (build-free)")
    ap.add_argument("--registry", default=DEFAULT_REGISTRY)
    ap.add_argument("--profile", default=intake.DEFAULT_PROFILE)
    ap.add_argument("--expect-reduction")
    ap.add_argument("--probe", choices=sorted(PROBES))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.probe:
        return run_probe(args.probe)
    if not args.artifact or not (args.reduction or (args.reduce_against and args.neutrino_emit)):
        print("--artifact plus either --reduction or (--reduce-against and --neutrino-emit) "
              "are required", file=sys.stderr)
        return 2
    try:
        result = conform(args.artifact, args.registry, args.profile,
                         neutrino_emit=args.neutrino_emit,
                         reduce_against_path=args.reduce_against,
                         reduction_path=args.reduction,
                         expect_reduction_path=args.expect_reduction)
    except (ValueError, OSError, json.JSONDecodeError) as ex:
        # Fail closed through the SAME versioned report envelope (null identity/
        # version fields), so a machine consumer can schema-negotiate on the
        # fail-closed path exactly as on the happy path.
        result = _result(None, [_diag("conformance.malformed", str(ex))], None)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["conformant"] else 1


def selftest():
    # Structural self-check: the CODES tuple is closed, the committed registry
    # validates as the governed contract at its own semantic-profile version, and
    # a version-drifted registry is refused. The end-to-end positive + tamper
    # witnesses live in the lit test (they need the built neutrino-emit).
    fails = []
    if len(set(CODES)) != len(CODES):
        fails.append("CODES are not unique")
    try:
        spv = json.load(open(DEFAULT_REGISTRY, encoding="utf-8")).get("semanticProfileVersion")
    except (OSError, json.JSONDecodeError) as e:
        spv = None
        fails.append(f"registry unreadable: {e}")
    good = []
    if validate_registry(DEFAULT_REGISTRY, spv, good) is None or good:
        fails.append(f"committed registry does not validate: {good}")
    drift = []
    if validate_registry(DEFAULT_REGISTRY, (spv or 0) + 1, drift) is not None \
            or not any(d["code"] == "conformance.stale_registry" for d in drift):
        fails.append("a version-drifted registry was not refused with conformance.stale_registry")
    if fails:
        for f in fails:
            print(f"[conformance.selftest] {f}", file=sys.stderr)
        return 1
    print(f"ok (selftest): governed registry validates + drift refused; {len(CODES)} closed codes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
