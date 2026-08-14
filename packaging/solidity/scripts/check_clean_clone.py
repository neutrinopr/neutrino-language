#!/usr/bin/env python3
"""Materialize and verify the exact Solidity backend extraction ()."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "packaging/solidity/extraction-manifest.json"

BACKEND_SOURCES = [
    "lib/backends/solidity/provider/SolidityTargetValidation.cpp",
    "lib/backends/solidity/provider/SolidityTargetAdapter.cpp",
    "lib/backends/solidity/provider/SolidityRenderer.cpp",
    "lib/backends/solidity/provider/SolidityRecipeProvider.cpp",
    "lib/backends/solidity/GenSolidityQuorumGuard.cpp",
    "lib/backends/solidity/provider/SolidityEmit.cpp",
]
SHARED_RUNTIME_SOURCES = [
    "lib/spec-contract/ValueModel.cpp",
    "lib/spec-contract/JsonUtil.cpp",
    "lib/spec-contract/Expr.cpp",
    "lib/spec-contract/BackendProjection.cpp",
    "lib/spec-contract/BackendProjectionCodec.cpp",
    "lib/spec-contract/BackendProtocol.cpp",
    "lib/spec-contract/BackendStartup.cpp",
    "lib/spec-contract/StrCase.cpp",
    "lib/codetext/CodeText.cpp",
    "lib/codetext/TargetPrinter.cpp",
    "lib/recipe/RecipeRuntime.cpp",
    "lib/recipe/RecipeModule.cpp",
    "lib/recipe/RecipeInterpreter.cpp",
    "lib/recipe/RecipeExecutor.cpp",
    "lib/recipe/RecipeProviderRegistry.cpp",
]
SHARED_RUNTIME_HEADERS = [
    "include/Neutrino/BackendProjection.h",
    "include/Neutrino/BackendProjectionCodec.h",
    "include/Neutrino/BackendProjectionDriver.h",
    "include/Neutrino/BackendProtocol.h",
    "include/Neutrino/BackendStartup.h",
    "include/Neutrino/CodeText.h",
    "include/Neutrino/Expr.h",
    "include/Neutrino/JsonUtil.h",
    "include/Neutrino/ProjectionGateMode.h",
    "include/Neutrino/RecipeModule.h",
    "include/Neutrino/RecipeProviderRegistry.h",
    "include/Neutrino/RecipeRuntime.h",
    "include/Neutrino/RecipeSessionStore.h",
    "include/Neutrino/StrCase.h",
    "include/Neutrino/TargetPrinter.h",
    "include/Neutrino/ValueModel.h",
]
SHARED_RUNTIME_CONSUMER_HEADERS = [
    "include/Neutrino/BackendProjectionDriver.h",
    "include/Neutrino/RecipeSessionStore.h",
]
BACKEND_HEADERS = [
    "include/Neutrino/SolidityEmit.h",
    "include/Neutrino/SolidityPackageArtifacts.h",
    "lib/backends/solidity/provider/SolidityRecipeProvider.h",
    "lib/backends/solidity/provider/SolidityRenderer.h",
    "lib/backends/solidity/provider/SolidityTargetAdapter.h",
    "lib/backends/solidity/provider/SolidityTargetValidation.h",
]
SHARED_RUNTIME_CONTRACT = [
    "packaging/shared/backend-source-runtime-v1.json",
]
TABLEGEN_INPUTS = [
    "lib/backends/BackendIdiom.td",
    "lib/backends/TargetPrinter.td",
    "lib/backends/solidity/model/SolidityTargetNodes.td",
    "lib/backends/solidity/recipes/SolidityIdiomRecipes.td",
    "lib/backends/solidity/recipes/SolidityEvidenceIdiomRecipes.td",
    "lib/backends/solidity/recipes/SolidityTemporalIdiomRecipes.td",
    "lib/backends/solidity/recipes/SolidityEffectfulIdiomRecipes.td",
    "lib/backends/solidity/recipes/SolidityProjectionSchema.td",
]
GENERATORS = [
    "scripts/generators/backend_recipe_gen.py",
    "scripts/generators/gen_backend_idiom_recipes.py",
    "scripts/generators/gen_finalized_projection_schema.py",
    "scripts/generators/gen_target_node_registry.py",
]
GENERATOR_INPUTS = [
    "docs/schemas/finalized-projection-v1.schema.json",
    "include/Neutrino/BackendProjection.h",
    "include/Neutrino/CoordinationPlan.h",
    "include/Neutrino/ProjectionGateMode.h",
]
AUTHORED_INCLUDES = [
    "lib/backends/solidity/CoordinationEnvelope.sol.inc",
    "lib/backends/solidity/ThresholdQuorumAcceptance.sol.inc",
    "lib/backends/solidity/provider/SolidityCallableCoverage.inc",
    "lib/backends/solidity/provider/SolidityRecipePackage.inc",
]
PACKAGE_BUILD = [
    "docs/m7-core-installed-export.json",
    "lib/backends/solidity/CMakeLists.txt",
    "lib/backends/solidity/EXTRACTION.md",
    "packaging/solidity/CMakeLists.txt",
    "packaging/solidity/README.md",
    "packaging/solidity/scripts/check_clean_clone.py",
    "packaging/solidity/src/SolidityBackendMain.cpp",
]
TESTS = [
    "lib/backends/solidity/test/solidity_stmt_shell_render_harness.cpp",
    "examples/target-profiles/solidity.target-profile.json",
    "test/ir/samples/Inputs/core_document_escrow/source/core_document_escrow.neu",
    "test/ir/samples/Inputs/core_document_escrow/scenario/core_document_escrow_happy_path.json",
    "test/ir/samples/Inputs/core_document_escrow/generated/solidity/foundry.toml",
    "test/ir/samples/Inputs/core_document_escrow/generated/solidity/src/CoreDocumentEscrow.sol",
    "test/ir/samples/Inputs/core_document_escrow/generated/solidity/test/CoreDocumentEscrow.t.sol",
]

GROUPS = {
    "backendSources": BACKEND_SOURCES,
    "sharedRuntimeSources": SHARED_RUNTIME_SOURCES,
    "sharedRuntimeHeaders": SHARED_RUNTIME_HEADERS,
    "sharedRuntimeContract": SHARED_RUNTIME_CONTRACT,
    "backendHeaders": BACKEND_HEADERS,
    "tablegenInputs": TABLEGEN_INPUTS,
    "generators": GENERATORS,
    "generatorInputs": GENERATOR_INPUTS,
    "authoredIncludes": AUTHORED_INCLUDES,
    "packageBuild": PACKAGE_BUILD,
    "testsAndFixtures": TESTS,
}

# The package's contract (M7_BACKEND_PACKAGE_BOUNDARY_ADR section 9) is that it owns
# *compilable Solidity sources*; the Foundry config and tests under
# test/ir/samples/.../generated/solidity are re-homed to the Web3 runtime layer. Those
# re-homed files are today the ONLY committed statement of the compiler settings the
# emitted sources actually require, so the package restates them here and proves them
# below rather than inheriting them from a fixture it is giving up. `optimizer`/`via_ir`
# are load-bearing, not stylistic: without them solc 0.8.x aborts the emitted contract
# with "Stack too deep", which the negative control in verify() asserts.
SOURCES_ONLY_FOUNDRY_TOML = (
    "[profile.default]\n"
    "src = 'src'\n"
    "out = 'out'\n"
    "libs = []\n"
    "optimizer = true\n"
    "via_ir = true\n"
)

GENERATED_PRODUCTS = [
    "BackendProjectionCodecFields.inc",
    "SolidityEmitBuilderDecls.inc",
    "SolidityEmitBuilders.inc",
    "SolidityPrinterHandlers.inc",
    "SolidityProjection.inc",
    "SolidityRecipeBuilders.inc",
    "SolidityTargetEnums.inc",
    "SolidityTargetNodes.inc",
    "finalized-projection-v1.schema.json",
    "solidity_recipes.inc",
]

DECLARED_BUILD_INPUTS = sorted(
    set(
        BACKEND_SOURCES
        + SHARED_RUNTIME_SOURCES
        + SHARED_RUNTIME_HEADERS
        + BACKEND_HEADERS
        + TABLEGEN_INPUTS
        + GENERATORS
        + GENERATOR_INPUTS
        + AUTHORED_INCLUDES
        + [
            "packaging/solidity/CMakeLists.txt",
            "packaging/solidity/src/SolidityBackendMain.cpp",
            "lib/backends/solidity/test/solidity_stmt_shell_render_harness.cpp",
        ]
    )
)
MATERIALIZED_BUILD_INPUTS = DECLARED_BUILD_INPUTS + ["CMakeLists.txt"]

GENERATED_EDGES = {
    "BackendProjectionCodecFields.inc": {
        "producer": "scripts/generators/gen_finalized_projection_schema.py",
        "inputs": GENERATOR_INPUTS,
    },
    "SolidityEmitBuilderDecls.inc": {
        "producer": "scripts/generators/backend_recipe_gen.py",
        "inputs": [
            "lib/backends/TargetPrinter.td",
            "lib/backends/solidity/model/SolidityTargetNodes.td",
        ],
    },
    "SolidityEmitBuilders.inc": {
        "producer": "scripts/generators/backend_recipe_gen.py",
        "inputs": [
            "lib/backends/TargetPrinter.td",
            "lib/backends/solidity/model/SolidityTargetNodes.td",
        ],
    },
    "SolidityPrinterHandlers.inc": {
        "producer": "scripts/generators/gen_target_node_registry.py",
        "inputs": [
            "lib/backends/TargetPrinter.td",
            "lib/backends/solidity/model/SolidityTargetNodes.td",
        ],
    },
    "SolidityProjection.inc": {
        "producer": "scripts/generators/backend_recipe_gen.py",
        "inputs": [
            "lib/backends/TargetPrinter.td",
            "lib/backends/solidity/model/SolidityTargetNodes.td",
            "lib/backends/solidity/recipes/SolidityProjectionSchema.td",
        ],
    },
    "SolidityRecipeBuilders.inc": {
        "producer": "scripts/generators/backend_recipe_gen.py",
        "inputs": [
            "lib/backends/BackendIdiom.td",
            "lib/backends/solidity/model/SolidityTargetNodes.td",
            "lib/backends/solidity/recipes/SolidityEffectfulIdiomRecipes.td",
            "lib/backends/solidity/recipes/SolidityEvidenceIdiomRecipes.td",
            "lib/backends/solidity/recipes/SolidityIdiomRecipes.td",
            "lib/backends/solidity/recipes/SolidityTemporalIdiomRecipes.td",
        ],
    },
    "SolidityTargetEnums.inc": {
        "producer": "scripts/generators/gen_target_node_registry.py",
        "inputs": [
            "lib/backends/TargetPrinter.td",
            "lib/backends/solidity/model/SolidityTargetNodes.td",
        ],
    },
    "SolidityTargetNodes.inc": {
        "producer": "scripts/generators/gen_target_node_registry.py",
        "inputs": [
            "lib/backends/TargetPrinter.td",
            "lib/backends/solidity/model/SolidityTargetNodes.td",
        ],
    },
    "solidity_recipes.inc": {
        "producer": "scripts/generators/gen_backend_idiom_recipes.py",
        "inputs": [
            "lib/backends/BackendIdiom.td",
            "lib/backends/solidity/recipes/SolidityEffectfulIdiomRecipes.td",
            "lib/backends/solidity/recipes/SolidityEvidenceIdiomRecipes.td",
            "lib/backends/solidity/recipes/SolidityIdiomRecipes.td",
            "lib/backends/solidity/recipes/SolidityTemporalIdiomRecipes.td",
        ],
    },
    "finalized-projection-v1.schema.json": {
        "producer": "scripts/generators/gen_finalized_projection_schema.py",
        "inputs": GENERATOR_INPUTS,
        "byteComparedWith": "docs/schemas/finalized-projection-v1.schema.json",
    },
}


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def file_identity(path: Path, relative: str) -> dict:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"artifact is not a regular file: {relative}")
    data = path.read_bytes()
    return {
        "path": relative,
        "byteLen": len(data),
        "sha256": digest(data),
    }


def source_identity() -> dict:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
    ).strip()
    paths = sorted(
        {path for group in GROUPS.values() for path in group}
        | {MANIFEST.relative_to(ROOT).as_posix()}
    )
    rows = []
    for relative in paths:
        current = (ROOT / relative).read_bytes()
        try:
            committed = subprocess.check_output(
                ["git", "show", f"{head}:{relative}"], cwd=ROOT
            )
        except subprocess.CalledProcessError as error:
            raise RuntimeError(
                f"manifested source is not committed at {head}: {relative}"
            ) from error
        if current != committed:
            raise RuntimeError(
                f"manifested source differs from commit {head}: {relative}"
            )
        rows.append(
            {
                "path": relative,
                "byteLen": len(committed),
                "sha256": digest(committed),
            }
        )
    return {
        "commit": head,
        "tree": tree,
        "manifestedBlobSetDigest": digest(canonical(rows)),
        "manifestedBlobCount": len(rows),
    }


def expected_shared_runtime_contract() -> dict:
    body = {
        "compileDefinitions": ["NEUTRINO_PROJECTION_CONSUMER_ONLY"],
        "dependencies": [
            {
                "identity": "LLVM Support",
                "majorVersion": 15,
            }
        ],
        "consumerHeaders": SHARED_RUNTIME_CONSUMER_HEADERS,
        "headers": [
            file_identity(ROOT / path, path)
            for path in sorted(SHARED_RUNTIME_HEADERS)
        ],
        "kind": "neutrino.backend-source-runtime/1",
        "schemaVersion": 1,
        "sources": [
            file_identity(ROOT / path, path)
            for path in sorted(SHARED_RUNTIME_SOURCES)
        ],
    }
    body["contractDigest"] = digest(canonical(body))
    return body


def check_shared_runtime_contract(write: bool) -> None:
    path = ROOT / SHARED_RUNTIME_CONTRACT[0]
    expected = expected_shared_runtime_contract()
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(
            json.dumps(expected, indent=2, sort_keys=True).encode() + b"\n"
        )
        return
    actual = json.loads(path.read_text())
    if actual != expected:
        raise RuntimeError(
            "shared runtime contract is stale; run "
            "check_clean_clone.py --write-manifest"
        )


def expected_manifest() -> dict:
    groups = {}
    for name, paths in GROUPS.items():
        ownership = (
            "neutrino.backend-source-runtime/1"
            if name
            in {
                "sharedRuntimeSources",
                "sharedRuntimeHeaders",
                "sharedRuntimeContract",
            }
            else "neutrino.solidity-package/1"
        )
        groups[name] = [
            {
                "path": path,
                "sha256": digest((ROOT / path).read_bytes()),
                "byteLen": (ROOT / path).stat().st_size,
                "provenance": f"neutrino-translator:{path}",
                "ownership": ownership,
                "licenseDisposition": "project-authored-apache-2.0",
            }
            for path in sorted(paths)
        ]
    return {
        "kind": "neutrino.solidity-extraction-manifest/1",
        "documentId": "urn:neutrino:document:solidity-package-extraction-v1",
        "unit": "NeutrinoBackendSolidity",
        "sourceBoundary": "lib/backends/solidity/EXTRACTION.md",
        "groups": groups,
        "generatedBuildProducts": GENERATED_PRODUCTS,
        "dependencyGraph": {
            "generatedEdges": GENERATED_EDGES,
            "linkEdges": [
                {
                    "from": "neutrino-solidity-backend",
                    "to": "neutrino-solidity-package-private",
                    "visibility": "private",
                },
                {
                    "from": "neutrino-solidity-package-private",
                    "to": "neutrino.backend-source-runtime/1",
                    "visibility": "private-source",
                },
                {
                    "from": "neutrino.backend-source-runtime/1",
                    "to": "LLVM Support 15",
                    "visibility": "private",
                },
            ],
            "runtimeEdge": {
                "from": "installed backend-free core",
                "to": "neutrino-solidity-backend",
                "startup": "neutrino.backend-startup/1",
                "contract": "neutrino.backend-protocol/1",
                "payload": "neutrino.finalized-projection/1",
            },
        },
        "installedCoreContract": {
            "manifest": "docs/m7-core-installed-export.json",
            "cppAbiPolicy": "forbidden",
            "startup": "neutrino.backend-startup/1",
            "protocol": "neutrino.backend-protocol/1",
            "projectionSchema": "neutrino.finalized-projection/1",
        },
        "sharedRuntimeContract": {
            "kind": "neutrino.backend-source-runtime/1",
            "contractPath": SHARED_RUNTIME_CONTRACT[0],
            "contractDigest": expected_shared_runtime_contract()[
                "contractDigest"
            ],
            "contractFileSha256": digest(
                (ROOT / SHARED_RUNTIME_CONTRACT[0]).read_bytes()
            ),
            "ownership": "versioned-shared-source-dependency",
            "cppAbiCrossesProcess": False,
            "contents": [
                "canonical finalized-projection consumer",
                "protocol state machine",
                "target-blind recipe runtime",
                "target-blind CodeText printer",
            ],
        },
        "provenance": {
            "licenseStatus": "project-authored-apache-2.0",
            "publicationAuthorized": False,
        },
        "forbiddenReachback": [
            "lib/backends/postgres",
            "translator-checkout-absolute-path",
            "undeclared-generated-product",
            "uninstalled-private-core-path",
        ],
    }


def check_manifest(write: bool) -> None:
    check_shared_runtime_contract(write)
    expected = expected_manifest()
    if write:
        MANIFEST.write_bytes(
            json.dumps(expected, indent=2, sort_keys=True).encode() + b"\n"
        )
        return
    actual = json.loads(MANIFEST.read_text())
    if actual != expected:
        raise RuntimeError(
            "extraction manifest is stale; run check_clean_clone.py --write-manifest"
        )


def materialize(destination: Path) -> None:
    for paths in GROUPS.values():
        for source in paths:
            target = destination / source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / source, target)
    shutil.copy2(
        ROOT / "packaging/solidity/CMakeLists.txt",
        destination / "CMakeLists.txt",
    )
    shutil.copy2(MANIFEST, destination / "extraction-manifest.json")


def audit_candidate(candidate: Path) -> list[str]:
    expected = {
        path
        for paths in GROUPS.values()
        for path in paths
    } | {"CMakeLists.txt", "extraction-manifest.json"}
    core_manifest = candidate / "docs/m7-core-installed-export.json"
    if (candidate / "core-install").exists() and core_manifest.is_file():
        value = json.loads(core_manifest.read_text())
        expected.update(
            "core-install/" + path
            for path in value["runtimeArtifacts"] + value["dataArtifacts"]
        )
    reasons = []
    actual = set()
    for path in candidate.rglob("*"):
        relative = path.relative_to(candidate).as_posix()
        if path.is_symlink():
            reasons.append(f"symlink:{relative}")
            continue
        if path.is_file():
            actual.add(relative)
    for missing in sorted(expected - actual):
        reasons.append(f"missing:{missing}")
    for extra in sorted(actual - expected):
        if extra.startswith("lib/backends/postgres/"):
            kind = "sibling-backend"
        elif extra.startswith("lib/backends/solidity/generated/"):
            kind = "undeclared-generated"
        elif extra.startswith("include/Neutrino/"):
            kind = "hidden-header"
        elif extra.startswith("core-private/"):
            kind = "private-core-path"
        else:
            kind = "undeclared-file"
        reasons.append(f"{kind}:{extra}")
    reasons.extend(audit_declared_access(candidate))
    return reasons


def audit_declared_access(candidate: Path) -> list[str]:
    reasons = []
    absolute_checkout = str(ROOT.resolve())
    quoted = re.compile(r"""["']([^"'\n]*\.\./[^"'\n]*)["']""")
    for relative in MATERIALIZED_BUILD_INPUTS:
        path = candidate / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        if absolute_checkout in text:
            reasons.append(f"declared-file-reachback:{relative}:absolute-checkout")
        for match in quoted.finditer(text):
            spelling = match.group(1)
            if "$" in spelling or "{" in spelling:
                continue
            resolved = (path.parent / spelling).resolve()
            try:
                resolved.relative_to(candidate.resolve())
            except ValueError:
                reasons.append(
                    f"declared-file-reachback:{relative}:relative-escape"
                )
    return reasons


def isolation_prefix() -> list[str]:
    sandbox = shutil.which("sandbox-exec")
    if sandbox is None:
        raise RuntimeError(
            "clean-clone proof requires a checkout-denying isolation boundary"
        )
    profile = (
        "(version 1)"
        "(allow default)"
        f'(deny file-read* (subpath "{ROOT.resolve()}"))'
    )
    return [sandbox, "-p", profile]


def run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command))
    subprocess.run(
        isolation_prefix() + command, cwd=cwd, env=env, check=True
    )


def run_expect(
    command: list[str],
    cwd: Path,
    expected: int,
    diagnostic: str,
    env: dict[str, str] | None = None,
) -> None:
    print("+", " ".join(command))
    completed = subprocess.run(
        isolation_prefix() + command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != expected or diagnostic not in completed.stderr:
        raise RuntimeError(
            f"expected exit {expected} with {diagnostic!r}: "
            f"{' '.join(command)}\nstdout:\n{completed.stdout}"
            f"\nstderr:\n{completed.stderr}"
        )


def compiler_header_closures(candidate: Path, build: Path) -> dict[str, set[str]]:
    output = subprocess.check_output(
        isolation_prefix() + ["ninja", "-C", str(build), "-t", "deps"],
        text=True,
    )
    closures: dict[str, set[str]] = {}
    current_target = None
    for raw in output.splitlines():
        if raw and not raw[0].isspace():
            match = re.search(r"CMakeFiles/([^/]+)\.dir/", raw)
            current_target = match.group(1) if match else None
            if current_target is not None:
                closures.setdefault(current_target, set())
            continue
        if current_target is None:
            continue
        spelling = raw.strip()
        if not spelling.startswith("/"):
            continue
        try:
            relative = (
                Path(spelling)
                .resolve()
                .relative_to(candidate.resolve())
                .as_posix()
            )
        except ValueError:
            continue
        if relative.startswith("include/Neutrino/") or (
            relative.startswith("lib/backends/solidity/provider/")
            and relative.endswith(".h")
        ):
            closures[current_target].add(relative)
    return closures


def verify_header_ownership(
    closures: dict[str, set[str]],
    *,
    shared_headers: set[str] | None = None,
    backend_headers: set[str] | None = None,
) -> dict[str, list[str]]:
    shared_headers = shared_headers or set(SHARED_RUNTIME_HEADERS)
    backend_headers = backend_headers or set(BACKEND_HEADERS)
    runtime_target = "neutrino-backend-source-runtime"
    backend_targets = {
        "neutrino-solidity-package-private",
        "neutrino-solidity-backend",
        "solidity-package-render-test",
    }
    missing_targets = sorted(
        ({runtime_target} | backend_targets) - set(closures)
    )
    if missing_targets:
        raise RuntimeError(
            f"compiler header closure has no objects for {missing_targets}"
        )

    runtime_used = closures[runtime_target]
    runtime_expected = shared_headers - set(SHARED_RUNTIME_CONSUMER_HEADERS)
    if runtime_used != runtime_expected:
        raise RuntimeError(
            "shared-runtime target header closure differs: "
            f"missing={sorted(runtime_expected - runtime_used)}, "
            f"extra={sorted(runtime_used - runtime_expected)}"
        )
    if runtime_used & backend_headers:
        raise RuntimeError(
            "shared-runtime target consumes backend-owned headers: "
            f"{sorted(runtime_used & backend_headers)}"
        )

    backend_used = set().union(*(closures[target] for target in backend_targets))
    declared = shared_headers | backend_headers
    if backend_used - declared:
        raise RuntimeError(
            "backend target header closure has undeclared headers: "
            f"{sorted(backend_used - declared)}"
        )
    if not backend_headers <= backend_used:
        raise RuntimeError(
            "backend-owned header closure is not exercised: "
            f"{sorted(backend_headers - backend_used)}"
        )
    observed_shared = runtime_used | backend_used
    if not shared_headers <= observed_shared:
        raise RuntimeError(
            "shared-runtime header closure is not exercised: "
            f"{sorted(shared_headers - observed_shared)}"
        )
    return {
        target: sorted(closures[target])
        for target in [runtime_target] + sorted(backend_targets)
    }


def verify_compiler_header_closure(
    candidate: Path, build: Path
) -> dict[str, list[str]]:
    closures = compiler_header_closures(candidate, build)
    verified = verify_header_ownership(closures)

    shared = set(SHARED_RUNTIME_HEADERS)
    backend = set(BACKEND_HEADERS)
    backend_only = "include/Neutrino/SolidityEmit.h"
    shared.add(backend_only)
    backend.remove(backend_only)
    try:
        verify_header_ownership(
            closures,
            shared_headers=shared,
            backend_headers=backend,
        )
    except RuntimeError as error:
        if "shared-runtime target header closure differs" not in str(error):
            raise RuntimeError(
                "backend-header misclassification failed for the wrong reason"
            ) from error
    else:
        raise RuntimeError(
            "backend-only header misclassified as shared did not bite"
        )
    return verified


def package_descriptor(binary: Path, package: Path) -> dict:
    entry = package / "bin/neutrino-solidity-backend"
    entry.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binary, entry)
    entry.chmod(0o755)
    profile = json.loads(
        (
            ROOT / "examples/target-profiles/solidity.target-profile.json"
        ).read_text()
    )
    descriptor = {
        "apiVersion": 1,
        "capabilities": ["emit", "stream"],
        "closure": [
            {
                "byteLen": entry.stat().st_size,
                "path": "bin/neutrino-solidity-backend",
                "sha256": digest(entry.read_bytes()),
            }
        ],
        "compatibilityBounds": {
            "coreProtocol": {
                "max": {"major": 1, "minor": 0},
                "min": {"major": 1, "minor": 0},
            },
            "projectionSchema": {"max": 5, "min": 5},
        },
        "entry": "bin/neutrino-solidity-backend",
        "kind": "neutrino.backend-package/1",
        "licenseIdentity": "spdx:Apache-2.0",
        "profileSummary": profile,
        "protocolMajor": 1,
        "protocolMinor": 0,
        "targetIdentity": "solidity",
        "targetProfileIdentity": "target.evm.v1",
    }
    descriptor["manifestDigest"] = digest(canonical(descriptor))
    (package / "backend-package.json").write_bytes(canonical(descriptor))
    return descriptor


def core_artifact_identity(core: Path, export_contract: dict) -> dict:
    rows = [
        file_identity(core / relative, relative)
        for relative in export_contract["runtimeArtifacts"]
        + export_contract["dataArtifacts"]
    ]
    return {
        "artifactCount": len(rows),
        "artifacts": rows,
        "treeDigest": digest(canonical(rows)),
    }


def require_core_identity(core: Path, expected: dict) -> None:
    contract = json.loads(
        (ROOT / "docs/m7-core-installed-export.json").read_text()
    )
    actual = core_artifact_identity(core, contract)
    if actual != {
        "artifactCount": expected["artifactCount"],
        "artifacts": expected["artifacts"],
        "treeDigest": expected["treeDigest"],
    }:
        raise RuntimeError("installed core artifact identity mismatch")


def materialize_core(core: Path, destination: Path) -> dict:
    manifest = ROOT / "docs/m7-core-installed-export.json"
    value = json.loads(manifest.read_text())
    if value.get("cppAbiPolicy") != "forbidden":
        raise RuntimeError("installed core does not enforce the zero-C++-ABI policy")
    supplied = core_artifact_identity(core, value)
    for rel in value["runtimeArtifacts"] + value["dataArtifacts"]:
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(core / rel, target)
    copied = core_artifact_identity(destination, value)
    if copied != supplied:
        raise RuntimeError("installed core changed while being materialized")
    supplied["exportContractDigest"] = digest(manifest.read_bytes())
    supplied["exportContractKind"] = value["kind"]
    return supplied


def core_substitution_probe(core: Path, identity: dict) -> None:
    entry = core / "bin/neutrino-gen"
    original = entry.read_bytes()
    if not original:
        raise RuntimeError("installed core entry is empty")
    mutated = bytearray(original)
    mutated[len(mutated) // 2] ^= 1
    entry.write_bytes(mutated)
    try:
        try:
            require_core_identity(core, identity)
        except RuntimeError as error:
            if "identity mismatch" not in str(error):
                raise
        else:
            raise RuntimeError("core-artifact substitution mutation did not bite")
    finally:
        entry.write_bytes(original)
        entry.chmod(0o755)
    require_core_identity(core, identity)


def reachback_probe(candidate: Path, probe: str) -> None:
    forbidden = {
        "hidden-header": candidate / "include/Neutrino/HiddenCorePrivate.h",
        "undeclared-generated": candidate
        / "lib/backends/solidity/generated/Undeclared.inc",
        "sibling-backend": candidate / "lib/backends/postgres/Reachback.cpp",
        "private-core-path": candidate / "core-private/BackendProjection.h",
    }
    path = forbidden[probe]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("probe\n")
    reasons = audit_candidate(candidate)
    if not any(reason.startswith(probe + ":") for reason in reasons):
        raise RuntimeError(f"{probe} mutation did not bite: {reasons}")
    path.unlink()


def declared_file_reachback_probe(candidate: Path, llvm_dir: str) -> None:
    cmake = candidate / "CMakeLists.txt"
    original = cmake.read_bytes()
    mutation = (
        "\n# biting declared-input reach-back mutation\n"
        f'file(READ "{ROOT.resolve()}/README.md" '
        "NEUTRINO_UNDECLARED_CHECKOUT_BYTES)\n"
    ).encode()
    cmake.write_bytes(original + mutation)
    try:
        reasons = audit_declared_access(candidate)
        if not any(
            reason.startswith("declared-file-reachback:") for reason in reasons
        ):
            raise RuntimeError(
                "declared-file reach-back mutation escaped the source audit"
            )
        probe_build = candidate / "reachback-build"
        command = [
            "cmake",
            "-S",
            str(candidate),
            "-B",
            str(probe_build),
            "-G",
            "Ninja",
            f"-DLLVM_DIR={llvm_dir}",
            "-DCMAKE_BUILD_TYPE=Release",
        ]
        completed = subprocess.run(
            isolation_prefix() + command,
            cwd=candidate,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if completed.returncode == 0:
            raise RuntimeError(
                "declared-file reach-back succeeded inside isolation boundary"
            )
        if "README.md" not in completed.stdout:
            raise RuntimeError(
                "declared-file reach-back failed for an unrelated reason"
            )
    finally:
        cmake.write_bytes(original)
        shutil.rmtree(candidate / "reachback-build", ignore_errors=True)


def declared_file_audit_probe(candidate: Path) -> None:
    cmake = candidate / "CMakeLists.txt"
    original = cmake.read_bytes()
    cmake.write_bytes(
        original
        + f'\nfile(READ "{ROOT.resolve()}/README.md" ESCAPED)\n'.encode()
    )
    try:
        reasons = audit_declared_access(candidate)
        if not any(
            reason.startswith("declared-file-reachback:") for reason in reasons
        ):
            raise RuntimeError(
                "declared-file reach-back mutation escaped the source audit"
            )
    finally:
        cmake.write_bytes(original)


def verify(args: argparse.Namespace) -> None:
    check_manifest(False)
    source = source_identity()
    supplied_core = args.core_prefix.resolve()
    with tempfile.TemporaryDirectory(prefix="neutrino-solidity-clone.") as raw:
        candidate = Path(raw)
        materialize(candidate)
        core = candidate / "core-install"
        core_identity = materialize_core(supplied_core, core)
        core_substitution_probe(core, core_identity)
        if reasons := audit_candidate(candidate):
            raise RuntimeError(f"fresh candidate inventory is not exact: {reasons}")
        for probe in (
            "hidden-header",
            "undeclared-generated",
            "sibling-backend",
            "private-core-path",
        ):
            reachback_probe(candidate, probe)
        declared_file_reachback_probe(candidate, args.llvm_dir)
        if reasons := audit_candidate(candidate):
            raise RuntimeError(
                f"candidate changed after reach-back probes: {reasons}"
            )

        build = candidate / "build"
        run(
            [
                "cmake",
                "-S",
                str(candidate),
                "-B",
                str(build),
                "-G",
                "Ninja",
                f"-DLLVM_DIR={args.llvm_dir}",
                "-DCMAKE_BUILD_TYPE=Release",
            ],
            candidate,
        )
        run(["cmake", "--build", str(build), "-j2"], candidate)
        header_closures = verify_compiler_header_closure(candidate, build)
        run(["ctest", "--test-dir", str(build), "--output-on-failure"], candidate)

        generated = build / "generated"
        if sorted(path.name for path in generated.iterdir()) != GENERATED_PRODUCTS:
            raise RuntimeError("generated build-product set is not exact")

        package = candidate / "package"
        descriptor = package_descriptor(
            build / "neutrino-solidity-backend", package
        )
        fixture_source = (
            candidate
            / "test/ir/samples/Inputs/core_document_escrow/source/core_document_escrow.neu"
        )
        fixture_scenario = (
            candidate
            / "test/ir/samples/Inputs/core_document_escrow/scenario/core_document_escrow_happy_path.json"
        )
        common = [
            str(core / "bin/neutrino-gen"),
            str(fixture_source),
            "--scenario",
            str(fixture_scenario),
            "--target",
            "solidity",
        ]

        run_expect(
            common + ["-o", str(candidate / "missing-package-output")],
            candidate,
            2,
            "error: --target must be",
        )
        duplicate = candidate / "duplicate-package"
        shutil.copytree(package, duplicate)
        run_expect(
            common
            + [
                "--backend-package-dir",
                str(package),
                "--backend-package-dir",
                str(duplicate),
                "-o",
                str(candidate / "duplicate-package-output"),
            ],
            candidate,
            2,
            "E_PACKAGE_DUPLICATE",
        )
        tampered = candidate / "tampered-package"
        shutil.copytree(package, tampered)
        tampered_descriptor = json.loads(
            (tampered / "backend-package.json").read_text()
        )
        tampered_descriptor["licenseIdentity"] = "tampered"
        (tampered / "backend-package.json").write_bytes(
            canonical(tampered_descriptor)
        )
        run_expect(
            common
            + [
                "--backend-package-dir",
                str(tampered),
                "-o",
                str(candidate / "tampered-package-output"),
            ],
            candidate,
            2,
            "E_PACKAGE_MANIFEST_DIGEST",
        )
        run_expect(
            common
            + [
                "--backend-package-dir",
                str(candidate / "disappeared-package"),
                "-o",
                str(candidate / "disappeared-package-output"),
            ],
            candidate,
            2,
            "E_PACKAGE_IO",
        )
        incompatible = candidate / "incompatible-package"
        shutil.copytree(package, incompatible)
        incompatible_descriptor = json.loads(
            (incompatible / "backend-package.json").read_text()
        )
        incompatible_descriptor["compatibilityBounds"]["coreProtocol"] = {
            "max": {"major": 2, "minor": 0},
            "min": {"major": 2, "minor": 0},
        }
        incompatible_descriptor.pop("manifestDigest")
        incompatible_descriptor["manifestDigest"] = digest(
            canonical(incompatible_descriptor)
        )
        (incompatible / "backend-package.json").write_bytes(
            canonical(incompatible_descriptor)
        )
        run_expect(
            common
            + [
                "--backend-package-dir",
                str(incompatible),
                "-o",
                str(candidate / "incompatible-package-output"),
            ],
            candidate,
            2,
            "E_VERSION",
        )

        output = candidate / "external-output"
        require_core_identity(core, core_identity)
        run(
            common
            + [
                "--backend-package-dir",
                str(package),
                "-o",
                "external-output",
            ],
            candidate,
        )
        produced = output / "src/CoreDocumentEscrow.sol"
        baseline = (
            candidate
            / "test/ir/samples/Inputs/core_document_escrow/generated/solidity/src/CoreDocumentEscrow.sol"
        )
        if produced.read_bytes() != baseline.read_bytes():
            raise RuntimeError("clean package Solidity bytes differ from baseline")

        dispatch_receipt = json.loads(
            (output / "backend-dispatch-receipt.json").read_text()
        )
        if (
            dispatch_receipt.get("targetIdentity") != "solidity"
            or dispatch_receipt.get("packageManifestDigest")
            != descriptor["manifestDigest"]
            or {
                row["path"]: (row["sha256"], row["byteLen"])
                for row in dispatch_receipt.get("artifacts", [])
            }.get("src/CoreDocumentEscrow.sol")
            != (digest(produced.read_bytes()), produced.stat().st_size)
        ):
            raise RuntimeError(
                "Solidity output is not bound to the verified dispatch receipt"
            )

        bundle_input = candidate / "bundle-input"
        bundle_input.mkdir()
        shutil.copy2(fixture_source, bundle_input / "source.neu")
        shutil.copy2(fixture_scenario, bundle_input / "scenario.json")
        (bundle_input / "target.json").write_bytes(
            canonical({"targets": ["solidity"]})
        )
        bundle_output = candidate / "bundle-output"
        bundle_environment = os.environ.copy()
        bundle_environment["NEUTRINO_GEN"] = str(core / "bin/neutrino-gen")
        run(
            [
                str(core / "bin/neutrino-bundle"),
                "--backend-package-dir",
                str(package),
                str(bundle_input),
                "-o",
                "bundle-output",
            ],
            candidate,
            env=bundle_environment,
        )
        bundled = bundle_output / "solidity/src/CoreDocumentEscrow.sol"
        if bundled.read_bytes() != baseline.read_bytes():
            raise RuntimeError("bundle consumer changed Solidity bytes")
        bundle = json.loads((bundle_output / "bundle.json").read_text())
        bundle_result = bundle["results"][0]
        if (
            not bundle["ok"]
            or bundle_result["target"] != "solidity"
            or bundle_result["catalogEntry"]["packageManifestDigest"]
            != descriptor["manifestDigest"]
        ):
            raise RuntimeError(
                "bundle result is not bound to the Solidity package"
            )

        equiv_output = candidate / "equiv-output"
        run(
            [
                str(core / "bin/neutrino-equiv"),
                str(fixture_source),
                "--scenario",
                str(fixture_scenario),
                "--backend-package-dir",
                str(package),
                "--target",
                "solidity",
                "--report",
                "equiv-output",
            ],
            candidate,
        )
        equivalence = json.loads(
            (equiv_output / "equivalence.json").read_text()
        )
        solidity_equivalence = equivalence["backends"][1]
        if (
            not equivalence["ok"]
            or solidity_equivalence["name"] != "solidity"
            or solidity_equivalence["status"] != "pass"
            or solidity_equivalence["packageManifestDigest"]
            != descriptor["manifestDigest"]
            or not solidity_equivalence["dispatchReceiptDigest"].startswith(
                "sha256:"
            )
        ):
            raise RuntimeError(
                "equiv result is not bound to the Solidity package receipt"
            )

        # SOURCES-ONLY WITNESS. The emitted sources must compile ALONE: no test/
        # directory, nothing copied out of the core tree, only the package's own
        # config. The `forge test` run below is handed core-repo Foundry fixtures and
        # therefore cannot witness this property, and neither can core lit -- a green
        # core suite says nothing about whether the package still compiles once those
        # fixtures are re-homed away from it.
        sources_only = candidate / "sources-only"
        shutil.copytree(output / "src", sources_only / "src")
        (sources_only / "foundry.toml").write_text(SOURCES_ONLY_FOUNDRY_TOML)
        run([str(args.forge), "build", "--root", str(sources_only)], candidate)
        compiled = (
            sources_only / "out/CoreDocumentEscrow.sol/CoreDocumentEscrow.json"
        )
        if not compiled.is_file():
            raise RuntimeError(
                "sources-only build emitted no compiled artifact for the contract"
            )

        # Negative control: keep the declared settings load-bearing. Drop them and the
        # same sources must FAIL to compile, so that a later edit relaxing the config
        # cannot quietly reduce the witness above to a no-op that proves nothing.
        naive = candidate / "sources-only-naive"
        shutil.copytree(output / "src", naive / "src")
        (naive / "foundry.toml").write_text(
            "[profile.default]\nsrc = 'src'\nout = 'out'\nlibs = []\n"
        )
        run_expect(
            [str(args.forge), "build", "--root", str(naive)],
            candidate,
            1,
            "Stack too deep",
        )

        shutil.copy2(
            candidate
            / "test/ir/samples/Inputs/core_document_escrow/generated/solidity/foundry.toml",
            output / "foundry.toml",
        )
        (output / "test").mkdir()
        shutil.copy2(
            candidate
            / "test/ir/samples/Inputs/core_document_escrow/generated/solidity/test/CoreDocumentEscrow.t.sol",
            output / "test/CoreDocumentEscrow.t.sol",
        )
        run([str(args.forge), "test", "--root", str(output)], candidate)

        receipt = {
            "kind": "neutrino.solidity-extraction-receipt/1",
            "sourceCommit": source["commit"],
            "sourceTree": source,
            "extractionManifestDigest": digest(MANIFEST.read_bytes()),
            "installedCore": core_identity,
            "packageManifestDigest": descriptor["manifestDigest"],
            "entryDigest": descriptor["closure"][0]["sha256"],
            "commands": [
                "cmake configure Release",
                "cmake build -j2",
                "ctest solidity-package-render",
                "neutrino-gen external solidity",
                "neutrino-bundle external solidity",
                "neutrino-equiv external solidity",
                "forge build (sources only, no test/, package config)",
                "forge test",
            ],
            "results": {
                "cleanCloneBuild": "pass",
                "compilerHeaderClosures": header_closures,
                "generatedProductsExact": len(GENERATED_PRODUCTS),
                "headerClassificationMutation": "rejected",
                "solidityBytes": digest(produced.read_bytes()),
                "dispatchReceipt": dispatch_receipt["receiptDigest"],
                "bundle": "pass",
                "equiv": "pass",
                "sourcesOnlyBuild": "pass",
                "sourcesOnlySettingsLoadBearing": "naive-config-rejected",
                "forge": "pass",
                "packageFailureMutations": 5,
                "reachbackMutations": 5,
                "coreArtifactSubstitution": "rejected-before-invocation",
            },
            "licenseGate": "project-authored-apache-2.0",
        }
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_bytes(
            json.dumps(receipt, indent=2, sort_keys=True).encode() + b"\n"
        )
        print(f"Solidity clean-clone proof OK; receipt: {args.receipt}")


def selftest() -> None:
    with tempfile.TemporaryDirectory(prefix="solidity-extraction-selftest.") as raw:
        candidate = Path(raw)
        materialize(candidate)
        if reasons := audit_candidate(candidate):
            raise RuntimeError(f"fresh candidate inventory is not exact: {reasons}")
        for probe in (
            "hidden-header",
            "undeclared-generated",
            "sibling-backend",
            "private-core-path",
        ):
            reachback_probe(candidate, probe)
        declared_file_audit_probe(candidate)
    print("Solidity extraction selftest OK: 5 reach-back probes bite")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-manifest", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--materialize-package", action="store_true")
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--package-dir", type=Path)
    parser.add_argument("--core-prefix", type=Path)
    parser.add_argument("--llvm-dir", default=os.environ.get("LLVM_DIR", ""))
    parser.add_argument("--forge", type=Path, default=Path("forge"))
    parser.add_argument(
        "--receipt",
        type=Path,
        default=Path("solidity-extraction-receipt.json"),
    )
    args = parser.parse_args()
    try:
        if args.write_manifest:
            check_manifest(True)
        elif args.selftest:
            check_manifest(False)
            selftest()
        elif args.materialize_package:
            if not args.binary or not args.package_dir:
                parser.error(
                    "--materialize-package requires --binary and --package-dir"
                )
            check_manifest(False)
            descriptor = package_descriptor(args.binary, args.package_dir)
            print(
                "Solidity repository package materialized: "
                f"{args.package_dir / 'backend-package.json'} "
                f"({descriptor['manifestDigest']})"
            )
        else:
            if not args.core_prefix or not args.llvm_dir:
                parser.error("--core-prefix and --llvm-dir are required")
            verify(args)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"solidity clean-clone FAILED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
