#!/usr/bin/env python3
""" /  S3a pressure-loop mutation protocol gate.

This is the cheap deterministic harness for mutation cases that later
expands into the complete forcing matrix. It stays below the  one-waist
contract: inputs are pressure-loop register rows plus protocol-local evidence
metadata, never capability-spec or target realization semantics.

The protocol proves:
  * the base register is v2-valid ();
  * each representative mutation fails independently;
  * every required S3a category has at least one biting case;
  * zero-case / skipped matrices fail closed; and
  * currently unrepresentable independence claims remain explicit unresolved
    decision rows, not fabricated executable evaluator evidence.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL = REPO / "examples/pressure-loop-mutations/s3a-representative.json"
VALIDATOR_DIR = REPO / "scripts/validators"
sys.path.insert(0, str(VALIDATOR_DIR))
import validate_pressure_loop_register as register_validator  # noqa: E402

KIND = "neutrino.pressure-loop-mutation-protocol"
SCHEMA_VERSION = 1
MIN_CASES = 5
REQUIRED_CATEGORIES = {
    "dropped-l2-obligation",
    "runtime-binding-moved-into-semantic-identity",
    "backend-inference-introduced",
    "bound-terminal-removed",
    "correlated-evidence-substituted",
}
CASE_REQUIRED = {"caseId", "category", "mutation", "expectedDiagnostic"}
CASE_ALLOWED = CASE_REQUIRED | {"description"}
MUTATION_REQUIRED = {
    "drop-row": {"op", "rowId"},
    "set-field": {"op", "rowId", "field", "value"},
    "set-evidence-locus": {"op", "rowId", "value"},
    "copy-evidence-ref": {"op", "fromRowId", "toRowId"},
}
STRING_MUTATION_FIELDS = {"op", "rowId", "fromRowId", "toRowId", "field"}


def diag(code: str, message: str, *, path: str = "$") -> dict[str, str]:
    return {"code": code, "severity": "error", "path": path, "message": message}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def repo_path(value: str, *, path: str) -> Path:
    p = Path(value)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"{path} must be repository-relative and contained")
    resolved = (REPO / p).resolve()
    if not str(resolved).startswith(str(REPO.resolve()) + "/"):
        raise ValueError(f"{path} escapes repository")
    return resolved


def row_index(register: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["rowId"]: row
        for row in register.get("rows", [])
        if isinstance(row, dict) and isinstance(row.get("rowId"), str)
    }


def validate_base(register: Any) -> list[dict[str, str]]:
    return register_validator.validate_obj(register)


def protocol_diagnostics(register: dict[str, Any], evidence_loci: dict[str, str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row_id, locus in sorted(evidence_loci.items()):
        if locus != "coordination-waist":
            out.append(diag(
                "pressure_loop_mutation.backend_inference",
                f"{row_id}: mutation evidence decision locus {locus!r} is not the coordination waist",
                path=f"$.evidenceLoci.{row_id}",
            ))

    owners: dict[tuple[str, str], list[str]] = {}
    for row in register.get("rows", []):
        if not isinstance(row, dict):
            continue
        row_id = row.get("rowId")
        for ref in row.get("evidenceRefs", []):
            if isinstance(row_id, str) and isinstance(ref, dict):
                key = (ref.get("type"), ref.get("ref"))
                if isinstance(key[0], str) and isinstance(key[1], str):
                    owners.setdefault(key, []).append(row_id)
    for key, row_ids in sorted(owners.items()):
        if len(set(row_ids)) > 1:
            out.append(diag(
                "pressure_loop_mutation.correlated_evidence",
                f"evidence ref {key!r} is reused across rows {sorted(set(row_ids))}",
                path="$.rows",
            ))
    return out


def assert_unrepresentable_independence(register: dict[str, Any], row_id: str | None) -> list[dict[str, str]]:
    if not row_id:
        return [diag("pressure_loop_mutation.independence_contract", "unrepresentableIndependenceRowId is required")]
    row = row_index(register).get(row_id)
    if not row:
        return [diag("pressure_loop_mutation.independence_contract", f"row {row_id!r} not found")]
    if not (
        row.get("outcome") == "unresolved"
        and row.get("class") == "3"
        and row.get("disposition") in {"LANGUAGE_DECISION_REQUIRED", "LAYER_DECISION_REQUIRED"}
        and row.get("currentArtifactOperation") is None
        and not row.get("evidenceRefs")
        and row.get("failedVerifierObligation")
        and row.get("minimalCounterexample")
        and row.get("linkedDecision")
    ):
        return [diag(
            "pressure_loop_mutation.independence_contract",
            f"{row_id}: unrepresentable independence must be an explicit unresolved decision row without executable evidence",
            path=f"$.rows.{row_id}",
        )]
    return []


def validate_mutation_shape(mutation: Any, *, path: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(mutation, dict):
        return [diag("pressure_loop_mutation.mutation_schema", "mutation must be an object", path=path)]
    op = mutation.get("op")
    if not isinstance(op, str) or not op:
        return [diag("pressure_loop_mutation.mutation_schema", "mutation op must be a non-empty string", path=f"{path}.op")]
    if op not in MUTATION_REQUIRED:
        return [diag("pressure_loop_mutation.mutation_schema", f"unknown mutation op {op!r}", path=f"{path}.op")]
    required = MUTATION_REQUIRED[op]
    for key in sorted(required - set(mutation)):
        out.append(diag("pressure_loop_mutation.mutation_schema", f"mutation {op!r} missing field {key!r}", path=path))
    for key in sorted(set(mutation) - required):
        out.append(diag("pressure_loop_mutation.mutation_schema", f"mutation {op!r} has unknown field {key!r}", path=f"{path}.{key}"))
    for key in sorted(required & STRING_MUTATION_FIELDS):
        value = mutation.get(key)
        if not isinstance(value, str) or not value:
            out.append(diag("pressure_loop_mutation.mutation_schema", f"mutation field {key!r} must be a non-empty string", path=f"{path}.{key}"))
    if op == "set-evidence-locus" and not isinstance(mutation.get("value"), str):
        out.append(diag("pressure_loop_mutation.mutation_schema", "set-evidence-locus value must be a string", path=f"{path}.value"))
    if op == "set-field":
        field = mutation.get("field")
        if isinstance(field, str) and field not in register_validator.ROW_ALLOWED:
            out.append(diag("pressure_loop_mutation.mutation_schema", f"set-field field {field!r} is not a v2 register row field", path=f"{path}.field"))
    return out


def apply_mutation(register: dict[str, Any], evidence_loci: dict[str, str], mutation: dict[str, Any]) -> None:
    op = mutation.get("op")
    if op not in MUTATION_REQUIRED:
        raise ValueError(f"unknown mutation op {op!r}")
    missing = sorted(MUTATION_REQUIRED[op] - set(mutation))
    if missing:
        raise ValueError(f"mutation {op!r} missing field(s) {missing}")
    rows = row_index(register)
    if op == "drop-row":
        row_id = mutation["rowId"]
        before = len(register["rows"])
        register["rows"] = [r for r in register["rows"] if not (isinstance(r, dict) and r.get("rowId") == row_id)]
        if len(register["rows"]) == before:
            raise ValueError(f"drop-row rowId {row_id!r} not found")
        return
    if op == "set-field":
        row = rows.get(mutation["rowId"])
        if row is None:
            raise ValueError(f"set-field rowId {mutation['rowId']!r} not found")
        field = mutation["field"]
        if field not in register_validator.ROW_ALLOWED:
            raise ValueError(f"set-field field {field!r} is not a v2 register row field")
        row[field] = mutation["value"]
        return
    if op == "set-evidence-locus":
        row_id = mutation["rowId"]
        if row_id not in rows:
            raise ValueError(f"set-evidence-locus rowId {row_id!r} not found")
        evidence_loci[row_id] = mutation["value"]
        return
    if op == "copy-evidence-ref":
        src = rows.get(mutation["fromRowId"])
        dst = rows.get(mutation["toRowId"])
        if src is None or dst is None:
            raise ValueError("copy-evidence-ref rowId not found")
        refs = src.get("evidenceRefs")
        if not isinstance(refs, list) or not refs:
            raise ValueError("copy-evidence-ref source row has no evidenceRefs")
        dst.setdefault("evidenceRefs", [])
        if not isinstance(dst["evidenceRefs"], list):
            raise ValueError("copy-evidence-ref destination evidenceRefs is not an array")
        dst["evidenceRefs"] = [copy.deepcopy(refs[0])]
        return
    raise AssertionError(op)


def validate_protocol(obj: Any) -> tuple[list[dict[str, str]], dict[str, Any] | None]:
    out: list[dict[str, str]] = []
    if not isinstance(obj, dict):
        return [diag("pressure_loop_mutation.schema", "protocol must be an object")], None
    allowed = {"kind", "schemaVersion", "baseRegisterRef", "unrepresentableIndependenceRowId", "cases"}
    for key in sorted(set(obj) - allowed):
        out.append(diag("pressure_loop_mutation.unknown_field", f"unknown field {key!r}", path=f"$.{key}"))
    if obj.get("kind") != KIND:
        out.append(diag("pressure_loop_mutation.kind", f"kind must be {KIND!r}", path="$.kind"))
    if obj.get("schemaVersion") != SCHEMA_VERSION:
        out.append(diag("pressure_loop_mutation.schema_version", "schemaVersion must be 1", path="$.schemaVersion"))
    try:
        base_ref = obj.get("baseRegisterRef")
        if not isinstance(base_ref, str) or not base_ref:
            raise ValueError("baseRegisterRef must be a non-empty string")
        base = load_json(repo_path(base_ref, path="$.baseRegisterRef"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        out.append(diag("pressure_loop_mutation.base_register", str(exc), path="$.baseRegisterRef"))
        return out, None
    base_errors = validate_base(base)
    out.extend(diag("pressure_loop_mutation.base_register", e["message"], path=e["path"]) for e in base_errors)
    out.extend(assert_unrepresentable_independence(base, obj.get("unrepresentableIndependenceRowId")))

    cases = obj.get("cases")
    if not isinstance(cases, list):
        out.append(diag("pressure_loop_mutation.schema", "cases must be an array", path="$.cases"))
        return out, base
    if len(cases) < MIN_CASES:
        out.append(diag("pressure_loop_mutation.zero_case", f"cases must contain at least {MIN_CASES} cases", path="$.cases"))

    seen_cases: set[str] = set()
    categories: set[str] = set()
    for idx, case in enumerate(cases):
        path = f"$.cases[{idx}]"
        if not isinstance(case, dict):
            out.append(diag("pressure_loop_mutation.schema", "case must be an object", path=path))
            continue
        for key in sorted(CASE_REQUIRED - set(case)):
            out.append(diag("pressure_loop_mutation.missing_field", f"missing required field {key!r}", path=path))
        for key in sorted(set(case) - CASE_ALLOWED):
            out.append(diag("pressure_loop_mutation.unknown_field", f"unknown field {key!r}", path=f"{path}.{key}"))
        case_id = case.get("caseId")
        if not isinstance(case_id, str) or not case_id:
            out.append(diag("pressure_loop_mutation.schema", "caseId must be non-empty", path=f"{path}.caseId"))
        elif case_id in seen_cases:
            out.append(diag("pressure_loop_mutation.duplicate_case", f"duplicate caseId {case_id!r}", path=f"{path}.caseId"))
        else:
            seen_cases.add(case_id)
        expected = case.get("expectedDiagnostic")
        if not isinstance(expected, str) or not expected:
            out.append(diag("pressure_loop_mutation.schema", "expectedDiagnostic must be a non-empty string", path=f"{path}.expectedDiagnostic"))
        category = case.get("category")
        if category not in REQUIRED_CATEGORIES:
            out.append(diag("pressure_loop_mutation.category", f"category must be one of {sorted(REQUIRED_CATEGORIES)}", path=f"{path}.category"))
        else:
            categories.add(category)
        out.extend(validate_mutation_shape(case.get("mutation"), path=f"{path}.mutation"))
    missing_categories = sorted(REQUIRED_CATEGORIES - categories)
    for category in missing_categories:
        out.append(diag("pressure_loop_mutation.missing_category", f"missing representative mutation category {category!r}", path="$.cases"))
    return out, base


def check_protocol(obj: Any) -> tuple[list[dict[str, str]], dict[str, Any]]:
    errors, base = validate_protocol(obj)
    report = {"kind": "neutrino.pressure-loop-mutation-report", "schemaVersion": 1, "cases": []}
    if errors or base is None:
        return errors, report
    for idx, case in enumerate(obj["cases"]):
        mutated = copy.deepcopy(base)
        evidence_loci = {
            row["rowId"]: "coordination-waist"
            for row in mutated.get("rows", [])
            if isinstance(row, dict) and isinstance(row.get("rowId"), str)
        }
        try:
            apply_mutation(mutated, evidence_loci, case["mutation"])
            diagnostics = validate_base(mutated) + protocol_diagnostics(mutated, evidence_loci)
        except (KeyError, TypeError, ValueError) as exc:
            diagnostics = [diag("pressure_loop_mutation.apply", str(exc), path=f"$.cases[{idx}].mutation")]
        codes = [d["code"] for d in diagnostics]
        report["cases"].append({
            "caseId": case.get("caseId"),
            "category": case.get("category"),
            "expectedDiagnostic": case.get("expectedDiagnostic"),
            "observedDiagnostics": codes,
        })
        if case.get("expectedDiagnostic") not in codes:
            errors.append(diag(
                "pressure_loop_mutation.not_caught",
                f"{case.get('caseId')}: expected {case.get('expectedDiagnostic')!r}, observed {codes}",
                path=f"$.cases[{idx}]",
            ))
    return errors, report


def print_result(errors: list[dict[str, str]], report: dict[str, Any], *, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": not errors, "diagnostics": errors, "report": report}, indent=2, sort_keys=True))
    elif errors:
        print("pressure-loop mutation protocol FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err['code']} {err['path']}: {err['message']}", file=sys.stderr)
    else:
        print(f"pressure-loop mutation protocol OK: {len(report['cases'])} representative mutations bite independently")
    return 1 if errors else 0


def mutated_protocol(mutator) -> dict[str, Any]:
    obj = load_json(DEFAULT_PROTOCOL)
    mutator(obj)
    return obj


def run_probe(probe: str) -> int:
    cleanup: Path | None = None

    def fabricated(o: dict[str, Any]) -> None:
        nonlocal cleanup
        cleanup = _write_temp_register_with_fabricated_independence()
        o["baseRegisterRef"] = cleanup.relative_to(REPO).as_posix()

    probes = {
        "zero-cases": lambda o: o.__setitem__("cases", []),
        "missing-category": lambda o: o.__setitem__("cases", o["cases"][:-1]),
        "wrong-expected-diagnostic": lambda o: o["cases"][0].__setitem__("expectedDiagnostic", "pressure_loop_mutation.never"),
        "fabricated-independence": fabricated,
        "unknown-mutation-field": lambda o: o["cases"][0]["mutation"].__setitem__("ignored", "unreviewed"),
        "non-string-evidence-locus": lambda o: o["cases"][2]["mutation"].__setitem__("value", ["backend-inference"]),
    }
    if probe not in probes:
        print(f"unknown pressure-loop mutation probe {probe!r}", file=sys.stderr)
        return 2
    try:
        errors, _ = check_protocol(mutated_protocol(probes[probe]))
    finally:
        if cleanup is not None:
            try:
                cleanup.unlink()
            except FileNotFoundError:
                pass
    if errors:
        print(f"probe-failed-as-expected:{probe}")
        return 1
    print(f"probe unexpectedly passed:{probe}")
    return 0


def _write_temp_register_with_fabricated_independence() -> Path:
    base = load_json(REPO / "examples/pressure-loop-register/v2-positive.json")
    for row in base["rows"]:
        if row["rowId"] == "r-004":
            row.update({
                "outcome": "accepted",
                "class": None,
                "disposition": "L1_CORE",
                "failedVerifierObligation": None,
                "minimalCounterexample": None,
                "linkedDecision": None,
                "supportStatus": "present",
                "currentArtifactOperation": "FabricatedEvaluator::proveIndependence",
                "evidenceRefs": [{"type": "executable", "ref": "fabricated/evaluator.json"}],
            })
            break
    path = REPO / ".pressure-loop-fabricated-independence.tmp.json"
    path.write_text(json.dumps(base, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def selftest() -> int:
    failures: list[str] = []
    errors, report = check_protocol(load_json(DEFAULT_PROTOCOL))
    if errors:
        failures.append("committed protocol failed: " + "; ".join(e["code"] for e in errors))
    for probe in (
        "zero-cases",
        "missing-category",
        "wrong-expected-diagnostic",
        "fabricated-independence",
        "unknown-mutation-field",
        "non-string-evidence-locus",
    ):
        if run_probe(probe) == 0:
            failures.append(f"probe {probe} did not fail")
    if failures:
        print("pressure-loop mutation protocol selftest FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"pressure-loop mutation protocol selftest PASS ({len(report['cases'])} cases; zero/missing/wrong/fabricated/shape probes fail closed)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate the  S3a pressure-loop mutation protocol harness")
    ap.add_argument("protocol", nargs="?", default=str(DEFAULT_PROTOCOL))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--probe", choices=[
        "zero-cases",
        "missing-category",
        "wrong-expected-diagnostic",
        "fabricated-independence",
        "unknown-mutation-field",
        "non-string-evidence-locus",
    ])
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.probe:
        return run_probe(args.probe)
    try:
        errors, report = check_protocol(load_json(Path(args.protocol)))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors, report = [diag("pressure_loop_mutation.io", str(exc))], {"kind": "neutrino.pressure-loop-mutation-report", "schemaVersion": 1, "cases": []}
    return print_result(errors, report, as_json=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
