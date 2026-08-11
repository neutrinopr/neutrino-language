#!/usr/bin/env python3
"""Derive and verify the backend-free core export from configured build facts."""

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


KIND = "neutrino.m7-core-export-report/1"
FINALIZED_PROJECTION_SCHEMA = "docs/schemas/finalized-projection-v1.schema.json"
INSTALLED_FINALIZED_PROJECTION_SCHEMA = (
    "share/neutrino/schemas/finalized-projection-v1.schema.json"
)
INSTALLED_EXPORT_KIND = "neutrino.m7-core-installed-export/1"
CORE_TARGETS = [
    "slot",
    "capability-spec",
    "agreement-identity",
    "coordination-plan",
    "semantic-requirements",
    "coordination-trace",
    "test-realization",
    # `capability` is NEUTRINO_TARGET_DRIVER in TargetRegistry.def and sits outside
    # every `#ifndef NEUTRINO_CORE_ONLY` guard (only `postgres` is guarded), so it
    # is a built-in core target and --list-targets has always reported it. This
    # list had simply drifted: the gate that reads it is registered only inside a
    # core-only configure, and until `make core-only-verify` nothing performed
    # that configure, so the comparison never executed and never complained.
    # Order matters -- the check is an exact list equality against --list-targets.
    "capability",
    "coverage",
    "security",
    "views",
]
FORBIDDEN_PREFIXES = (
    "examples/domains/",
    "lib/backends/",
    "lib/slots/full/",
)
FORBIDDEN_SHARED_HEADERS = (
    "GenOracle",
    "GenPostgres",
    "GenSolidity",
    "PgDdl",
    "RecipeProvider",
    "RecipeRuntime",
    "SolidityEmit",
    "SqlEmitter",
    "TargetPrinter",
)
FORBIDDEN_BUILD_GRAPH_TOKENS = (
    "NeutrinoBackend",
    "lib/backends/",
    "examples/domains/",
    "GenOracle",
    "SlotBackendClaims",
)
FORBIDDEN_INSTALLED_TOKENS = (
    "NeutrinoBackend",
    "lib/backends/",
    "GenOracle",
    "GenPostgres",
    "GenSolidity",
    "PostgresTarget",
    "SlotBackendClaims",
    "SolidityTarget",
)
FORBIDDEN_PRIVATE_SYMBOL_TOKENS = (
    "Oracle",
    "Postgres",
    "SlotBackendClaims",
    "Solidity",
    "guardToSql",
    "toSql",
)
REQUIRED_SECURITY_CORE_FILES = {
    "include/Neutrino/GenSecurity.h",
    "include/Neutrino/GenSecuritySpec.h",
    "lib/security/CMakeLists.txt",
    "lib/security/GenSecuritySpec.cpp",
    "lib/security/SecurityAdmission.cpp",
    "lib/security/SecurityAdmission.h",
    "lib/security/SecurityTarget.cpp",
    "lib/security/test/security_policy_smoke.cpp",
    "test/core/security/insecure-capability-spec.json",
}
REQUIRED_COVERAGE_CORE_FILES = {
    "include/Neutrino/GenCoverage.h",
    "include/Neutrino/GenCoverageSpec.h",
    "lib/coverage/CMakeLists.txt",
    "lib/coverage/CoverageTarget.cpp",
    "lib/coverage/GenCoverageSpec.cpp",
    "lib/coverage/test/coverage_spec_smoke.cpp",
    "test/core/coverage/capability-spec.json",
}
REQUIRED_SLOT_CORE_FILES = {
    "include/Neutrino/GenSlot.h",
    "include/Neutrino/GenSlotSpec.h",
    "lib/slots/CMakeLists.txt",
    "lib/slots/GenSlotSpec.cpp",
    "lib/slots/SlotTarget.cpp",
    "lib/slots/test/slot_spec_smoke.cpp",
    "test/core/slots/capability-spec.json",
}
REQUIRED_VIEWS_CORE_FILES = {
    "include/Neutrino/GenViews.h",
    "include/Neutrino/GenViewsSpec.h",
    "lib/views/CMakeLists.txt",
    "lib/views/GenViewsSpec.cpp",
    "lib/views/ViewsTarget.cpp",
    "lib/views/test/views_spec_smoke.cpp",
    "test/core/views/capability-spec.json",
    "test/core/views/generated/LeftActor.json",
    "test/core/views/generated/RightActor.json",
    "test/core/views/source.neu",
}


class CheckFailure(RuntimeError):
    def __init__(self, identity, detail):
        super().__init__(f"{identity}: {detail}")
        self.identity = identity


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def file_identity(path):
    if path.is_symlink() or not path.is_file():
        raise CheckFailure("core_export.non_regular", str(path))
    data = path.read_bytes()
    return {
        "sha256": digest_bytes(data),
        "byteLen": len(data),
        "mode": format(path.stat().st_mode & 0o777, "04o"),
    }


def run(argv, cwd=None, capture=True):
    result = subprocess.run(
        [str(item) for item in argv],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise CheckFailure(
            "core_export.command",
            f"{' '.join(str(item) for item in argv)}: {detail}",
        )
    return result.stdout if capture else ""


def validate_schema_instance(value, schema, where="$"):
    if "const" in schema and value != schema["const"]:
        raise CheckFailure("core_export.json_schema", f"{where}: const mismatch")
    if "enum" in schema and value not in schema["enum"]:
        raise CheckFailure("core_export.json_schema", f"{where}: value not in enum")
    expected_type = schema.get("type")
    type_ok = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
    }.get(expected_type, True)
    if not type_ok:
        raise CheckFailure(
            "core_export.json_schema", f"{where}: expected {expected_type}"
        )
    if isinstance(value, dict):
        required = set(schema.get("required", []))
        missing = required - set(value)
        if missing:
            raise CheckFailure(
                "core_export.json_schema", f"{where}: missing {sorted(missing)}"
            )
        properties = schema.get("properties", {})
        extras = set(value) - set(properties)
        additional = schema.get("additionalProperties", True)
        if extras and additional is False:
            raise CheckFailure(
                "core_export.json_schema", f"{where}: unknown {sorted(extras)}"
            )
        for key, child in value.items():
            child_schema = properties.get(key)
            if child_schema is None and isinstance(additional, dict):
                child_schema = additional
            if child_schema is not None:
                validate_schema_instance(child, child_schema, f"{where}.{key}")
        if len(value) < schema.get("minProperties", 0):
            raise CheckFailure(
                "core_export.json_schema", f"{where}: too few properties"
            )
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise CheckFailure("core_export.json_schema", f"{where}: too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise CheckFailure("core_export.json_schema", f"{where}: too many items")
        if schema.get("uniqueItems") and len({canonical(item) for item in value}) != len(
            value
        ):
            raise CheckFailure(
                "core_export.json_schema", f"{where}: duplicate array item"
            )
        item_schema = schema.get("items")
        if item_schema:
            for ordinal, item in enumerate(value):
                validate_schema_instance(item, item_schema, f"{where}[{ordinal}]")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise CheckFailure("core_export.json_schema", f"{where}: string too short")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise CheckFailure(
                "core_export.json_schema", f"{where}: pattern mismatch"
            )
    if isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", value):
            raise CheckFailure("core_export.json_schema", f"{where}: below minimum")


def inside(path, root):
    try:
        return path.resolve().is_relative_to(root.resolve())
    except AttributeError:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False


def relative_source_file(raw, source_root, excluded_root=None):
    path = Path(raw)
    if not path.is_absolute():
        return None
    if (
        not inside(path, source_root)
        or (excluded_root is not None and inside(path, excluded_root))
        or not path.is_file()
    ):
        return None
    return path.resolve().relative_to(source_root.resolve()).as_posix()


def ninja_words(text):
    sentinel = "\0"
    return [word.replace(sentinel, " ") for word in text.replace("$ ", sentinel).split()]


def build_graph_paths(source_root, build_dir):
    values = set()
    output = run(["ninja", "-C", build_dir, "-t", "inputs", "core-only"])
    for raw in output.splitlines():
        rel = relative_source_file(raw.strip(), source_root, build_dir)
        if rel:
            values.add(rel)

    deps = run(["ninja", "-C", build_dir, "-t", "deps"])
    for raw in deps.splitlines():
        rel = relative_source_file(raw.strip(), source_root, build_dir)
        if rel:
            values.add(rel)
    build_ninja = (build_dir / "build.ninja").read_text(encoding="utf-8")
    marker = "build CMakeFiles/core-only-runtime-inputs "
    runtime_edge = next(
        (line for line in build_ninja.splitlines() if line.startswith(marker)), None
    )
    if runtime_edge is None:
        raise CheckFailure(
            "core_export.runtime_graph", "runtime input edge is absent"
        )
    for raw in ninja_words(runtime_edge):
        rel = relative_source_file(raw, source_root, build_dir)
        if rel:
            values.add(rel)
    if not values:
        raise CheckFailure("core_export.empty_graph", "Ninja reported no source inputs")
    return values


def configure_graph_paths(source_root, build_dir):
    build_ninja = (build_dir / "build.ninja").read_text(encoding="utf-8")
    marker = "build build.ninja: RERUN_CMAKE | "
    line = next(
        (candidate for candidate in build_ninja.splitlines() if candidate.startswith(marker)),
        None,
    )
    if line is None:
        raise CheckFailure(
            "core_export.configure_graph", "Ninja RERUN_CMAKE edge is absent"
        )
    values = set()
    for raw in ninja_words(line[len(marker) :]):
        rel = relative_source_file(
            raw, source_root, build_dir
        )
        if rel:
            values.add(rel)
    if "CMakeLists.txt" not in values:
        raise CheckFailure(
            "core_export.configure_graph", "root CMakeLists.txt is not configured"
        )
    return values


def load_overlay_policy(source_root, policy_path):
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckFailure("core_export.overlay_schema", str(exc)) from exc
    schema_path = source_root / "docs/schemas/m7-core-export-overlays.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validate_schema_instance(policy, schema)
    if set(policy) != {"schemaVersion", "boundary", "overlays"}:
        raise CheckFailure("core_export.overlay_schema", "unknown or missing root key")
    if policy["schemaVersion"] != 1 or not isinstance(policy["overlays"], list):
        raise CheckFailure("core_export.overlay_schema", "invalid policy version/rows")
    paths = []
    seen = set()
    classes = {
        "boundary",
        "contributor",
        "documentation",
        "license",
        "schema",
        "security",
    }
    for row in policy["overlays"]:
        if set(row) != {"path", "policyClass"} or row["policyClass"] not in classes:
            raise CheckFailure("core_export.overlay_schema", f"invalid row: {row!r}")
        rel = row["path"]
        if (
            not isinstance(rel, str)
            or Path(rel).is_absolute()
            or ".." in Path(rel).parts
            or rel in seen
        ):
            raise CheckFailure("core_export.overlay_path", str(rel))
        path = source_root / rel
        if not path.is_file():
            raise CheckFailure("core_export.overlay_missing", rel)
        seen.add(rel)
        paths.append(rel)
    if policy["boundary"] not in seen:
        raise CheckFailure(
            "core_export.boundary_missing", "signed boundary is not an overlay"
        )
    return policy, set(paths)


def assert_no_public_cpp_abi(manifest):
    for key in ("publicTargets", "publicHeaders", "cmakeExports"):
        if manifest.get(key) != []:
            raise CheckFailure(
                "core_export.cpp_abi_forbidden",
                f"{key} must remain empty under the subprocess protocol",
            )


def load_installed_export_schema(manifest_path):
    schema_path = (
        manifest_path.parent / "schemas" / "m7-core-installed-export.schema.json"
    )
    try:
        return json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckFailure("core_export.installed_manifest_schema", str(exc)) from exc


def load_installed_export(path):
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckFailure("core_export.installed_manifest", str(exc)) from exc
    # The shape contract is declared, not just asserted in code, so the consumer
    # boundary has something to read. Identity lives in the release receipt --
    # see docs/process/M7_CORE_RELEASE_RECEIPT.md.
    validate_schema_instance(manifest, load_installed_export_schema(path))
    required = {
        "kind",
        "schemaVersion",
        "cppAbiPolicy",
        "protocolContract",
        "runtimeArtifacts",
        "dataArtifacts",
        "internalTargets",
        "internalSourceHeaders",
        "internalGeneratedHeaders",
        "publicTargets",
        "publicHeaders",
        "cmakeExports",
    }
    if set(manifest) != required:
        raise CheckFailure(
            "core_export.installed_manifest",
            f"unknown or missing root keys: {sorted(set(manifest) ^ required)}",
        )
    if (
        manifest["kind"] != INSTALLED_EXPORT_KIND
        or manifest["schemaVersion"] != 1
        or manifest["cppAbiPolicy"] != "forbidden"
    ):
        raise CheckFailure(
            "core_export.installed_manifest", "unsupported installed export"
        )
    protocol = manifest["protocolContract"]
    if protocol != {
        "boundary": "share/neutrino/docs/M7_BACKEND_PACKAGE_BOUNDARY_ADR.md",
        "canonicalProjectionSchema": INSTALLED_FINALIZED_PROJECTION_SCHEMA,
        "protocol": "neutrino.backend-protocol/1",
        "startup": "neutrino.backend-startup/1",
    }:
        raise CheckFailure(
            "core_export.protocol_contract", "installed protocol binding drifted"
        )
    for key in (
        "runtimeArtifacts",
        "dataArtifacts",
        "internalTargets",
        "internalSourceHeaders",
        "internalGeneratedHeaders",
    ):
        values = manifest[key]
        if (
            not isinstance(values, list)
            or not values
            or values != sorted(values)
            or len(values) != len(set(values))
            or not all(isinstance(value, str) and value for value in values)
        ):
            raise CheckFailure(
                "core_export.installed_manifest",
                f"{key} must be a non-empty sorted unique string array",
            )
    assert_no_public_cpp_abi(manifest)
    for rel in (
        manifest["internalSourceHeaders"] + manifest["internalGeneratedHeaders"]
    ):
        if (
            Path(rel).is_absolute()
            or ".." in Path(rel).parts
            or not rel.startswith("include/Neutrino/")
        ):
            raise CheckFailure("core_export.installed_header", rel)
        classify_forbidden(rel)
    if any(not path.startswith("bin/") for path in manifest["runtimeArtifacts"]):
        raise CheckFailure(
            "core_export.installed_manifest", "runtime artifacts must live under bin/"
        )
    if any(not path.startswith("share/") for path in manifest["dataArtifacts"]):
        raise CheckFailure(
            "core_export.installed_manifest", "data artifacts must live under share/"
        )
    return manifest


def ninja_logical_lines(text):
    pending = ""
    for raw in text.splitlines():
        if raw.endswith(" $"):
            pending += raw[:-2]
            continue
        yield pending + raw
        pending = ""
    if pending:
        yield pending


def ninja_build_edges(build_dir):
    edges = {}
    text = (build_dir / "build.ninja").read_text(encoding="utf-8")
    for line in ninja_logical_lines(text):
        if not line.startswith("build ") or ": " not in line:
            continue
        outputs, rule_and_inputs = line[6:].split(": ", 1)
        words = ninja_words(rule_and_inputs)
        if not words:
            continue
        inputs = [word for word in words[1:] if word not in {"|", "||", "|@"}]
        for output in ninja_words(outputs):
            edges[output] = inputs
    return edges


def configured_library_closure(build_dir):
    edges = ninja_build_edges(build_dir)
    pending = ["core-only"]
    visited = set()
    targets = set()
    while pending:
        node = pending.pop()
        if node in visited:
            continue
        visited.add(node)
        pending.extend(edges.get(node, []))
        name = Path(node).name
        match = re.fullmatch(r"lib(Neutrino[A-Za-z0-9_]+)\.(?:a|dylib|so)", name)
        if match:
            targets.add(match.group(1))
    if not targets:
        raise CheckFailure(
            "core_export.target_closure", "no Neutrino library is reachable"
        )
    return sorted(targets)


def configured_header_closure(source_root, build_dir, targets):
    output = run(["ninja", "-C", build_dir, "-t", "deps"])
    source_headers = set()
    generated_headers = set()
    active = False
    needles = tuple(f"obj.{target}.dir/" for target in targets)
    for line in output.splitlines():
        if line and not line.startswith(" "):
            active = any(needle in line for needle in needles)
            continue
        if not active or not line.strip():
            continue
        path = Path(line.strip()).resolve()
        if inside(path, build_dir):
            rel = path.relative_to(build_dir).as_posix()
            if (
                rel.startswith("include/Neutrino/")
                and not rel.endswith((".cpp.inc", ".d"))
            ):
                generated_headers.add(rel)
            continue
        if inside(path, source_root):
            rel = path.relative_to(source_root).as_posix()
            if rel.startswith("include/Neutrino/"):
                source_headers.add(rel)
    if not source_headers or not generated_headers:
        raise CheckFailure(
            "core_export.header_closure",
            "compiler dependency graph yielded an empty header partition",
        )
    return sorted(source_headers), sorted(generated_headers)


def cache_value(build_dir, key):
    prefix = f"{key}:"
    for line in (build_dir / "CMakeCache.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return line.split("=", 1)[1]
    raise CheckFailure("core_export.dependency", f"{key} is absent from CMakeCache")


def core_tests(build_dir):
    data = json.loads(
        run(["ctest", "--test-dir", build_dir, "--show-only=json-v1"])
    )
    names = []
    for test in data.get("tests", []):
        labels = []
        for prop in test.get("properties", []):
            if prop.get("name") == "LABELS":
                labels = prop.get("value", [])
        if "core-only" in labels:
            names.append(test["name"])
    if not names:
        raise CheckFailure("core_export.tests", "no core-only CTest is configured")
    return sorted(names)


def expected_installed_paths(manifest):
    paths = set(manifest["runtimeArtifacts"] + manifest["dataArtifacts"])
    return paths


def assert_no_private_link_text(text):
    for token in FORBIDDEN_INSTALLED_TOKENS:
        if token in text:
            raise CheckFailure("core_export.installed_private_link", token)


def assert_no_private_symbol_text(target, text):
    for token in FORBIDDEN_PRIVATE_SYMBOL_TOKENS:
        if token in text:
            raise CheckFailure(
                "core_export.installed_private_symbol", f"{target}: {token}"
            )


INSTALLED_EXPORT_CANONICAL_PATH = "share/neutrino/m7-core-installed-export.json"


def verify_installed_manifest_copy(stage, installed_export_path):
    """The installed shape contract must be the exact file it claims to be.

    The release receipt's ``installedExportSha256`` is computed over the source
    manifest. If the installed copy could differ, a consumer reading the prefix
    would be holding a contract the receipt does not describe, and the digest
    would authenticate the wrong bytes. Byte equality is therefore required
    rather than assumed from ``install(FILES)`` copying verbatim.
    """
    installed = Path(stage) / INSTALLED_EXPORT_CANONICAL_PATH
    if not installed.is_file():
        raise CheckFailure(
            "core_export.installed_manifest_absent",
            f"{INSTALLED_EXPORT_CANONICAL_PATH} is not installed",
        )
    declared = Path(installed_export_path).read_bytes()
    if installed.read_bytes() != declared:
        raise CheckFailure(
            "core_export.installed_manifest_drift",
            f"{INSTALLED_EXPORT_CANONICAL_PATH} differs from the source manifest "
            "that installedExportSha256 is computed over",
        )


def verify_installed_export(stage, manifest, source_root, build_dir):
    actual = {
        path.relative_to(stage).as_posix()
        for path in stage.rglob("*")
        if path.is_file()
    }
    expected = expected_installed_paths(manifest)
    cpp_artifacts = sorted(
        rel
        for rel in actual
        if rel.startswith("include/")
        or rel.startswith("lib/")
        or rel.endswith((".a", ".dylib", ".so"))
    )
    if cpp_artifacts:
        raise CheckFailure(
            "core_export.cpp_abi_forbidden", cpp_artifacts[0]
        )
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise CheckFailure(
            "core_export.installed_closure",
            f"missing={missing[:4]} extra={extra[:4]}",
        )
    for rel in sorted(actual):
        classify_forbidden(rel)
        data = (stage / rel).read_bytes()
        for forbidden_root in (source_root.resolve(), build_dir.resolve()):
            if str(forbidden_root).encode("utf-8") in data:
                raise CheckFailure(
                    "core_export.installed_build_reference",
                    f"{rel}: {forbidden_root}",
                )
    return sorted(actual)


def installed_interface(source_root, build_dir, manifest, installed_export_path=None):
    stage = build_dir / "core-only-install"
    if stage.exists():
        shutil.rmtree(stage)
    run(
        [
            "cmake",
            "--install",
            build_dir,
            "--prefix",
            stage,
            "--component",
            "NeutrinoCore",
        ]
    )
    verify_installed_export(stage, manifest, source_root, build_dir)
    verify_installed_manifest_copy(
        stage,
        installed_export_path
        or (Path(source_root) / "docs/m7-core-installed-export.json"),
    )
    rows = []
    for path in sorted(item for item in stage.rglob("*") if item.is_file()):
        rows.append(
            {
                "path": path.relative_to(stage).as_posix(),
                **file_identity(path),
            }
        )
    if not rows:
        raise CheckFailure("core_export.install_graph", "installed interface is empty")
    return rows


def derive_report(source_root, build_dir, policy_path, installed_export_path):
    dirty = run(
        [
            "git",
            "-C",
            source_root,
            "status",
            "--porcelain",
            "--untracked-files=no",
        ]
    ).strip()
    if dirty:
        raise CheckFailure(
            "core_export.dirty_source",
            "tracked source changes are not bound by the source Git identity",
        )
    policy, overlays = load_overlay_policy(source_root, policy_path)
    installed_export = load_installed_export(installed_export_path)
    provenance = {}
    for rel in build_graph_paths(source_root, build_dir):
        provenance.setdefault(rel, set()).add("build-graph")
    for rel in configure_graph_paths(source_root, build_dir):
        provenance.setdefault(rel, set()).add("configure-graph")
    for rel in overlays:
        provenance.setdefault(rel, set()).add("reviewed-overlay")

    assert_coverage_core_export(set(provenance))
    assert_security_core_export(set(provenance))
    assert_slot_core_export(set(provenance))
    assert_views_core_export(set(provenance))
    assert_core_build_graph(build_dir)
    target_closure = configured_library_closure(build_dir)
    if target_closure != installed_export["internalTargets"]:
        raise CheckFailure(
            "core_export.target_closure",
            f"manifest={installed_export['internalTargets']} "
            f"configured={target_closure}",
        )
    source_headers, generated_headers = configured_header_closure(
        source_root, build_dir, target_closure
    )
    if source_headers != installed_export["internalSourceHeaders"]:
        raise CheckFailure(
            "core_export.source_header_closure",
            f"manifest={installed_export['internalSourceHeaders']} "
            f"configured={source_headers}",
        )
    if generated_headers != installed_export["internalGeneratedHeaders"]:
        raise CheckFailure(
            "core_export.generated_header_closure",
            f"manifest={installed_export['internalGeneratedHeaders']} "
            f"configured={generated_headers}",
        )
    for target in target_closure:
        install_stage = build_dir / "core-only-install"
        candidates = [
            path
            for path in build_dir.rglob(f"lib{target}.a")
            if not inside(path, install_stage)
        ]
        if len(candidates) != 1:
            raise CheckFailure(
                "core_export.library_artifact",
                f"{target}: expected one archive, observed {candidates}",
            )
        assert_no_private_symbol_text(target, run(["nm", "-g", candidates[0]]))

    files = []
    for rel in sorted(provenance):
        classify_forbidden(rel)
        path = source_root / rel
        files.append(
            {
                "path": rel,
                **file_identity(path),
                "provenance": sorted(provenance[rel]),
            }
        )
    targets = run(
        [build_dir / "tools/neutrino-gen/neutrino-gen", "--list-targets"]
    ).splitlines()
    if targets != CORE_TARGETS:
        raise CheckFailure(
            "core_export.target_set",
            f"expected {CORE_TARGETS!r}, observed {targets!r}",
        )

    llvm_dir = Path(cache_value(build_dir, "LLVM_DIR"))
    mlir_dir = Path(cache_value(build_dir, "MLIR_DIR"))
    dependencies = {
        "boundarySha256": file_identity(source_root / policy["boundary"])["sha256"],
        "cmakeVersion": run(["cmake", "--version"]).splitlines()[0],
        "llvmConfigSha256": file_identity(llvm_dir / "LLVMConfig.cmake")["sha256"],
        "mlirConfigSha256": file_identity(mlir_dir / "MLIRConfig.cmake")["sha256"],
        "ninjaVersion": run(["ninja", "--version"]).strip(),
        "sourceGitSha": run(["git", "-C", source_root, "rev-parse", "HEAD"]).strip(),
        "installedExportSha256": file_identity(installed_export_path)["sha256"],
    }
    report = {
        "kind": KIND,
        "schemaVersion": 1,
        "manifestDigest": "sha256:" + digest_bytes(canonical(files)),
        "files": files,
        "configuredTargets": targets,
        "tests": core_tests(build_dir),
        "dependencies": dependencies,
        "installedInterface": installed_interface(
            source_root, build_dir, installed_export, installed_export_path
        ),
        "installedExport": {
            "kind": installed_export["kind"],
            "cppAbiPolicy": installed_export["cppAbiPolicy"],
            "internalTargets": target_closure,
            "internalSourceHeaders": source_headers,
            "internalGeneratedHeaders": generated_headers,
            "publicTargets": [],
            "publicHeaders": [],
            "cmakeExports": [],
            "protocolContract": installed_export["protocolContract"],
        },
    }
    assert_finalized_projection_schema(report)
    report_schema = json.loads(
        (source_root / "docs/schemas/m7-core-export-report.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validate_report(report, report_schema)
    return report


def assert_finalized_projection_schema(report):
    exported = {row.get("path") for row in report.get("files", [])}
    if FINALIZED_PROJECTION_SCHEMA not in exported:
        raise CheckFailure(
            "core_export.finalized_projection_export",
            FINALIZED_PROJECTION_SCHEMA,
        )
    installed = {row.get("path") for row in report.get("installedInterface", [])}
    if INSTALLED_FINALIZED_PROJECTION_SCHEMA not in installed:
        raise CheckFailure(
            "core_export.finalized_projection_install",
            INSTALLED_FINALIZED_PROJECTION_SCHEMA,
        )


def validate_report(report, schema=None):
    if schema is not None:
        validate_schema_instance(report, schema)
    required = {
        "kind",
        "schemaVersion",
        "manifestDigest",
        "files",
        "configuredTargets",
        "tests",
        "dependencies",
        "installedInterface",
        "installedExport",
    }
    if set(report) != required or report.get("kind") != KIND:
        raise CheckFailure("core_export.report_schema", "invalid report envelope")
    if report.get("schemaVersion") != 1:
        raise CheckFailure("core_export.report_schema", "unsupported schemaVersion")
    files = report.get("files")
    if not isinstance(files, list) or not files:
        raise CheckFailure("core_export.report_schema", "files must be non-empty")
    paths = [row.get("path") for row in files]
    if paths != sorted(paths):
        raise CheckFailure("core_export.order", "manifest paths are not sorted")
    if len(paths) != len(set(paths)):
        raise CheckFailure("core_export.duplicate", "duplicate manifest path")
    expected = "sha256:" + digest_bytes(canonical(files))
    if report.get("manifestDigest") != expected:
        raise CheckFailure("core_export.manifest_digest", "digest does not recompute")


def classify_forbidden(rel):
    if any(rel.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        raise CheckFailure("core_export.forbidden_family", rel)
    if rel.startswith("include/Neutrino/") and any(
        token in Path(rel).name for token in FORBIDDEN_SHARED_HEADERS
    ):
        raise CheckFailure("core_export.forbidden_shared_header", rel)


def assert_security_core_export(paths):
    missing = sorted(REQUIRED_SECURITY_CORE_FILES - set(paths))
    if missing:
        raise CheckFailure("core_export.security_missing", missing[0])


def assert_coverage_core_export(paths):
    missing = sorted(REQUIRED_COVERAGE_CORE_FILES - set(paths))
    if missing:
        raise CheckFailure("core_export.coverage_missing", missing[0])


def assert_slot_core_export(paths):
    missing = sorted(REQUIRED_SLOT_CORE_FILES - set(paths))
    if missing:
        raise CheckFailure("core_export.slot_missing", missing[0])


def assert_views_core_export(paths):
    missing = sorted(REQUIRED_VIEWS_CORE_FILES - set(paths))
    if missing:
        raise CheckFailure("core_export.views_missing", missing[0])


def assert_target_neutral_views(views):
    forbidden_keys = {
        "backend",
        "dispatch",
        "lowering",
        "package",
        "renderer",
        "target",
    }

    def visit(value):
        if isinstance(value, dict):
            found = forbidden_keys & set(value)
            if found:
                raise CheckFailure(
                    "core_export.views_backend_claim",
                    f"forbidden keys {sorted(found)}",
                )
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(views)
    encoded = canonical(views)
    for target in (b'"solidity"', b'"postgres"', b'"oracle"'):
        if target in encoded:
            raise CheckFailure(
                "core_export.views_backend_claim", target.decode("ascii")
            )


def assert_target_neutral_slot(capability):
    if "backends" in capability:
        raise CheckFailure(
            "core_export.slot_backend_claim", "forbidden key 'backends'"
        )
    encoded = canonical(capability)
    for target in (b'"solidity"', b'"postgres"', b'"oracle"'):
        if target in encoded:
            raise CheckFailure(
                "core_export.slot_backend_claim", target.decode("ascii")
            )


def assert_target_neutral_coverage(report):
    forbidden_keys = {"targets", "maturityRule"} & set(report)
    if forbidden_keys:
        raise CheckFailure(
            "core_export.coverage_backend_claim",
            f"forbidden keys {sorted(forbidden_keys)}",
        )
    encoded = canonical(report)
    for target in (b'"solidity"', b'"postgres"'):
        if target in encoded:
            raise CheckFailure(
                "core_export.coverage_backend_claim", target.decode("ascii")
            )


def assert_core_build_graph(build_dir):
    build_graph = (build_dir / "build.ninja").read_text(encoding="utf-8")
    for token in FORBIDDEN_BUILD_GRAPH_TOKENS:
        if token in build_graph:
            raise CheckFailure("core_export.forbidden_build_graph", token)


def tree_files(tree):
    values = set()
    for root, dirs, files in os.walk(tree):
        dirs[:] = sorted(d for d in dirs if d not in {".git", "out-core"})
        for name in sorted(files):
            values.add((Path(root) / name).relative_to(tree).as_posix())
    return values


def verify_tree(tree, report, forbidden_source=None):
    schema_path = tree / "docs/schemas/m7-core-export-report.schema.json"
    schema = (
        json.loads(schema_path.read_text(encoding="utf-8"))
        if schema_path.is_file()
        else None
    )
    validate_report(report, schema)
    rows = report["files"]
    expected = {row["path"] for row in rows}
    actual = tree_files(tree)
    missing = sorted(expected - actual)
    if missing:
        raise CheckFailure("core_export.missing", missing[0])
    extra = sorted(actual - expected)
    if extra:
        rel = extra[0]
        classify_forbidden(rel)
        if Path(rel).suffix == ".inc":
            raise CheckFailure("core_export.generated_asset", rel)
        raise CheckFailure("core_export.unreviewed", rel)
    for row in rows:
        classify_forbidden(row["path"])
        observed = file_identity(tree / row["path"])
        if observed != {
            "sha256": row["sha256"],
            "byteLen": row["byteLen"],
            "mode": row["mode"],
        }:
            raise CheckFailure("core_export.stale", row["path"])
    if forbidden_source:
        needle = str(Path(forbidden_source).resolve()).encode("utf-8")
        for rel in sorted(actual):
            data = (tree / rel).read_bytes()
            if needle in data:
                raise CheckFailure("core_export.source_fallback", rel)


def copy_candidate(source_root, report, destination):
    for row in report["files"]:
        source = source_root / row["path"]
        target = destination / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def check_runtime(source_root, build_dir):
    gen = build_dir / "tools/neutrino-gen/neutrino-gen"
    targets = run([gen, "--list-targets"]).splitlines()
    if targets != CORE_TARGETS:
        raise CheckFailure("core_export.target_set", repr(targets))
    with tempfile.TemporaryDirectory(prefix="neutrino-core-runtime-") as raw:
        temp = Path(raw)
        source = source_root / "test/ir/coordination_trace.neu"
        scenario = source_root / "test/ir/coordination_trace.scn.json"
        traces = []
        for ordinal in (1, 2):
            out = temp / f"trace-{ordinal}"
            run(
                [
                    gen,
                    "--target=coordination-trace",
                    f"--scenario={scenario}",
                    source,
                    "-o",
                    out,
                ]
            )
            traces.append((out / "coordination-trace.json").read_bytes())
        if traces[0] != traces[1]:
            raise CheckFailure("core_export.trace_determinism", "two runs differ")
        trace = json.loads(traces[0])
        if not isinstance(trace, dict) or not trace:
            raise CheckFailure("core_export.trace_shape", "empty/non-object trace")

        coverage_out = temp / "coverage"
        run(
            [
                gen,
                "--target=coverage",
                f"--scenario={scenario}",
                source,
                "-o",
                coverage_out,
            ]
        )
        coverage = json.loads(
            (coverage_out / "coverage.json").read_text(encoding="utf-8")
        )
        assert_target_neutral_coverage(coverage)

        slot_out = temp / "slot"
        run([gen, "--target=slot", source, "-o", slot_out])
        slot_capability = json.loads(
            (slot_out / "capability.json").read_text(encoding="utf-8")
        )
        assert_target_neutral_slot(slot_capability)

        views_source = source_root / "test/core/views/source.neu"
        views_spec_out = temp / "views-spec"
        run(
            [
                gen,
                "--target=capability-spec",
                views_source,
                "-o",
                views_spec_out,
            ]
        )
        if (
            views_spec_out / "capability-spec.json"
        ).read_bytes() != (
            source_root / "test/core/views/capability-spec.json"
        ).read_bytes():
            raise CheckFailure(
                "core_export.views_spec_drift",
                "synthetic views capability contract did not regenerate",
            )
        views_out = temp / "views"
        run([gen, "--target=views", views_source, "-o", views_out])
        observed_views = []
        for participant in ("LeftActor", "RightActor"):
            observed = views_out / f"{participant}.json"
            expected = (
                source_root / "test/core/views/generated" / f"{participant}.json"
            )
            if observed.read_bytes() != expected.read_bytes():
                raise CheckFailure(
                    "core_export.views_drift",
                    f"{participant}.json did not regenerate",
                )
            observed_views.append(
                json.loads(observed.read_text(encoding="utf-8"))
            )
        assert_target_neutral_views(observed_views)

        spec_out = temp / "spec"
        run([gen, "--target=capability-spec", source, "-o", spec_out])
        run(
            [
                sys.executable,
                source_root / "scripts/validators/validate_capability_spec.py",
                spec_out / "capability-spec.json",
            ]
        )
        realization_out = temp / "realization"
        run(
            [
                gen,
                "--target=test-realization",
                f"--scenario={scenario}",
                source,
                "-o",
                realization_out,
            ]
        )
        run(
            [
                sys.executable,
                source_root / "scripts/validators/validate_test_realization.py",
                realization_out / "test-realization.json",
                "--spec",
                spec_out / "capability-spec.json",
            ]
        )


def check_candidate(source_root, build_dir, report):
    assert_finalized_projection_schema(report)
    llvm_dir = cache_value(build_dir, "LLVM_DIR")
    mlir_dir = cache_value(build_dir, "MLIR_DIR")
    with tempfile.TemporaryDirectory(prefix="neutrino-core-candidate-") as raw:
        candidate = Path(raw) / "src"
        candidate.mkdir()
        copy_candidate(source_root, report, candidate)
        verify_tree(candidate, report, forbidden_source=source_root)
        candidate_build = Path(raw) / "build"
        run(
            [
                "cmake",
                "-S",
                candidate,
                "-B",
                candidate_build,
                "-G",
                "Ninja",
                f"-DMLIR_DIR={mlir_dir}",
                f"-DLLVM_DIR={llvm_dir}",
                "-DNEUTRINO_CORE_ONLY=ON",
                "-DCMAKE_BUILD_TYPE=Release",
            ]
        )
        run(["cmake", "--build", candidate_build, "--target", "core-only", "-j2"])
        verify_tree(candidate, report, forbidden_source=source_root)
        candidate_install = Path(raw) / "install"
        run(
            [
                "cmake",
                "--install",
                candidate_build,
                "--prefix",
                candidate_install,
                "--component",
                "NeutrinoCore",
            ]
        )
        installed_export_manifest = load_installed_export(
            candidate / "docs/m7-core-installed-export.json"
        )
        verify_installed_export(
            candidate_install,
            installed_export_manifest,
            candidate,
            candidate_build,
        )
        installed_schema = candidate_install / INSTALLED_FINALIZED_PROJECTION_SCHEMA
        if not installed_schema.is_file():
            raise CheckFailure(
                "core_export.finalized_projection_install",
                INSTALLED_FINALIZED_PROJECTION_SCHEMA,
            )
        if file_identity(installed_schema)["sha256"] != file_identity(
            candidate / FINALIZED_PROJECTION_SCHEMA
        )["sha256"]:
            raise CheckFailure(
                "core_export.finalized_projection_install",
                "installed schema identity differs from the exported source",
            )
        needle = str(source_root.resolve()).encode("utf-8")
        for path in sorted(
            item for item in candidate_build.rglob("*") if item.is_file()
        ):
            if needle in path.read_bytes():
                raise CheckFailure(
                    "core_export.source_fallback",
                    path.relative_to(candidate_build).as_posix(),
                )
        deps = run(["ninja", "-C", candidate_build, "-t", "deps"])
        if str(source_root.resolve()) in deps:
            raise CheckFailure("core_export.source_fallback", "ninja dependency log")


def install_prefix_witness(manifest_path):
    """Prove a clean install prefix, and that it ships the digested contract.

    Built from the real committed manifest in an isolated root, so the witness
    cannot drift from what is actually installed and cannot pollute the
    selftest tree (which is itself scanned for unreviewed files).
    """
    if not manifest_path.is_file():
        raise CheckFailure(
            "core_export.installed_manifest", f"{manifest_path} is absent"
        )
    manifest = load_installed_export(manifest_path)
    with tempfile.TemporaryDirectory(prefix="neutrino-core-prefix-") as raw:
        root = Path(raw)
        prefix = root / "prefix"
        for rel in sorted(expected_installed_paths(manifest)):
            target = prefix / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
        canonical_copy = prefix / INSTALLED_EXPORT_CANONICAL_PATH
        canonical_copy.write_bytes(manifest_path.read_bytes())

        def verify():
            verify_installed_export(prefix, manifest, root / "src", root / "bld")

        # A clean prefix satisfies the closure and the byte-equality legs.
        verify()
        verify_installed_manifest_copy(prefix, manifest_path)

        # The installed contract must be the exact file the receipt digests.
        canonical_copy.write_bytes(manifest_path.read_bytes() + b"\n")
        expect_failure(
            "core_export.installed_manifest_drift",
            lambda: verify_installed_manifest_copy(prefix, manifest_path),
        )
        canonical_copy.unlink()
        expect_failure(
            "core_export.installed_manifest_absent",
            lambda: verify_installed_manifest_copy(prefix, manifest_path),
        )
        canonical_copy.write_bytes(manifest_path.read_bytes())

        # An undeclared file in the prefix is not a clean install.
        stray = prefix / "share" / "neutrino" / "stray.json"
        stray.write_bytes(b"{}")
        expect_failure("core_export.installed_closure", verify)
        stray.unlink()

        # A declared artifact missing from the prefix is equally not clean.
        absent = prefix / sorted(expected_installed_paths(manifest))[0]
        payload = absent.read_bytes()
        absent.unlink()
        expect_failure("core_export.installed_closure", verify)
        absent.write_bytes(payload)

        # The backend-free guarantee still holds over the installed prefix.
        abi = prefix / "lib" / "libNeutrinoEmit.a"
        abi.parent.mkdir(parents=True, exist_ok=True)
        abi.write_bytes(b"!<arch>")
        expect_failure("core_export.cpp_abi_forbidden", verify)
        abi.unlink()

        # Clean again at the end, so no probe left the prefix broken.
        verify()
        verify_installed_manifest_copy(prefix, manifest_path)


def expect_failure(identity, callback):
    try:
        callback()
    except CheckFailure as exc:
        if exc.identity == identity:
            return
        raise CheckFailure(
            "core_export.selftest",
            f"expected {identity}, observed {exc.identity}: {exc}",
        ) from exc
    raise CheckFailure("core_export.selftest", f"{identity} mutation survived")


def selftest():
    with tempfile.TemporaryDirectory(prefix="neutrino-core-export-selftest-") as raw:
        tree = Path(raw)
        (tree / "required.txt").write_text("required\n", encoding="utf-8")
        identity = file_identity(tree / "required.txt")
        files = [
            {
                "path": "required.txt",
                **identity,
                "provenance": ["build-graph"],
            }
        ]
        report = {
            "kind": KIND,
            "schemaVersion": 1,
            "manifestDigest": "sha256:" + digest_bytes(canonical(files)),
            "files": files,
            "configuredTargets": ["coordination-trace"],
            "tests": ["core-only-runtime"],
            "dependencies": {"llvmConfigSha256": "0" * 64},
            "installedInterface": [
                {
                    "path": "bin/neutrino-gen",
                    "sha256": "0" * 64,
                    "byteLen": 0,
                    "mode": "0755",
                }
            ],
            "installedExport": {
                "kind": INSTALLED_EXPORT_KIND,
                "cppAbiPolicy": "forbidden",
                "internalTargets": ["NeutrinoSpecContract"],
                "internalSourceHeaders": ["include/Neutrino/BackendProtocol.h"],
                "internalGeneratedHeaders": ["include/Neutrino/BuildInfo.h"],
                "publicTargets": [],
                "publicHeaders": [],
                "cmakeExports": [],
                "protocolContract": {
                    "boundary": "share/neutrino/docs/"
                    "M7_BACKEND_PACKAGE_BOUNDARY_ADR.md",
                    "canonicalProjectionSchema": (
                        INSTALLED_FINALIZED_PROJECTION_SCHEMA
                    ),
                    "protocol": "neutrino.backend-protocol/1",
                    "startup": "neutrino.backend-startup/1",
                },
            },
        }
        verify_tree(tree, report)

        # The manifest shape contract is enforced from the declared schema, so a
        # manifest that drifts from it is refused rather than silently accepted.
        # Identity is deliberately absent here and lives in the release receipt
        # (docs/process/M7_CORE_RELEASE_RECEIPT.md); these probes pin the shape
        # the consumer boundary is entitled to assume.
        docs_root = Path(__file__).resolve().parents[2] / "docs"
        manifest_path = docs_root / "m7-core-installed-export.json"
        if manifest_path.is_file():
            manifest_schema = load_installed_export_schema(manifest_path)
            good_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            validate_schema_instance(good_manifest, manifest_schema)

            unrooted = json.loads(json.dumps(good_manifest))
            unrooted["runtimeArtifacts"] = ["libexec/neutrino-emit"]
            expect_failure(
                "core_export.json_schema",
                lambda: validate_schema_instance(unrooted, manifest_schema),
            )

            duplicated = json.loads(json.dumps(good_manifest))
            duplicated["runtimeArtifacts"] = ["bin/neutrino-emit", "bin/neutrino-emit"]
            expect_failure(
                "core_export.json_schema",
                lambda: validate_schema_instance(duplicated, manifest_schema),
            )

            # A C++ ABI surface must stay refused by the declared contract, not
            # only by the hand-written check that already covers it.
            abi = json.loads(json.dumps(good_manifest))
            abi["publicTargets"] = ["NeutrinoSpecContract"]
            expect_failure(
                "core_export.json_schema",
                lambda: validate_schema_instance(abi, manifest_schema),
            )

            # Identity must not creep back into the shape manifest: the fixed
            # point in M7_CORE_RELEASE_RECEIPT.md §1 is why it cannot live here.
            with_identity = json.loads(json.dumps(good_manifest))
            with_identity["runtimeArtifacts"] = [
                {"path": "bin/neutrino-emit", "sha256": "0" * 64, "mode": "0755"}
            ]
            expect_failure(
                "core_export.json_schema",
                lambda: validate_schema_instance(with_identity, manifest_schema),
            )

        expect_failure(
            "core_export.security_missing",
            lambda: assert_security_core_export(set()),
        )
        expect_failure(
            "core_export.coverage_missing",
            lambda: assert_coverage_core_export(set()),
        )
        expect_failure(
            "core_export.coverage_backend_claim",
            lambda: assert_target_neutral_coverage(
                {"targets": [{"target": "solidity"}]}
            ),
        )
        expect_failure(
            "core_export.slot_missing",
            lambda: assert_slot_core_export(set()),
        )
        expect_failure(
            "core_export.views_missing",
            lambda: assert_views_core_export(set()),
        )
        expect_failure(
            "core_export.views_backend_claim",
            lambda: assert_target_neutral_views(
                [{"participant": {"name": "LeftActor"}, "package": "solidity"}]
            ),
        )
        expect_failure(
            "core_export.slot_backend_claim",
            lambda: assert_target_neutral_slot(
                {"backends": ["solidity", "postgres"]}
            ),
        )

        build_dir = tree / "build"
        build_dir.mkdir()
        (build_dir / "build.ninja").write_text(
            "build core: phony NeutrinoBackendOracle\n", encoding="utf-8"
        )
        expect_failure(
            "core_export.forbidden_build_graph",
            lambda: assert_core_build_graph(build_dir),
        )
        (build_dir / "build.ninja").write_text(
            "build core: phony lib/slots/full/SlotBackendClaims.cpp\n",
            encoding="utf-8",
        )
        expect_failure(
            "core_export.forbidden_build_graph",
            lambda: assert_core_build_graph(build_dir),
        )
        (build_dir / "build.ninja").unlink()
        build_dir.rmdir()

        expect_failure(
            "core_export.forbidden_family",
            lambda: classify_forbidden("lib/slots/full/SlotBackendClaims.cpp"),
        )
        expect_failure(
            "core_export.installed_private_link",
            lambda: assert_no_private_link_text(
                "INTERFACE_LINK_LIBRARIES NeutrinoBackendPostgres"
            ),
        )
        expect_failure(
            "core_export.installed_private_symbol",
            lambda: assert_no_private_symbol_text(
                "NeutrinoEmit", "T __ZN8neutrino18emitSolidityProjectEv"
            ),
        )
        expect_failure(
            "core_export.cpp_abi_forbidden",
            lambda: assert_no_public_cpp_abi(
                {
                    "publicTargets": ["NeutrinoSpecContract"],
                    "publicHeaders": [],
                    "cmakeExports": [],
                }
            ),
        )

        boundary_report = json.loads(json.dumps(report))
        boundary_report["files"].append(
            {"path": FINALIZED_PROJECTION_SCHEMA}
        )
        boundary_report["installedInterface"].append(
            {"path": INSTALLED_FINALIZED_PROJECTION_SCHEMA}
        )
        assert_finalized_projection_schema(boundary_report)
        missing_export = json.loads(json.dumps(boundary_report))
        missing_export["files"] = [
            row
            for row in missing_export["files"]
            if row["path"] != FINALIZED_PROJECTION_SCHEMA
        ]
        expect_failure(
            "core_export.finalized_projection_export",
            lambda: assert_finalized_projection_schema(missing_export),
        )
        missing_install = json.loads(json.dumps(boundary_report))
        missing_install["installedInterface"] = [
            row
            for row in missing_install["installedInterface"]
            if row["path"] != INSTALLED_FINALIZED_PROJECTION_SCHEMA
        ]
        expect_failure(
            "core_export.finalized_projection_install",
            lambda: assert_finalized_projection_schema(missing_install),
        )

        install_prefix_witness(docs_root / "m7-core-installed-export.json")

        missing = Path(raw) / "missing"
        missing.mkdir()
        expect_failure("core_export.missing", lambda: verify_tree(missing, report))

        duplicate = json.loads(json.dumps(report))
        duplicate["files"].append(duplicate["files"][0])
        duplicate["manifestDigest"] = "sha256:" + digest_bytes(
            canonical(duplicate["files"])
        )
        expect_failure(
            "core_export.duplicate", lambda: verify_tree(tree, duplicate)
        )

        stale = json.loads(json.dumps(report))
        stale["files"][0]["sha256"] = "1" * 64
        stale["manifestDigest"] = "sha256:" + digest_bytes(canonical(stale["files"]))
        expect_failure("core_export.stale", lambda: verify_tree(tree, stale))

        extra = tree / "extra.txt"
        extra.write_text("extra\n", encoding="utf-8")
        expect_failure("core_export.unreviewed", lambda: verify_tree(tree, report))
        extra.unlink()

        backend = tree / "include/Neutrino/GenSolidityPrivate.h"
        backend.parent.mkdir(parents=True)
        backend.write_text("backend\n", encoding="utf-8")
        expect_failure(
            "core_export.forbidden_shared_header", lambda: verify_tree(tree, report)
        )
        backend.unlink()

        domain = tree / "examples/domains/private.neu"
        domain.parent.mkdir(parents=True)
        domain.write_text("domain\n", encoding="utf-8")
        expect_failure(
            "core_export.forbidden_family", lambda: verify_tree(tree, report)
        )
        domain.unlink()

        generated = tree / "undeclared.inc"
        generated.write_text("generated\n", encoding="utf-8")
        expect_failure(
            "core_export.generated_asset", lambda: verify_tree(tree, report)
        )
        generated.unlink()

        fallback = tree / "required.txt"
        fallback.write_text("/private/source/fallback\n", encoding="utf-8")
        fallback_identity = file_identity(fallback)
        fallback_report = json.loads(json.dumps(report))
        fallback_report["files"][0].update(fallback_identity)
        fallback_report["manifestDigest"] = "sha256:" + digest_bytes(
            canonical(fallback_report["files"])
        )
        expect_failure(
            "core_export.source_fallback",
            lambda: verify_tree(
                tree, fallback_report, forbidden_source="/private/source/fallback"
            ),
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--installed-export", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--derive", action="store_true")
    parser.add_argument("--check-candidate", action="store_true")
    parser.add_argument("--check-runtime", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    try:
        if args.selftest:
            selftest()
        elif args.check_runtime:
            check_runtime(args.source_root.resolve(), args.build_dir.resolve())
        elif args.derive:
            report = derive_report(
                args.source_root.resolve(),
                args.build_dir.resolve(),
                args.policy.resolve(),
                args.installed_export.resolve(),
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif args.check_candidate:
            report = json.loads(args.report.read_text(encoding="utf-8"))
            check_candidate(
                args.source_root.resolve(), args.build_dir.resolve(), report
            )
        else:
            parser.error("select one action")
    except (CheckFailure, OSError, json.JSONDecodeError) as exc:
        print(f"check_core_only_export: FAIL: {exc}", file=sys.stderr)
        return 1
    print("check_core_only_export: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
