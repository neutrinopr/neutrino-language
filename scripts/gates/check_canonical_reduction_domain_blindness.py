#!/usr/bin/env python3
""" /  S4 canonical-reduction domain-blindness proof.

The S4 proof compares selected semantic requirement subgraphs from different
L2/domain refinements after reducing them to the one-waist verifier contract.
It intentionally does not compare entire flow specs: extra domain obligations
remain explicit and outside the selected reduced set.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = REPO / "examples/pressure-loop-reduction/s4-domain-blindness.json"
KIND = "neutrino.canonical-reduction-domain-blindness"
SCHEMA_VERSION = 1
MIN_GRAPHS = 2
SEMANTIC_FIELDS = ("evidenceClass", "feature", "independence", "obligation", "terminalBound")
FORBIDDEN_BELOW_WAIST_KEYS = {
    "backend",
    "backendBranch",
    "domain",
    "domainBranch",
    "domainLabel",
    "domainReducer",
    "sourceDomain",
    "target",
}
PROBES = {
    "name-collision",
    "domain-reducer",
    "backend-branch",
    "remove-shared-obligation",
    "change-shared-obligation",
    "domain-label-below-waist",
}


def diag(code: str, message: str, *, path: str = "$") -> dict[str, str]:
    return {"code": code, "severity": "error", "path": path, "message": message}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value)


def object_at(value: Any, *, path: str, out: list[dict[str, str]]) -> bool:
    if not isinstance(value, dict):
        out.append(diag("canonical_reduction.schema", "must be an object", path=path))
        return False
    return True


def check_forbidden_below_waist(value: Any, *, path: str, out: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in FORBIDDEN_BELOW_WAIST_KEYS:
                out.append(diag(
                    "canonical_reduction.below_waist_label",
                    f"below-waist reduced semantics must not contain {key!r}",
                    path=child_path,
                ))
            check_forbidden_below_waist(child, path=child_path, out=out)
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            check_forbidden_below_waist(child, path=f"{path}[{idx}]", out=out)


def semantic_projection(req: dict[str, Any], *, path: str, out: list[dict[str, str]]) -> dict[str, str] | None:
    sem = req.get("verifierSemantics")
    if not isinstance(sem, dict):
        out.append(diag("canonical_reduction.schema", "requirement.verifierSemantics must be an object", path=f"{path}.verifierSemantics"))
        return None
    for key in sorted(set(sem) - set(SEMANTIC_FIELDS)):
        out.append(diag("canonical_reduction.semantic_field", f"unknown verifier semantic field {key!r}", path=f"{path}.verifierSemantics.{key}"))
    projected: dict[str, str] = {}
    for key in SEMANTIC_FIELDS:
        value = sem.get(key)
        if not nonempty(value):
            out.append(diag("canonical_reduction.semantic_field", f"{key} must be a non-empty string", path=f"{path}.verifierSemantics.{key}"))
        else:
            projected[key] = value
    check_forbidden_below_waist(sem, path=f"{path}.verifierSemantics", out=out)
    return projected if len(projected) == len(SEMANTIC_FIELDS) else None


def reduced_set(graph: dict[str, Any], *, path: str, out: list[dict[str, str]]) -> tuple[list[dict[str, str]], bytes, str] | None:
    reqs = graph.get("requirements")
    selected = graph.get("selectedRequirementIds")
    extras = graph.get("extraRequirementIds", [])
    if not isinstance(reqs, list) or not reqs:
        out.append(diag("canonical_reduction.schema", "requirements must be a non-empty array", path=f"{path}.requirements"))
        return None
    if not isinstance(selected, list) or not selected:
        out.append(diag("canonical_reduction.schema", "selectedRequirementIds must be a non-empty array", path=f"{path}.selectedRequirementIds"))
        return None
    if not isinstance(extras, list):
        out.append(diag("canonical_reduction.schema", "extraRequirementIds must be an array", path=f"{path}.extraRequirementIds"))
        return None

    by_id: dict[str, dict[str, Any]] = {}
    name_semantics: dict[str, dict[str, str]] = {}
    for idx, req in enumerate(reqs):
        rpath = f"{path}.requirements[{idx}]"
        if not object_at(req, path=rpath, out=out):
            continue
        rid = req.get("id")
        name = req.get("name")
        if not nonempty(rid):
            out.append(diag("canonical_reduction.schema", "requirement id must be a non-empty string", path=f"{rpath}.id"))
            continue
        if rid in by_id:
            out.append(diag("canonical_reduction.duplicate_requirement", f"duplicate requirement id {rid!r}", path=f"{rpath}.id"))
        by_id[rid] = req
        if not nonempty(name):
            out.append(diag("canonical_reduction.schema", "requirement name must be a non-empty string", path=f"{rpath}.name"))
        sem = semantic_projection(req, path=rpath, out=out)
        if nonempty(name) and sem is not None:
            prior = name_semantics.get(name)
            if prior is not None and prior != sem:
                out.append(diag(
                    "canonical_reduction.name_collision",
                    f"requirement name {name!r} maps to multiple verifier semantic meanings",
                    path=f"{rpath}.name",
                ))
            name_semantics[name] = sem

    selected_ids = []
    for idx, rid in enumerate(selected):
        if not nonempty(rid):
            out.append(diag("canonical_reduction.schema", "selected requirement id must be a non-empty string", path=f"{path}.selectedRequirementIds[{idx}]"))
        elif rid not in by_id:
            out.append(diag("canonical_reduction.missing_selected", f"selected requirement {rid!r} is not declared", path=f"{path}.selectedRequirementIds[{idx}]"))
        else:
            selected_ids.append(rid)
    for idx, rid in enumerate(extras):
        if not nonempty(rid):
            out.append(diag("canonical_reduction.schema", "extra requirement id must be a non-empty string", path=f"{path}.extraRequirementIds[{idx}]"))
        elif rid not in by_id:
            out.append(diag("canonical_reduction.missing_extra", f"extra requirement {rid!r} is not declared", path=f"{path}.extraRequirementIds[{idx}]"))
        elif rid in selected_ids:
            out.append(diag("canonical_reduction.extra_selected_overlap", f"extra requirement {rid!r} is also selected", path=f"{path}.extraRequirementIds[{idx}]"))

    reduced: list[dict[str, str]] = []
    for rid in selected_ids:
        sem = semantic_projection(by_id[rid], path=f"{path}.requirements.{rid}", out=out)
        if sem is not None:
            reduced.append(sem)
    unique = {json.dumps(x, sort_keys=True) for x in reduced}
    if len(unique) != len(reduced):
        out.append(diag("canonical_reduction.duplicate_semantics", "selected reduced set contains duplicate verifier semantics", path=f"{path}.selectedRequirementIds"))
    reduced_sorted = sorted(reduced, key=lambda item: canonical_bytes(item))
    body = canonical_bytes(reduced_sorted)
    return reduced_sorted, body, hashlib.sha256(body).hexdigest()


def validate_obj(obj: Any) -> tuple[list[dict[str, str]], dict[str, Any]]:
    out: list[dict[str, str]] = []
    report: dict[str, Any] = {"kind": "neutrino.canonical-reduction-domain-blindness-report", "schemaVersion": 1, "groups": []}
    if not object_at(obj, path="$", out=out):
        return out, report
    allowed = {"kind", "schemaVersion", "proofId", "groups"}
    for key in sorted(set(obj) - allowed):
        out.append(diag("canonical_reduction.unknown_field", f"unknown field {key!r}", path=f"$.{key}"))
    if obj.get("kind") != KIND:
        out.append(diag("canonical_reduction.kind", f"kind must be {KIND!r}", path="$.kind"))
    if obj.get("schemaVersion") != SCHEMA_VERSION:
        out.append(diag("canonical_reduction.schema_version", "schemaVersion must be 1", path="$.schemaVersion"))
    if not nonempty(obj.get("proofId")):
        out.append(diag("canonical_reduction.schema", "proofId must be a non-empty string", path="$.proofId"))

    groups = obj.get("groups")
    if not isinstance(groups, list) or not groups:
        out.append(diag("canonical_reduction.schema", "groups must be a non-empty array", path="$.groups"))
        return out, report

    for gidx, group in enumerate(groups):
        gpath = f"$.groups[{gidx}]"
        if not object_at(group, path=gpath, out=out):
            continue
        graphs = group.get("sourceGraphs")
        if not isinstance(graphs, list) or len(graphs) < MIN_GRAPHS:
            out.append(diag("canonical_reduction.schema", f"sourceGraphs must contain at least {MIN_GRAPHS} graphs", path=f"{gpath}.sourceGraphs"))
            continue
        spec_verifications = group.get("specVerifications", [])
        if not isinstance(spec_verifications, list):
            out.append(diag("canonical_reduction.schema", "specVerifications must be an array", path=f"{gpath}.specVerifications"))
            spec_verifications = []
        spec_by_graph = {p.get("graphId"): p for p in spec_verifications if isinstance(p, dict)}
        graph_reports: list[dict[str, Any]] = []
        canonical_bodies: list[bytes] = []
        canonical_hashes: list[str] = []
        for idx, graph in enumerate(graphs):
            path = f"{gpath}.sourceGraphs[{idx}]"
            if not object_at(graph, path=path, out=out):
                continue
            gid = graph.get("graphId")
            if not nonempty(gid):
                out.append(diag("canonical_reduction.schema", "graphId must be a non-empty string", path=f"{path}.graphId"))
                continue
            result = reduced_set(graph, path=path, out=out)
            if result is None:
                continue
            reduced, body, digest = result
            canonical_bodies.append(body)
            canonical_hashes.append(digest)
            spec = spec_by_graph.get(gid)
            if not isinstance(spec, dict):
                out.append(diag("canonical_reduction.spec_verification", f"missing spec verification for graph {gid!r}", path=f"{gpath}.specVerifications"))
            else:
                if spec.get("result") != "accepted":
                    out.append(diag("canonical_reduction.spec_verification", f"graph {gid!r} spec verification result is not accepted", path=f"{gpath}.specVerifications"))
                if spec.get("canonicalReducedSha256") != digest:
                    out.append(diag(
                        "canonical_reduction.spec_verification",
                        f"graph {gid!r} spec verification hash {spec.get('canonicalReducedSha256')!r} != computed {digest}",
                        path=f"{gpath}.specVerifications",
                    ))
            graph_reports.append({"graphId": gid, "canonicalReducedSha256": digest, "reduced": reduced})
        if canonical_bodies and len(set(canonical_bodies)) != 1:
            out.append(diag("canonical_reduction.not_equivalent", "selected reduced sets are not byte-identical", path=f"{gpath}.sourceGraphs"))
        if canonical_hashes and len(set(canonical_hashes)) != 1:
            out.append(diag("canonical_reduction.hash_mismatch", "selected reduced hashes differ", path=f"{gpath}.sourceGraphs"))
        report["groups"].append({
            "groupId": group.get("groupId"),
            "canonicalReducedSha256": canonical_hashes[0] if canonical_hashes else None,
            "graphs": graph_reports,
        })
    return out, report


def print_result(errors: list[dict[str, str]], report: dict[str, Any], *, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": not errors, "diagnostics": errors, "report": report}, indent=2, sort_keys=True))
    elif errors:
        print("canonical-reduction domain-blindness FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err['code']} {err['path']}: {err['message']}", file=sys.stderr)
    else:
        groups = len(report.get("groups", []))
        print(f"canonical-reduction domain-blindness OK: {groups} group(s) byte-identical below the waist")
    return 1 if errors else 0


def mutated_fixture(probe: str) -> dict[str, Any]:
    obj = load_json(DEFAULT_FIXTURE)
    group = obj["groups"][0]
    first = group["sourceGraphs"][0]
    second = group["sourceGraphs"][1]
    if probe == "name-collision":
        first["requirements"][0]["name"] = "shared_collision"
        first["requirements"][1]["name"] = "shared_collision"
    elif probe == "domain-reducer":
        second["requirements"][0]["verifierSemantics"]["domainReducer"] = "github-handoff-only"
    elif probe == "backend-branch":
        first["requirements"][0]["verifierSemantics"]["backendBranch"] = "solidity"
    elif probe == "remove-shared-obligation":
        second["selectedRequirementIds"] = second["selectedRequirementIds"][:-1]
    elif probe == "change-shared-obligation":
        second["requirements"][1]["verifierSemantics"]["terminalBound"] = "runtime-host"
    elif probe == "domain-label-below-waist":
        first["requirements"][0]["verifierSemantics"]["domainLabel"] = first.get("sourceDomain")
    else:
        raise ValueError(f"unknown probe {probe!r}")
    return obj


def run_probe(probe: str) -> int:
    if probe not in PROBES:
        print(f"unknown canonical-reduction probe {probe!r}", file=sys.stderr)
        return 2
    errors, _ = validate_obj(mutated_fixture(probe))
    if errors:
        print(f"probe-failed-as-expected:{probe}")
        return 1
    print(f"probe unexpectedly passed:{probe}")
    return 0


def selftest() -> int:
    errors, report = validate_obj(load_json(DEFAULT_FIXTURE))
    failures: list[str] = []
    if errors:
        failures.append("committed fixture failed: " + "; ".join(e["code"] for e in errors))
    for probe in sorted(PROBES):
        if run_probe(probe) == 0:
            failures.append(f"probe {probe} did not fail")
    if failures:
        print("canonical-reduction domain-blindness selftest FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    groups = len(report.get("groups", []))
    print(f"canonical-reduction domain-blindness selftest PASS ({groups} group(s); {len(PROBES)} probes fail closed)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate the  S4 canonical-reduction domain-blindness proof")
    ap.add_argument("fixture", nargs="?", default=str(DEFAULT_FIXTURE))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--probe", choices=sorted(PROBES))
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if args.probe:
        return run_probe(args.probe)
    try:
        errors, report = validate_obj(load_json(Path(args.fixture)))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors = [diag("canonical_reduction.io", str(exc))]
        report = {"kind": "neutrino.canonical-reduction-domain-blindness-report", "schemaVersion": 1, "groups": []}
    return print_result(errors, report, as_json=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
