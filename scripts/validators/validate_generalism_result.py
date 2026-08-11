#!/usr/bin/env python3
"""Validate and render the M6 generalism result envelope ().

This is a stdlib-only contract validator. It mirrors the normative schema in
docs/schemas/generalism-result.schema.json and enforces cross-field invariants:

- required adapters cannot be skipped in a passing profile;
- zero required cases cannot pass;
- verdict/cause combinations are stable and non-overlapping;
- external-solc results are downstream compiler compatibility only;
- evidence references build-tools receipts/packages instead of embedding a
  parallel receipt format.

Exit 0 ok / 1 validation failures / 2 usage or I/O.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

KIND = "neutrino.generalism-result"
SCHEMA_VERSION = 1
VERDICTS = {"FAITHFUL", "REFUSED", "SILENT", "BROKEN"}
PROFILE_STATUS = {"PASS", "FAIL"}
PROFILES = {"PR_FAST", "PR_FULL", "NIGHTLY_RELEASE"}
ADAPTER_STATUS = {"RAN", "SKIPPED"}
RAILS = {"translator", "build-tools", "external-solc"}
KINDS = {"semantic", "live-runtime", "external-compiler-compat"}
PROOF_SCOPES = {
    "neu-semantic-correctness",
    "live-runtime-behavior",
    "downstream-compiler-compatibility",
}
CAUSES = {
    "success",
    "governed_refusal",
    "semantic_mismatch",
    "compile_failure",
    "runtime_timeout",
    "missing_optional_tool",
    "missing_required_tool",
    "governed_protocol_limit",
    "substrate_protocol_limit",
    "resource_limit",
    "internal_error",
}
CAUSE_BY_VERDICT = {
    "FAITHFUL": {"success"},
    "REFUSED": {"governed_refusal", "governed_protocol_limit"},
    "SILENT": {"semantic_mismatch"},
    "BROKEN": {
        "compile_failure",
        "runtime_timeout",
        "missing_required_tool",
        "substrate_protocol_limit",
        "resource_limit",
        "internal_error",
    },
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA256_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
M4_BINDING_ID_RE = re.compile(r"^bind-[0-9a-f]{64}$")
REPO_ROOT = Path(__file__).resolve().parents[2]
M4_REPORT_KIND = "neutrino.m4-evidence-verification-report"
M4_REPORT_SCHEMA_VERSION = 1
M4_REPORT_SIGNER_ID = "m4-dev-signer"
M4_REPORT_SIGNATURE_ALG = "ed25519"
M4_REPORT_PUBLIC_KEY_HEX = "9f100c82052396780e2a4043633c139dccb18a2853950484171ceecf4f627612"


def diag(code: str, message: str, *, path: str = "$", severity: str = "error") -> dict[str, str]:
    return {"code": code, "severity": severity, "path": path, "message": message}


def is_nonempty(v: Any) -> bool:
    return isinstance(v, str) and v != ""


def is_sha(v: Any) -> bool:
    return isinstance(v, str) and bool(SHA256_RE.fullmatch(v))


def sha256_digest_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical_json_digest(obj: Any) -> str:
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_digest_bytes(canonical)


def resolve_artifact_ref(ref: Any, path: str, out: list[dict[str, str]]) -> Path | None:
    if not is_nonempty(ref):
        out.append(diag("generalism.missing_field", "artifact ref must be a non-empty string", path=path))
        return None
    p = Path(ref)
    if p.is_absolute() or ".." in p.parts:
        out.append(diag("generalism.evidence_ref", "artifact ref must be a repository-relative path without '..'", path=path))
        return None
    resolved = (REPO_ROOT / p).resolve()
    try:
        common = os.path.commonpath([str(REPO_ROOT), str(resolved)])
    except ValueError:
        common = ""
    if common != str(REPO_ROOT):
        out.append(diag("generalism.evidence_ref", "artifact ref escapes repository root", path=path))
        return None
    if not resolved.is_file():
        out.append(diag("generalism.evidence_ref", f"referenced artifact does not exist: {ref}", path=path))
        return None
    return resolved


def load_artifact(ref: Any, path: str, out: list[dict[str, str]]) -> tuple[dict[str, Any] | None, bytes | None]:
    artifact_path = resolve_artifact_ref(ref, path, out)
    if artifact_path is None:
        return None, None
    try:
        data = artifact_path.read_bytes()
        obj = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        out.append(diag("generalism.evidence_ref", f"cannot read referenced artifact: {e}", path=path))
        return None, None
    if not isinstance(obj, dict):
        out.append(diag("generalism.evidence_ref", "referenced artifact must be a JSON object", path=path))
        return None, data
    return obj, data


def validate_authoritative_report_cli(
    report: dict[str, Any],
    trace_ref: Any,
    package_ref: Any,
    producer_revision: Any,
    out: list[dict[str, str]],
) -> None:
    cli = os.environ.get("NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_CLI")
    expected_revision = os.environ.get("NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_REVISION")
    if not is_nonempty(cli):
        out.append(diag("generalism.evidence_ref", "NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_CLI is required to verify M4 evidence reports", path="$.evidence.verificationReportRef"))
        return
    if not is_nonempty(expected_revision) or not re.fullmatch(r"[0-9a-f]{40}", expected_revision):
        out.append(diag("generalism.evidence_ref", "NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_REVISION must pin a 40-hex build-tools revision", path="$.evidence.verificationReportRef"))
        return
    if producer_revision != expected_revision:
        out.append(diag("generalism.evidence_ref", f"verification report producer.revision {producer_revision!r} must match pinned build-tools revision {expected_revision!r}", path="$.evidence.verificationReportRef"))
        return

    cli_path = Path(cli)
    if not cli_path.is_file():
        out.append(diag("generalism.evidence_ref", f"pinned build-tools verification CLI does not exist: {cli}", path="$.evidence.verificationReportRef"))
        return
    trace_path = resolve_artifact_ref(trace_ref, "$.evidence.verificationReportRef.artifacts.executionTrace.artifactRef", out)
    package_path = resolve_artifact_ref(package_ref, "$.evidence.evidencePackageRef", out)
    if trace_path is None or package_path is None:
        return

    cmd = [
        sys.executable,
        str(cli_path),
        "--trace",
        str(trace_path),
        "--evidence",
        str(package_path),
        "--artifact-root",
        str(REPO_ROOT),
        "--producer-revision",
        expected_revision,
    ]
    try:
        proc = subprocess.run(cmd, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        out.append(diag("generalism.evidence_ref", f"failed to execute pinned build-tools verification CLI: {e}", path="$.evidence.verificationReportRef"))
        return
    if proc.returncode != 0:
        details = (proc.stderr or proc.stdout or "").strip()
        out.append(diag("generalism.evidence_ref", f"pinned build-tools verification CLI rejected the referenced artifacts: {details}", path="$.evidence.verificationReportRef"))
        return
    try:
        generated = json.loads(proc.stdout)
    except ValueError as e:
        out.append(diag("generalism.evidence_ref", f"pinned build-tools verification CLI emitted invalid JSON: {e}", path="$.evidence.verificationReportRef"))
        return
    if generated != report:
        out.append(diag("generalism.evidence_ref", "referenced verification report must match the pinned build-tools CLI output", path="$.evidence.verificationReportRef"))


def validate_verification_report(ev: dict[str, Any], out: list[dict[str, str]]) -> None:
    report, report_bytes = load_artifact(ev.get("verificationReportRef"), "$.evidence.verificationReportRef", out)
    if report is None or report_bytes is None:
        return
    if sha256_digest_bytes(report_bytes) != ev.get("verificationReportDigest"):
        out.append(diag("generalism.hash", "verificationReportDigest must match referenced verification report bytes", path="$.evidence.verificationReportDigest"))
    if report.get("kind") != M4_REPORT_KIND:
        out.append(diag("generalism.evidence_kind", f"verification report kind must be {M4_REPORT_KIND!r}", path="$.evidence.verificationReportRef"))
    if report.get("schemaVersion") != M4_REPORT_SCHEMA_VERSION:
        out.append(diag("generalism.schema", "verification report schemaVersion must be 1", path="$.evidence.verificationReportRef"))
    if report.get("ok") is not True:
        out.append(diag("generalism.evidence_ref", "verification report must have ok: true", path="$.evidence.verificationReportRef"))
    attestation = report.get("attestation") if isinstance(report.get("attestation"), dict) else {}
    if not attestation:
        out.append(diag("generalism.evidence_ref", "verification report must carry a signed attestation", path="$.evidence.verificationReportRef"))
    else:
        result_attestation = ev.get("verificationReportAttestation") if isinstance(ev.get("verificationReportAttestation"), dict) else {}
        if attestation != result_attestation:
            out.append(diag("generalism.evidence_ref", "verificationReportAttestation must match referenced verification report attestation", path="$.evidence.verificationReportAttestation"))
        expected_attestation = {
            "signerId": M4_REPORT_SIGNER_ID,
            "signatureAlg": M4_REPORT_SIGNATURE_ALG,
            "publicKey": M4_REPORT_PUBLIC_KEY_HEX,
        }
        for key, expected_value in expected_attestation.items():
            if attestation.get(key) != expected_value:
                out.append(diag("generalism.evidence_ref", f"verification report attestation.{key} must be {expected_value!r}", path=f"$.evidence.verificationReportRef.attestation.{key}"))
        if not (isinstance(attestation.get("payloadDigest"), str) and SHA256_DIGEST_RE.fullmatch(attestation["payloadDigest"])):
            out.append(diag("generalism.hash", "verification report attestation.payloadDigest must match sha256:<64 hex>", path="$.evidence.verificationReportRef.attestation.payloadDigest"))
        if not (isinstance(attestation.get("signature"), str) and re.fullmatch(r"[0-9a-f]{128}", attestation["signature"])):
            out.append(diag("generalism.hash", "verification report attestation.signature must be 128 lowercase hex characters", path="$.evidence.verificationReportRef.attestation.signature"))
    producer = report.get("producer") if isinstance(report.get("producer"), dict) else {}
    if producer.get("name") != "neutrino-build-tools":
        out.append(diag("generalism.evidence_ref", "verification report producer.name must be neutrino-build-tools", path="$.evidence.verificationReportRef"))
    if not (isinstance(producer.get("revision"), str) and re.fullmatch(r"[0-9a-f]{40}", producer["revision"])):
        out.append(diag("generalism.evidence_ref", "verification report producer.revision must be a pinned 40-hex git revision", path="$.evidence.verificationReportRef"))
    checks = report.get("checks")
    required_checks = {"m4.verify_evidence", "m4.validate_receipt"}
    if not (isinstance(checks, list) and required_checks <= set(checks)):
        out.append(diag("generalism.evidence_ref", "verification report must include m4.verify_evidence and m4.validate_receipt checks", path="$.evidence.verificationReportRef"))
    artifacts = report.get("artifacts") if isinstance(report.get("artifacts"), dict) else {}
    receipt = artifacts.get("bindingReceipt") if isinstance(artifacts.get("bindingReceipt"), dict) else {}
    package = artifacts.get("evidencePackage") if isinstance(artifacts.get("evidencePackage"), dict) else {}
    trace = artifacts.get("executionTrace") if isinstance(artifacts.get("executionTrace"), dict) else {}
    expected = {
        "$.evidence.bindingReceiptArtifactRef": (receipt.get("artifactRef"), ev.get("bindingReceiptArtifactRef")),
        "$.evidence.bindingReceiptKind": (receipt.get("kind"), ev.get("bindingReceiptKind")),
        "$.evidence.bindingReceiptSchemaVersion": (receipt.get("schemaVersion"), ev.get("bindingReceiptSchemaVersion")),
        "$.evidence.bindingReceiptRef": (receipt.get("bindingId"), ev.get("bindingReceiptRef")),
        "$.evidence.bindingReceiptDigest": (receipt.get("digest"), ev.get("bindingReceiptDigest")),
        "$.evidence.evidencePackageRef": (package.get("artifactRef"), ev.get("evidencePackageRef")),
        "$.evidence.evidencePackageKind": (package.get("kind"), ev.get("evidencePackageKind")),
        "$.evidence.evidencePackageSchemaVersion": (package.get("schemaVersion"), ev.get("evidencePackageSchemaVersion")),
        "$.evidence.evidencePackageDigest": (package.get("digest"), ev.get("evidencePackageDigest")),
        "$.evidence.evidencePackageTraceSha256": (package.get("traceSha256"), ev.get("evidencePackageTraceSha256")),
    }
    for path, (reported, actual) in expected.items():
        if reported != actual:
            out.append(diag("generalism.evidence_ref", f"verification report value {reported!r} must match result value {actual!r}", path=path))
    signer = ev.get("evidencePackageSigner") if isinstance(ev.get("evidencePackageSigner"), dict) else {}
    reported_signer = package.get("signer") if isinstance(package.get("signer"), dict) else {}
    for k in ("id", "signatureAlg", "publicKey"):
        if reported_signer.get(k) != signer.get(k):
            out.append(diag("generalism.evidence_ref", f"verification report signer.{k} must match result signer.{k}", path=f"$.evidence.evidencePackageSigner.{k}"))
    if trace.get("bindingReceiptRef") != ev.get("bindingReceiptRef"):
        out.append(diag("generalism.evidence_ref", "verification report trace.bindingReceiptRef must match result bindingReceiptRef", path="$.evidence.bindingReceiptRef"))
    if trace.get("bindingReceiptDigest") != ev.get("bindingReceiptDigest"):
        out.append(diag("generalism.hash", "verification report trace.bindingReceiptDigest must match result bindingReceiptDigest", path="$.evidence.bindingReceiptDigest"))
    validate_authoritative_report_cli(
        report,
        trace.get("artifactRef"),
        ev.get("evidencePackageRef"),
        producer.get("revision"),
        out,
    )



def validate_component(obj: Any, path: str, out: list[dict[str, str]]) -> None:
    allowed = {"name", "version", "revision", "imageDigest"}
    if not isinstance(obj, dict):
        out.append(diag("generalism.schema", "component identity must be an object", path=path))
        return
    for k in sorted(set(obj) - allowed):
        out.append(diag("generalism.unknown_field", f"unknown component field {k!r}", path=f"{path}.{k}"))
    for k in ("name", "version", "revision"):
        if not is_nonempty(obj.get(k)):
            out.append(diag("generalism.missing_field", f"component.{k} must be a non-empty string", path=f"{path}.{k}"))
    if "imageDigest" in obj and not (isinstance(obj["imageDigest"], str) and SHA256_DIGEST_RE.fullmatch(obj["imageDigest"])):
        out.append(diag("generalism.schema", "imageDigest must match sha256:<64 hex>", path=f"{path}.imageDigest"))


def validate_hash_map(obj: Any, path: str, out: list[dict[str, str]]) -> None:
    if not isinstance(obj, dict) or not obj:
        out.append(diag("generalism.schema", "artifactHashes must be a non-empty object", path=path))
        return
    for k, v in sorted(obj.items()):
        if not is_nonempty(k) or not is_sha(v):
            out.append(diag("generalism.hash", "artifact hash entries must be non-empty keys with 64-hex values", path=f"{path}.{k}"))


def validate_shape(obj: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(obj, dict):
        return [diag("generalism.schema", "top-level result must be a JSON object")]
    allowed = {
        "schemaVersion",
        "kind",
        "runId",
        "capability",
        "semanticProfile",
        "executionProfile",
        "provenance",
        "adapters",
        "cases",
        "summary",
        "evidence",
    }
    required = allowed
    for k in sorted(set(obj) - allowed):
        out.append(diag("generalism.unknown_field", f"unknown field {k!r}", path=f"$.{k}"))
    for k in sorted(required - set(obj)):
        out.append(diag("generalism.missing_field", f"missing {k!r}", path=f"$.{k}"))
    if obj.get("schemaVersion") != SCHEMA_VERSION:
        out.append(diag("generalism.schema_version", f"schemaVersion must be {SCHEMA_VERSION}", path="$.schemaVersion"))
    if obj.get("kind") != KIND:
        out.append(diag("generalism.kind", f"kind must be {KIND!r}", path="$.kind"))
    if not is_nonempty(obj.get("runId")):
        out.append(diag("generalism.missing_field", "runId must be a non-empty string", path="$.runId"))

    cap = obj.get("capability")
    if not isinstance(cap, dict):
        out.append(diag("generalism.schema", "capability must be an object", path="$.capability"))
    else:
        cap_allowed = {"id", "version", "sourceHash", "specHash", "scenarioHash", "artifactHashes"}
        for k in sorted(set(cap) - cap_allowed):
            out.append(diag("generalism.unknown_field", f"unknown capability field {k!r}", path=f"$.capability.{k}"))
        for k in ("id", "version"):
            if not is_nonempty(cap.get(k)):
                out.append(diag("generalism.missing_field", f"capability.{k} must be a non-empty string", path=f"$.capability.{k}"))
        for k in ("sourceHash", "specHash", "scenarioHash"):
            if not is_sha(cap.get(k)):
                out.append(diag("generalism.hash", f"capability.{k} must be 64 lowercase hex", path=f"$.capability.{k}"))
        validate_hash_map(cap.get("artifactHashes"), "$.capability.artifactHashes", out)

    sem = obj.get("semanticProfile")
    if not isinstance(sem, dict):
        out.append(diag("generalism.schema", "semanticProfile must be an object", path="$.semanticProfile"))
    else:
        for k in sorted(set(sem) - {"id", "version"}):
            out.append(diag("generalism.unknown_field", f"unknown semanticProfile field {k!r}", path=f"$.semanticProfile.{k}"))
        for k in ("id", "version"):
            if not is_nonempty(sem.get(k)):
                out.append(diag("generalism.missing_field", f"semanticProfile.{k} must be a non-empty string", path=f"$.semanticProfile.{k}"))

    prof = obj.get("executionProfile")
    if not isinstance(prof, dict):
        out.append(diag("generalism.schema", "executionProfile must be an object", path="$.executionProfile"))
    else:
        for k in sorted(set(prof) - {"name", "requiredAdapters", "optionalAdapters", "requiredCaseFloor"}):
            out.append(diag("generalism.unknown_field", f"unknown executionProfile field {k!r}", path=f"$.executionProfile.{k}"))
        if prof.get("name") not in PROFILES:
            out.append(diag("generalism.schema", f"executionProfile.name must be one of {sorted(PROFILES)}", path="$.executionProfile.name"))
        for k in ("requiredAdapters", "optionalAdapters"):
            if not isinstance(prof.get(k), list) or any(not is_nonempty(v) for v in prof.get(k, [])):
                out.append(diag("generalism.schema", f"executionProfile.{k} must be an array of non-empty strings", path=f"$.executionProfile.{k}"))
            elif len(set(prof[k])) != len(prof[k]):
                out.append(diag("generalism.schema", f"executionProfile.{k} must not contain duplicates", path=f"$.executionProfile.{k}"))
        floor = prof.get("requiredCaseFloor")
        if not (isinstance(floor, int) and not isinstance(floor, bool) and floor >= 1):
            out.append(diag("generalism.schema", "executionProfile.requiredCaseFloor must be an integer >= 1", path="$.executionProfile.requiredCaseFloor"))

    prov = obj.get("provenance")
    if not isinstance(prov, dict):
        out.append(diag("generalism.schema", "provenance must be an object", path="$.provenance"))
    else:
        for k in sorted(set(prov) - {"translator", "backends", "tools", "runtimes", "commands", "configurationHash"}):
            out.append(diag("generalism.unknown_field", f"unknown provenance field {k!r}", path=f"$.provenance.{k}"))
        validate_component(prov.get("translator"), "$.provenance.translator", out)
        for key in ("backends", "tools", "runtimes"):
            vals = prov.get(key)
            if not isinstance(vals, list):
                out.append(diag("generalism.schema", f"provenance.{key} must be an array", path=f"$.provenance.{key}"))
            elif key == "backends" and not vals:
                out.append(diag("generalism.schema", "provenance.backends must not be empty", path=f"$.provenance.{key}"))
            else:
                for i, comp in enumerate(vals):
                    validate_component(comp, f"$.provenance.{key}[{i}]", out)
        commands = prov.get("commands")
        if not isinstance(commands, list) or not commands:
            out.append(diag("generalism.schema", "provenance.commands must be a non-empty array", path="$.provenance.commands"))
        else:
            for i, cmd in enumerate(commands):
                if not isinstance(cmd, dict):
                    out.append(diag("generalism.schema", "command must be an object", path=f"$.provenance.commands[{i}]"))
                    continue
                for k in sorted(set(cmd) - {"name", "argv"}):
                    out.append(diag("generalism.unknown_field", f"unknown command field {k!r}", path=f"$.provenance.commands[{i}].{k}"))
                if not is_nonempty(cmd.get("name")):
                    out.append(diag("generalism.missing_field", "command.name must be a non-empty string", path=f"$.provenance.commands[{i}].name"))
                if not isinstance(cmd.get("argv"), list) or not cmd["argv"] or any(not is_nonempty(v) for v in cmd["argv"]):
                    out.append(diag("generalism.schema", "command.argv must be a non-empty string array", path=f"$.provenance.commands[{i}].argv"))
        if not is_sha(prov.get("configurationHash")):
            out.append(diag("generalism.hash", "provenance.configurationHash must be 64 lowercase hex", path="$.provenance.configurationHash"))

    for i, adapter in enumerate(obj.get("adapters") if isinstance(obj.get("adapters"), list) else []):
        if not isinstance(adapter, dict):
            out.append(diag("generalism.schema", "adapter must be an object", path=f"$.adapters[{i}]"))
            continue
        allowed_adapter = {"adapterId", "rail", "kind", "required", "status", "skipReason", "proofScope"}
        for k in sorted(set(adapter) - allowed_adapter):
            out.append(diag("generalism.unknown_field", f"unknown adapter field {k!r}", path=f"$.adapters[{i}].{k}"))
        if not is_nonempty(adapter.get("adapterId")):
            out.append(diag("generalism.missing_field", "adapterId must be a non-empty string", path=f"$.adapters[{i}].adapterId"))
        if adapter.get("rail") not in RAILS:
            out.append(diag("generalism.schema", f"rail must be one of {sorted(RAILS)}", path=f"$.adapters[{i}].rail"))
        if adapter.get("kind") not in KINDS:
            out.append(diag("generalism.schema", f"kind must be one of {sorted(KINDS)}", path=f"$.adapters[{i}].kind"))
        if not isinstance(adapter.get("required"), bool):
            out.append(diag("generalism.schema", "required must be boolean", path=f"$.adapters[{i}].required"))
        if adapter.get("status") not in ADAPTER_STATUS:
            out.append(diag("generalism.schema", f"status must be one of {sorted(ADAPTER_STATUS)}", path=f"$.adapters[{i}].status"))
        if adapter.get("proofScope") not in PROOF_SCOPES:
            out.append(diag("generalism.schema", f"proofScope must be one of {sorted(PROOF_SCOPES)}", path=f"$.adapters[{i}].proofScope"))
        if "skipReason" in adapter and adapter.get("skipReason") not in CAUSES:
            out.append(diag("generalism.schema", f"skipReason must be one of {sorted(CAUSES)}", path=f"$.adapters[{i}].skipReason"))
    if not isinstance(obj.get("adapters"), list) or not obj.get("adapters"):
        out.append(diag("generalism.schema", "adapters must be a non-empty array", path="$.adapters"))

    cases = obj.get("cases")
    if not isinstance(cases, list):
        out.append(diag("generalism.schema", "cases must be an array", path="$.cases"))
    else:
        for i, case in enumerate(cases):
            if not isinstance(case, dict):
                out.append(diag("generalism.schema", "case must be an object", path=f"$.cases[{i}]"))
                continue
            allowed_case = {"caseId", "adapterId", "required", "verdict", "cause", "semanticObservations", "environmentMetrics"}
            for k in sorted(set(case) - allowed_case):
                out.append(diag("generalism.unknown_field", f"unknown case field {k!r}", path=f"$.cases[{i}].{k}"))
            for k in ("caseId", "adapterId"):
                if not is_nonempty(case.get(k)):
                    out.append(diag("generalism.missing_field", f"{k} must be a non-empty string", path=f"$.cases[{i}].{k}"))
            if not isinstance(case.get("required"), bool):
                out.append(diag("generalism.schema", "required must be boolean", path=f"$.cases[{i}].required"))
            if case.get("verdict") not in VERDICTS:
                out.append(diag("generalism.schema", f"verdict must be one of {sorted(VERDICTS)}", path=f"$.cases[{i}].verdict"))
            if case.get("cause") is not None and case.get("cause") not in CAUSES:
                out.append(diag("generalism.schema", f"cause must be one of {sorted(CAUSES)} or null", path=f"$.cases[{i}].cause"))
            for k in ("semanticObservations", "environmentMetrics"):
                if not isinstance(case.get(k), dict):
                    out.append(diag("generalism.schema", f"{k} must be an object", path=f"$.cases[{i}].{k}"))

    summary = obj.get("summary")
    if not isinstance(summary, dict):
        out.append(diag("generalism.schema", "summary must be an object", path="$.summary"))
    else:
        for k in sorted(set(summary) - {"verdict", "profileStatus", "requiredCasesRun", "counts"}):
            out.append(diag("generalism.unknown_field", f"unknown summary field {k!r}", path=f"$.summary.{k}"))
        if summary.get("verdict") not in VERDICTS:
            out.append(diag("generalism.schema", f"summary.verdict must be one of {sorted(VERDICTS)}", path="$.summary.verdict"))
        if summary.get("profileStatus") not in PROFILE_STATUS:
            out.append(diag("generalism.schema", "summary.profileStatus must be PASS or FAIL", path="$.summary.profileStatus"))
        if not (isinstance(summary.get("requiredCasesRun"), int) and not isinstance(summary.get("requiredCasesRun"), bool) and summary["requiredCasesRun"] >= 0):
            out.append(diag("generalism.schema", "summary.requiredCasesRun must be a non-negative integer", path="$.summary.requiredCasesRun"))
        counts = summary.get("counts")
        if not isinstance(counts, dict):
            out.append(diag("generalism.schema", "summary.counts must be an object", path="$.summary.counts"))
        else:
            for verdict in sorted(VERDICTS):
                if not (isinstance(counts.get(verdict), int) and not isinstance(counts.get(verdict), bool) and counts[verdict] >= 0):
                    out.append(diag("generalism.schema", f"summary.counts.{verdict} must be a non-negative integer", path=f"$.summary.counts.{verdict}"))
            for k in sorted(set(counts) - VERDICTS):
                out.append(diag("generalism.unknown_field", f"unknown count {k!r}", path=f"$.summary.counts.{k}"))

    ev = obj.get("evidence")
    if not isinstance(ev, dict):
        out.append(diag("generalism.schema", "evidence must be an object", path="$.evidence"))
    else:
        evidence_fields = {
            "bindingReceiptKind",
            "bindingReceiptSchemaVersion",
            "bindingReceiptArtifactRef",
            "bindingReceiptRef",
            "bindingReceiptDigest",
            "evidencePackageKind",
            "evidencePackageSchemaVersion",
            "evidencePackageRef",
            "evidencePackageDigest",
            "evidencePackageTraceSha256",
            "evidencePackageSigner",
            "verificationReportRef",
            "verificationReportDigest",
            "verificationReportAttestation",
        }
        for k in sorted(set(ev) - evidence_fields):
            out.append(diag("generalism.unknown_field", f"unknown evidence field {k!r}", path=f"$.evidence.{k}"))
        for k in ("bindingReceiptKind", "bindingReceiptArtifactRef", "bindingReceiptRef", "evidencePackageKind",
                  "evidencePackageRef", "verificationReportRef"):
            if not is_nonempty(ev.get(k)):
                out.append(diag("generalism.missing_field", f"evidence.{k} must be a non-empty string", path=f"$.evidence.{k}"))
        if ev.get("bindingReceiptKind") != "neutrino.m4-binding-receipt":
            out.append(diag("generalism.evidence_kind", "bindingReceiptKind must be 'neutrino.m4-binding-receipt'", path="$.evidence.bindingReceiptKind"))
        if ev.get("evidencePackageKind") != "neutrino.m4-evidence-package":
            out.append(diag("generalism.evidence_kind", "evidencePackageKind must be 'neutrino.m4-evidence-package'", path="$.evidence.evidencePackageKind"))
        for k in ("bindingReceiptSchemaVersion", "evidencePackageSchemaVersion"):
            if ev.get(k) != 1:
                out.append(diag("generalism.schema", f"evidence.{k} must be 1", path=f"$.evidence.{k}"))
        for k in ("bindingReceiptDigest", "evidencePackageDigest", "verificationReportDigest"):
            if not (isinstance(ev.get(k), str) and SHA256_DIGEST_RE.fullmatch(ev[k])):
                out.append(diag("generalism.hash", f"evidence.{k} must match sha256:<64 hex>", path=f"$.evidence.{k}"))
        if not (isinstance(ev.get("bindingReceiptRef"), str) and M4_BINDING_ID_RE.fullmatch(ev["bindingReceiptRef"])):
            out.append(diag("generalism.evidence_ref", "bindingReceiptRef must be an M4 bindingId 'bind-<64 hex>'", path="$.evidence.bindingReceiptRef"))
        if not is_sha(ev.get("evidencePackageTraceSha256")):
            out.append(diag("generalism.hash", "evidencePackageTraceSha256 must be 64 lowercase hex", path="$.evidence.evidencePackageTraceSha256"))
        signer = ev.get("evidencePackageSigner")
        if not isinstance(signer, dict):
            out.append(diag("generalism.schema", "evidencePackageSigner must be an object", path="$.evidence.evidencePackageSigner"))
        else:
            for k in sorted(set(signer) - {"id", "signatureAlg", "publicKey"}):
                out.append(diag("generalism.unknown_field", f"unknown evidencePackageSigner field {k!r}", path=f"$.evidence.evidencePackageSigner.{k}"))
            if not is_nonempty(signer.get("id")):
                out.append(diag("generalism.missing_field", "evidencePackageSigner.id must be a non-empty string", path="$.evidence.evidencePackageSigner.id"))
            if signer.get("signatureAlg") != "ed25519":
                out.append(diag("generalism.schema", "evidencePackageSigner.signatureAlg must be 'ed25519'", path="$.evidence.evidencePackageSigner.signatureAlg"))
            if not is_sha(signer.get("publicKey")):
                out.append(diag("generalism.hash", "evidencePackageSigner.publicKey must be 64 lowercase hex", path="$.evidence.evidencePackageSigner.publicKey"))
        report_attestation = ev.get("verificationReportAttestation")
        if not isinstance(report_attestation, dict):
            out.append(diag("generalism.schema", "verificationReportAttestation must be an object", path="$.evidence.verificationReportAttestation"))
        else:
            for k in sorted(set(report_attestation) - {"signerId", "signatureAlg", "publicKey", "payloadDigest", "signature"}):
                out.append(diag("generalism.unknown_field", f"unknown verificationReportAttestation field {k!r}", path=f"$.evidence.verificationReportAttestation.{k}"))
            if report_attestation.get("signerId") != M4_REPORT_SIGNER_ID:
                out.append(diag("generalism.evidence_ref", f"verificationReportAttestation.signerId must be {M4_REPORT_SIGNER_ID!r}", path="$.evidence.verificationReportAttestation.signerId"))
            if report_attestation.get("signatureAlg") != M4_REPORT_SIGNATURE_ALG:
                out.append(diag("generalism.schema", "verificationReportAttestation.signatureAlg must be 'ed25519'", path="$.evidence.verificationReportAttestation.signatureAlg"))
            if report_attestation.get("publicKey") != M4_REPORT_PUBLIC_KEY_HEX:
                out.append(diag("generalism.hash", "verificationReportAttestation.publicKey must match the pinned build-tools report signer", path="$.evidence.verificationReportAttestation.publicKey"))
            if not (isinstance(report_attestation.get("payloadDigest"), str) and SHA256_DIGEST_RE.fullmatch(report_attestation["payloadDigest"])):
                out.append(diag("generalism.hash", "verificationReportAttestation.payloadDigest must match sha256:<64 hex>", path="$.evidence.verificationReportAttestation.payloadDigest"))
            if not (isinstance(report_attestation.get("signature"), str) and re.fullmatch(r"[0-9a-f]{128}", report_attestation["signature"])):
                out.append(diag("generalism.hash", "verificationReportAttestation.signature must be 128 lowercase hex characters", path="$.evidence.verificationReportAttestation.signature"))
        package, package_bytes = load_artifact(ev.get("evidencePackageRef"), "$.evidence.evidencePackageRef", out)
        if package is not None and package_bytes is not None:
            if sha256_digest_bytes(package_bytes) != ev.get("evidencePackageDigest"):
                out.append(diag("generalism.hash", "evidencePackageDigest must match referenced evidence package bytes", path="$.evidence.evidencePackageDigest"))
            if package.get("kind") != ev.get("evidencePackageKind"):
                out.append(diag("generalism.evidence_kind", "evidencePackageKind must match referenced package.kind", path="$.evidence.evidencePackageKind"))
            if package.get("schemaVersion") != ev.get("evidencePackageSchemaVersion"):
                out.append(diag("generalism.schema", "evidencePackageSchemaVersion must match referenced package.schemaVersion", path="$.evidence.evidencePackageSchemaVersion"))
            trace = package.get("trace") if isinstance(package.get("trace"), dict) else {}
            if trace.get("sha256") != ev.get("evidencePackageTraceSha256"):
                out.append(diag("generalism.hash", "evidencePackageTraceSha256 must match referenced package.trace.sha256", path="$.evidence.evidencePackageTraceSha256"))
            package_signer = package.get("signer") if isinstance(package.get("signer"), dict) else {}
            signer = ev.get("evidencePackageSigner") if isinstance(ev.get("evidencePackageSigner"), dict) else {}
            for k in ("id", "signatureAlg", "publicKey"):
                if package_signer.get(k) != signer.get(k):
                    out.append(diag("generalism.evidence_ref", f"evidencePackageSigner.{k} must match referenced package.signer.{k}", path=f"$.evidence.evidencePackageSigner.{k}"))
        receipt, _receipt_bytes = load_artifact(ev.get("bindingReceiptArtifactRef"), "$.evidence.bindingReceiptArtifactRef", out)
        if receipt is not None:
            if receipt.get("kind") != ev.get("bindingReceiptKind"):
                out.append(diag("generalism.evidence_kind", "bindingReceiptKind must match referenced receipt.kind", path="$.evidence.bindingReceiptKind"))
            if receipt.get("schemaVersion") != ev.get("bindingReceiptSchemaVersion"):
                out.append(diag("generalism.schema", "bindingReceiptSchemaVersion must match referenced receipt.schemaVersion", path="$.evidence.bindingReceiptSchemaVersion"))
            if receipt.get("bindingId") != ev.get("bindingReceiptRef"):
                out.append(diag("generalism.evidence_ref", "bindingReceiptRef must match referenced receipt.bindingId", path="$.evidence.bindingReceiptRef"))
            if canonical_json_digest(receipt) != ev.get("bindingReceiptDigest"):
                out.append(diag("generalism.hash", "bindingReceiptDigest must match referenced receipt canonical digest", path="$.evidence.bindingReceiptDigest"))
        validate_verification_report(ev, out)
        validate_result_binding(obj, ev, out)
    return out


def validate_result_binding(obj: dict[str, Any], ev: dict[str, Any], out: list[dict[str, str]]) -> None:
    """Bind the signed evidence to THIS result: the execution trace's signed `comparisonPayload.
    resultDigest` must equal the canonical digest of the enclosing envelope (minus its evidence
    block). A valid but grafted evidence block from another envelope therefore fails closed."""
    report, _ = load_artifact(ev.get("verificationReportRef"), "$.evidence.verificationReportRef", out)
    if not isinstance(report, dict):
        return
    arts = report.get("artifacts") if isinstance(report.get("artifacts"), dict) else {}
    trace_meta = arts.get("executionTrace") if isinstance(arts.get("executionTrace"), dict) else {}
    trace, _ = load_artifact(trace_meta.get("artifactRef"),
                             "$.evidence.verificationReportRef.artifacts.executionTrace.artifactRef", out)
    if not isinstance(trace, dict):
        return
    payload = trace.get("comparisonPayload") if isinstance(trace.get("comparisonPayload"), dict) else {}
    bound = payload.get("resultDigest")
    expected = canonical_json_digest({k: v for k, v in obj.items() if k != "evidence"})
    if bound != expected:
        out.append(diag("generalism.evidence_binding",
                        f"signed evidence resultDigest {bound!r} is not bound to this result "
                        f"(expected {expected!r})", path="$.evidence"))


def validate_invariants(obj: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    adapters = obj.get("adapters") if isinstance(obj.get("adapters"), list) else []
    cases = obj.get("cases") if isinstance(obj.get("cases"), list) else []
    profile = obj.get("executionProfile") if isinstance(obj.get("executionProfile"), dict) else {}
    summary = obj.get("summary") if isinstance(obj.get("summary"), dict) else {}

    adapter_by_id = {
        a.get("adapterId"): a for a in adapters
        if isinstance(a, dict) and is_nonempty(a.get("adapterId"))
    }
    required_adapters = set(profile.get("requiredAdapters") if isinstance(profile.get("requiredAdapters"), list) else [])
    optional_adapters = set(profile.get("optionalAdapters") if isinstance(profile.get("optionalAdapters"), list) else [])

    overlap = required_adapters & optional_adapters
    for adapter_id in sorted(overlap):
        out.append(diag("generalism.profile_overlap", f"adapter {adapter_id!r} is both required and optional", path="$.executionProfile"))

    for adapter_id in sorted(required_adapters | optional_adapters):
        if adapter_id not in adapter_by_id:
            out.append(diag("generalism.adapter_missing", f"execution profile names missing adapter {adapter_id!r}", path="$.adapters"))

    for adapter_id, adapter in sorted(adapter_by_id.items()):
        if adapter.get("required") and adapter_id not in required_adapters:
            out.append(diag("generalism.profile_membership", f"required adapter {adapter_id!r} is absent from executionProfile.requiredAdapters", path="$.executionProfile.requiredAdapters"))
        if adapter_id in required_adapters and adapter.get("required") is not True:
            out.append(diag("generalism.profile_membership", f"profile-required adapter {adapter_id!r} must declare required=true", path="$.adapters"))
        if adapter_id in optional_adapters and adapter.get("required") is not False:
            out.append(diag("generalism.profile_membership", f"profile-optional adapter {adapter_id!r} must declare required=false", path="$.adapters"))
        if not adapter.get("required") and adapter_id not in optional_adapters and adapter_id not in required_adapters:
            out.append(diag("generalism.profile_membership", f"optional adapter {adapter_id!r} is absent from executionProfile.optionalAdapters", path="$.executionProfile.optionalAdapters"))
        if adapter.get("status") == "SKIPPED" and "skipReason" not in adapter:
            out.append(diag("generalism.skip_reason", f"skipped adapter {adapter_id!r} must carry skipReason", path="$.adapters"))
        if adapter.get("status") == "RAN" and "skipReason" in adapter:
            out.append(diag("generalism.skip_reason", f"ran adapter {adapter_id!r} must not carry skipReason", path="$.adapters"))
        if adapter.get("required") and adapter.get("status") == "SKIPPED":
            out.append(diag("generalism.required_adapter_skipped", f"required adapter {adapter_id!r} was skipped", path="$.adapters"))
        if adapter.get("rail") == "external-solc" and adapter.get("proofScope") != "downstream-compiler-compatibility":
            out.append(diag("generalism.external_solc_scope", "external-solc adapters are downstream compiler compatibility only", path="$.adapters"))

    semantic_adapter_ids = {
        adapter_id for adapter_id, adapter in adapter_by_id.items()
        if adapter.get("proofScope") != "downstream-compiler-compatibility"
    }
    required_cases = [
        c for c in cases
        if isinstance(c, dict) and c.get("required") and c.get("adapterId") in semantic_adapter_ids
    ]
    actual_required_count = len(required_cases)
    floor = profile.get("requiredCaseFloor")
    if isinstance(floor, int) and actual_required_count < floor:
        out.append(diag("generalism.required_case_floor", f"required case count {actual_required_count} is below floor {floor}", path="$.cases"))
    if summary.get("requiredCasesRun") != actual_required_count:
        out.append(diag("generalism.summary_drift", f"summary.requiredCasesRun {summary.get('requiredCasesRun')} != actual required cases {actual_required_count}", path="$.summary.requiredCasesRun"))
    if summary.get("profileStatus") == "PASS" and actual_required_count == 0:
        out.append(diag("generalism.vacuous_pass", "a passing profile must run at least one required case", path="$.summary.profileStatus"))

    semantic_counts = {v: 0 for v in VERDICTS}
    all_counts = {v: 0 for v in VERDICTS}
    for i, case in enumerate(cases):
        if not isinstance(case, dict):
            continue
        verdict = case.get("verdict")
        cause = case.get("cause")
        adapter_id = case.get("adapterId")
        if adapter_id not in adapter_by_id:
            out.append(diag("generalism.case_adapter_missing", f"case references unknown adapter {adapter_id!r}", path=f"$.cases[{i}].adapterId"))
        adapter = adapter_by_id.get(adapter_id, {})
        if adapter.get("status") == "SKIPPED":
            out.append(diag("generalism.case_adapter_skipped", f"case belongs to skipped adapter {adapter_id!r}", path=f"$.cases[{i}].adapterId"))
        is_semantic_case = adapter.get("proofScope") != "downstream-compiler-compatibility"
        if verdict in all_counts:
            all_counts[verdict] += 1
        if verdict in semantic_counts and is_semantic_case:
            semantic_counts[verdict] += 1
        if verdict in CAUSE_BY_VERDICT:
            allowed = CAUSE_BY_VERDICT[verdict]
            if cause not in allowed:
                out.append(diag("generalism.verdict_cause", f"{verdict} cannot carry cause {cause!r}; expected one of {sorted(allowed)}", path=f"$.cases[{i}].cause"))
        if adapter.get("rail") == "external-solc" and adapter.get("proofScope") != "downstream-compiler-compatibility":
            out.append(diag("generalism.external_solc_scope", "external-solc compatibility cannot be a .neu semantic proof", path=f"$.cases[{i}].adapterId"))

    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    for verdict, count in sorted(semantic_counts.items()):
        if counts.get(verdict) != count:
            out.append(diag("generalism.summary_drift", f"summary.counts.{verdict} {counts.get(verdict)} != observed {count}", path=f"$.summary.counts.{verdict}"))

    if summary.get("profileStatus") == "PASS":
        if any(a.get("required") and a.get("status") == "SKIPPED" for a in adapter_by_id.values()):
            out.append(diag("generalism.required_adapter_skipped_pass", "a profile with skipped required adapters cannot pass", path="$.summary.profileStatus"))
        if all_counts["SILENT"] or all_counts["BROKEN"]:
            out.append(diag("generalism.bad_profile_pass", "a passing profile cannot contain SILENT or BROKEN cases", path="$.summary.profileStatus"))
    if summary.get("verdict") in VERDICTS:
        # Any adapter-level BROKEN/SILENT dominates the overall result, but downstream
        # external compiler successes are not counted as semantic FAITHFUL proof.
        if all_counts["BROKEN"]:
            expected = "BROKEN"
        elif all_counts["SILENT"]:
            expected = "SILENT"
        elif semantic_counts["FAITHFUL"]:
            expected = "FAITHFUL"
        elif semantic_counts["REFUSED"]:
            expected = "REFUSED"
        else:
            expected = "BROKEN"
        if summary["verdict"] != expected:
            out.append(diag("generalism.summary_drift", f"summary.verdict {summary['verdict']} != aggregate {expected}", path="$.summary.verdict"))

    return out


def validate(obj: Any) -> list[dict[str, str]]:
    diagnostics = validate_shape(obj)
    if isinstance(obj, dict):
        diagnostics.extend(validate_invariants(obj))
    return sorted(diagnostics, key=lambda d: (d["code"], d["path"], d["message"]))


def render_markdown(result: dict[str, Any], diagnostics: list[dict[str, str]]) -> str:
    summary = result.get("summary") if isinstance(result, dict) else {}
    profile = result.get("executionProfile") if isinstance(result, dict) else {}
    lines = [
        f"# Generalism Result: {result.get('runId', '<invalid>') if isinstance(result, dict) else '<invalid>'}",
        "",
        f"- Profile: {profile.get('name', '<invalid>') if isinstance(profile, dict) else '<invalid>'}",
        f"- Status: {summary.get('profileStatus', 'FAIL') if isinstance(summary, dict) else 'FAIL'}",
        f"- Verdict: {summary.get('verdict', 'BROKEN') if isinstance(summary, dict) else 'BROKEN'}",
        f"- Required cases run: {summary.get('requiredCasesRun', 0) if isinstance(summary, dict) else 0}",
        "",
        "## Cases",
        "",
        "| Case | Adapter | Verdict | Cause |",
        "|---|---|---|---|",
    ]
    for case in result.get("cases", []) if isinstance(result, dict) and isinstance(result.get("cases"), list) else []:
        if isinstance(case, dict):
            lines.append(
                f"| {case.get('caseId', '')} | {case.get('adapterId', '')} | "
                f"{case.get('verdict', '')} | {case.get('cause', '')} |"
            )
    lines.extend(["", "## Diagnostics", ""])
    if diagnostics:
        for d in diagnostics:
            lines.append(f"- `{d['code']}` at `{d['path']}`: {d['message']}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def load(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate an M6 generalism result envelope")
    ap.add_argument("file")
    ap.add_argument("--json", action="store_true", help="print structured validation report")
    ap.add_argument("--markdown", help="write a Markdown report generated from the JSON result")
    args = ap.parse_args()

    try:
        result = load(args.file)
    except (OSError, ValueError) as e:
        report = {
            "schemaVersion": 1,
            "kind": "neutrino.generalism-result-validation",
            "ok": False,
            "file": os.path.basename(args.file),
            "diagnostics": [diag("generalism.io", f"cannot read result: {e}")],
        }
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(f"FAIL: {e}", file=sys.stderr)
        return 2

    diagnostics = validate(result)
    ok = not diagnostics
    report = {
        "schemaVersion": 1,
        "kind": "neutrino.generalism-result-validation",
        "ok": ok,
        "file": os.path.basename(args.file),
        "runId": result.get("runId") if isinstance(result, dict) else None,
        "diagnostics": diagnostics,
    }
    if args.markdown:
        Path(args.markdown).write_text(render_markdown(result if isinstance(result, dict) else {}, diagnostics), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    elif ok:
        print(f"ok - {args.file}")
    else:
        for d in diagnostics:
            print(f"{d['code']} {d['path']}: {d['message']}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
