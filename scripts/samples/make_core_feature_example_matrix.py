#!/usr/bin/env python3
"""Build the compiler-derived semantic feature x domain-example matrix.

The feature universe comes only from the committed vocabulary after a byte
comparison with the compiler query. Per-example features come only from the
`semantic-requirements` target on source and canonical-spec reconstruction.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VOCABULARY = REPO / "docs/semantic-feature-vocabulary.json"
MATRIX = REPO / "docs/core-feature-example-matrix.json"
CORPUS = REPO / "docs/m6-curated-example-corpus.json"
METRIC_KEYS = {
    "expressionDepth", "effectCount", "effectGroupCount",
    "attestationCount", "computeCount", "operationSteps",
}


def compact(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def render(obj):
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def rel(path):
    # Preserve the manifest-owned checkout path rather than resolving its
    # symlink to an arbitrary local clone outside the repository.
    return str(Path(os.path.abspath(path)).relative_to(REPO))


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def discover_examples(domains_dir=None):
    if domains_dir is not None:
        raise ValueError("committed-domain discovery is retired; hydrate the curated packs")
    sys.path.insert(0, str(REPO / "scripts" / "gates"))
    import m6_pack_resolver

    manifest = load_json(CORPUS)
    members = m6_pack_resolver.resolve_members(manifest, repo=REPO)
    found = []
    for example_id in manifest["examples"]:
        member = members[example_id]
        source = member.source_path
        spec = member.spec_path
        directory = member.root
        if not source.is_file() or not spec.is_file():
            raise ValueError(
                f"pack {example_id!r} must provide source and capability-spec payloads"
            )
        found.append((example_id, source, spec, directory))
    if not found:
        raise ValueError("no curated packs resolved")
    return found


def semantic_requirement_errors(artifact, vocabulary):
    errors = []
    if not isinstance(artifact, dict):
        return ["semantic-requirements artifact must be an object"]
    expected = {"kind", "schemaVersion", "semanticProfileVersion", "requirements", "metrics"}
    unknown = sorted(set(artifact) - expected)
    missing = sorted(expected - set(artifact))
    if unknown:
        errors.append(f"semantic-requirements unknown fields: {unknown}")
    if missing:
        errors.append(f"semantic-requirements missing fields: {missing}")
    if artifact.get("kind") != "neutrino.semantic-requirements":
        errors.append("semantic-requirements kind is malformed")
    if artifact.get("schemaVersion") != 1:
        errors.append("semantic-requirements schemaVersion must equal 1")
    version = artifact.get("semanticProfileVersion")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        errors.append("semanticProfileVersion must be a positive integer")
    requirements = artifact.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        errors.append("requirements must be a non-empty array")
        requirements = []
    pairs = []
    features = []
    for index, requirement in enumerate(requirements):
        where = f"requirements[{index}]"
        if not isinstance(requirement, dict):
            errors.append(f"{where} must be an object")
            continue
        if set(requirement) != {"feature", "primitive"}:
            errors.append(f"{where} must contain exactly feature and primitive")
            continue
        feature, primitive = requirement.get("feature"), requirement.get("primitive")
        if not isinstance(feature, str) or not isinstance(primitive, str) or not primitive:
            errors.append(f"{where} feature/primitive must be non-empty strings")
            continue
        if feature not in vocabulary:
            errors.append(f"{where} unknown semantic feature {feature!r}")
        pairs.append((feature, primitive))
        features.append(feature)
    if pairs != sorted(pairs):
        errors.append("requirements must be sorted by feature then primitive")
    if len(pairs) != len(set(pairs)) or len(features) != len(set(features)):
        errors.append("requirements must contain unique features and pairs")
    metrics = artifact.get("metrics")
    if not isinstance(metrics, dict) or set(metrics) != METRIC_KEYS:
        errors.append(f"metrics must contain exactly {sorted(METRIC_KEYS)}")
    elif any(not isinstance(value, int) or isinstance(value, bool) or value < 0
             for value in metrics.values()):
        errors.append("metrics values must be non-negative integers")
    return errors


def compare_projections(example_id, source_bytes, spec_bytes):
    if source_bytes != spec_bytes:
        return [f"{example_id}: source/spec semantic-requirements bytes disagree"]
    return []


def compare_example_binding(example_id, source_requirements, spec_requirements,
                            source_identity, spec_identity):
    errors = compare_projections(example_id, source_requirements, spec_requirements)
    if source_identity != spec_identity:
        errors.append(f"{example_id}: source/spec agreement-identity bytes disagree")
    return errors


def agreement_identity_errors(artifact):
    if not isinstance(artifact, dict):
        return ["agreement-identity artifact must be an object"]
    errors = []
    if artifact.get("kind") != "neutrino.agreement-identity":
        errors.append("agreement-identity kind is malformed")
    capability_hash = artifact.get("capabilityHash")
    agreement_hash = (artifact.get("identity") or {}).get("agreementHash")
    for name, value in (("capabilityHash", capability_hash),
                        ("identity.agreementHash", agreement_hash)):
        if (not isinstance(value, str) or len(value) != 64 or
                any(character not in "0123456789abcdef" for character in value)):
            errors.append(f"agreement-identity {name} is malformed")
    return errors


def run_projection(neutrino_gen, input_path, output_dir, from_spec=False):
    command = [neutrino_gen, "--target=semantic-requirements"]
    if from_spec:
        command.append("--from-spec")
    command += [str(input_path), "-o", str(output_dir)]
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(
            f"semantic-requirements target failed for {input_path} (exit {result.returncode}): "
            f"{result.stderr.strip()}")
    artifact = output_dir / "semantic-requirements.json"
    if not artifact.is_file():
        raise RuntimeError(f"semantic-requirements target omitted {artifact}")
    return artifact.read_bytes(), load_json(artifact)


def run_identity(neutrino_gen, input_path, output_dir, from_spec=False):
    command = [neutrino_gen, "--target=agreement-identity"]
    if from_spec:
        command.append("--from-spec")
    command += [str(input_path), "-o", str(output_dir)]
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(
            f"agreement-identity target failed for {input_path} (exit {result.returncode}): "
            f"{result.stderr.strip()}")
    artifact = output_dir / "agreement-identity.json"
    if not artifact.is_file():
        raise RuntimeError(f"agreement-identity target omitted {artifact}")
    return artifact.read_bytes(), load_json(artifact)


def backend_golden_presence(directory, procedure):
    contract_name = "".join(part[:1].upper() + part[1:]
                            for part in procedure.split("_") if part)
    solidity_contract = directory / f"generated/solidity/src/{contract_name}.sol"
    postgres_dir = directory / "generated/postgres"
    return {
        "solidity": solidity_contract.is_file(),
        # This is artifact presence, not backend admissibility. A governed,
        # scenario-free PostgreSQL member has an ordinary deterministic
        # procedure without a fabricated behavioral schema/bundle. The M6
        # release gate derives admissibility from the target profile first and
        # then interprets this bit relative to that classification.
        "postgres": (postgres_dir / "procedure.sql").is_file(),
    }


def observe_examples(neutrino_gen, vocabulary_artifact, *, examples=None,
                     projection_runner=run_projection, identity_runner=run_identity):
    vocabulary = set(vocabulary_artifact["features"])
    semantic_profile_version = vocabulary_artifact["semanticProfileVersion"]
    observations = []
    seen = set()
    seen_capability_hashes = {}
    errors = []
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        example_rows = discover_examples() if examples is None else examples
        for example_id, source, spec_path, directory in example_rows:
            if example_id in seen:
                errors.append(f"duplicate example identity {example_id!r}")
                continue
            seen.add(example_id)
            source_bytes, source_artifact = projection_runner(
                neutrino_gen, source, root / f"{example_id}.source")
            spec_bytes, spec_artifact = projection_runner(
                neutrino_gen, spec_path, root / f"{example_id}.spec", from_spec=True)
            source_identity_bytes, source_identity = identity_runner(
                neutrino_gen, source, root / f"{example_id}.source-identity")
            spec_identity_bytes, spec_identity = identity_runner(
                neutrino_gen, spec_path, root / f"{example_id}.spec-identity", from_spec=True)
            errors.extend(compare_example_binding(
                example_id, source_bytes, spec_bytes,
                source_identity_bytes, spec_identity_bytes))
            errors.extend(f"{example_id}: {error}"
                          for error in semantic_requirement_errors(source_artifact, vocabulary))
            errors.extend(f"{example_id} from-spec: {error}"
                          for error in semantic_requirement_errors(spec_artifact, vocabulary))
            errors.extend(f"{example_id}: {error}"
                          for error in agreement_identity_errors(source_identity))
            errors.extend(f"{example_id} from-spec: {error}"
                          for error in agreement_identity_errors(spec_identity))
            if source_artifact.get("semanticProfileVersion") != semantic_profile_version:
                errors.append(
                    f"{example_id}: semanticProfileVersion differs from the vocabulary")
            if spec_artifact.get("semanticProfileVersion") != semantic_profile_version:
                errors.append(
                    f"{example_id} from-spec: semanticProfileVersion differs from the vocabulary")
            capability_hash = source_identity.get("capabilityHash")
            if capability_hash in seen_capability_hashes:
                errors.append(
                    f"{example_id}: duplicate capability identity also used by "
                    f"{seen_capability_hashes[capability_hash]}")
            elif isinstance(capability_hash, str):
                seen_capability_hashes[capability_hash] = example_id
            features = sorted(requirement["feature"]
                              for requirement in source_artifact.get("requirements", [])
                              if isinstance(requirement, dict) and isinstance(requirement.get("feature"), str))
            observations.append({
                "id": example_id,
                "source": rel(source),
                "spec": rel(spec_path),
                "capabilityHash": capability_hash,
                "features": features,
                "metrics": source_artifact.get("metrics"),
                "backendGoldens": backend_golden_presence(directory, example_id),
            })
    return observations, errors


def build_matrix(vocabulary_artifact, observations):
    features = vocabulary_artifact["features"]
    coverage = {feature: [] for feature in features}
    duplicate_ids = []
    duplicate_capability_hashes = []
    seen = set()
    capability_identities = set()
    unknown = []
    for observation in observations:
        example_id = observation["id"]
        if example_id in seen:
            duplicate_ids.append(example_id)
        seen.add(example_id)
        capability_hash = observation.get("capabilityHash")
        if capability_hash in capability_identities:
            duplicate_capability_hashes.append(capability_hash)
        capability_identities.add(capability_hash)
        for feature in observation["features"]:
            if feature not in coverage:
                unknown.append((example_id, feature))
            else:
                coverage[feature].append(example_id)
    if duplicate_ids:
        raise ValueError(f"duplicate example identity {sorted(set(duplicate_ids))}")
    if duplicate_capability_hashes:
        raise ValueError(
            f"duplicate capability identity {sorted(set(duplicate_capability_hashes))}")
    if unknown:
        raise ValueError(f"unknown semantic features {unknown}")
    groups = defaultdict(list)
    for observation in observations:
        groups[tuple(observation["features"])].append(observation["id"])
    candidates = [
        {"features": list(feature_set), "examples": sorted(example_ids)}
        for feature_set, example_ids in sorted(groups.items()) if len(example_ids) >= 2
    ]
    vocabulary_bytes = VOCABULARY.read_bytes()
    return {
        "kind": "neutrino.core-feature-example-matrix",
        "schemaVersion": 1,
        "semanticProfileVersion": vocabulary_artifact["semanticProfileVersion"],
        "vocabulary": {
            "path": "docs/semantic-feature-vocabulary.json",
            "sha256": hashlib.sha256(vocabulary_bytes).hexdigest(),
            "featureCount": len(features),
        },
        "exampleCount": len(observations),
        "examples": sorted(observations, key=lambda observation: observation["id"]),
        "featureCoverage": [
            {"feature": feature, "examples": sorted(coverage[feature])}
            for feature in features
        ],
        "gaps": [feature for feature in features if not coverage[feature]],
        "candidateVarianceGroups": candidates,
    }


def require_no_gaps_errors(matrix):
    return [f"uncovered semantic feature {feature}" for feature in matrix.get("gaps", [])]


def matrix_errors(matrix, vocabulary):
    errors = []
    expected = {
        "kind", "schemaVersion", "semanticProfileVersion", "vocabulary",
        "exampleCount", "examples", "featureCoverage", "gaps", "candidateVarianceGroups",
    }
    if not isinstance(matrix, dict) or set(matrix) != expected:
        return ["matrix must contain exactly the closed top-level fields"]
    coverage = matrix.get("featureCoverage")
    if not isinstance(coverage, list):
        return ["featureCoverage must be an array"]
    covered_features = [row.get("feature") for row in coverage if isinstance(row, dict)]
    if covered_features != vocabulary["features"]:
        errors.append("featureCoverage must contain every vocabulary feature exactly once in order")
    if matrix.get("semanticProfileVersion") != vocabulary.get("semanticProfileVersion"):
        errors.append("matrix semanticProfileVersion differs from the vocabulary")
    example_ids = [row.get("id") for row in matrix.get("examples", []) if isinstance(row, dict)]
    if len(example_ids) != len(set(example_ids)):
        errors.append("matrix contains duplicate example identities")
    if matrix.get("exampleCount") != len(example_ids):
        errors.append("exampleCount does not equal examples length")
    return errors


def compiler_vocabulary_errors(neutrino_translate):
    result = subprocess.run([neutrino_translate, "--semantic-feature-vocabulary"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        return [f"compiler vocabulary query failed with exit {result.returncode}"]
    committed = VOCABULARY.read_bytes()
    if result.stdout != committed:
        return ["committed vocabulary bytes differ from compiler-owned registry output"]
    return []


def _selftest_fixtures():
    vocabulary = {
        "features": ["authorization:explicit", "terminal:success"],
        "semanticProfileVersion": 3,
    }
    good = {
        "kind": "neutrino.semantic-requirements", "schemaVersion": 1,
        "semanticProfileVersion": 3,
        "requirements": [
            {"feature": "authorization:explicit", "primitive": "transition authorization"},
            {"feature": "terminal:success", "primitive": "terminal projection"},
        ],
        "metrics": {key: 0 for key in METRIC_KEYS},
    }
    return vocabulary, good


def swapped_equal_observation_spec_detected(vocabulary, requirement_artifact):
    fixture_root = REPO / "test/fixtures/core-feature-identity-swap"
    source_a, source_b = fixture_root / "a.neu", fixture_root / "b.neu"
    spec_a, spec_b = fixture_root / "a.json", fixture_root / "b.json"
    identity_a = {
        "kind": "neutrino.agreement-identity",
        "capabilityHash": "a" * 64,
        "identity": {"agreementHash": "1" * 64},
    }
    identity_b = {
        "kind": "neutrino.agreement-identity",
        "capabilityHash": "b" * 64,
        "identity": {"agreementHash": "2" * 64},
    }
    identities = {
        source_a: identity_a, source_b: identity_b,
        spec_a: identity_a, spec_b: identity_b,
    }
    specs = {spec_a, spec_b}
    requirement_bytes = render(requirement_artifact).encode("utf-8")

    def projection_runner(_neutrino_gen, input_path, _output_dir, from_spec=False):
        path = Path(input_path)
        assert from_spec == (path in specs)
        return requirement_bytes, copy.deepcopy(requirement_artifact)

    def identity_runner(_neutrino_gen, input_path, _output_dir, from_spec=False):
        path = Path(input_path)
        assert from_spec == (path in specs)
        artifact = copy.deepcopy(identities[path])
        return render(artifact).encode("utf-8"), artifact

    swapped_examples = [
        ("a", source_a, spec_b, fixture_root / "a"),
        ("b", source_b, spec_a, fixture_root / "b"),
    ]
    _observations, errors = observe_examples(
        "injected-runner", vocabulary, examples=swapped_examples,
        projection_runner=projection_runner, identity_runner=identity_runner)
    identity_errors = [error for error in errors
                       if "agreement-identity bytes disagree" in error]
    return identity_errors == [
        "a: source/spec agreement-identity bytes disagree",
        "b: source/spec agreement-identity bytes disagree",
    ]


def probe(probe_id):
    vocabulary, good = _selftest_fixtures()
    detected = False
    if probe_id == "unknown-feature":
        tampered = copy.deepcopy(good)
        tampered["requirements"][1]["feature"] = "terminal:unknown"
        detected = any("unknown semantic feature" in error for error in
                       semantic_requirement_errors(tampered, set(vocabulary["features"])))
    elif probe_id == "missing-projection":
        tampered = copy.deepcopy(good)
        tampered.pop("requirements")
        detected = any("missing fields" in error for error in
                       semantic_requirement_errors(tampered, set(vocabulary["features"])))
    elif probe_id == "unknown-field":
        tampered = copy.deepcopy(good)
        tampered["invented"] = True
        detected = any("unknown fields" in error for error in
                       semantic_requirement_errors(tampered, set(vocabulary["features"])))
    elif probe_id == "source-spec-disagreement":
        detected = bool(compare_projections("x", b"source", b"spec"))
    elif probe_id == "swapped-equal-observation-spec":
        detected = swapped_equal_observation_spec_detected(vocabulary, good)
    elif probe_id == "backend-side-artifact-only":
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            shared = directory / "generated/solidity/src/ThresholdQuorumAcceptance.sol"
            harness = directory / "generated/solidity/test/OnlyHarness.t.sol"
            side_sql = directory / "generated/postgres/reconciliation.sql"
            for path in (shared, harness, side_sql):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("side artifact only\n", encoding="utf-8")
            detected = backend_golden_presence(directory, "only_harness") == {
                "solidity": False, "postgres": False}
    elif probe_id == "source-only-postgres-artifact":
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            procedure = directory / "generated/postgres/procedure.sql"
            procedure.parent.mkdir(parents=True, exist_ok=True)
            procedure.write_text("SELECT 1;\n", encoding="utf-8")
            detected = backend_golden_presence(directory, "source_only") == {
                "solidity": False, "postgres": True}
    else:
        observation = {
            "id": "x", "source": "s", "spec": "p", "capabilityHash": "0" * 64,
            "features": list(vocabulary["features"]), "metrics": good["metrics"],
            "backendGoldens": {"solidity": False, "postgres": False},
        }
        if probe_id == "duplicate-example":
            try:
                build_matrix(vocabulary, [observation, copy.deepcopy(observation)])
            except ValueError as error:
                detected = "duplicate example identity" in str(error)
        elif probe_id == "duplicate-capability-identity":
            duplicate = copy.deepcopy(observation)
            duplicate["id"] = "y"
            try:
                build_matrix(vocabulary, [observation, duplicate])
            except ValueError as error:
                detected = "duplicate capability identity" in str(error)
        elif probe_id == "added-vocabulary-gap":
            extended = copy.deepcopy(vocabulary)
            extended["features"].append("time:explicit_input")
            matrix = build_matrix(extended, [observation])
            detected = require_no_gaps_errors(matrix) == [
                "uncovered semantic feature time:explicit_input"]
        elif probe_id == "missing-vocabulary-row":
            matrix = build_matrix(vocabulary, [observation])
            matrix["featureCoverage"].pop()
            detected = any("every vocabulary feature" in error
                           for error in matrix_errors(matrix, vocabulary))
        else:
            raise ValueError(f"unknown probe {probe_id!r}")
    if not detected:
        print(f"probe unexpectedly survived:{probe_id}", file=sys.stderr)
        return 0
    print(f"probe-failed-as-expected:{probe_id}", file=sys.stderr)
    return 1


def selftest():
    vocabulary, good = _selftest_fixtures()
    assert semantic_requirement_errors(good, set(vocabulary["features"])) == []
    unknown = copy.deepcopy(good)
    unknown["requirements"][1]["feature"] = "terminal:unknown"
    assert any("unknown semantic feature" in error
               for error in semantic_requirement_errors(unknown, set(vocabulary["features"])))
    missing = copy.deepcopy(good)
    missing.pop("requirements")
    assert any("missing fields" in error for error in semantic_requirement_errors(
        missing, set(vocabulary["features"])))
    extra = copy.deepcopy(good)
    extra["invented"] = True
    assert any("unknown fields" in error for error in semantic_requirement_errors(
        extra, set(vocabulary["features"])))
    assert compare_projections("x", b"a", b"b") == [
        "x: source/spec semantic-requirements bytes disagree"]
    assert compare_example_binding("x", b"same", b"same", b"a", b"b") == [
        "x: source/spec agreement-identity bytes disagree"]
    observation = {
        "id": "x", "source": "s", "spec": "p", "capabilityHash": "0" * 64,
        "features": list(vocabulary["features"]), "metrics": good["metrics"],
        "backendGoldens": {"solidity": False, "postgres": False},
    }
    try:
        build_matrix(vocabulary, [observation, copy.deepcopy(observation)])
        raise AssertionError("duplicate example identity did not fail")
    except ValueError as error:
        assert "duplicate example identity" in str(error)
    duplicate = copy.deepcopy(observation)
    duplicate["id"] = "y"
    try:
        build_matrix(vocabulary, [observation, duplicate])
        raise AssertionError("duplicate capability identity did not fail")
    except ValueError as error:
        assert "duplicate capability identity" in str(error)
    extended = copy.deepcopy(vocabulary)
    extended["features"].append("time:explicit_input")
    matrix = build_matrix(extended, [observation])
    assert matrix["gaps"] == ["time:explicit_input"]
    assert require_no_gaps_errors(matrix) == ["uncovered semantic feature time:explicit_input"]
    assert matrix_errors(matrix, extended) == []
    for probe_id in ("unknown-feature", "missing-projection", "unknown-field",
                     "duplicate-example", "duplicate-capability-identity",
                     "source-spec-disagreement", "swapped-equal-observation-spec",
                     "added-vocabulary-gap", "missing-vocabulary-row",
                     "backend-side-artifact-only",
                     "source-only-postgres-artifact"):
        assert probe(probe_id) == 1
    print("core-feature example matrix selftest OK: closed projection, bound identity, parity, "
          "backend-golden, and gap tampers bite")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--neutrino-gen")
    parser.add_argument("--neutrino-translate")
    parser.add_argument("--out", default=str(MATRIX))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--probe", choices=(
        "unknown-feature", "missing-projection", "unknown-field", "duplicate-example",
        "duplicate-capability-identity", "source-spec-disagreement",
        "swapped-equal-observation-spec", "added-vocabulary-gap",
        "missing-vocabulary-row", "backend-side-artifact-only",
        "source-only-postgres-artifact"))
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if args.probe:
        return probe(args.probe)
    if not args.neutrino_gen or not args.neutrino_translate:
        parser.error("--neutrino-gen and --neutrino-translate are required")
    vocabulary = load_json(VOCABULARY)
    errors = compiler_vocabulary_errors(args.neutrino_translate)
    observations, observation_errors = observe_examples(args.neutrino_gen, vocabulary)
    errors.extend(observation_errors)
    matrix = build_matrix(vocabulary, observations)
    errors.extend(matrix_errors(matrix, vocabulary))
    output = render(matrix)
    out_path = Path(args.out)
    if args.check:
        if not out_path.is_file() or out_path.read_text(encoding="utf-8") != output:
            errors.append(f"{rel(out_path)} is stale; regenerate it")
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"core-feature example matrix OK: {len(observations)} examples, "
          f"{len(vocabulary['features'])} features, gaps={matrix['gaps']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
