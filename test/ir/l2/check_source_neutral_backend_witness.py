#!/usr/bin/env python3
""" S1 external source-neutral governed-backend witness.

This driver composes existing authorities; it introduces no semantic model:

  v3 artifact -> M7 admission -> registered capabilities ->  reduction
  -> CoordinationPlan -> every mechanically discovered governed backend

The rendered Solidity and SQL bytes are intentionally not compared. The
core-owned reference trace remains independently executable, while governed
backend equivalence is reported separately and cannot complete until verified
packages cover the mechanically discovered denominator. The  authority
gate must hold at hard zero.
"""

from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
GATES = os.path.join(REPO, "scripts", "gates")
DOMAIN = os.path.join(REPO, "scripts", "domain")
sys.path[:0] = [GATES, DOMAIN]

import check_m7_reduction_conformance as conformance  # noqa: E402
import check_semantic_authority as authority  # noqa: E402
import classify_m7_intake as intake  # noqa: E402
import validate_l2_domain_semantics_v2 as l2v2  # noqa: E402

ARTIFACT = os.path.join(
    REPO, "examples", "m7-intake",
    "source_neutral_settlement_release.l2v3.json")
SPEC = os.path.join(
    REPO, "test", "ir", "samples", "Inputs", "core_document_escrow", "generated",
    "capability-spec", "capability-spec.json")
SOURCE = os.path.join(
    REPO, "test", "ir", "samples", "Inputs", "core_document_escrow", "source",
    "core_document_escrow.neu")
SCENARIO = os.path.join(
    REPO, "test", "ir", "samples", "Inputs", "core_document_escrow", "scenario",
    "core_document_escrow_happy_path.json")
REGISTRY = os.path.join(REPO, "docs", "semantic-capability-registry.json")
PROFILE = os.path.join(REPO, "docs", "m7-intake-profile.json")

PRODUCTION_ROOTS = ("include", "lib", "tools")
PRODUCTION_SUFFIXES = (".c", ".cc", ".cpp", ".h", ".hh", ".hpp", ".inc", ".td")
PROBES = (
    "unsupported-semantics",
    "concept-id-dispatch",
    "direct-l2-backend-read",
    "omitted-governed-backend",
    "backend-equivalence-denominator",
)


class WitnessError(RuntimeError):
    pass


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _run(argv, *, env=None):
    result = subprocess.run(
        argv, cwd=REPO, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise WitnessError(f"{' '.join(argv)} failed ({result.returncode}): {detail}")
    return result


def _governed_rows():
    return sorted(
        authority.governed_backends(authority.SourceTree()),
        key=lambda row: row["target"])


def _assert_backend_coverage(governed, rendered):
    expected = set(governed)
    actual = set(rendered)
    if not expected or actual != expected:
        raise WitnessError(
            f"governed backend coverage drift: expected={sorted(expected)} "
            f"rendered={sorted(actual)}")


def _expanded_identity_spellings(spellings):
    expanded = {spelling for spelling in spellings if spelling}
    for spelling in spellings:
        if not spelling:
            continue
        words = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[0-9]+", spelling)
        if words:
            expanded.add("_".join(word.lower() for word in words))
    return expanded


def _identity_spellings(artifact):
    external = {
        artifact["domain"],
        artifact["implements"],
        *(concept["name"] for concept in artifact["concepts"]),
        *(reduction[field]
          for reduction in artifact["reductions"]
          for field in ("id", "from", "to")),
        *(failure[field]
          for failure in artifact["failureModes"]
          for field in ("name", "compensation")),
        *(invariant[field]
          for invariant in artifact["invariants"]
          for field in ("name", "onFailure")),
        *(entry["subject"] for entry in artifact["provenance"]),
    }
    registered = {
        artifact["implements"],
        *(feature["name"] for feature in artifact["l1Features"]),
    }
    # Registered L1 capabilities are deliberately shared vocabulary.  Every
    # other identity is owned by the external artifact and must remain absent
    # from backend/reducer/legalizer/printer production code.
    return sorted(
        _expanded_identity_spellings(external)
        - _expanded_identity_spellings(registered))


def _concept_code_hits(artifact, sources):
    forbidden = _identity_spellings(artifact)
    hits = []
    for path, text in sources:
        for token in forbidden:
            if token in text:
                hits.append(f"{path} contains {token!r}")
    return hits


def _prove_no_concept_code(artifact):
    sources = []
    scanned = 0
    for root in PRODUCTION_ROOTS:
        for path in sorted(glob.glob(os.path.join(REPO, root, "**"), recursive=True)):
            if not os.path.isfile(path) or not path.endswith(PRODUCTION_SUFFIXES):
                continue
            scanned += 1
            text = open(path, encoding="utf-8", errors="replace").read()
            sources.append((os.path.relpath(path, REPO), text))
    if scanned == 0:
        raise WitnessError("concept-neutrality scan discovered no production sources")
    hits = _concept_code_hits(artifact, sources)
    if hits:
        raise WitnessError(
            "external concept leaked into C++/TableGen/reducer/legalizer/printer: "
            + "; ".join(hits))
    return scanned


def _unsupported_semantics_probe(artifact):
    bad = copy.deepcopy(artifact)
    for feature in bad["l1Features"]:
        if feature["name"] == "effect:credit":
            feature["name"] = "effect:teleport"
    for reduction in bad["reductions"]:
        if reduction["to"] == "effect:credit":
            reduction["to"] = "effect:teleport"
    bad["domainSemanticsHash"] = l2v2._hash_of(l2v2._canonical_body(bad))
    profile = intake.load_profile(PROFILE)
    vocabulary, spv = intake.resolve_profile_vocabulary(profile)
    report = intake.classify(bad, profile, vocabulary, spv)
    codes = {diag["code"] for diag in report["diagnostics"]}
    if report["admitted"] or "intake.unregistered_capability" not in codes:
        raise WitnessError(
            "unsupported semantic capability escaped M7 admission")


def _concept_dispatch_probe(artifact):
    findings = authority.scan_cpp(
        "lib/backends/probe/ConceptDispatch.cpp",
        'void probe(const char *conceptId) { '
        'if (conceptId == "SourceNeutralSettlementRelease") return; }\n')
    if not any(
            item["authorityClass"] == "domain-concept-dispatch"
            for item in findings):
        raise WitnessError("concept-ID dispatch mutation escaped authority discovery")

    planted = (
        ("reduction-id", "reductions", "id", "ProbeReductionIdentity"),
        ("failure-name", "failureModes", "name", "ProbeFailureIdentity"),
        ("failure-compensation", "failureModes", "compensation",
         "ProbeCompensationIdentity"),
        ("invariant-name", "invariants", "name", "ProbeInvariantIdentity"),
        ("invariant-failure", "invariants", "onFailure",
         "ProbeInvariantFailureIdentity"),
        ("provenance-subject", "provenance", "subject",
         "ProbeProvenanceIdentity"),
    )
    for family, collection, field, identity in planted:
        mutated = copy.deepcopy(artifact)
        mutated[collection][0][field] = identity
        path = f"lib/backends/probe/{family}.cpp"
        hits = _concept_code_hits(
            mutated,
            [(path, f'if (semanticId == "{identity}") return;\n')])
        if not any(identity in hit for hit in hits):
            raise WitnessError(
                f"{family} identity mutation escaped production-source "
                "concept-neutrality scan")


def _direct_read_probe():
    findings = authority.scan_cpp(
        "lib/backends/probe/DirectRead.cpp",
        'void probe(const CoordinationPlan &plan, '
        'const L2DomainArtifact &sidecar) { '
        '(void)plan.effects; (void)sidecar; }\n')
    classes = {item["authorityClass"] for item in findings}
    if not {"direct-plan-read", "source-or-l2-read"} <= classes:
        raise WitnessError(
            "direct L2/backend carrier mutation escaped authority discovery")


def _omitted_backend_probe():
    governed = [row["target"] for row in _governed_rows()]
    try:
        _assert_backend_coverage(governed, governed[:-1])
    except WitnessError:
        return
    raise WitnessError("omitted governed backend mutation passed")


def _assert_backend_equivalence(governed, backend_equivalence):
    expected = sorted(set(governed))
    required = backend_equivalence.get("requiredBackends")
    compared = backend_equivalence.get("comparedBackends")
    status = backend_equivalence.get("status")
    if not expected or required != expected:
        raise WitnessError(
            "backend-equivalence required denominator does not match "
            "governedBackends")
    if not isinstance(compared, list) or compared != sorted(set(compared)):
        raise WitnessError(
            "backend-equivalence compared identities are not a unique "
            "deterministic set")
    if not set(compared) <= set(expected):
        raise WitnessError(
            "backend-equivalence compared identities are outside the "
            "governed denominator")
    if status == "complete":
        if compared != expected:
            raise WitnessError(
                "completed backend equivalence does not cover exactly the "
                "governed denominator")
        return
    if status == "pending" and compared != expected:
        return
    raise WitnessError(
        "backend-equivalence status is inconsistent with compared identities")


def _backend_equivalence_denominator_probe():
    governed = [row["target"] for row in _governed_rows()]
    valid = {
        "status": "complete",
        "requiredBackends": governed,
        "comparedBackends": governed,
    }
    _assert_backend_equivalence(governed, valid)
    mutations = []
    for compared in ([], governed[:-1]):
        bad = copy.deepcopy(valid)
        bad["comparedBackends"] = compared
        mutations.append(bad)
    escaped = []
    for index, bad in enumerate(mutations):
        try:
            _assert_backend_equivalence(governed, bad)
        except WitnessError:
            continue
        escaped.append(index)
    if escaped:
        raise WitnessError(
            "completed backend equivalence accepted an empty/mismatched "
            "compared set")


def selftest():
    artifact = _load(ARTIFACT)
    probes = {
        "unsupported-semantics": lambda: _unsupported_semantics_probe(artifact),
        "concept-id-dispatch": lambda: _concept_dispatch_probe(artifact),
        "direct-l2-backend-read": _direct_read_probe,
        "omitted-governed-backend": _omitted_backend_probe,
        "backend-equivalence-denominator":
            _backend_equivalence_denominator_probe,
    }
    if set(probes) != set(PROBES):
        raise WitnessError("probe registry drift")
    for name in PROBES:
        probes[name]()
        print(f"[PASS] {name}")
    print(f"SELFTEST: PASS ({len(PROBES)} biting mutations)")


def _assert_source_spec_identity(neutrino_gen, work):
    generated = os.path.join(work, "source-spec")
    _run([
        neutrino_gen, "--target=capability-spec", SOURCE, "-o", generated])
    regenerated = os.path.join(generated, "capability-spec.json")
    if open(regenerated, "rb").read() != open(SPEC, "rb").read():
        raise WitnessError(
            "source capability-spec does not byte-match the external coordination-plan input")


def _render_backends(neutrino_gen, rows, work):
    rendered = {}
    for row in rows:
        name = row["target"]
        out = os.path.join(work, "rendered", name)
        _run([
            neutrino_gen, f"--target={name}", "--from-spec",
            "--profile", os.path.join(REPO, row["profile"]),
            SPEC, "-o", out])
        artifacts = sorted(
            path for path in glob.glob(os.path.join(out, "**"), recursive=True)
            if os.path.isfile(path)
            and os.path.basename(path) not in {"manifest.json", "diagnostics.json"})
        if not artifacts:
            raise WitnessError(f"{name} render emitted no production artifact")
        rendered[name] = [
            os.path.relpath(path, out).replace(os.sep, "/") for path in artifacts]
    _assert_backend_coverage(
        [row["target"] for row in rows], rendered)
    return rendered


def _core_reference_trace(neutrino_equiv, work):
    report_dir = os.path.join(work, "equivalence")
    env = dict(os.environ)
    env["PATH"] = "/nonexistent"
    _run([
        neutrino_equiv, f"--scenario={SCENARIO}", SOURCE,
        f"--report={report_dir}", "--reference-only"], env=env)
    report = _load(os.path.join(report_dir, "equivalence.json"))
    trace = report.get("traceEquivalence") or {}
    if (report.get("mode") != "reference-only"
            or trace.get("backends") != []
            or not trace.get("ok")
            or trace.get("executedCases", 0) < 1
            or trace.get("observationCount", 0) < 1):
        raise WitnessError(
            "normalized trace/effect equivalence was vacuous or divergent")
    return {
        "mode": "reference-only",
        "executedCases": trace["executedCases"],
        "observationCount": trace["observationCount"],
    }


def live(neutrino_gen, neutrino_emit, neutrino_equiv, output):
    artifact = _load(ARTIFACT)
    rows = _governed_rows()
    governed = [row["target"] for row in rows]
    with tempfile.TemporaryDirectory(prefix="neutrino-662-s1.") as work:
        authority_path = os.path.join(work, "semantic-authority.json")
        _run([
            sys.executable,
            os.path.join(GATES, "check_semantic_authority.py"),
            "--output", authority_path])
        authority_report = _load(authority_path)
        if (authority_report.get("mode") != "enforce"
                or authority_report.get("governedBackends") != governed):
            raise WitnessError(
                "semantic-authority enforcement must share the governed "
                "backend denominator")

        reduction = conformance.conform(
            ARTIFACT, REGISTRY, PROFILE, neutrino_emit=neutrino_emit,
            reduce_against_path=SPEC)
        if not reduction["conformant"]:
            raise WitnessError(
                f"external intake/reduction failed: {reduction['diagnostics']}")
        if set(reduction["reducedExecutableCapabilities"]) != {
                "effect:credit", "effect:debit"}:
            raise WitnessError("external reduction capability set drift")

        _assert_source_spec_identity(neutrino_gen, work)
        plan_out = os.path.join(work, "coordination-plan")
        _run([
            neutrino_gen, "--target=coordination-plan", "--from-spec",
            SPEC, "-o", plan_out])
        coordination_plan = _load(os.path.join(plan_out, "coordination-plan.json"))
        projection = _load(os.path.join(plan_out, "backend-projection.json"))
        if not coordination_plan or not projection:
            raise WitnessError("external reduction did not reach a non-empty CoordinationPlan")

        rendered = _render_backends(neutrino_gen, rows, work)
        core_reference = _core_reference_trace(neutrino_equiv, work)
        backend_equivalence = {
            "status": "pending",
            "requiredBackends": governed,
            "comparedBackends": [],
        }
        _assert_backend_equivalence(governed, backend_equivalence)
        scanned = _prove_no_concept_code(artifact)

        report = {
            "kind": "neutrino.source-neutral-backend-witness",
            "schemaVersion": 2,
            "artifact": os.path.relpath(ARTIFACT, REPO),
            "artifactHash": artifact["domainSemanticsHash"],
            "capabilities": reduction["reducedExecutableCapabilities"],
            "coordinationPlan": {
                "procedure": coordination_plan.get("procedure"),
                "projectionSchemaVersion": projection.get("schemaVersion"),
            },
            "governedBackends": governed,
            "renderedArtifacts": rendered,
            "coreReferenceTrace": core_reference,
            "backendEquivalence": backend_equivalence,
            "conceptSpecificProductionMatches": 0,
            "productionSourcesScanned": scanned,
            "semanticAuthorityMode": authority_report["mode"],
        }
        text = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if output:
            with open(output, "w", encoding="utf-8") as handle:
                handle.write(text)
        else:
            sys.stdout.write(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--neutrino-gen")
    parser.add_argument("--neutrino-emit")
    parser.add_argument("--neutrino-equiv")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        if args.selftest:
            selftest()
            return 0
        if not all((args.neutrino_gen, args.neutrino_emit, args.neutrino_equiv)):
            parser.error(
                "--neutrino-gen, --neutrino-emit and --neutrino-equiv are required")
        live(
            os.path.abspath(args.neutrino_gen),
            os.path.abspath(args.neutrino_emit),
            os.path.abspath(args.neutrino_equiv),
            args.output)
        return 0
    except (OSError, ValueError, WitnessError) as error:
        print(f"source-neutral-backend-witness: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
