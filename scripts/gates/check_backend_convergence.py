#!/usr/bin/env python3
""" structural-zero gate for the two production backend adapters."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SOL_PROVIDER = Path("lib/backends/solidity/provider/SolidityRecipeProvider.cpp")
SOL_ADAPTER = Path("lib/backends/solidity/provider/SolidityTargetAdapter.cpp")
SOL_VALIDATION = Path("lib/backends/solidity/provider/SolidityTargetValidation.cpp")
SOL_RENDERER = Path("lib/backends/solidity/provider/SolidityRenderer.cpp")
PG_MODEL = Path("lib/backends/postgres/model/PostgresModel.cpp")
SOL_PROVIDER_HEADER = Path("lib/backends/solidity/provider/SolidityRecipeProvider.h")
SOL_ADAPTER_HEADER = Path("lib/backends/solidity/provider/SolidityTargetAdapter.h")
SOL_VALIDATION_HEADER = Path("lib/backends/solidity/provider/SolidityTargetValidation.h")
SOL_RENDERER_HEADER = Path("lib/backends/solidity/provider/SolidityRenderer.h")
PG_HEADER = Path("lib/backends/postgres/model/PostgresModel.h")
SOL_ENTRY = Path("lib/backends/solidity/provider/GenSoliditySpec.cpp")
PG_ENTRY = Path("lib/backends/postgres/GenPostgresSpec.cpp")
SOL_TD = Path("lib/backends/solidity/model/SolidityTargetNodes.td")
PG_TD = Path("lib/backends/postgres/model/PostgresTargetNodes.td")
PROJECTION_DRIVER = Path("include/Neutrino/BackendProjectionDriver.h")
SEMANTIC_AUTHORITY_GATE = Path("scripts/gates/check_semantic_authority.py")

LEGACY = re.compile(
    r"\b(?:legalize(?:Solidity|Postgres|Evidence|Effectful|Temporal|"
    r"PostgresTemporal|ProjectedNonTemporal)\w*|"
    r"print(?:Solidity|Postgres)|renderQuorumSchema)\b"
)
REQUIRED_IDIOMS = {
    SOL_TD: ("ContractShell", "FunctionSig", "EventDecl", "StorageDecl"),
    PG_TD: (
        "CallableSig",
        "CallableBody",
        "CallableClose",
        "DeclareSection",
        "EffectLedgerComment",
    ),
}
MODEL_ENTRIES = {
    SOL_PROVIDER_HEADER: ("materializeSolidityProjectionArtifact",),
    SOL_RENDERER_HEADER: ("renderSolidityProjection",),
    PG_HEADER: ("materializePostgresProjection", "renderPostgresProjection"),
}
SEMANTIC_AUTHORITY_SURFACES = {
    SOL_PROVIDER,
    SOL_ADAPTER,
    SOL_VALIDATION,
    SOL_RENDERER,
    SOL_PROVIDER_HEADER,
    SOL_ADAPTER_HEADER,
    SOL_VALIDATION_HEADER,
    SOL_RENDERER_HEADER,
    PG_MODEL,
    PG_HEADER,
    SOL_ENTRY,
    PG_ENTRY,
}
SEMANTIC_AUTHORITY_CLASSES = {
    "backend-discovery",
    "backend-semantic-branch",
    "carveout-integrity",
    "decision-bearing-table",
    "domain-concept-dispatch",
}
GENERIC_DECISION_HELPER = re.compile(
    r"\bprojection_driver\s*::\s*(?:when|choose|require)\s*\("
)
GENERIC_DECISION_ALIAS = re.compile(
    r"\b(?:namespace\s+[A-Za-z_]\w*\s*=\s*"
    r"(?:neutrino\s*::\s*)?projection_driver|"
    r"using\s+(?:neutrino\s*::\s*)?projection_driver\s*::\s*"
    r"(?:when|choose|require))\b"
)


def _read(path: Path, overrides: dict[Path, str]) -> str:
    if path in overrides:
        return overrides[path]
    return (REPO / path).read_text(encoding="utf-8")


def _code(text: str) -> str:
    """Erase comments and literals while preserving token separation."""
    pattern = re.compile(
        r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'",
        re.DOTALL,
    )
    return pattern.sub(" ", text)


def _function_span(text: str, name: str) -> tuple[int, int] | None:
    match = re.search(
        rf"\b{name}\s*\([^;]*?\)\s*(?:->\s*[\w:<>]+\s*)?\{{",
        text,
        re.DOTALL,
    )
    if not match:
        return None
    depth = 0
    for index in range(match.end() - 1, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return match.start(), index + 1
    return None


def _without_pg_carveouts(text: str) -> str:
    spans = []
    for name in ("projectedPolicyCarrier", "buildTemporalAcceptGate"):
        span = _function_span(text, name)
        if span is None:
            return text
        spans.append(span)
    chars = list(text)
    for start, end in spans:
        return_type = re.search(r"\bCoordinationPlan\s*$", text[:start])
        if return_type:
            start = return_type.start()
        chars[start:end] = " " * (end - start)
    return "".join(chars)


def _semantic_authority_errors(overrides: dict[Path, str]) -> list[str]:
    """Consume 's authoritative classifier for the final adapter surface."""
    spec = importlib.util.spec_from_file_location(
        "_backend_convergence_semantic_authority",
        REPO / SEMANTIC_AUTHORITY_GATE,
    )
    if spec is None or spec.loader is None:
        return ["semantic-authority-classifier:unavailable"]
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tree = module.SourceTree({str(path): text for path, text in overrides.items()})
    report = module.build_report(tree, report_only=False)
    errors = []
    for backend, section in report["backends"].items():
        for authority_class, findings in section["findings"].items():
            if authority_class not in SEMANTIC_AUTHORITY_CLASSES:
                continue
            for finding in findings:
                path = Path(finding["path"])
                if path not in SEMANTIC_AUTHORITY_SURFACES:
                    continue
                errors.append(
                    "semantic-authority:"
                    f"{backend}:{authority_class}:{path}:{finding['symbol']}"
                )
    return errors


def validate(overrides: dict[Path, str] | None = None) -> list[str]:
    overrides = overrides or {}
    errors: list[str] = []
    errors.extend(_semantic_authority_errors(overrides))

    production = []
    for base in (Path("include/Neutrino"), Path("lib/backends")):
        for path in (REPO / base).rglob("*"):
            rel = path.relative_to(REPO)
            if path.suffix in {".h", ".cpp", ".inc"}:
                production.append(rel)
    production.extend(path for path in overrides if path not in production)
    for path in sorted(set(production)):
        code = _code(_read(path, overrides))
        if path != Path("include/Neutrino/BackendProjectionDriver.h"):
            if GENERIC_DECISION_HELPER.search(code):
                errors.append(f"generic-decision-helper:{path}")
            if GENERIC_DECISION_ALIAS.search(code):
                errors.append(f"generic-decision-alias:{path}")
        found = sorted(set(LEGACY.findall(code)))
        if found:
            errors.append(f"legacy-entry:{path}:{','.join(found)}")

    for path in (
        SOL_PROVIDER,
        SOL_ADAPTER,
        SOL_VALIDATION,
        SOL_RENDERER,
        SOL_ADAPTER_HEADER,
        SOL_VALIDATION_HEADER,
        SOL_RENDERER_HEADER,
        PG_MODEL,
        PG_HEADER,
    ):
        text = _read(path, overrides)
        direct = re.findall(r'^\s*#\s*include\s+"([^"]+)"', text, re.MULTILINE)
        forbidden = [
            item
            for item in direct
            if re.search(r"(CoordinationPlan|Spec|View|L2)", item)
        ]
        if forbidden:
            errors.append(f"backend-intake-include:{path}:{','.join(forbidden)}")

    sol_code = "\n".join(
        _code(_read(path, overrides))
        for path in (SOL_PROVIDER, SOL_ADAPTER, SOL_VALIDATION, SOL_RENDERER)
    )
    if re.search(r"\b(?:CoordinationPlan|coordinationPlan)\b", sol_code):
        errors.append("backend-source-authority-read:solidity")
    if "projectBackendGraph" in sol_code:
        errors.append("backend-projector-call:solidity")

    pg_text = _read(PG_MODEL, overrides)
    pg_code = _code(_without_pg_carveouts(pg_text))
    if re.search(r"\b(?:CoordinationPlan|coordinationPlan|AttestationPolicy)\b", pg_code):
        errors.append("backend-source-authority-read:postgres")
    if "projectBackendGraph" in pg_code:
        errors.append("backend-projector-call:postgres")

    for path, entries in MODEL_ENTRIES.items():
        code = _code(_read(path, overrides))
        for entry in entries:
            count = len(re.findall(rf"\b{entry}\s*\(", code))
            if count != 1:
                errors.append(f"adapter-entry-cardinality:{path}:{entry}:{count}")

    for path, names in REQUIRED_IDIOMS.items():
        text = _read(path, overrides)
        for name in names:
            count = len(re.findall(rf"^\s*def\s+{name}\b", text, re.MULTILINE))
            if count != 1:
                errors.append(f"idiom-cardinality:{path}:{name}:{count}")

    driver_code = _code(_read(PROJECTION_DRIVER, overrides))
    if re.search(r"\b(?:Solidity|Postgres|TargetSpec|targetName|domainName)\b",
                 driver_code):
        errors.append("shared-driver-target-dispatch")

    entry_contracts = {
        SOL_ENTRY: (
            "projectBackendGraph",
            "materializeSolidityProjectionArtifact",
        ),
        PG_ENTRY: (
            "projectBackendGraph",
            "materializePostgresProjection",
            "renderPostgresProjection",
        ),
    }
    for path, tokens in entry_contracts.items():
        code = _code(_read(path, overrides))
        for token in tokens:
            if token not in code:
                errors.append(f"thin-adapter-missing:{path}:{token}")

    return errors


def _probe(name: str) -> dict[Path, str]:
    overrides: dict[Path, str] = {}
    if name == "missing-idiom":
        text = _read(SOL_TD, {})
        overrides[SOL_TD] = text.replace(
            "def ContractShell", "def ContractShellRemoved", 1
        )
    elif name == "duplicate-binding":
        text = _read(PG_TD, {})
        overrides[PG_TD] = text + "\ndef CallableBody : PgNode<999, \"x\", 1, \"x\">;\n"
    elif name == "alternate-entry":
        text = _read(SOL_ENTRY, {})
        overrides[SOL_ENTRY] = (
            text
            + "\nnamespace neutrino { void legalizeSolidityLegacy() {} }\n"
        )
    elif name == "dormant-helper":
        text = _read(PG_MODEL, {})
        overrides[PG_MODEL] = (
            text
            + "\nstatic void replayFromPlan(const CoordinationPlan &p) "
            "{ (void)p.workflowKey; }\n"
        )
    elif name == "legacy-resurrection":
        overrides[Path("lib/backends/solidity/LegacyRail.cpp")] = (
            "namespace neutrino { void legalizeSolidity() {} }\n"
        )
    elif name == "projected-field-branch":
        text = _read(SOL_PROVIDER, {})
        overrides[SOL_PROVIDER] = (
            text
            + "\nstatic void selectProjectedLedger("
            "const projection::BackendProjectionGraph &projection) "
            "{ if (projection.ledgerPostings.empty()) return; }\n"
        )
    elif name == "projected-field-helper":
        text = _read(SOL_PROVIDER, {})
        overrides[SOL_PROVIDER] = (
            text
            + "\nstatic void selectProjectedBalance("
            "const projection::BackendProjectionGraph &projection) "
            "{ projection_driver::when(!projection.balanceAssertions.empty(), "
            "[] {}); }\n"
        )
    elif name == "projected-field-helper-alias":
        text = _read(SOL_PROVIDER, {})
        overrides[SOL_PROVIDER] = (
            text
            + "\nnamespace pd = neutrino::projection_driver;\n"
            "static void selectProjectedBalanceAlias("
            "const projection::BackendProjectionGraph &projection) "
            "{ pd::when(!projection.balanceAssertions.empty(), [] {}); }\n"
        )
    elif name == "projected-field-helper-wrapper":
        wrapper = Path("include/Neutrino/ProjectionDecisionWrapper.h")
        overrides[wrapper] = (
            '#include "Neutrino/BackendProjectionDriver.h"\n'
            "namespace neutrino { template <typename Action> "
            "void visitBalance(bool present, Action action) { "
            "projection_driver::when(present, action); } }\n"
        )
        text = _read(SOL_PROVIDER, {})
        overrides[SOL_PROVIDER] = (
            '#include "Neutrino/ProjectionDecisionWrapper.h"\n'
            + text
            + "\nstatic void selectProjectedBalanceWrapper("
            "const projection::BackendProjectionGraph &projection) "
            "{ neutrino::visitBalance(!projection.balanceAssertions.empty(), "
            "[] {}); }\n"
        )
    elif name == "shared-driver-target-dispatch":
        text = _read(PROJECTION_DRIVER, {})
        overrides[PROJECTION_DRIVER] = (
            text
            + "\nnamespace neutrino::projection_driver { "
            "enum class Postgres { Enabled }; }\n"
        )
    else:
        raise ValueError(name)
    return overrides


PROBES = (
    "missing-idiom",
    "duplicate-binding",
    "alternate-entry",
    "dormant-helper",
    "legacy-resurrection",
    "projected-field-branch",
    "projected-field-helper",
    "projected-field-helper-alias",
    "projected-field-helper-wrapper",
    "shared-driver-target-dispatch",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--probe", choices=PROBES)
    args = parser.parse_args()

    if args.probe:
        errors = validate(_probe(args.probe))
        if errors:
            print(f"probe-failed-as-expected:{args.probe}")
            for error in errors:
                print(error)
            return 1
        print(f"probe-did-not-bite:{args.probe}")
        return 0

    errors = validate()
    if errors:
        for error in errors:
            print(error)
        return 1
    if args.selftest:
        for probe in PROBES:
            if not validate(_probe(probe)):
                print(f"selftest-probe-did-not-bite:{probe}")
                return 1
        print("backend-convergence-selftest:ok")
    else:
        print("backend-convergence:ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
