#!/usr/bin/env python3
"""Enforce the source-neutral M7 intake bijection and prohibit code bypasses.

This gate consumes the authorities landed by the intake and conformance slices:
the v3 schema/profile, compiler-owned capability registry, admission classifier,
canonical reducer, and committed source-neutral reduction witness.  It adds no
semantic interpretation.  Instead it proves their stable identities remain
registered, their executable references form a non-vacuous bijection, every
admitted behavior-driving field has one authoritative consumer, and additions
below the intake waist do not reintroduce domain-specific authority.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))

import check_m7_reduction_conformance as conformance  # noqa: E402

PROFILE_PATH = "docs/m7-intake-profile.json"
SCHEMA_PATH = "docs/schemas/l2-domain-semantics-v3.schema.json"
REGISTRY_PATH = "docs/semantic-capability-registry.json"
PROJECTION_CONTRACT_PATH = "docs/m7-intake-projection-contract.json"
ARTIFACT_PATH = "examples/m7-intake/core_document_escrow_external.l2v3.json"
REDUCTION_PATH = "examples/m7-intake/core_document_escrow_external.reduction.json"
REPORT_PATH = (
    "examples/m7-intake/"
    "core_document_escrow_external.intake-bijection-report.json"
)
ADMISSION_PATH = "scripts/gates/classify_m7_intake.py"
CONFORMANCE_PATH = "scripts/gates/check_m7_reduction_conformance.py"
REDUCER_PATH = "lib/L2Reduction.cpp"
REDUCER_CLI_PATH = "tools/neutrino-emit/neutrino-emit.cpp"
VALIDATOR_PATH = "scripts/domain/validate_l2_domain_semantics_v2.py"
DOMAIN_DATA_ROOT = os.path.join("examples", "domains")
M7_INTAKE_ROOT = os.path.join("examples", "m7-intake")

REPORT_KIND = "neutrino.m7-intake-bijection-report"
EXECUTABLE_RELATIONS = {"expands", "discharges"}

CODES = (
    "bijection.unknown_capability",
    "bijection.unconsumed_field",
    "bijection.concept_dispatch",
    "bijection.compiled_domain_registration",
    "bijection.direct_domain_read",
    "bijection.self_authorized_widening",
    "bijection.descriptive_influence",
    "bijection.stale_registration",
    "bijection.non_vacuous",
    "bijection.malformed",
)

CONSUMER_PROOFS = {
    "envelope-kind": (
        "envelope-negotiation",
        ADMISSION_PATH,
        'artifact.get("kind") != v2.KIND',
    ),
    "envelope-schema-version": (
        "envelope-negotiation",
        ADMISSION_PATH,
        'artifact.get("schemaVersion") != v3.SCHEMA_VERSION',
    ),
    "semantic-profile-version": (
        "version-binding",
        ADMISSION_PATH,
        'iv["semanticProfileVersion"] != spv',
    ),
    "reduction-semantics-version": (
        "version-binding",
        ADMISSION_PATH,
        'iv["reductionSemanticsVersion"] != rs_pin',
    ),
    "reducer-domain": (
        "generic-reducer",
        REDUCER_PATH,
        (
            'if (auto d = s.getString("domain"))',
            "m.domain = d->str();",
        ),
    ),
    "validator-import-capability": (
        "cross-record-contract",
        VALIDATOR_PATH,
        'cap = imp["capability"]',
    ),
    "reducer-l1-name": (
        "generic-reducer",
        REDUCER_PATH,
        (
            'auto name = o->getString("name");',
            "m.l1Features.push_back({name->str(), kind->str()});",
        ),
    ),
    "reducer-l1-kind": (
        "generic-reducer",
        REDUCER_PATH,
        (
            'auto kind = o->getString("kind");',
            "m.l1Features.push_back({name->str(), kind->str()});",
        ),
    ),
    "validator-concept-name": (
        "cross-record-contract",
        VALIDATOR_PATH,
        'concepts = {c["name"]: c for c in obj["concepts"]}',
    ),
    "validator-concept-classification": (
        "cross-record-contract",
        VALIDATOR_PATH,
        'concepts.get(frm, {}).get("classification")',
    ),
    "reducer-edge-id": (
        "generic-reducer",
        REDUCER_PATH,
        (
            'auto id = o->getString("id");',
            "m.edges.push_back({id->str(), from->str(), to->str(), rel->str()});",
        ),
    ),
    "reducer-edge-from": (
        "generic-reducer",
        REDUCER_PATH,
        (
            'auto from = o->getString("from");',
            "m.edges.push_back({id->str(), from->str(), to->str(), rel->str()});",
        ),
    ),
    "reducer-edge-to": (
        "generic-reducer",
        REDUCER_PATH,
        (
            'auto to = o->getString("to");',
            "m.edges.push_back({id->str(), from->str(), to->str(), rel->str()});",
        ),
    ),
    "reducer-edge-relation": (
        "generic-reducer",
        REDUCER_PATH,
        (
            'auto rel = o->getString("relation");',
            "m.edges.push_back({id->str(), from->str(), to->str(), rel->str()});",
        ),
    ),
    "admission-edge-lossiness": (
        "mapping-admission",
        ADMISSION_PATH,
        'seen_pairs[(frm, to)] = r["lossiness"]',
    ),
    "validator-failure-name": (
        "cross-record-contract",
        VALIDATOR_PATH,
        'fmodes = {f["name"] for f in obj["failureModes"]}',
    ),
    "validator-invariant-on-failure": (
        "cross-record-contract",
        VALIDATOR_PATH,
        'of = inv.get("onFailure")',
    ),
    "validator-provenance-subject": (
        "cross-record-contract",
        VALIDATOR_PATH,
        'accepted = {p["subject"] for p in obj["provenance"]',
    ),
    "validator-provenance-status": (
        "cross-record-contract",
        VALIDATOR_PATH,
        'if p["status"] == "accepted"}',
    ),
    "admission-provenance-version": (
        "provenance-admission",
        ADMISSION_PATH,
        'pr.get("standardVersion")',
    ),
    "admission-provenance-hash": (
        "provenance-admission",
        ADMISSION_PATH,
        'pr.get("excerptHash")',
    ),
    "validator-domain-hash": (
        "hash-contract",
        VALIDATOR_PATH,
        'recomputed != obj["domainSemanticsHash"]',
    ),
}

# Exact registration over the schema-derived leaf surface.  A field is either
# bound to a concrete semantic consumer identity above, or explicitly excluded
# from influencing the generic coordination projection.
FIELD_BINDINGS = {
    "kind": ("envelope-kind", None),
    "schemaVersion": ("envelope-schema-version", None),
    "domain": ("reducer-domain", None),
    "version": (None, "artifact release metadata is excluded from coordination"),
    "implements": (None, "domain identity is excluded below the intake waist"),
    "coverage": (None, "coverage metadata is excluded from coordination"),
    "imports[].capability": ("validator-import-capability", None),
    "imports[].version": (None, "import version is resolved before coordination"),
    "l1Features[].name": ("reducer-l1-name", None),
    "l1Features[].kind": ("reducer-l1-kind", None),
    "concepts[].name": ("validator-concept-name", None),
    "concepts[].kind": (None, "concept taxonomy is excluded from coordination"),
    "concepts[].classification": ("validator-concept-classification", None),
    "reductions[].id": ("reducer-edge-id", None),
    "reductions[].from": ("reducer-edge-from", None),
    "reductions[].to": ("reducer-edge-to", None),
    "reductions[].relation": ("reducer-edge-relation", None),
    "reductions[].lossiness": ("admission-edge-lossiness", None),
    "failureModes[].name": ("validator-failure-name", None),
    "failureModes[].compensation": (
        None,
        "compensation prose is excluded from coordination",
    ),
    "invariants[].name": (None, "invariant labels are excluded from coordination"),
    "invariants[].predicate": (
        None,
        "domain predicates are excluded from generic capability selection",
    ),
    "invariants[].onFailure": ("validator-invariant-on-failure", None),
    "provenance[].subject": ("validator-provenance-subject", None),
    "provenance[].source": (None, "source identity is excluded from coordination"),
    "provenance[].status": ("validator-provenance-status", None),
    "provenance[].standardVersion": ("admission-provenance-version", None),
    "provenance[].excerptHash": ("admission-provenance-hash", None),
    "provenance[].reviewer": (None, "reviewer identity is excluded from coordination"),
    "intakeVersioning.semanticProfileVersion": ("semantic-profile-version", None),
    "intakeVersioning.reductionSemanticsVersion": (
        "reduction-semantics-version",
        None,
    ),
    "domainSemanticsHash": ("validator-domain-hash", None),
}
PROOF_FIELDS = {
    proof: field
    for field, (proof, _rejection) in FIELD_BINDINGS.items()
    if proof is not None
}
if len(PROOF_FIELDS) != sum(
    proof is not None for proof, _rejection in FIELD_BINDINGS.values()
):
    raise AssertionError("consumption proofs must be field-specific")

STABLE_IDENTITIES = {
    "intake-projection-contract": (
        PROJECTION_CONTRACT_PATH,
        '"kind": "neutrino.m7-intake-projection-contract"',
    ),
    "intake-profile": (
        PROFILE_PATH,
        '"kind": "neutrino.m7-intake-profile"',
    ),
    "intake-schema": (
        SCHEMA_PATH,
        '"$id": "https://neutrino/contracts/l2-domain-semantics/v3"',
    ),
    "capability-registry": (
        REGISTRY_PATH,
        '"kind": "neutrino.semantic-capability-registry"',
    ),
    "admission-entrypoint": (ADMISSION_PATH, "def classify_file("),
    "conformance-entrypoint": (CONFORMANCE_PATH, "def conform("),
    "reducer-entrypoint": (
        REDUCER_PATH,
        "reduceSidecarToCoordinationPlan(",
    ),
    "reducer-cli": (REDUCER_CLI_PATH, 'kind == "domain-reduction"'),
    "fast-registration": (
        "cmake/NeutrinoTests.cmake",
        "fast-m7-intake-bijection=m7_intake_bijection="
        "fast,contract,completeness,domain,policy",
    ),
    "architecture-registration": (
        "scripts/architecture_boundaries.json",
        '"check_m7_intake_bijection.py"',
    ),
    "integrity-registration": (
        "scripts/gates/gate_integrity_manifest.json",
        '"id": "m7_intake_bijection"',
    ),
}

BELOW_WAIST_PREFIXES = (
    "lib/backends/",
    "lib/spec-contract/",
    "lib/targets/CoordinationPlanTarget.cpp",
)
REDUCTION_PREFIXES = (
    "lib/L2Reduction.cpp",
    "lib/targets/CoordinationPlanTarget.cpp",
    "lib/spec-contract/",
)
COMPILER_SUFFIXES = (".h", ".hpp", ".cpp", ".cc", ".td")
CAPABILITY_ID = re.compile(
    r"\b(?:attestation|authorization|coordination|effect|guard|identity|"
    r"invariant|replay|terminal|time):[a-z][a-z0-9_]*\b"
)


def _load(path):
    with open(os.path.join(REPO, path), encoding="utf-8") as fh:
        return json.load(fh)


def _text(path):
    with open(os.path.join(REPO, path), encoding="utf-8") as fh:
        return fh.read()


def _diag(code, message):
    if code not in CODES:
        raise AssertionError(f"unknown diagnostic code {code}")
    return {"code": code, "message": message}


def _git(*args, check=True):
    result = subprocess.run(
        ["git", *args],
        cwd=REPO,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result


def _resolve_base(explicit):
    candidate = (
        os.environ.get("PR_BASE_SHA")
        or os.environ.get("GITHUB_BASE_SHA")
        or explicit
        or "origin/main"
    )
    merged = _git("merge-base", "HEAD", candidate, check=False)
    if merged.returncode:
        return None
    return merged.stdout.strip()


def _changed_lines(base):
    if not base:
        return [], set()
    result = _git(
        "diff",
        "--unified=0",
        "--no-ext-diff",
        f"{base}...HEAD",
        "--",
        "include",
        "lib",
        "tools",
        DOMAIN_DATA_ROOT,
        "examples/m7-intake",
        REGISTRY_PATH,
        PROFILE_PATH,
        PROJECTION_CONTRACT_PATH,
        check=False,
    )
    if result.returncode:
        return [], set()
    path = None
    lines = []
    paths = set()
    for line in result.stdout.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            paths.add(path)
        elif path and line.startswith("+") and not line.startswith("+++"):
            lines.append((path, line[1:]))
    return lines, paths


def _base_json(base, path):
    if not base:
        return None
    result = _git("show", f"{base}:{path}", check=False)
    if result.returncode:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def _base_text_sha256(base, path):
    if not base:
        return None
    result = _git("show", f"{base}:{path}", check=False)
    if result.returncode:
        return None
    return hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()


def _below_waist_texts(prefixes):
    texts = {}
    for prefix in prefixes:
        absolute = os.path.join(REPO, prefix)
        if os.path.isfile(absolute):
            texts[prefix] = _text(prefix)
            continue
        if not os.path.isdir(absolute):
            continue
        for root, _dirs, files in os.walk(absolute):
            for name in sorted(files):
                if not name.endswith(COMPILER_SUFFIXES):
                    continue
                path = os.path.relpath(os.path.join(root, name), REPO)
                texts[path] = _text(path)
    return texts


def _admitted_artifacts():
    artifacts = []
    root = os.path.join(REPO, M7_INTAKE_ROOT)
    for name in sorted(os.listdir(root)):
        if not name.endswith(".l2v3.json"):
            continue
        path = os.path.join(root, name)
        try:
            with open(path, encoding="utf-8") as fh:
                artifact = json.load(fh)
            report = conformance.intake.classify_file(
                path,
                os.path.join(REPO, PROFILE_PATH),
            )
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if report.get("admitted"):
            artifacts.append(artifact)
    return artifacts


def _snapshot(base_ref=None):
    base = _resolve_base(base_ref)
    changed_lines, changed_paths = _changed_lines(base)
    projection_contract = _load(PROJECTION_CONTRACT_PATH)
    boundary_prefixes = projection_contract.get("closedBoundary", {}).get(
        "prefixes",
        [],
    )
    conformance_report = conformance.conform(
        os.path.join(REPO, ARTIFACT_PATH),
        os.path.join(REPO, REGISTRY_PATH),
        os.path.join(REPO, PROFILE_PATH),
        reduction_path=os.path.join(REPO, REDUCTION_PATH),
    )
    return {
        "profile": _load(PROFILE_PATH),
        "schema": _load(SCHEMA_PATH),
        "registry": _load(REGISTRY_PATH),
        "projectionContract": projection_contract,
        "artifact": _load(ARTIFACT_PATH),
        "admittedArtifacts": _admitted_artifacts(),
        "reduction": _load(REDUCTION_PATH),
        "stableTexts": {
            path: _text(path)
            for path, _anchor in STABLE_IDENTITIES.values()
        },
        "consumerTexts": {
            path: _text(path)
            for _authority, path, _anchor in CONSUMER_PROOFS.values()
        },
        "fieldBindings": copy.deepcopy(FIELD_BINDINGS),
        "changedLines": changed_lines,
        "changedPaths": changed_paths,
        "baseRegistry": _base_json(base, REGISTRY_PATH),
        "baseProfile": _base_json(base, PROFILE_PATH),
        "baseProjectionContract": _base_json(base, PROJECTION_CONTRACT_PATH),
        "baseReducerSha256": _base_text_sha256(base, REDUCER_PATH),
        "baseResolved": base is not None,
        "conformanceReport": conformance_report,
        "backends": sorted(
            name
            for name in os.listdir(os.path.join(REPO, "lib", "backends"))
            if os.path.isdir(os.path.join(REPO, "lib", "backends", name))
        ),
        "belowWaistTexts": _below_waist_texts(boundary_prefixes),
    }


def _stable_identity_checks(snapshot, diags):
    if not snapshot.get("baseResolved"):
        diags.append(
            _diag(
                "bijection.stale_registration",
                "no authoritative PR base is resolvable for stable-identity comparison",
            )
        )
    for name, (path, anchor) in STABLE_IDENTITIES.items():
        text = snapshot["stableTexts"].get(path)
        if text is None or anchor not in text:
            diags.append(
                _diag(
                    "bijection.stale_registration",
                    f"stable identity {name!r} is missing or stale at {path}",
                )
            )

    profile = snapshot["profile"]
    schema = snapshot["schema"]
    registry = snapshot["registry"]
    if profile.get("kind") != "neutrino.m7-intake-profile":
        diags.append(_diag("bijection.stale_registration", "intake profile kind drifted"))
    if schema.get("$id") != "https://neutrino/contracts/l2-domain-semantics/v3":
        diags.append(_diag("bijection.stale_registration", "intake schema identity drifted"))
    if registry.get("kind") != "neutrino.semantic-capability-registry":
        diags.append(_diag("bijection.stale_registration", "capability registry kind drifted"))
    if (
        registry.get("semanticProfileVersion")
        != profile.get("capabilityNamespace", {}).get("semanticProfileVersion")
    ):
        diags.append(
            _diag(
                "bijection.stale_registration",
                "profile and registry semantic versions are not identical",
            )
        )


def _referential_checks(snapshot, diags):
    registry_records = snapshot["registry"].get("capabilities")
    artifact = snapshot["artifact"]
    bindings = snapshot["reduction"].get("bindings")
    if not isinstance(registry_records, list) or not isinstance(bindings, list):
        diags.append(_diag("bijection.malformed", "registry or reduction is malformed"))
        return [], []
    if not snapshot["conformanceReport"].get("conformant"):
        diags.append(
            _diag(
                "bijection.malformed",
                "the authoritative admission/reduction conformance seam rejected the fixture",
            )
        )

    registry_ids = [item.get("id") for item in registry_records if isinstance(item, dict)]
    if len(registry_ids) != len(registry_records) or len(set(registry_ids)) != len(
        registry_ids
    ):
        diags.append(_diag("bijection.malformed", "capability identities are missing or duplicated"))
    known = set(registry_ids)
    concepts = {
        item.get("name"): item.get("classification")
        for item in artifact.get("concepts", [])
        if isinstance(item, dict)
    }
    exec_edges = {
        (
            item.get("id"),
            item.get("from"),
            item.get("to"),
            item.get("relation"),
        )
        for item in artifact.get("reductions", [])
        if isinstance(item, dict) and item.get("relation") in EXECUTABLE_RELATIONS
    }
    exec_bindings = [
        (
            item.get("edge"),
            item.get("concept"),
            item.get("feature"),
            item.get("relation"),
        )
        for item in bindings
        if isinstance(item, dict) and item.get("relation") in EXECUTABLE_RELATIONS
    ]
    executable_concepts = {
        name for name, classification in concepts.items() if classification == "executable"
    }
    reduced_concepts = {edge[1] for edge in exec_edges}
    for concept in sorted(executable_concepts - reduced_concepts):
        diags.append(
            _diag(
                "bijection.unknown_capability",
                f"executable concept {concept!r} has no registered generic reduction",
            )
        )
    for edge in sorted(exec_edges):
        if edge[2] not in known:
            diags.append(
                _diag(
                    "bijection.unknown_capability",
                    f"executable edge {edge[0]!r} targets unknown capability {edge[2]!r}",
                )
            )
        if concepts.get(edge[1]) != "executable":
            diags.append(
                _diag(
                    "bijection.descriptive_influence",
                    f"non-executable concept {edge[1]!r} authors an executable edge",
                )
            )
    for binding in sorted(exec_bindings):
        if binding[2] not in known:
            diags.append(
                _diag(
                    "bijection.unknown_capability",
                    f"consumer binding {binding[0]!r} uses unknown capability {binding[2]!r}",
                )
            )
        if concepts.get(binding[1]) != "executable":
            diags.append(
                _diag(
                    "bijection.descriptive_influence",
                    f"non-executable concept {binding[1]!r} influences the reduction",
                )
            )
    if len(exec_bindings) != len(set(exec_bindings)) or set(exec_bindings) != exec_edges:
        diags.append(
            _diag(
                "bijection.unknown_capability",
                "executable concepts and generic consumer bindings are not bijective",
            )
        )
    return exec_edges, exec_bindings


def _schema_leaf_surface(schema):
    leaves = {}

    def visit(node, prefix, required):
        node_type = node.get("type")
        if node_type == "object":
            required_children = set(node.get("required", []))
            for name, child in node.get("properties", {}).items():
                path = f"{prefix}.{name}" if prefix else name
                visit(child, path, required and name in required_children)
            return
        if node_type == "array":
            visit(node.get("items", {}), prefix + "[]", required)
            return
        leaves[prefix] = "required" if required else "optional"

    visit(schema, "", True)
    return leaves


def _consumer_scope(text, proof):
    if proof.startswith("reducer-"):
        anchor = "modelOfSidecar("
    elif proof == "validator-domain-hash":
        anchor = "def validate("
    elif proof.startswith("validator-"):
        anchor = "def validate_semantics("
    else:
        anchor = "def classify("
    start = text.find(anchor)
    if start < 0:
        return ""
    if anchor.startswith("def "):
        following = re.search(r"(?m)^def\s+", text[start + len(anchor):])
        return (
            text[start:]
            if following is None
            else text[start:start + len(anchor) + following.start()]
        )
    opening = text.find("{", start)
    if opening < 0:
        return ""
    depth = 0
    for pos in range(opening, len(text)):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                return text[start:pos + 1]
    return ""


def _projection_contract_checks(snapshot, diags):
    contract = snapshot["projectionContract"]
    projection = contract.get("fieldProjection")
    trusted = contract.get("trustedReducer")
    boundary = contract.get("closedBoundary")
    if (
        contract.get("kind") != "neutrino.m7-intake-projection-contract"
        or contract.get("schemaVersion") != 1
        or not isinstance(projection, dict)
        or not isinstance(trusted, dict)
        or not isinstance(boundary, dict)
    ):
        diags.append(
            _diag(
                "bijection.stale_registration",
                "the trusted M7 projection contract is malformed",
            )
        )
        return

    reducer_fields = {
        field
        for field, (proof, _rejection) in snapshot["fieldBindings"].items()
        if proof is not None and CONSUMER_PROOFS.get(proof, (None,))[0] == "generic-reducer"
    }
    if set(projection) != reducer_fields or any(
        not isinstance(target, str) or not target
        for target in projection.values()
    ):
        diags.append(
            _diag(
                "bijection.unconsumed_field",
                "the typed projection contract does not exactly cover reducer-bound fields",
            )
        )

    reducer_text = snapshot["consumerTexts"].get(REDUCER_PATH, "")
    reducer_sha = hashlib.sha256(reducer_text.encode("utf-8")).hexdigest()
    approved = trusted.get("approvedSourceSha256")
    if (
        trusted.get("path") != REDUCER_PATH
        or trusted.get("outputType") != "neutrino::L2Reduction"
        or not isinstance(approved, list)
        or reducer_sha not in approved
    ):
        diags.append(
            _diag(
                "bijection.unconsumed_field",
                "the trusted typed reducer source is not pre-approved by the projection contract",
            )
        )

    reducer_diff_claimed = any(
        path == REDUCER_PATH for path, _line in snapshot["changedLines"]
    )
    if (
        reducer_diff_claimed
        and reducer_sha == snapshot.get("baseReducerSha256")
    ):
        diags.append(
            _diag(
                "bijection.unconsumed_field",
                "trusted reducer changes are not represented by the hashed source snapshot",
            )
        )

    base_contract = snapshot.get("baseProjectionContract")
    contract_changed = isinstance(base_contract, dict) and base_contract != contract
    governed_code_changed = any(
        path == REDUCER_PATH or path.startswith(BELOW_WAIST_PREFIXES)
        for path in snapshot["changedPaths"]
    )
    if contract_changed and governed_code_changed:
        diags.append(
            _diag(
                "bijection.self_authorized_widening",
                "projection authority and governed implementation change in the same review",
            )
        )

    if tuple(boundary.get("prefixes", [])) != BELOW_WAIST_PREFIXES:
        diags.append(
            _diag(
                "bijection.stale_registration",
                "the closed below-waist prefix inventory drifted",
            )
        )
        return
    headers = boundary.get("forbiddenBelowWaistHeaders")
    symbols = boundary.get("forbiddenBelowWaistSymbols")
    if not isinstance(headers, list) or not headers or not isinstance(symbols, list) or not symbols:
        diags.append(
            _diag(
                "bijection.stale_registration",
                "the closed below-waist API inventory is vacuous",
            )
        )
        return
    for path, text in snapshot["belowWaistTexts"].items():
        structural = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
        structural = re.sub(r"//[^\n]*", " ", structural)
        forbidden_header = next(
            (
                header
                for header in headers
                if re.search(
                    rf"#\s*include\s*[<\"]{re.escape(header)}[>\"]",
                    structural,
                )
            ),
            None,
        )
        forbidden_symbol = next(
            (
                symbol
                for symbol in symbols
                if re.search(rf"\b{re.escape(symbol)}\b", structural)
            ),
            None,
        )
        if forbidden_header or forbidden_symbol:
            detail = forbidden_header or forbidden_symbol
            diags.append(
                _diag(
                    "bijection.direct_domain_read",
                    f"{path} crosses the closed domain-artifact API boundary via {detail!r}",
                )
            )


def _field_checks(snapshot, diags):
    schema_fields = _schema_leaf_surface(snapshot["schema"])
    bindings = snapshot["fieldBindings"]
    registered = set(bindings)
    for field in sorted(set(schema_fields) - registered):
        diags.append(
            _diag(
                "bijection.unconsumed_field",
                f"admitted schema leaf {field!r} has no consumer or rejection",
            )
        )
    stale = registered - set(schema_fields)
    if stale:
        diags.append(
            _diag(
                "bijection.unconsumed_field",
                f"field registrations are stale for absent schema leaves {sorted(stale)}",
            )
        )
    for field, (consumer, rejection) in bindings.items():
        if consumer is None:
            if not rejection:
                diags.append(
                    _diag(
                        "bijection.unconsumed_field",
                        f"schema leaf {field!r} has no explicit rejection reason",
                    )
                )
            continue
        proof = CONSUMER_PROOFS.get(consumer)
        if proof is None:
            diags.append(
                _diag(
                    "bijection.unconsumed_field",
                    f"schema leaf {field!r} names unknown consumption proof {consumer!r}",
                )
            )
            continue
        if PROOF_FIELDS.get(consumer) != field:
            diags.append(
                _diag(
                    "bijection.unconsumed_field",
                    f"schema leaf {field!r} is rebound to the field-specific "
                    f"proof for {PROOF_FIELDS.get(consumer)!r}",
                )
            )
            continue
        authority, path, anchors = proof
        if authority == "generic-reducer":
            continue
        scope = _consumer_scope(snapshot["consumerTexts"].get(path, ""), consumer)
        anchors = (anchors,) if isinstance(anchors, str) else anchors
        if any(anchor not in scope for anchor in anchors):
            diags.append(
                _diag(
                    "bijection.unconsumed_field",
                    f"schema leaf {field!r} consumption proof {consumer!r} "
                    f"for {authority!r} is stale",
                )
            )
    if not bindings:
        diags.append(_diag("bijection.unconsumed_field", "field accounting is vacuous"))


def _semantic_identity_spellings(snapshot):
    identities = set()
    for artifact in snapshot["admittedArtifacts"]:
        identities.add(artifact.get("domain"))
        identities.update(
            item.get("name")
            for item in artifact.get("concepts", [])
            if isinstance(item, dict)
        )
    identities.discard(None)
    symbols = set()
    for identity in identities:
        words = [word for word in re.split(r"[^A-Za-z0-9]+", identity) if word]
        if not words:
            continue
        symbols.add("".join(words).lower())
        if len(words) > 1:
            symbols.add("".join(words[-2:]).lower())
    return identities, symbols


def _without_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", " ", text)
    return re.sub(r"(?m)^\s*#[^\n]*", " ", text)


def _source_bypass_checks(snapshot, diags):
    semantic_identities, semantic_symbols = _semantic_identity_spellings(snapshot)
    additions = {}
    for path, line in snapshot["changedLines"]:
        additions.setdefault(path, []).append(line)
    for path, lines in additions.items():
        structural = re.sub(r"\s+", " ", _without_comments("\n".join(lines)))
        lowered = structural.lower()
        compiler_file = path.endswith(COMPILER_SUFFIXES)
        declared_symbols = re.findall(
            r"\b(?:def|class)\s+([A-Za-z_]\w*)", structural
        )
        closed_op_registration = path.endswith(".td") and re.search(
            r"\bdef\s+[A-Za-z_]\w*Op\b", structural
        )
        identity_registration = any(
            any(spelling in symbol.lower() for spelling in semantic_symbols)
            for symbol in declared_symbols
        )
        if compiler_file and (
            closed_op_registration
            or identity_registration
            or (
                (
                    path.startswith("include/")
                    or path.startswith("lib/")
                    or path.startswith("tools/")
                )
                and re.search(
                    r"\b(?:register|class|def)\s+\w*(?:concept|domain)|"
                    r"NEUTRINO_[A-Z_]*(?:CONCEPT|DOMAIN)",
                    structural,
                    re.IGNORECASE,
                )
            )
        ):
            diags.append(
                _diag(
                    "bijection.compiled_domain_registration",
                    f"{path} adds concept/domain compiled authority",
                )
            )
        tainted = {"concept", "conceptid", "conceptname", "domain", "domainid", "domainname"}
        assignments = re.findall(
            r"\b([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\b", structural
        )
        changed = True
        while changed:
            changed = False
            for lhs, rhs in assignments:
                if rhs.lower() in tainted and lhs.lower() not in tainted:
                    tainted.add(lhs.lower())
                    changed = True
        dispatch_uses_identity = False
        for match in re.finditer(r"\b(?:if|switch)\b", structural):
            window = structural[max(0, match.start() - 300):match.end() + 500]
            if any(
                re.search(rf"\b{re.escape(name)}\b", window, re.IGNORECASE)
                for name in tainted
            ):
                dispatch_uses_identity = True
                break
        identity_literal = any(
            re.search(
                rf"(?P<quote>[\"']){re.escape(identity)}(?P=quote)",
                structural,
            )
            for identity in semantic_identities
        )
        identity_comparison = re.search(
            r"(?:\.\s*(?:from|conceptName|domain)|"
            r"\b(?:from|conceptName|domain)\b)\s*==\s*[\"'][^\"']+[\"']|"
            r"[\"'][^\"']+[\"']\s*==\s*(?:\.\s*(?:from|conceptName|domain)|"
            r"\b(?:from|conceptName|domain)\b)",
            structural,
            re.IGNORECASE,
        )
        if path.startswith(REDUCTION_PREFIXES) and (
            dispatch_uses_identity or identity_literal or identity_comparison
        ):
            diags.append(
                _diag(
                    "bijection.concept_dispatch",
                    f"{path} adds concept/domain dispatch below admission",
                )
            )
        schema_fields = {
            component.removesuffix("[]")
            for leaf in _schema_leaf_surface(snapshot["schema"])
            for component in leaf.split(".")
        }
        field_pattern = "|".join(
            re.escape(field) for field in sorted(schema_fields, key=len, reverse=True)
        )
        semantic_accessor = re.search(
            r"(?:\bget(?:String|Array|Object|Integer|Boolean|Number)?\s*\(|"
            rf"\[\s*)[\"'](?:{field_pattern})[\"']",
            structural,
            re.IGNORECASE,
        )
        if path.startswith(BELOW_WAIST_PREFIXES) and (
            identity_literal
            or semantic_accessor
            or re.search(
                r"\b(?:l2::|DomainOp|domainSemantics|conceptId|domainId)\b",
                structural,
                re.IGNORECASE,
            )
        ):
            diags.append(
                _diag(
                    "bijection.direct_domain_read",
                    f"{path} directly reads L2/domain identity below the waist",
                )
            )
        if path.startswith("lib/backends/") and (
            CAPABILITY_ID.search(structural)
            or "knownsemanticfeatures" in lowered
            or "semantic-capability-registry" in lowered
        ):
            diags.append(
                _diag(
                    "bijection.direct_domain_read",
                    f"{path} selects a semantic capability in a backend",
                )
            )


def _widening_checks(snapshot, diags):
    base_registry = snapshot.get("baseRegistry")
    if not isinstance(base_registry, dict):
        if snapshot.get("baseResolved"):
            diags.append(
                _diag(
                    "bijection.stale_registration",
                    "the base capability registry is missing or malformed",
                )
            )
        return
    current = snapshot["registry"]
    registry_changed = base_registry != current
    profile_changed = False
    if isinstance(snapshot.get("baseProfile"), dict):
        profile_changed = snapshot["baseProfile"] != snapshot["profile"]
    benefiting_data = any(
        path.startswith((DOMAIN_DATA_ROOT + "/", "examples/m7-intake/"))
        and path not in {REPORT_PATH}
        for path in snapshot["changedPaths"]
    )
    if (registry_changed or profile_changed) and benefiting_data:
        diags.append(
            _diag(
                "bijection.self_authorized_widening",
                "capability widening/version drift is bundled with benefiting domain data",
            )
        )


def evaluate(snapshot):
    diags = []
    _stable_identity_checks(snapshot, diags)
    exec_edges, exec_bindings = _referential_checks(snapshot, diags)
    _projection_contract_checks(snapshot, diags)
    _field_checks(snapshot, diags)
    _source_bypass_checks(snapshot, diags)
    _widening_checks(snapshot, diags)

    counts = {
        "concepts": len(snapshot["artifact"].get("concepts", [])),
        "capabilities": len(snapshot["registry"].get("capabilities", [])),
        "consumers": len(exec_bindings),
        "governedBackends": len(snapshot["backends"]),
    }
    if any(value == 0 for value in counts.values()):
        diags.append(
            _diag(
                "bijection.non_vacuous",
                f"discovery is vacuous: {counts}",
            )
        )
    diags = sorted(diags, key=lambda item: (CODES.index(item["code"]), item["message"]))
    stable = [
        {
            "id": name,
            "path": path,
            "anchorSha256": hashlib.sha256(anchor.encode("utf-8")).hexdigest(),
        }
        for name, (path, anchor) in sorted(STABLE_IDENTITIES.items())
    ]
    return {
        "kind": REPORT_KIND,
        "schemaVersion": 1,
        "conformant": not diags,
        "sourceNeutralFixture": ARTIFACT_PATH,
        "capabilityRegistryVersion": snapshot["registry"].get(
            "semanticProfileVersion"
        ),
        "trustedProjection": {
            "contract": PROJECTION_CONTRACT_PATH,
            "reducer": REDUCER_PATH,
            "sourceSha256": hashlib.sha256(
                snapshot["consumerTexts"][REDUCER_PATH].encode("utf-8")
            ).hexdigest(),
        },
        "counts": counts,
        "executableBindings": [
            {
                "edge": edge,
                "concept": concept,
                "capability": feature,
                "relation": relation,
            }
            for edge, concept, feature, relation in sorted(exec_bindings)
        ],
        "capabilityRealizations": [
            {
                "capability": capability,
                "genericRealization": "reduceSidecarToCoordinationPlan",
            }
            for capability in sorted({binding[2] for binding in exec_bindings})
        ],
        "fieldAccounting": [
            {
                "field": field,
                "presence": _schema_leaf_surface(snapshot["schema"])[field],
                "disposition": "consumed" if consumer else "rejected",
                "authority": (
                    CONSUMER_PROOFS[consumer][0] if consumer is not None else None
                ),
                "proof": consumer,
                "reason": rejection,
            }
            for field, (consumer, rejection) in sorted(
                snapshot["fieldBindings"].items()
            )
        ],
        "stableIdentities": stable,
        "diagnostics": diags,
    }


def _probe_unknown(snapshot):
    snapshot["reduction"]["bindings"][0]["feature"] = "effect:unknown"


def _probe_unconsumed(snapshot):
    snapshot["schema"]["properties"]["reductions"]["items"]["properties"][
        "ignoredBehaviorProbe"
    ] = {"type": "boolean"}


def _probe_deleted_consumption(snapshot):
    snapshot["consumerTexts"][REDUCER_PATH] = snapshot["consumerTexts"][
        REDUCER_PATH
    ].replace(
        'auto to = o->getString("to");',
        'if (false) { auto to = o->getString("to"); '
        'm.edges.push_back({id->str(), from->str(), to->str(), rel->str()}); } '
        "auto to = ignoredEndpoint();",
    )


def _probe_dispatch(snapshot):
    snapshot["changedLines"].extend(
        [
            (
                "lib/L2Reduction.cpp",
                'bool selects(const Edge &e) { return e.from == "escrow_funded"; }',
            ),
            ("lib/L2Reduction.cpp", "if (selects(edge)) return special;"),
        ]
    )


def _probe_compiled(snapshot):
    snapshot["changedLines"].extend(
        [
            ("include/Neutrino/NeutrinoOps.td", "def"),
            ("include/Neutrino/NeutrinoOps.td", "EscrowFundedOp;"),
        ]
    )


def _probe_direct_read(snapshot):
    snapshot["changedLines"].extend(
        [
            (
                "lib/backends/postgres/PostgresModel.cpp",
                'auto identity = sidecar.getString("domain");',
            ),
        ]
    )


def _probe_unseen_identity(snapshot):
    snapshot["changedLines"].extend(
        [
            (
                "lib/L2Reduction.cpp",
                'bool selects(const Edge &e) { return e.from == "shipment_released"; }',
            ),
            ("lib/L2Reduction.cpp", "if (selects(edge)) return special;"),
        ]
    )


def _probe_schema_field_read(snapshot):
    snapshot["changedLines"].append(
        (
            "lib/backends/postgres/PostgresModel.cpp",
            'auto records = sidecar.getArray("provenance");',
        )
    )


def _probe_non_equality_dispatch(snapshot):
    snapshot["changedLines"].append(
        (
            REDUCER_PATH,
            'if (edge.from.starts_with("shipment_")) return special;',
        )
    )


def _probe_closed_api(snapshot):
    path = "lib/backends/postgres/model/PostgresModel.cpp"
    snapshot["belowWaistTexts"][path] += '\n#include "Neutrino/L2Reduction.h"\n'


def _probe_projection_self_authorization(snapshot):
    snapshot["baseProjectionContract"] = copy.deepcopy(
        snapshot["projectionContract"]
    )
    snapshot["projectionContract"]["trustedReducer"]["approvedSourceSha256"].append(
        "0" * 64
    )
    snapshot["changedPaths"].update({PROJECTION_CONTRACT_PATH, REDUCER_PATH})


def _probe_widening(snapshot):
    snapshot["baseRegistry"] = copy.deepcopy(snapshot["registry"])
    snapshot["registry"]["capabilities"][0]["category"] = "obligation"
    snapshot["changedPaths"].add(
        os.path.join(DOMAIN_DATA_ROOT, "probe", "domain-semantics.json")
    )


def _probe_descriptive(snapshot):
    snapshot["reduction"]["bindings"][0]["concept"] = "settlement_balanced"


def _probe_registration(snapshot):
    path, anchor = STABLE_IDENTITIES["fast-registration"]
    snapshot["stableTexts"][path] = snapshot["stableTexts"][path].replace(anchor, "")


PROBES = {
    "unknown-capability-anchor": ("bijection.unknown_capability", _probe_unknown),
    "ignored-behavior-field": ("bijection.unconsumed_field", _probe_unconsumed),
    "deleted-field-consumption": (
        "bijection.unconsumed_field",
        _probe_deleted_consumption,
    ),
    "concept-id-dispatch": ("bijection.concept_dispatch", _probe_dispatch),
    "compiled-domain-registration": (
        "bijection.compiled_domain_registration",
        _probe_compiled,
    ),
    "direct-domain-read": ("bijection.direct_domain_read", _probe_direct_read),
    "unseen-domain-identity": (
        "bijection.concept_dispatch",
        _probe_unseen_identity,
    ),
    "non-escrow-schema-read": (
        "bijection.direct_domain_read",
        _probe_schema_field_read,
    ),
    "non-equality-domain-dispatch": (
        "bijection.unconsumed_field",
        _probe_non_equality_dispatch,
    ),
    "below-waist-domain-api": (
        "bijection.direct_domain_read",
        _probe_closed_api,
    ),
    "self-authorized-projection-change": (
        "bijection.self_authorized_widening",
        _probe_projection_self_authorization,
    ),
    "bundled-capability-widening": (
        "bijection.self_authorized_widening",
        _probe_widening,
    ),
    "descriptive-coordination-influence": (
        "bijection.descriptive_influence",
        _probe_descriptive,
    ),
    "stale-gate-registration": (
        "bijection.stale_registration",
        _probe_registration,
    ),
}


def run_probe(name, base_ref=None):
    snapshot = _snapshot(base_ref)
    expected, mutate = PROBES[name]
    mutate(snapshot)
    report = evaluate(snapshot)
    codes = {item["code"] for item in report["diagnostics"]}
    if report["conformant"] or expected not in codes:
        print(
            f"probe {name} unexpectedly passed: "
            f"conformant={report['conformant']} codes={sorted(codes)}"
        )
        return 0
    print(f"probe-failed-as-expected:{name}")
    return 1


def selftest(base_ref=None):
    failures = []
    clean = evaluate(_snapshot(base_ref))
    if not clean["conformant"]:
        failures.append(f"clean tree failed: {clean['diagnostics']}")
    for name in sorted(PROBES):
        expected, mutate = PROBES[name]
        snapshot = _snapshot(base_ref)
        mutate(snapshot)
        report = evaluate(snapshot)
        codes = {item["code"] for item in report["diagnostics"]}
        if report["conformant"] or expected not in codes:
            failures.append(f"{name} did not bite with {expected}: {sorted(codes)}")
        else:
            print(f"probe-failed-as-expected:{name}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print(
        f"m7 intake bijection selftest PASS "
        f"(clean tree + {len(PROBES)} fail-closed probes)"
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref")
    parser.add_argument("--probe", choices=sorted(PROBES))
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.probe:
        return run_probe(args.probe, args.base_ref)
    if args.selftest:
        return selftest(args.base_ref)
    report = evaluate(_snapshot(args.base_ref))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["conformant"] else 1


if __name__ == "__main__":
    sys.exit(main())
