#!/usr/bin/env python3
"""Positive M6 release gate over the one curated corpus and compiler semantics."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


REPO = Path(__file__).resolve().parents[2]

# The deterministic, receipt-verified pack resolver. Every curated member is
# hydrated through it; there is no in-core production-domain fallback.
sys.path.insert(0, str(REPO / "scripts" / "gates"))
import m6_pack_resolver as pack_resolver  # noqa: E402

MANIFEST_PATH = REPO / "docs" / "m6-curated-example-corpus.json"
VOCABULARY_PATH = REPO / "docs" / "semantic-feature-vocabulary.json"
MATRIX_PATH = REPO / "docs" / "core-feature-example-matrix.json"
PROFILE_DIR = REPO / "examples" / "target-profiles"
TARGET_REGISTRY_PATH = REPO / "include" / "Neutrino" / "TargetRegistry.def"
WORKFLOW_PATH = REPO / ".github" / "workflows" / "release-gate.yml"
INTEGRITY_PATH = REPO / "scripts" / "gates" / "gate_integrity_manifest.json"
GATE_ID = "m6_positive_release"
MUTATION_MARKER = "posting-obligation mutations bite"
PROBES = (
    "corpus-member",
    "feature",
    "pair",
    "backend-witness",
    "backend-cell",
    "matrix-outcome",
    "mutation",
    "workflow-invocation",
    "manifest-registration",
)
LIMITS = {
    "expressionDepth": "maxExpressionDepth",
    "effectCount": "maxEffects",
    "effectGroupCount": "maxEffectGroups",
    "attestationCount": "maxAttestations",
    "computeCount": "maxComputes",
    "operationSteps": "maxOperationSteps",
}
TARGET_ROW = re.compile(
    r'NEUTRINO_TARGET\(\s*"([^"]+)"\s*,\s*\w+\s*,'
    r'\s*/\*gated=\*/\s*(true|false)\s*,'
    r'\s*/\*scenarioFree=\*/\s*(true|false)\s*\)'
)


class CheckError(RuntimeError):
    pass


def run(command, *, expected=0):
    result = subprocess.run(
        [str(item) for item in command],
        cwd=REPO,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != expected:
        raise CheckError(
            f"command returned {result.returncode}, expected {expected}: "
            f"{' '.join(map(str, command))}\n{result.stdout}{result.stderr}"
        )
    return result


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CheckError(f"cannot load module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_manifest(path=MANIFEST_PATH):
    structural = load_module(
        REPO / "scripts" / "gates" / "check_m6_curated_example_corpus.py",
        "m6_curated_example_corpus",
    )
    raw = path.read_bytes()
    errors = structural.validate_manifest(raw, repo=REPO)
    if errors:
        raise CheckError("curated corpus invalid: " + "; ".join(errors))
    return json.loads(raw)


def load_vocabulary(path=VOCABULARY_PATH):
    data = json.loads(path.read_text(encoding="utf-8"))
    features = data.get("features")
    if (
        data.get("kind") != "neutrino.semantic-feature-vocabulary"
        or data.get("schemaVersion") != 1
        or not isinstance(features, list)
        or not features
        or any(not isinstance(item, str) or not item for item in features)
        or len(features) != len(set(features))
    ):
        raise CheckError("semantic feature vocabulary is malformed")
    return data


def governed_targets(registry_path=TARGET_REGISTRY_PATH):
    rows = []
    for line in registry_path.read_text(encoding="utf-8").splitlines():
        match = TARGET_ROW.fullmatch(line.strip())
        if match:
            rows.append(
                (match.group(1), match.group(2) == "true", match.group(3) == "true")
            )
    if len(rows) < 7 or len({row[0] for row in rows}) != len(rows):
        raise CheckError("authoritative target registry is malformed or vacuous")
    targets = {name for name, gated, scenario_free in rows if gated and not scenario_free}
    if not targets:
        raise CheckError("target registry has no governed scenario-bearing backends")
    return targets


def load_profiles(
    profile_dir=PROFILE_DIR, *, expected_targets=None, validate=False
):
    profiles = {}
    for path in sorted(profile_dir.glob("*.target-profile.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        target = data.get("target")
        if not isinstance(target, str) or not target or target in profiles:
            raise CheckError(f"invalid or duplicate target profile in {path}")
        semantic = data.get("semanticProfile")
        if not isinstance(semantic, dict):
            raise CheckError(f"{path}: missing semanticProfile")
        profiles[target] = {"path": path, "data": data}
        if validate:
            run([
                sys.executable,
                REPO / "scripts" / "validators" / "validate_target_profile.py",
                path,
            ])
    if not profiles:
        raise CheckError("no committed target profiles found")
    expected = expected_targets if expected_targets is not None else governed_targets()
    if set(profiles) != set(expected):
        raise CheckError(
            "profile/registry backend drift: "
            f"profiles={sorted(profiles)}, governed={sorted(expected)}"
        )
    return profiles


def validate_backend_authorities(targets, profiles, checker_dir=None):
    checker_dir = checker_dir or REPO / "test" / "curated"
    checker_targets = {
        path.name.removeprefix("check_").removesuffix("_goldens.py")
        for path in checker_dir.glob("check_*_goldens.py")
    }
    if set(profiles) != set(targets) or checker_targets != set(targets):
        raise CheckError(
            "governed backend authority is not exact: "
            f"registry={sorted(targets)}, profiles={sorted(profiles)}, "
            f"checkers={sorted(checker_targets)}"
        )


def requirement_features(artifact):
    requirements = artifact.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        raise CheckError("semantic-requirements artifact has no requirements")
    features = []
    for requirement in requirements:
        if (
            not isinstance(requirement, dict)
            or set(requirement) != {"feature", "primitive"}
            or not isinstance(requirement["feature"], str)
            or not isinstance(requirement["primitive"], str)
        ):
            raise CheckError(f"malformed semantic requirement: {requirement!r}")
        features.append(requirement["feature"])
    if len(features) != len(set(features)):
        raise CheckError("semantic-requirements artifact repeats a feature")
    return features


def validate_feature_coverage(vocabulary, artifacts):
    expected = set(vocabulary["features"])
    covered = {
        feature
        for artifact in artifacts.values()
        for feature in requirement_features(artifact)
    }
    missing = sorted(expected - covered)
    unknown = sorted(covered - expected)
    if missing or unknown:
        raise CheckError(
            f"semantic feature coverage is not exact: missing={missing}, unknown={unknown}"
        )
    for member, artifact in artifacts.items():
        if artifact.get("semanticProfileVersion") != vocabulary.get(
            "semanticProfileVersion"
        ):
            raise CheckError(f"{member}: semantic profile version differs from vocabulary")
    return sorted(covered)


def hydrate_members(manifest):
    """Resolve every curated member from a receipt-verified published pack."""
    hydrated = pack_resolver.resolve_members(manifest, repo=REPO)
    for member, resolved in hydrated.items():
        # Enforce the role contract before use, so an incomplete pack fails
        # through the resolver diagnostic rather than an incidental exception.
        missing = [
            role
            for role, value in (
                ("capability-spec", resolved.spec_path),
                ("source", resolved.source_path),
            )
            if value is None
        ]
        if missing:
            raise pack_resolver.PackResolutionError(
                f"{member}: hydrated pack is missing release-gate role(s) {missing}"
            )
    return hydrated


def emit_semantic_requirements(gen, manifest, sources, work):
    artifacts = {}
    for member in manifest["examples"]:
        src = sources[member]
        source = src.source_path
        committed_spec = src.spec_path
        source_spec = work / member / "source-spec"
        run([gen, "--target=capability-spec", source, "-o", source_spec])
        if (source_spec / "capability-spec.json").read_bytes() != committed_spec.read_bytes():
            raise CheckError(f"{member}: committed capability-spec is stale")

        direct = work / member / "requirements-source"
        rebuilt = work / member / "requirements-spec"
        run([gen, "--target=semantic-requirements", source, "-o", direct])
        run([
            gen,
            "--target=semantic-requirements",
            "--from-spec",
            committed_spec,
            "-o",
            rebuilt,
        ])
        direct_path = direct / "semantic-requirements.json"
        rebuilt_path = rebuilt / "semantic-requirements.json"
        if direct_path.read_bytes() != rebuilt_path.read_bytes():
            raise CheckError(
                f"{member}: source/from-spec semantic-requirements differ"
            )
        artifacts[member] = json.loads(direct_path.read_text(encoding="utf-8"))
    return artifacts


def expected_refusal(artifact, profile):
    semantic = profile["semanticProfile"]
    supported = set(semantic.get("features", []))
    for requirement in artifact["requirements"]:
        if requirement["feature"] not in supported:
            return {
                "code": "legality.unsupported_feature",
                "message": (
                    f"required feature '{requirement['feature']}' "
                    f"({requirement['primitive']}) is not supported by target "
                    f"'{profile['profileId']}'"
                ),
                "severity": "error",
                "unsupportedFeature": requirement["feature"],
                "primitive": requirement["primitive"],
            }
    metrics = artifact.get("metrics")
    limits = semantic.get("limits")
    if not isinstance(metrics, dict) or not isinstance(limits, dict):
        raise CheckError("semantic metrics/profile limits are malformed")
    for metric, limit in LIMITS.items():
        if metrics.get(metric, 0) > limits.get(limit, -1):
            raise CheckError(
                f"curated member exceeds {limit}; add exact limit diagnostic accounting"
            )
    return None


def read_diagnostics(out):
    path = out / "diagnostics.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CheckError(f"cannot load diagnostics from {out}: {error}") from error
    diagnostics = data.get("diagnostics")
    if not isinstance(diagnostics, list):
        raise CheckError(f"{out}: malformed diagnostics")
    return diagnostics


def classify_backends(gen, manifest, profiles, artifacts, sources, work):
    cells = []
    for target, profile_entry in sorted(profiles.items()):
        profile_path = profile_entry["path"]
        profile = profile_entry["data"]
        if profile["semanticProfile"].get("version") != artifacts[
            manifest["examples"][0]
        ].get("semanticProfileVersion"):
            raise CheckError(f"{target}: semantic profile version drift")
        for member in manifest["examples"]:
            src = sources[member]
            spec = src.spec_path
            scenario_bearing = (
                src.scenario_dir is not None
                and any(src.scenario_dir.glob("*.json"))
            )
            out = work / target / member
            shutil.rmtree(out, ignore_errors=True)
            command = [
                gen,
                f"--target={target}",
                "--from-spec",
                f"--profile={profile_path}",
                spec,
                "-o",
                out,
            ]
            result = subprocess.run(
                [str(item) for item in command],
                cwd=REPO,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            refusal = expected_refusal(artifacts[member], profile)
            if refusal is None:
                if result.returncode:
                    raise CheckError(
                        f"{target}/{member}: supported render failed "
                        f"({result.returncode})\n{result.stdout}{result.stderr}"
                    )
                if read_diagnostics(out):
                    raise CheckError(f"{target}/{member}: successful render diagnosed errors")
                cells.append(
                    {
                        "target": target,
                        "name": member,
                        "classification": (
                            "scenario-bearing"
                            if scenario_bearing
                            else "source-only-supported"
                        ),
                    }
                )
                continue
            if scenario_bearing:
                raise CheckError(
                    f"{target}/{member}: scenario-bearing curated member is unsupported"
                )
            if result.returncode != 6:
                raise CheckError(
                    f"{target}/{member}: refusal exited {result.returncode}, expected 6"
                )
            expected_diagnostic = {
                key: refusal[key] for key in ("code", "message", "severity")
            }
            if read_diagnostics(out) != [expected_diagnostic]:
                raise CheckError(
                    f"{target}/{member}: refusal diagnostic is not exact"
                )
            emitted = {
                path.relative_to(out)
                for path in out.rglob("*")
                if path.is_file()
            }
            if emitted != {Path("diagnostics.json"), Path("manifest.json")}:
                raise CheckError(
                    f"{target}/{member}: refused render emitted artifacts: {emitted}"
                )
            manifest_out = json.loads(
                (out / "manifest.json").read_text(encoding="utf-8")
            )
            if manifest_out.get("artifacts") != []:
                raise CheckError(f"{target}/{member}: refusal manifest lists artifacts")
            cells.append(
                {
                    "target": target,
                    "name": member,
                    "classification": "source-only-unsupported",
                    "unsupportedFeature": refusal["unsupportedFeature"],
                    "primitive": refusal["primitive"],
                    "diagnostic": expected_diagnostic,
                }
            )
    validate_backend_matrix(manifest, set(profiles), cells)
    return cells


def validate_backend_matrix(manifest, targets, cells):
    expected = {
        (target, member)
        for target in targets
        for member in manifest["examples"]
    }
    actual = [(cell.get("target"), cell.get("name")) for cell in cells]
    if len(actual) != len(set(actual)):
        raise CheckError("backend witness matrix contains duplicate cells")
    missing = sorted(expected - set(actual))
    extra = sorted(set(actual) - expected)
    if missing or extra:
        raise CheckError(
            f"backend witness matrix is not exact: missing={missing}, extra={extra}"
        )
    allowed = {
        "scenario-bearing",
        "source-only-supported",
        "source-only-unsupported",
    }
    if any(cell.get("classification") not in allowed for cell in cells):
        raise CheckError("backend witness matrix contains an unknown classification")


def validate_core_matrix_outcomes(manifest, targets, cells, matrix=None):
    """Bind the compiler-derived matrix's artifact observation to the governed
    target-relative classification.

    The classification is derived before artifact inspection from scenario
    presence plus target-profile legality.  The matrix bit is only the measured
    presence witness: supported members require an artifact, while unsupported
    members require none.
    """
    matrix = matrix or json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    examples = matrix.get("examples")
    if not isinstance(examples, list):
        raise CheckError("core feature matrix has no example observations")
    by_name = {
        row.get("id"): row
        for row in examples
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    if len(by_name) != len(examples):
        raise CheckError("core feature matrix has duplicate or malformed examples")
    missing_members = sorted(set(manifest["examples"]) - set(by_name))
    if missing_members:
        raise CheckError(
            f"core feature matrix omits curated members: {missing_members}"
        )
    by_cell = {(cell["target"], cell["name"]): cell for cell in cells}
    expected_cells = {
        (target, member)
        for target in targets
        for member in manifest["examples"]
    }
    if set(by_cell) != expected_cells:
        raise CheckError("backend witness matrix must be exact before matrix reconciliation")
    for target, member in sorted(expected_cells):
        observed = by_name[member].get("backendGoldens")
        if not isinstance(observed, dict) or set(observed) != set(targets):
            raise CheckError(
                f"{member}: matrix backend artifact observation is not target-exact"
            )
        actual = observed.get(target)
        if not isinstance(actual, bool):
            raise CheckError(f"{target}/{member}: matrix artifact presence is not boolean")
        classification = by_cell[(target, member)]["classification"]
        expected = classification != "source-only-unsupported"
        if actual != expected:
            raise CheckError(
                f"{target}/{member}: matrix artifact presence {actual} disagrees "
                f"with governed {classification} outcome"
            )


def run_golden_witnesses(gen, profiles, cells, work):
    by_cell = {(cell["target"], cell["name"]): cell for cell in cells}
    for target, profile_entry in sorted(profiles.items()):
        checker = REPO / "test" / "curated" / f"check_{target}_goldens.py"
        if not checker.is_file():
            raise CheckError(f"{target}: missing curated production checker")
        target_work = work / target
        run([
            sys.executable,
            checker,
            "--repo",
            REPO,
            "--gen",
            gen,
            "--profile",
            profile_entry["path"],
            "--work",
            target_work,
        ])
        report_path = target_work / "classification.json"
        if not report_path.is_file():
            raise CheckError(f"{target}: curated checker emitted no classification report")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        members = report.get("members")
        if not isinstance(members, list):
            raise CheckError(f"{target}: malformed classification report")
        reported = {(target, item.get("name")): item for item in members}
        expected_keys = {key for key in by_cell if key[0] == target}
        if set(reported) != expected_keys:
            raise CheckError(f"{target}: checker classification membership differs")
        for key in expected_keys:
            expected = by_cell[key]
            actual = reported[key]
            for field in (
                "name",
                "classification",
                "unsupportedFeature",
                "primitive",
            ):
                if field in expected and actual.get(field) != expected[field]:
                    raise CheckError(
                        f"{target}/{key[1]}: classification field {field} differs"
                    )
        # Consume each backend authority's negative witnesses as part of the
        # release surface, not merely as separately registered tests.
        run([
            sys.executable,
            checker,
            "--repo",
            REPO,
            "--gen",
            gen,
            "--selftest",
        ])


def validate_pair_witness(manifest, targets, report):
    if (
        report.get("kind") != "neutrino.canonical-plan-render-evidence"
        or report.get("schemaVersion") != 1
        or not isinstance(report.get("pairs"), list)
    ):
        raise CheckError("canonical pair/render evidence report is malformed")
    expected = {pair["id"]: pair for pair in manifest["variancePairs"]}
    witnessed = {
        pair.get("id"): pair
        for pair in report["pairs"]
        if isinstance(pair, dict) and isinstance(pair.get("id"), str)
    }
    if len(witnessed) != len(report["pairs"]) or set(witnessed) != set(expected):
        raise CheckError(
            f"variance-pair witness is not exact: "
            f"missing={sorted(set(expected) - set(witnessed))}, "
            f"extra={sorted(set(witnessed) - set(expected))}"
        )
    for pair_id, pair in witnessed.items():
        frozen = expected[pair_id]
        if pair.get("a") != frozen["a"] or pair.get("b") != frozen["b"]:
            raise CheckError(f"{pair_id}: witnessed endpoints differ from the manifest")
        if not re.fullmatch(r"[0-9a-f]{64}", pair.get("semanticSha256", "")):
            raise CheckError(f"{pair_id}: semantic digest is missing or malformed")
        backends = pair.get("backends")
        if not isinstance(backends, list):
            raise CheckError(f"{pair_id}: backend render evidence is missing")
        by_target = {
            backend.get("target"): backend
            for backend in backends
            if isinstance(backend, dict) and isinstance(backend.get("target"), str)
        }
        if len(by_target) != len(backends) or set(by_target) != set(targets):
            raise CheckError(
                f"{pair_id}: backend render evidence is not exact: "
                f"witnessed={sorted(by_target)}, governed={sorted(targets)}"
            )
        for target, backend in by_target.items():
            if not re.fullmatch(
                r"[0-9a-f]{64}", backend.get("normalizedSha256", "")
            ) or not backend.get("artifacts"):
                raise CheckError(
                    f"{pair_id}/{target}: normalized render evidence is incomplete"
                )
    mutation = report.get("mutation")
    if (
        not isinstance(mutation, dict)
        or mutation.get("kind") != "add-balanced-posting-obligation"
        or mutation.get("semanticChanged") is not True
        or set(mutation.get("renderChangedTargets", [])) != set(targets)
    ):
        raise CheckError("independent obligation mutation evidence is incomplete")
    return [witnessed[pair["id"]] for pair in manifest["variancePairs"]]


def validate_mutation_output(output):
    if MUTATION_MARKER not in output:
        raise CheckError("independent obligation mutation witness is missing")


def run_semantic_witness(gen, manifest, work):
    checker = REPO / "test" / "ir" / "check_canonical_plan_semantics.py"
    report_path = work / "canonical-plan-render-evidence.json"
    result = run([
        sys.executable,
        checker,
        gen,
        REPO / "examples",
        MANIFEST_PATH,
        REPO / "docs" / "diagnostic-taxonomy.json",
        report_path,
    ])
    evidence = validate_pair_witness(
        manifest,
        governed_targets(),
        json.loads(report_path.read_text(encoding="utf-8")),
    )
    validate_mutation_output(result.stdout)
    return evidence


def assert_workflow_invocation(text):
    if (
        "scripts/gates/check_m6_release_gate.py" not in text
        or "--gen out/tools/neutrino-gen/neutrino-gen" not in text
    ):
        raise CheckError("release-gate workflow invocation is missing or weakened")


def assert_integrity_registration(data):
    gates = data.get("gates")
    if not isinstance(gates, list):
        raise CheckError("gate-integrity manifest has no gates")
    matches = [gate for gate in gates if gate.get("id") == GATE_ID]
    if len(matches) != 1:
        raise CheckError("positive release gate registration is missing or duplicated")
    gate = matches[0]
    if gate.get("gatePath") != "scripts/gates/check_m6_release_gate.py":
        raise CheckError("positive release gate path is not governed")
    if set(gate.get("governedSurface", {}).get("tamperSet", [])) != set(PROBES):
        raise CheckError("positive release gate tamper set is incomplete")


def apply_probe(probe):
    manifest = load_manifest()
    if probe == "corpus-member":
        mutated = copy.deepcopy(manifest)
        mutated["examples"].pop()
        targets = governed_targets()
        validate_backend_matrix(
            mutated,
            targets,
            [
                {
                    "target": target,
                    "name": member,
                    "classification": "scenario-bearing",
                }
                for target in targets
                for member in manifest["examples"]
            ],
        )
        return
    if probe == "feature":
        vocabulary = load_vocabulary()
        artifacts = {
            "synthetic": {
                "semanticProfileVersion": vocabulary["semanticProfileVersion"],
                "requirements": [
                    {"feature": feature, "primitive": "synthetic"}
                    for feature in vocabulary["features"][:-1]
                ],
            }
        }
        validate_feature_coverage(vocabulary, artifacts)
        return
    if probe == "pair":
        checker = REPO / "test" / "ir" / "check_canonical_plan_semantics.py"
        result = subprocess.run(
            [sys.executable, checker, "--probe-render-mismatch"],
            cwd=REPO,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if (
            result.returncode
            and "probe-pair probe-target render differs modulo permitted labels"
            in result.stderr
        ):
            raise CheckError("production pair-render mismatch bit as required")
        return
    if probe == "backend-witness":
        targets = governed_targets() | {"synthetic-governed-backend"}
        profiles = load_profiles(expected_targets=governed_targets())
        validate_backend_authorities(targets, profiles)
        return
    if probe == "backend-cell":
        targets = {"postgres", "solidity"}
        validate_backend_matrix(
            manifest,
            targets,
            [
                {
                    "target": target,
                    "name": member,
                    "classification": "scenario-bearing",
                }
                for target in targets
                for member in manifest["examples"]
            ][:-1],
        )
        return
    if probe == "matrix-outcome":
        targets = {"postgres", "solidity"}
        members = hydrate_members(manifest)
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
        by_id = {row["id"]: row for row in matrix["examples"]}
        cells = [
            {
                "target": target,
                "name": member,
                "classification": (
                    "source-only-unsupported"
                    if members[member].scenario_dir is None
                    and not by_id[member]["backendGoldens"][target]
                    else (
                        "source-only-supported"
                        if members[member].scenario_dir is None
                        else "scenario-bearing"
                    )
                ),
            }
            for target in targets
            for member in manifest["examples"]
        ]
        mutated = copy.deepcopy(matrix)
        source_only_supported = next(
            row
            for row in mutated["examples"]
            if members[row["id"]].scenario_dir is None
            and row["backendGoldens"]["postgres"]
        )
        source_only_supported["backendGoldens"]["postgres"] = False
        validate_core_matrix_outcomes(manifest, targets, cells, mutated)
        return
    if probe == "mutation":
        validate_mutation_output("canonical sem(plan) OK without the required probe")
        return
    if probe == "workflow-invocation":
        assert_workflow_invocation("")
        return
    if probe == "manifest-registration":
        data = json.loads(INTEGRITY_PATH.read_text(encoding="utf-8"))
        data["gates"] = [
            gate for gate in data["gates"] if gate.get("id") != GATE_ID
        ]
        assert_integrity_registration(data)
        return
    raise CheckError(f"unknown probe {probe!r}")


def run_probe(probe):
    if probe not in PROBES:
        print(f"unknown positive-release probe {probe!r}", file=sys.stderr)
        return 2
    try:
        apply_probe(probe)
    except CheckError:
        print(f"probe-failed-as-expected:{probe}")
        return 1
    print(f"probe unexpectedly passed:{probe}")
    return 0


def selftest():
    failures = [probe for probe in PROBES if run_probe(probe) != 1]
    if failures:
        print(f"positive M6 release selftest FAILED: {failures}", file=sys.stderr)
        return 1
    print(f"positive M6 release selftest OK ({len(PROBES)} probes fail closed)")
    return 0


def discover_gen():
    configured = os.environ.get("NEUTRINO_GEN")
    candidates = [
        Path(configured) if configured else None,
        REPO / "out" / "tools" / "neutrino-gen" / "neutrino-gen",
        REPO / "build" / "tools" / "neutrino-gen" / "neutrino-gen",
    ]
    for candidate in candidates:
        if candidate and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("neutrino-gen")
    if found:
        return Path(found)
    raise CheckError("neutrino-gen not found; pass --gen or set NEUTRINO_GEN")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--gen", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--probe", choices=PROBES)
    args = parser.parse_args(argv)
    if args.probe:
        return run_probe(args.probe)
    if args.selftest:
        return selftest()
    try:
        gen = (args.gen or discover_gen()).resolve()
        work = (args.work or Path(tempfile.mkdtemp(prefix="m6-positive-release.")))
        work = work.resolve()
        work.mkdir(parents=True, exist_ok=True)
        for child in ("semantic-requirements", "classification", "goldens"):
            shutil.rmtree(work / child, ignore_errors=True)
        manifest = load_manifest()
        vocabulary = load_vocabulary()
        targets = governed_targets()
        profiles = load_profiles(expected_targets=targets, validate=True)
        validate_backend_authorities(targets, profiles)
        sources = hydrate_members(manifest)
        requirements = emit_semantic_requirements(
            gen, manifest, sources, work / "semantic-requirements"
        )
        covered = validate_feature_coverage(vocabulary, requirements)
        cells = classify_backends(
            gen, manifest, profiles, requirements, sources, work / "classification"
        )
        validate_core_matrix_outcomes(manifest, targets, cells)
        run_golden_witnesses(gen, profiles, cells, work / "goldens")
        pairs = run_semantic_witness(gen, manifest, work / "semantic-witness")
        assert_workflow_invocation(WORKFLOW_PATH.read_text(encoding="utf-8"))
        assert_integrity_registration(
            json.loads(INTEGRITY_PATH.read_text(encoding="utf-8"))
        )
        report = {
            "schemaVersion": 1,
            "kind": "neutrino.m6-positive-release-gate",
            "members": manifest["examples"],
            "semanticFeatures": covered,
            "variancePairs": pairs,
            "backendWitnesses": cells,
            "mutationWitness": "add-balanced-posting-obligation",
        }
        (work / "release-gate-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (CheckError, OSError, json.JSONDecodeError) as error:
        print(f"positive M6 release gate FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "positive M6 release gate OK: "
        f"{len(manifest['examples'])} members, {len(covered)} semantic features, "
        f"{len(profiles)} targets, {len(pairs)} variance pairs, obligation mutation bites"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
