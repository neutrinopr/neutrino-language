#!/usr/bin/env python3
"""Validate the M6 pressure-loop register v2 contract ().

The schema is `docs/schemas/pressure-loop-register.schema.json`. This stdlib
validator mirrors the structural schema and enforces the semantic row contract
JSON Schema cannot express without adding a runtime dependency:

  - schemaVersion 2 only; v1 is retired and rejected;
  - accepted iff class is null;
  - unresolved iff class is 1/2/3 and failedVerifierObligation is present;
  - decision-required rows are Class 3 with counterexample + linked decision;
  - unsupported refusals are absent, unresolved, and carry refusal evidence;
  - present/partial support carries current artifact operation + executable
    evidence, and partial support has explicit absent sibling rows; and
  - L3_RUNTIME / DESCRIPTIVE_ONLY are orthogonal: accepted, class null, and no
    fabricated verifier design or current artifact.

Exit 0 ok / 1 validation failures / 2 usage or I/O.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

KIND = "neutrino.pressure-loop-register"
SCHEMA_VERSION = 2
OUTCOMES = {"accepted", "unresolved"}
CLASSES = {"1", "2", "3", None}
DISPOSITIONS = {
    "L1_CORE",
    "L2_REFINEMENT",
    "L3_RUNTIME",
    "DESCRIPTIVE_ONLY",
    "UNSUPPORTED_REFUSED",
    "LANGUAGE_DECISION_REQUIRED",
    "LAYER_DECISION_REQUIRED",
}
DECISION_DISPOSITIONS = {"LANGUAGE_DECISION_REQUIRED", "LAYER_DECISION_REQUIRED"}
ORTHOGONAL_DISPOSITIONS = {"L3_RUNTIME", "DESCRIPTIVE_ONLY"}
AUTHORITY_WEIGHT_TIERS = {"1", "2", "3"}
SUPPORT_STATUSES = {"present", "partial", "absent"}
EVIDENCE_REF_TYPES = {"executable", "refusal"}

ROOT_REQUIRED = {"kind", "schemaVersion", "rows"}
ROOT_ALLOWED = ROOT_REQUIRED
ROW_REQUIRED = {
    "rowId",
    "requirement",
    "provenance",
    "outcome",
    "class",
    "disposition",
    "failedVerifierObligation",
    "minimalCounterexample",
    "owner",
    "linkedDecision",
    "supportStatus",
    "currentArtifactOperation",
    "evidenceRefs",
}
ROW_ALLOWED = ROW_REQUIRED
PROVENANCE_REQUIRED = {"source", "authorityWeightTier"}
PROVENANCE_ALLOWED = PROVENANCE_REQUIRED
EVIDENCE_REF_REQUIRED = {"type", "ref"}
EVIDENCE_REF_ALLOWED = EVIDENCE_REF_REQUIRED
TAMPER_IDS = {
    "v1-retired",
    "accepted-class",
    "unresolved-obligation",
    "decision-class",
    "decision-counterexample",
    "unsupported-refused",
    "support-artifact",
    "partial-sibling",
    "orthogonal-artifact",
    "duplicate-row",
    "unknown-field",
}


def diag(code: str, message: str, *, path: str = "$", severity: str = "error") -> dict[str, str]:
    return {"code": code, "severity": severity, "path": path, "message": message}


def is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def check_object(value: Any, *, path: str, required: set[str], allowed: set[str], out: list[dict[str, str]]) -> bool:
    if not isinstance(value, dict):
        out.append(diag("pressure_loop.schema", "must be an object", path=path))
        return False
    for key in sorted(required - set(value)):
        out.append(diag("pressure_loop.missing_field", f"missing required field {key!r}", path=path))
    for key in sorted(set(value) - allowed):
        out.append(diag("pressure_loop.unknown_field", f"unknown field {key!r}", path=f"{path}.{key}"))
    return True


def check_nonempty(value: Any, *, path: str, out: list[dict[str, str]]) -> None:
    if not is_nonempty_string(value):
        out.append(diag("pressure_loop.schema", "must be a non-empty string", path=path))


def check_nullable_nonempty(value: Any, *, path: str, out: list[dict[str, str]]) -> None:
    if value is not None and not is_nonempty_string(value):
        out.append(diag("pressure_loop.schema", "must be null or a non-empty string", path=path))


def check_enum(value: Any, choices: set[Any], *, path: str, name: str, out: list[dict[str, str]]) -> None:
    try:
        valid = value in choices
    except TypeError:
        valid = False
    if not valid:
        printable = sorted(str(c) for c in choices)
        out.append(diag("pressure_loop.enum", f"{name} must be one of {printable}", path=path))


def has_evidence(row: dict[str, Any], evidence_type: str) -> bool:
    refs = row.get("evidenceRefs")
    return isinstance(refs, list) and any(isinstance(r, dict) and r.get("type") == evidence_type for r in refs)


def validate_obj(obj: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not check_object(obj, path="$", required=ROOT_REQUIRED, allowed=ROOT_ALLOWED, out=out):
        return out
    if obj.get("kind") != KIND:
        out.append(diag("pressure_loop.kind", f"kind must be {KIND!r}", path="$.kind"))
    schema_version = obj.get("schemaVersion")
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        out.append(diag("pressure_loop.schema_version", "schemaVersion must be 2; v1 registers are retired", path="$.schemaVersion"))

    rows = obj.get("rows")
    if not isinstance(rows, list):
        out.append(diag("pressure_loop.schema", "rows must be an array", path="$.rows"))
        return out
    if not rows:
        out.append(diag("pressure_loop.schema", "rows must contain at least one register row", path="$.rows"))
        return out

    seen: dict[str, int] = {}
    absent_by_requirement: dict[str, list[int]] = {}
    for idx, row in enumerate(rows):
        if isinstance(row, dict) and row.get("supportStatus") == "absent" and is_nonempty_string(row.get("requirement")):
            absent_by_requirement.setdefault(row["requirement"], []).append(idx)

    for idx, row in enumerate(rows):
        path = f"$.rows[{idx}]"
        if not check_object(row, path=path, required=ROW_REQUIRED, allowed=ROW_ALLOWED, out=out):
            continue

        row_id = row.get("rowId")
        check_nonempty(row_id, path=f"{path}.rowId", out=out)
        if is_nonempty_string(row_id):
            if row_id in seen:
                out.append(diag("pressure_loop.duplicate_row", f"duplicate rowId {row_id!r}; first seen at $.rows[{seen[row_id]}]", path=f"{path}.rowId"))
            else:
                seen[row_id] = idx
        requirement = row.get("requirement")
        check_nonempty(requirement, path=f"{path}.requirement", out=out)
        check_nonempty(row.get("owner"), path=f"{path}.owner", out=out)
        check_enum(row.get("outcome"), OUTCOMES, path=f"{path}.outcome", name="outcome", out=out)
        check_enum(row.get("class"), CLASSES, path=f"{path}.class", name="class", out=out)
        disposition = row.get("disposition")
        check_enum(disposition, DISPOSITIONS, path=f"{path}.disposition", name="disposition", out=out)
        support = row.get("supportStatus")
        check_enum(support, SUPPORT_STATUSES, path=f"{path}.supportStatus", name="supportStatus", out=out)
        check_nullable_nonempty(row.get("failedVerifierObligation"), path=f"{path}.failedVerifierObligation", out=out)
        check_nullable_nonempty(row.get("minimalCounterexample"), path=f"{path}.minimalCounterexample", out=out)
        check_nullable_nonempty(row.get("linkedDecision"), path=f"{path}.linkedDecision", out=out)
        check_nullable_nonempty(row.get("currentArtifactOperation"), path=f"{path}.currentArtifactOperation", out=out)

        provenance = row.get("provenance")
        if check_object(provenance, path=f"{path}.provenance", required=PROVENANCE_REQUIRED, allowed=PROVENANCE_ALLOWED, out=out):
            check_nonempty(provenance.get("source"), path=f"{path}.provenance.source", out=out)
            check_enum(
                provenance.get("authorityWeightTier"),
                AUTHORITY_WEIGHT_TIERS,
                path=f"{path}.provenance.authorityWeightTier",
                name="authorityWeightTier",
                out=out,
            )

        refs = row.get("evidenceRefs")
        if not isinstance(refs, list):
            out.append(diag("pressure_loop.schema", "evidenceRefs must be an array", path=f"{path}.evidenceRefs"))
        else:
            ref_seen: set[tuple[str, str]] = set()
            for ref_idx, ref in enumerate(refs):
                ref_path = f"{path}.evidenceRefs[{ref_idx}]"
                if not check_object(ref, path=ref_path, required=EVIDENCE_REF_REQUIRED, allowed=EVIDENCE_REF_ALLOWED, out=out):
                    continue
                check_enum(ref.get("type"), EVIDENCE_REF_TYPES, path=f"{ref_path}.type", name="evidenceRefs[].type", out=out)
                check_nonempty(ref.get("ref"), path=f"{ref_path}.ref", out=out)
                if is_nonempty_string(ref.get("type")) and is_nonempty_string(ref.get("ref")):
                    key = (ref["type"], ref["ref"])
                    if key in ref_seen:
                        out.append(diag("pressure_loop.duplicate_evidence_ref", f"duplicate evidence ref {key!r}", path=ref_path))
                    ref_seen.add(key)

        klass = row.get("class")
        outcome = row.get("outcome")
        failed = row.get("failedVerifierObligation")
        if (outcome == "accepted") != (klass is None):
            out.append(diag("pressure_loop.accepted_class", "accepted rows must have class null, and class-null rows must be accepted", path=f"{path}.class"))
        if outcome == "unresolved" and (klass not in {"1", "2", "3"} or not is_nonempty_string(failed)):
            out.append(diag("pressure_loop.unresolved_obligation", "unresolved rows must have class 1/2/3 and failedVerifierObligation", path=path))
        if klass in {"1", "2", "3"} and (outcome != "unresolved" or not is_nonempty_string(failed)):
            out.append(diag("pressure_loop.unresolved_obligation", "class 1/2/3 rows must be unresolved with failedVerifierObligation", path=path))

        if disposition in DECISION_DISPOSITIONS:
            if klass != "3":
                out.append(diag("pressure_loop.decision_contract", "decision-required rows must be Class 3", path=f"{path}.class"))
            if not is_nonempty_string(row.get("minimalCounterexample")):
                out.append(diag("pressure_loop.decision_counterexample", "decision-required rows must carry minimalCounterexample", path=f"{path}.minimalCounterexample"))
            if not is_nonempty_string(row.get("linkedDecision")):
                out.append(diag("pressure_loop.linked_decision", "decision-required rows must carry linkedDecision", path=f"{path}.linkedDecision"))

        if disposition == "UNSUPPORTED_REFUSED":
            if support != "absent" or outcome != "unresolved" or not has_evidence(row, "refusal"):
                out.append(diag("pressure_loop.unsupported_refused", "UNSUPPORTED_REFUSED rows must be absent, unresolved, and carry refusal evidence", path=path))

        if support in {"present", "partial"}:
            if not is_nonempty_string(row.get("currentArtifactOperation")) or not has_evidence(row, "executable"):
                out.append(diag("pressure_loop.support_artifact", "present/partial rows require currentArtifactOperation and executable evidence", path=path))
        if support == "partial":
            siblings = [i for i in absent_by_requirement.get(requirement, []) if i != idx]
            if not siblings:
                out.append(diag("pressure_loop.partial_sibling", "partial rows require an explicit absent sibling row for uncovered obligations", path=f"{path}.supportStatus"))
        if support == "absent" and row.get("currentArtifactOperation") is not None:
            out.append(diag("pressure_loop.absent_artifact", "absent rows must not carry currentArtifactOperation", path=f"{path}.currentArtifactOperation"))

        if disposition in ORTHOGONAL_DISPOSITIONS:
            fabricated = (
                klass is not None
                or outcome != "accepted"
                or row.get("failedVerifierObligation") is not None
                or row.get("minimalCounterexample") is not None
                or row.get("linkedDecision") is not None
                or row.get("currentArtifactOperation") is not None
                or support != "absent"
                or bool(row.get("evidenceRefs"))
            )
            if fabricated:
                out.append(diag("pressure_loop.orthogonal_disposition", "L3_RUNTIME/DESCRIPTIVE_ONLY rows are orthogonal and must not fabricate verifier design or artifact evidence", path=path))

    return out


def load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_file(path: Path) -> list[dict[str, str]]:
    try:
        return validate_obj(load(path))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return [diag("pressure_loop.io", f"cannot read register: {exc}")]


def evidence(evidence_type: str, ref: str) -> dict[str, str]:
    return {"type": evidence_type, "ref": ref}


def good_register() -> dict[str, Any]:
    return {
        "kind": KIND,
        "schemaVersion": SCHEMA_VERSION,
        "rows": [
            {
                "rowId": "r-001",
                "requirement": "Evidence event carries an observation source.",
                "provenance": {"source": "M6_L2_BRIDGE_ADR Decision 4", "authorityWeightTier": "1"},
                "outcome": "accepted",
                "class": None,
                "disposition": "L1_CORE",
                "failedVerifierObligation": None,
                "minimalCounterexample": None,
                "owner": "translator",
                "linkedDecision": None,
                "supportStatus": "present",
                "currentArtifactOperation": "SolStmt::emitEvent",
                "evidenceRefs": [evidence("executable", "test/ir/l2/domain_semantics_emit.mlir")],
            },
            {
                "rowId": "r-002",
                "requirement": "Hybrid settlement obligation coverage.",
                "provenance": {"source": "stress-corpus/case-042", "authorityWeightTier": "2"},
                "outcome": "accepted",
                "class": None,
                "disposition": "L2_REFINEMENT",
                "failedVerifierObligation": None,
                "minimalCounterexample": None,
                "owner": "translator",
                "linkedDecision": None,
                "supportStatus": "partial",
                "currentArtifactOperation": "L2Reduction::emitSettlementEdge",
                "evidenceRefs": [evidence("executable", "fixtures/pressure-loop/hybrid-settlement.l2.json")],
            },
            {
                "rowId": "r-003",
                "requirement": "Hybrid settlement obligation coverage.",
                "provenance": {"source": "stress-corpus/case-042/uncovered", "authorityWeightTier": "2"},
                "outcome": "unresolved",
                "class": "2",
                "disposition": "UNSUPPORTED_REFUSED",
                "failedVerifierObligation": "No executable L2 edge covers the external settlement reversal obligation.",
                "minimalCounterexample": None,
                "owner": "translator",
                "linkedDecision": None,
                "supportStatus": "absent",
                "currentArtifactOperation": None,
                "evidenceRefs": [evidence("refusal", "neutrino-")],
            },
            {
                "rowId": "r-004",
                "requirement": "Unfactored lifecycle branch needs an explicit layer decision.",
                "provenance": {"source": "stress-corpus/case-017", "authorityWeightTier": "2"},
                "outcome": "unresolved",
                "class": "3",
                "disposition": "LAYER_DECISION_REQUIRED",
                "failedVerifierObligation": "No single L2 reduction can preserve both branch meanings.",
                "minimalCounterexample": "Two accepted source obligations collapse to the same target transition.",
                "owner": "architecture-owner",
                "linkedDecision": "neutrino-",
                "supportStatus": "absent",
                "currentArtifactOperation": None,
                "evidenceRefs": [],
            },
            {
                "rowId": "r-005",
                "requirement": "Runtime-only telemetry is tracked outside the static pressure-loop register.",
                "provenance": {"source": "M6_L2_BRIDGE_ADR Runtime boundary", "authorityWeightTier": "1"},
                "outcome": "accepted",
                "class": None,
                "disposition": "L3_RUNTIME",
                "failedVerifierObligation": None,
                "minimalCounterexample": None,
                "owner": "runtime-owner",
                "linkedDecision": None,
                "supportStatus": "absent",
                "currentArtifactOperation": None,
                "evidenceRefs": [],
            },
        ],
    }


def selftest() -> int:
    failures: list[str] = []

    def expect_ok(name: str, obj: dict[str, Any]) -> None:
        diagnostics = validate_obj(obj)
        if diagnostics:
            failures.append(f"{name}: expected ok, got {diagnostics}")

    def expect_fail(name: str, obj: dict[str, Any], code: str) -> None:
        diagnostics = validate_obj(obj)
        if not any(d["code"] == code for d in diagnostics):
            failures.append(f"{name}: expected {code}, got {diagnostics}")

    base = good_register()
    expect_ok("positive", base)

    v1 = copy.deepcopy(base)
    v1["schemaVersion"] = 1
    expect_fail("v1 retired", v1, "pressure_loop.schema_version")

    accepted_class = copy.deepcopy(base)
    accepted_class["rows"][0]["class"] = "1"
    expect_fail("accepted+class rejected", accepted_class, "pressure_loop.accepted_class")

    unresolved_missing_obligation = copy.deepcopy(base)
    unresolved_missing_obligation["rows"][2]["failedVerifierObligation"] = None
    expect_fail("unresolved missing obligation", unresolved_missing_obligation, "pressure_loop.unresolved_obligation")

    decision_wrong_class = copy.deepcopy(base)
    decision_wrong_class["rows"][3]["class"] = "2"
    expect_fail("decision wrong class", decision_wrong_class, "pressure_loop.decision_contract")

    decision_missing_counterexample = copy.deepcopy(base)
    decision_missing_counterexample["rows"][3]["minimalCounterexample"] = None
    expect_fail("decision row missing counterexample", decision_missing_counterexample, "pressure_loop.decision_counterexample")

    decision_missing_link = copy.deepcopy(base)
    decision_missing_link["rows"][3]["linkedDecision"] = None
    expect_fail("decision row missing linked decision", decision_missing_link, "pressure_loop.linked_decision")

    unsupported_no_refusal = copy.deepcopy(base)
    unsupported_no_refusal["rows"][2]["evidenceRefs"] = []
    expect_fail("unsupported refusal evidence", unsupported_no_refusal, "pressure_loop.unsupported_refused")

    present_missing_exec = copy.deepcopy(base)
    present_missing_exec["rows"][0]["evidenceRefs"] = []
    expect_fail("present executable evidence", present_missing_exec, "pressure_loop.support_artifact")

    partial_missing_sibling = copy.deepcopy(base)
    partial_missing_sibling["rows"][2]["requirement"] = "Different uncovered obligation"
    expect_fail("partial absent sibling", partial_missing_sibling, "pressure_loop.partial_sibling")

    orthogonal_fabricated = copy.deepcopy(base)
    orthogonal_fabricated["rows"][4]["currentArtifactOperation"] = "fakeRuntimeArtifact"
    expect_fail("orthogonal artifact", orthogonal_fabricated, "pressure_loop.orthogonal_disposition")

    malformed = copy.deepcopy(base)
    malformed["rows"][0]["outcome"] = "maybe"
    expect_fail("enum", malformed, "pressure_loop.enum")

    enum_type = copy.deepcopy(base)
    enum_type["rows"][0]["outcome"] = []
    expect_fail("enum list value", enum_type, "pressure_loop.enum")

    enum_object = copy.deepcopy(base)
    enum_object["rows"][0]["provenance"]["authorityWeightTier"] = {}
    expect_fail("enum object value", enum_object, "pressure_loop.enum")

    bool_schema_version = copy.deepcopy(base)
    bool_schema_version["schemaVersion"] = True
    expect_fail("boolean schemaVersion", bool_schema_version, "pressure_loop.schema_version")

    duplicate = copy.deepcopy(base)
    duplicate["rows"][1]["rowId"] = duplicate["rows"][0]["rowId"]
    expect_fail("duplicate row", duplicate, "pressure_loop.duplicate_row")

    duplicate_evidence = copy.deepcopy(base)
    duplicate_evidence["rows"][0]["evidenceRefs"].append(copy.deepcopy(duplicate_evidence["rows"][0]["evidenceRefs"][0]))
    expect_fail("duplicate evidence ref", duplicate_evidence, "pressure_loop.duplicate_evidence_ref")

    unknown = copy.deepcopy(base)
    unknown["rows"][0]["extra"] = True
    expect_fail("unknown row field", unknown, "pressure_loop.unknown_field")

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "register.json"
        path.write_text(json.dumps(base), encoding="utf-8")
        diagnostics = validate_file(path)
        if diagnostics:
            failures.append(f"file positive: expected ok, got {diagnostics}")

    if failures:
        print("pressure-loop register selftest FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("pressure-loop register selftest PASS (v2 positive + v1 retirement + semantic negatives + duplicate/unknown negatives)")
    return 0


def mutated_for_probe(probe_id: str) -> tuple[dict[str, Any], str]:
    obj = good_register()
    if probe_id == "v1-retired":
        obj["schemaVersion"] = 1
        return obj, "pressure_loop.schema_version"
    if probe_id == "accepted-class":
        obj["rows"][0]["class"] = "1"
        return obj, "pressure_loop.accepted_class"
    if probe_id == "unresolved-obligation":
        obj["rows"][2]["failedVerifierObligation"] = None
        return obj, "pressure_loop.unresolved_obligation"
    if probe_id == "decision-class":
        obj["rows"][3]["class"] = "2"
        return obj, "pressure_loop.decision_contract"
    if probe_id == "decision-counterexample":
        obj["rows"][3]["minimalCounterexample"] = None
        return obj, "pressure_loop.decision_counterexample"
    if probe_id == "unsupported-refused":
        obj["rows"][2]["evidenceRefs"] = []
        return obj, "pressure_loop.unsupported_refused"
    if probe_id == "support-artifact":
        obj["rows"][0]["currentArtifactOperation"] = None
        return obj, "pressure_loop.support_artifact"
    if probe_id == "partial-sibling":
        obj["rows"][2]["requirement"] = "Different uncovered obligation"
        return obj, "pressure_loop.partial_sibling"
    if probe_id == "orthogonal-artifact":
        obj["rows"][4]["currentArtifactOperation"] = "fakeRuntimeArtifact"
        return obj, "pressure_loop.orthogonal_disposition"
    if probe_id == "duplicate-row":
        obj["rows"][1]["rowId"] = obj["rows"][0]["rowId"]
        return obj, "pressure_loop.duplicate_row"
    if probe_id == "unknown-field":
        obj["rows"][0]["extra"] = True
        return obj, "pressure_loop.unknown_field"
    raise KeyError(probe_id)


def run_probe(probe_id: str) -> int:
    if probe_id not in TAMPER_IDS:
        print(f"unknown pressure-loop register probe {probe_id}", file=sys.stderr)
        return 2
    obj, expected = mutated_for_probe(probe_id)
    diagnostics = validate_obj(obj)
    if any(d["code"] == expected for d in diagnostics):
        print(f"probe-failed-as-expected:{probe_id}")
        return 1
    print(f"probe unexpectedly passed or failed wrong invariant for {probe_id}: {diagnostics}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a neutrino.pressure-loop-register v2 artifact")
    parser.add_argument("register", nargs="?", help="pressure-loop register JSON file")
    parser.add_argument("--json", action="store_true", help="emit diagnostics JSON")
    parser.add_argument("--selftest", action="store_true", help="run embedded non-vacuity checks")
    parser.add_argument("--probe", choices=sorted(TAMPER_IDS), help="run one embedded tamper probe")
    args = parser.parse_args(argv)

    if args.probe:
        return run_probe(args.probe)
    if args.selftest:
        return selftest()
    if not args.register:
        parser.error("register is required unless --selftest is used")

    diagnostics = validate_file(Path(args.register))
    result = {"ok": not diagnostics, "diagnostics": diagnostics}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    elif diagnostics:
        for d in diagnostics:
            print(f"{d['code']}: {d['path']}: {d['message']}", file=sys.stderr)
    return 0 if not diagnostics else 1


if __name__ == "__main__":
    raise SystemExit(main())
