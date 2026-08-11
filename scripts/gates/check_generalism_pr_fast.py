#!/usr/bin/env python3
"""PR-fast consumer gate for the  generalism-result envelope.

This script intentionally does not run, classify, or infer generalism outcomes.
It consumes the shared result envelope validated by
scripts/validators/validate_generalism_result.py and applies the PR-fast policy
needed by :

- the result must be a PR_FAST result;
- schema/provenance validation must pass;
- required adapters and required semantic cases must be non-vacuous;
- SILENT and BROKEN must be absent;
- the envelope must report a passing FAITHFUL profile.

Exit 0 ok / 1 gate or validation failures / 2 usage or I/O.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATORS = REPO_ROOT / "scripts" / "validators"
sys.path.insert(0, str(VALIDATORS))

import validate_generalism_result as result_contract  # noqa: E402

REPORT_KIND = "neutrino.generalism-pr-fast-gate"
REPORT_VERSION = 1
EXPECTED_PROFILE = "PR_FAST"


def diag(code: str, message: str, *, path: str = "$", severity: str = "error") -> dict[str, str]:
    return {"code": code, "severity": severity, "path": path, "message": message}


def _counts(summary: dict[str, Any]) -> dict[str, int]:
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    return {v: counts.get(v, 0) for v in sorted(result_contract.VERDICTS)}


def adapter_case_counts(result: Any) -> dict[str, int]:
    if not isinstance(result, dict):
        return {}
    cases = result.get("cases") if isinstance(result.get("cases"), list) else []
    counts: dict[str, int] = {}
    for case in cases:
        if isinstance(case, dict) and case.get("required") is True and isinstance(case.get("adapterId"), str):
            counts[case["adapterId"]] = counts.get(case["adapterId"], 0) + 1
    return dict(sorted(counts.items()))


def gate_diagnostics(result: Any, validation_diagnostics: list[dict[str, str]]) -> list[dict[str, str]]:
    if validation_diagnostics:
        return [
            diag(
                "generalism.pr_fast.validation",
                "generalism result contract validation must pass before PR-fast gating",
                path="$",
            ),
            *validation_diagnostics,
        ]
    if not isinstance(result, dict):
        return [diag("generalism.pr_fast.schema", "result must be a JSON object")]

    out: list[dict[str, str]] = []
    profile = result.get("executionProfile") if isinstance(result.get("executionProfile"), dict) else {}
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    adapters = result.get("adapters") if isinstance(result.get("adapters"), list) else []
    cases = result.get("cases") if isinstance(result.get("cases"), list) else []
    counts = _counts(summary)
    per_adapter_counts = adapter_case_counts(result)

    if profile.get("name") != EXPECTED_PROFILE:
        out.append(diag("generalism.pr_fast.profile", f"PR-fast gate only accepts {EXPECTED_PROFILE} results", path="$.executionProfile.name"))
    if summary.get("profileStatus") != "PASS":
        out.append(diag("generalism.pr_fast.status", "PR-fast gate requires summary.profileStatus == PASS", path="$.summary.profileStatus"))
    if summary.get("verdict") != "FAITHFUL":
        out.append(diag("generalism.pr_fast.verdict", "PR-fast gate requires summary.verdict == FAITHFUL", path="$.summary.verdict"))
    if counts.get("SILENT", 0) != 0:
        out.append(diag("generalism.pr_fast.silent", "PR-fast gate forbids SILENT cases", path="$.summary.counts.SILENT"))
    if counts.get("BROKEN", 0) != 0:
        out.append(diag("generalism.pr_fast.broken", "PR-fast gate forbids BROKEN cases", path="$.summary.counts.BROKEN"))

    adapter_ids: set[str] = set()
    for i, adapter in enumerate(adapters):
        if not isinstance(adapter, dict) or not isinstance(adapter.get("adapterId"), str):
            continue
        adapter_id = adapter["adapterId"]
        if adapter_id in adapter_ids:
            out.append(diag("generalism.pr_fast.duplicate_adapter", f"duplicate adapterId {adapter_id!r}", path=f"$.adapters[{i}].adapterId"))
        adapter_ids.add(adapter_id)

    case_ids: set[str] = set()
    for i, case in enumerate(cases):
        if not isinstance(case, dict) or not isinstance(case.get("caseId"), str):
            continue
        case_id = case["caseId"]
        if case_id in case_ids:
            out.append(diag("generalism.pr_fast.duplicate_case", f"duplicate caseId {case_id!r}", path=f"$.cases[{i}].caseId"))
        case_ids.add(case_id)

    required_adapter_ids = {
        a.get("adapterId") for a in adapters
        if isinstance(a, dict) and a.get("required") is True
    }
    if not required_adapter_ids:
        out.append(diag("generalism.pr_fast.non_vacuous", "PR-fast gate requires at least one required adapter", path="$.adapters"))
    skipped_required = sorted(
        a.get("adapterId") for a in adapters
        if isinstance(a, dict) and a.get("required") is True and a.get("status") == "SKIPPED"
    )
    for adapter_id in skipped_required:
        out.append(diag("generalism.pr_fast.required_adapter_skipped", f"required adapter {adapter_id!r} was skipped", path="$.adapters"))
    for adapter in adapters:
        if (
            isinstance(adapter, dict)
            and adapter.get("required") is True
            and adapter.get("status") == "RAN"
            and isinstance(adapter.get("adapterId"), str)
            and per_adapter_counts.get(adapter["adapterId"], 0) == 0
        ):
            out.append(diag("generalism.pr_fast.required_adapter_uncovered", f"required adapter {adapter['adapterId']!r} executed zero required cases", path="$.cases"))

    required_cases = [
        c for c in cases
        if isinstance(c, dict) and c.get("required") is True and c.get("adapterId") in required_adapter_ids
    ]
    distinct_required_case_ids = {
        c.get("caseId") for c in required_cases
        if isinstance(c.get("caseId"), str)
    }
    required_floor = profile.get("requiredCaseFloor")
    if not required_cases:
        out.append(diag("generalism.pr_fast.non_vacuous", "PR-fast gate requires at least one required semantic case", path="$.cases"))
    if isinstance(required_floor, int) and len(distinct_required_case_ids) < required_floor:
        out.append(diag("generalism.pr_fast.required_case_floor", f"distinct required case count {len(distinct_required_case_ids)} is below floor {required_floor}", path="$.cases"))
    if summary.get("requiredCasesRun") != len(required_cases):
        out.append(diag("generalism.pr_fast.summary_drift", "summary.requiredCasesRun must equal required cases consumed by the gate", path="$.summary.requiredCasesRun"))

    return sorted(out, key=lambda d: (d["code"], d["path"], d["message"]))


def render_report(result: Any, file_name: str, diagnostics: list[dict[str, str]]) -> dict[str, Any]:
    summary = result.get("summary") if isinstance(result, dict) and isinstance(result.get("summary"), dict) else {}
    profile = result.get("executionProfile") if isinstance(result, dict) and isinstance(result.get("executionProfile"), dict) else {}
    return {
        "schemaVersion": REPORT_VERSION,
        "kind": REPORT_KIND,
        "ok": not diagnostics,
        "file": file_name,
        "runId": result.get("runId") if isinstance(result, dict) else None,
        "profile": profile.get("name"),
        "verdict": summary.get("verdict"),
        "profileStatus": summary.get("profileStatus"),
        "requiredCasesRun": summary.get("requiredCasesRun"),
        "counts": _counts(summary),
        "adapterCaseCounts": adapter_case_counts(result),
        "diagnostics": diagnostics,
    }


def render_markdown(report: dict[str, Any], result: Any) -> str:
    lines = [
        f"# Generalism PR-fast Gate: {report.get('runId') or '<invalid>'}",
        "",
        f"- File: {report.get('file')}",
        f"- Profile: {report.get('profile')}",
        f"- Status: {report.get('profileStatus')}",
        f"- Verdict: {report.get('verdict')}",
        f"- Required cases run: {report.get('requiredCasesRun')}",
        f"- Gate: {'PASS' if report.get('ok') else 'FAIL'}",
        "",
        "## Counts",
        "",
        "| Verdict | Count |",
        "|---|---:|",
    ]
    for verdict, count in sorted((report.get("counts") or {}).items()):
        lines.append(f"| {verdict} | {count} |")
    lines.extend(["", "## Required Case Counts By Adapter", "", "| Adapter | Required cases |", "|---|---:|"])
    adapter_counts = report.get("adapterCaseCounts") if isinstance(report.get("adapterCaseCounts"), dict) else {}
    if adapter_counts:
        for adapter_id, count in sorted(adapter_counts.items()):
            lines.append(f"| {adapter_id} | {count} |")
    else:
        lines.append("| <none> | 0 |")
    lines.extend(["", "## Required Cases", "", "| Case | Adapter | Verdict | Cause |", "|---|---|---|---|"])
    for case in result.get("cases", []) if isinstance(result, dict) and isinstance(result.get("cases"), list) else []:
        if isinstance(case, dict) and case.get("required") is True:
            lines.append(f"| {case.get('caseId', '')} | {case.get('adapterId', '')} | {case.get('verdict', '')} | {case.get('cause', '')} |")
    lines.extend(["", "## Diagnostics", ""])
    diagnostics = report.get("diagnostics") if isinstance(report.get("diagnostics"), list) else []
    if diagnostics:
        for d in diagnostics:
            lines.append(f"- `{d['code']}` at `{d['path']}`: {d['message']}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def load(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    ap = argparse.ArgumentParser(description="Gate a  generalism-result envelope for PR-fast CI")
    ap.add_argument("file", help="generalism-result JSON envelope")
    ap.add_argument("--report-dir", help="directory for retained JSON/Markdown gate reports")
    ap.add_argument("--json", action="store_true", help="print the gate report as JSON")
    args = ap.parse_args()

    path = Path(args.file)
    try:
        result = load(path)
        validation = result_contract.validate(result)
    except (OSError, ValueError) as e:
        result = {}
        validation = [diag("generalism.pr_fast.io", f"cannot read result: {e}")]

    diagnostics = gate_diagnostics(result, validation)
    report = render_report(result, str(path), diagnostics)
    if args.report_dir:
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / "generalism-pr-fast-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (report_dir / "generalism-pr-fast-report.md").write_text(
            render_markdown(report, result),
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif report["ok"]:
        print(f"ok - {args.file}")
    else:
        for d in diagnostics:
            print(f"{d['code']} {d['path']}: {d['message']}", file=sys.stderr)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
