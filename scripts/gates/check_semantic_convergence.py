#!/usr/bin/env python3
"""Run the mandatory backend semantic-convergence sub-gate.

This scoped enforcement combines the semantic-authority inventory and the
source-neutral governed-backend witness. It is necessary anti-reinference
evidence, not the terminal M7-entry verdict: recipe-candidate zero, package
separation, and terminal integration evidence are governed separately.
"""

import argparse
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VALIDATORS = os.path.join(REPO, "scripts", "validators")
sys.path.insert(0, VALIDATORS)

import verify_domain_pack as schema_validator  # noqa: E402

AUTHORITY = "scripts/gates/check_semantic_authority.py"
WITNESS = "test/ir/l2/check_source_neutral_backend_witness.py"
REPORT_SCHEMA = "docs/schemas/semantic-convergence-report.schema.json"
AUTHORITY_SCHEMA = "docs/schemas/semantic-authority-report.schema.json"
WITNESS_SCHEMA = (
    "docs/schemas/source-neutral-backend-witness-report.schema.json")
TRANSITION_PROBE = "hard-zero-enforcement"
SCHEMA_PROBE = "malformed-report-schema"


class ConvergenceError(RuntimeError):
    pass


def _load_module(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(REPO, rel))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(check_id, argv):
    result = subprocess.run(
        argv, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return {
        "id": check_id,
        "status": "pass" if result.returncode == 0 else "fail",
    }


def _load_json(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _hard_zero(report):
    if not report or report.get("mode") != "enforce":
        return False
    return all(
        not findings
        for backend in report.get("backends", {}).values()
        for findings in backend.get("findings", {}).values())


def _backend_equivalence_complete(report, governed):
    if not report:
        return False
    backend_equivalence = report.get("backendEquivalence") or {}
    required = backend_equivalence.get("requiredBackends")
    compared = backend_equivalence.get("comparedBackends")
    return (
        backend_equivalence.get("status") == "complete"
        and required == governed
        and compared == governed
        and bool(governed)
    )


def _validate_instance(instance, schema_rel, label):
    schema = _load_json(os.path.join(REPO, schema_rel))
    if schema is None:
        raise ConvergenceError(f"committed schema is missing: {schema_rel}")
    diagnostics = []
    schema_validator._validate(
        instance, schema, label, diagnostics, schema)
    if diagnostics:
        raise ConvergenceError(
            f"{label} violates {schema_rel}: {diagnostics[0]}")


def _validate_report(report):
    _validate_instance(report, REPORT_SCHEMA, "semanticConvergence")
    authority_report = report["semanticAuthority"]
    witness_report = report["sourceNeutralWitness"]
    if authority_report is not None:
        _validate_instance(
            authority_report, AUTHORITY_SCHEMA,
            "semanticConvergence.semanticAuthority")
    if witness_report is not None:
        _validate_instance(
            witness_report, WITNESS_SCHEMA,
            "semanticConvergence.sourceNeutralWitness")

    governed = report["governedBackends"]
    if (authority_report is not None
            and authority_report["governedBackends"] != governed):
        raise ConvergenceError("semantic-authority backend denominator drift")
    if (witness_report is not None
            and witness_report["governedBackends"] != governed):
        raise ConvergenceError("source-neutral witness backend denominator drift")
    if witness_report is not None:
        backend_equivalence = witness_report["backendEquivalence"]
        if backend_equivalence["requiredBackends"] != governed:
            raise ConvergenceError(
                "backend-equivalence required denominator drift")
        compared = backend_equivalence["comparedBackends"]
        if (backend_equivalence["status"] == "complete"
                and compared != governed):
            raise ConvergenceError(
                "completed backend equivalence does not cover the governed "
                "denominator")
        if not set(compared) <= set(governed):
            raise ConvergenceError(
                "backend-equivalence compared identities are outside the "
                "governed denominator")
        if (backend_equivalence["status"] == "pending"
                and compared == governed):
            raise ConvergenceError(
                "pending backend equivalence already covers the governed "
                "denominator")
    check_ids = [item["id"] for item in report["representativeSuite"]]
    if len(check_ids) != len(set(check_ids)):
        raise ConvergenceError(
            "representative suite contains duplicate checks")
    passed = (
        bool(governed)
        and _hard_zero(authority_report)
        and witness_report is not None
        and _backend_equivalence_complete(witness_report, governed)
        and all(item["status"] == "pass"
                for item in report["representativeSuite"])
    )
    expected_verdict = "pass" if passed else "fail"
    if report["scopeVerdict"] != expected_verdict:
        raise ConvergenceError(
            f"semantic-convergence scope verdict is "
            f"{report['scopeVerdict']!r}, "
            f"expected {expected_verdict!r}")


def _transition_probe():
    authority = _load_module("_semantic_convergence_authority", AUTHORITY)
    base = authority.SourceTree()
    rel = "lib/backends/solidity/EnforcementTransition.cpp"
    overlay = {
        rel: (
            "void evade(const BackendProjectionGraph &graph) { "
            "if (graph.executionMode == ExecutionMode::Temporal) return; }\n")
    }
    report = authority.build_report(authority.SourceTree(overlay))
    matches = [
        finding
        for backend in report["backends"].values()
        for finding in backend["findings"].get("backend-semantic-branch", [])
        if finding["path"] == rel and "executionMode" in finding["evidence"]
    ]
    if matches and not _hard_zero(report):
        print(f"probe-failed-as-expected:{TRANSITION_PROBE}")
        return 1
    print(f"probe unexpectedly passed:{TRANSITION_PROBE}")
    return 0


def _valid_probe_report():
    governed = ["solidity"]
    return {
        "kind": "neutrino.semantic-convergence-report",
        "schemaVersion": 1,
        "reportSchema": REPORT_SCHEMA,
        "scopeVerdict": "pass",
        "governedBackends": governed,
        "semanticAuthority": {
            "kind": "neutrino.semantic-authority-report",
            "schemaVersion": 1,
            "mode": "enforce",
            "governedBackends": governed,
            "carveoutRegistry":
                "docs/security-primitive-carveout-registry.json",
            "backends": {
                "solidity": {
                    "profile":
                        "examples/target-profiles/solidity.target-profile.json",
                    "surfaces": [],
                    "findings": {},
                }
            },
        },
        "sourceNeutralWitness": {
            "kind": "neutrino.source-neutral-backend-witness",
            "schemaVersion": 2,
            "artifact": "probe.l2v3.json",
            "artifactHash": "0" * 64,
            "capabilities": ["effect:credit"],
            "coordinationPlan": {
                "procedure": "probe",
                "projectionSchemaVersion": 5,
            },
            "governedBackends": governed,
            "renderedArtifacts": {"solidity": ["src/Probe.sol"]},
            "coreReferenceTrace": {
                "mode": "reference-only",
                "executedCases": 1,
                "observationCount": 1,
            },
            "backendEquivalence": {
                "status": "complete",
                "requiredBackends": governed,
                "comparedBackends": governed,
            },
            "conceptSpecificProductionMatches": 0,
            "productionSourcesScanned": 1,
            "semanticAuthorityMode": "enforce",
        },
        "representativeSuite": [{"id": "probe", "status": "pass"}],
    }


def _schema_probe():
    valid = _valid_probe_report()
    _validate_report(valid)
    mutations = []

    bad = copy.deepcopy(valid)
    bad["governedBackends"] = "not-an-array"
    mutations.append(("governed-backends-type", bad))

    bad = copy.deepcopy(valid)
    bad["semanticAuthority"] = None
    mutations.append(("missing-pass-authority", bad))

    bad = copy.deepcopy(valid)
    bad["semanticAuthority"]["backends"]["solidity"]["unexpected"] = True
    mutations.append(("malformed-authority-child", bad))

    bad = copy.deepcopy(valid)
    bad["sourceNeutralWitness"]["coreReferenceTrace"][
        "observationCount"] = "one"
    mutations.append(("malformed-witness-child", bad))

    bad = copy.deepcopy(valid)
    bad["sourceNeutralWitness"]["backendEquivalence"][
        "comparedBackends"] = []
    mutations.append(("empty-completed-backend-equivalence", bad))

    bad = copy.deepcopy(valid)
    bad["sourceNeutralWitness"]["backendEquivalence"][
        "comparedBackends"] = ["postgres"]
    mutations.append(("mismatched-completed-backend-equivalence", bad))

    bad = copy.deepcopy(valid)
    bad["sourceNeutralWitness"]["backendEquivalence"].update(
        status="pending", comparedBackends=[])
    mutations.append(("pending-backend-equivalence-claimed-pass", bad))

    bad = copy.deepcopy(valid)
    bad["representativeSuite"][0].update(
        status="invalid", unexpected=True)
    mutations.append(("malformed-suite-row", bad))

    escaped = []
    for name, report in mutations:
        try:
            _validate_report(report)
        except ConvergenceError:
            continue
        escaped.append(name)
    if not escaped:
        print(f"probe-failed-as-expected:{SCHEMA_PROBE}")
        return 1
    print(
        f"probe unexpectedly passed:{SCHEMA_PROBE}: {', '.join(escaped)}")
    return 0


def selftest():
    checks = [
        _run("semantic-authority-probes", [
            sys.executable, os.path.join(REPO, AUTHORITY), "--selftest"]),
        _run("source-neutral-witness-probes", [
            sys.executable, os.path.join(REPO, WITNESS), "--selftest"]),
    ]
    transition_bites = _transition_probe() == 1
    checks.append({
        "id": TRANSITION_PROBE,
        "status": "pass" if transition_bites else "fail",
    })
    schema_bites = _schema_probe() == 1
    checks.append({
        "id": SCHEMA_PROBE,
        "status": "pass" if schema_bites else "fail",
    })
    for check in checks:
        print(f"  [{'PASS' if check['status'] == 'pass' else 'FAIL'}] "
              f"{check['id']}")
    ok = all(check["status"] == "pass" for check in checks)
    print(f"SELFTEST: {'PASS' if ok else 'FAIL'} ({len(checks)} checks)")
    return 0 if ok else 1


def live(neutrino_gen, neutrino_emit, neutrino_equiv, output):
    with tempfile.TemporaryDirectory(
            prefix="neutrino-semantic-convergence.") as work:
        authority_path = os.path.join(work, "semantic-authority.json")
        witness_path = os.path.join(work, "source-neutral-witness.json")
        suite = [
            _run("semantic-authority-zero", [
                sys.executable, os.path.join(REPO, AUTHORITY),
                "--output", authority_path]),
            _run("semantic-authority-probes", [
                sys.executable, os.path.join(REPO, AUTHORITY), "--selftest"]),
            _run("source-neutral-witness", [
                sys.executable, os.path.join(REPO, WITNESS),
                "--neutrino-gen", neutrino_gen,
                "--neutrino-emit", neutrino_emit,
                "--neutrino-equiv", neutrino_equiv,
                "--output", witness_path]),
            _run("source-neutral-witness-probes", [
                sys.executable, os.path.join(REPO, WITNESS), "--selftest"]),
            _run("backend-convergence-probes", [
                sys.executable,
                os.path.join(REPO, "scripts/gates/check_backend_convergence.py"),
                "--selftest"]),
            _run("m7-intake-bijection-probes", [
                sys.executable,
                os.path.join(REPO, "scripts/gates/check_m7_intake_bijection.py"),
                "--selftest"]),
            _run("security-primitive-carveout", [
                sys.executable,
                os.path.join(
                    REPO, "scripts/gates/check_security_primitive_carveout.py")]),
            _run("security-primitive-carveout-probes", [
                sys.executable,
                os.path.join(
                    REPO, "scripts/gates/check_security_primitive_carveout.py"),
                "--selftest"]),
        ]
        authority_report = _load_json(authority_path)
        witness_report = _load_json(witness_path)
        governed = (
            authority_report.get("governedBackends", [])
            if authority_report else [])
        passed = (
            _hard_zero(authority_report)
            and witness_report is not None
            and witness_report.get("governedBackends") == governed
            and _backend_equivalence_complete(witness_report, governed)
            and all(check["status"] == "pass" for check in suite)
        )
        report = {
            "kind": "neutrino.semantic-convergence-report",
            "schemaVersion": 1,
            "reportSchema": REPORT_SCHEMA,
            "scopeVerdict": "pass" if passed else "fail",
            "governedBackends": governed,
            "semanticAuthority": authority_report,
            "sourceNeutralWitness": witness_report,
            "representativeSuite": suite,
        }
        _validate_report(report)
        payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if output:
            os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
            with open(output, "w", encoding="utf-8") as handle:
                handle.write(payload)
        else:
            sys.stdout.write(payload)
        if not passed:
            failed = [check["id"] for check in suite
                      if check["status"] != "pass"]
            print(
                "semantic-convergence: scoped semantic/security gate failed"
                + (f" ({', '.join(failed)})" if failed else ""),
                file=sys.stderr)
            return 1
        return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument(
        "--probe", choices=(TRANSITION_PROBE, SCHEMA_PROBE))
    parser.add_argument("--neutrino-gen")
    parser.add_argument("--neutrino-emit")
    parser.add_argument("--neutrino-equiv")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        if args.selftest:
            return selftest()
        if args.probe:
            return (
                _transition_probe()
                if args.probe == TRANSITION_PROBE else _schema_probe())
        if not all((args.neutrino_gen, args.neutrino_emit, args.neutrino_equiv)):
            parser.error(
                "--neutrino-gen, --neutrino-emit and --neutrino-equiv are "
                "required")
        return live(
            os.path.abspath(args.neutrino_gen),
            os.path.abspath(args.neutrino_emit),
            os.path.abspath(args.neutrino_equiv),
            args.output)
    except (OSError, ValueError, ConvergenceError) as error:
        print(f"semantic-convergence: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
