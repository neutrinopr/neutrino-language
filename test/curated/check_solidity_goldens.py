#!/usr/bin/env python3
"""Validate the architect-curated Solidity corpus through production generators."""

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


class CheckError(RuntimeError):
    pass


def run(argv, *, env=None):
    proc = subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env)
    if proc.returncode:
        raise CheckError(
            f"command failed ({proc.returncode}): {' '.join(map(str, argv))}\n"
            f"{proc.stdout}{proc.stderr}")


def files_under(root):
    root = Path(root)
    if not root.is_dir():
        raise CheckError(f"missing directory: {root}")
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def compare_tree(generated, golden, description):
    generated_files = files_under(generated)
    golden_files = files_under(golden)
    if generated_files.keys() != golden_files.keys():
        missing = sorted(str(path) for path in generated_files.keys() - golden_files.keys())
        extra = sorted(str(path) for path in golden_files.keys() - generated_files.keys())
        raise CheckError(
            f"{description}: file set differs; missing golden={missing}, extra golden={extra}")
    stale = [str(path) for path in generated_files
             if generated_files[path] != golden_files[path]]
    if stale:
        raise CheckError(f"{description}: stale golden bytes: {stale}")


def load_manifest(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckError(f"cannot load curated corpus manifest {path}: {exc}") from exc
    # Consume the ONE architect-approved corpus manifest (). Its structural
    # validity (schema, freeze provenance) is owned by check_m6_curated_example_corpus.py;
    # here we read only the membership + variance pairs that drive golden coverage.
    required = {"schemaVersion", "kind", "examples", "variancePairs", "packs"}
    if not required <= set(data):
        raise CheckError(f"manifest must carry {sorted(required)}")
    if data["schemaVersion"] != 2 or data["kind"] != "neutrino.m6-curated-example-corpus":
        raise CheckError("unsupported curated corpus manifest identity")
    examples = data["examples"]
    if (not isinstance(examples, list) or len(examples) != 7 or
            any(not isinstance(name, str) or
                not re.fullmatch(r"[a-z][a-z0-9_]*", name) for name in examples) or
            len(set(examples)) != len(examples)):
        raise CheckError("curated corpus must contain exactly seven unique example names")
    pairs = data["variancePairs"]
    if not isinstance(pairs, list) or len(pairs) != 3:
        raise CheckError("curated corpus must contain exactly three variance pairs")
    seen_pairs = set()
    for pair in pairs:
        if not isinstance(pair, dict) or not {"a", "b"} <= set(pair):
            raise CheckError("each variance pair must contain a and b")
        edge = (pair["a"], pair["b"])
        if edge[0] == edge[1] or any(name not in examples for name in edge):
            raise CheckError(f"invalid variance pair: {edge}")
        if edge in seen_pairs:
            raise CheckError(f"duplicate variance pair: {edge}")
        seen_pairs.add(edge)
    return data


def one_file(directory, suffix):
    matches = sorted(Path(directory).glob(f"*{suffix}"))
    if len(matches) != 1:
        raise CheckError(f"expected exactly one *{suffix} in {directory}, found {len(matches)}")
    return matches[0]


def forge_env():
    env = os.environ.copy()
    library_path = env.get("FORGE_DYLD_LIBRARY_PATH")
    if library_path:
        env["DYLD_LIBRARY_PATH"] = library_path
    return env


_DUMMY_INPUT = {"money": 1, "decimal": 1, "party": "p", "currency": "EUR",
                "evidence": "sha256:aa", "string": "x", "extension": 1}


def synth_scenario(spec, path):
    # The direct-source Solidity render always requires a scenario. A source-only
    # curated member has no committed one, so synthesize a minimal scenario from the
    # spec inputs purely to drive the render: the src/ contract is scenario-VALUE
    # independent (only the test/ harness consumes concrete values), so the src bytes
    # equal both the committed golden and the --from-spec output.
    procedure = spec.get("procedure") or spec.get("name")
    if not procedure:
        raise CheckError("capability-spec carries no procedure name to synthesize a scenario")
    inputs = {i["name"]: _DUMMY_INPUT.get(i["category"], "x") for i in spec.get("inputs", [])}
    path.write_text(json.dumps({"scenario": "curated_source_parity", "procedure": procedure,
                                "inputs": inputs, "expect": {}}), encoding="utf-8")


def hydrate_members(repo, manifest):
    sys.path.insert(0, str(repo / "scripts" / "gates"))
    import check_m6_release_gate as release_gate

    return release_gate.hydrate_members(manifest)


def check_example(repo, gen, work, name, member, *, profile=None, forge=None, solc=None):
    domain = member.root
    source = member.source_path
    spec = member.spec_path
    golden = domain / "generated" / "solidity"
    if source is None or spec is None or not source.is_file() or not spec.is_file():
        raise CheckError(f"{name}: missing canonical source or capability-spec")

    example_work = work / name
    shutil.rmtree(example_work, ignore_errors=True)
    example_work.mkdir(parents=True)
    source_spec = example_work / "source-spec"
    from_spec = example_work / "from-spec"
    run([gen, "--target=capability-spec", source, "-o", source_spec])
    generated_spec = source_spec / "capability-spec.json"
    if generated_spec.read_bytes() != spec.read_bytes():
        raise CheckError(f"{name}: committed capability-spec is stale relative to source")

    profile_arg = [f"--profile={profile}"] if profile else []
    run([gen, "--target=solidity", "--from-spec", *profile_arg, spec, "-o", from_spec])
    compare_tree(from_spec / "src", golden / "src",
                 f"{name}: --from-spec Solidity source golden")

    # Direct source->Solidity production render for EVERY curated member (: source
    # and --from-spec outputs must agree). A committed scenario drives it when present;
    # a source-only member uses a scenario synthesized from its spec inputs.
    scenarios = (
        sorted(member.scenario_dir.glob("*.json"))
        if member.scenario_dir is not None
        else []
    )
    if len(scenarios) > 1:
        raise CheckError(f"{name}: curated pack has ambiguous scenarios")
    scenario = scenarios[0] if scenarios else None
    committed_scenario = scenario is not None
    render_scenario = scenario
    if not committed_scenario:
        render_scenario = example_work / "synth-scenario.json"
        synth_scenario(json.loads(spec.read_text(encoding="utf-8")), render_scenario)
    source_render = example_work / "source-render"
    run([gen, "--target=solidity", *profile_arg, f"--scenario={render_scenario}",
         source, "-o", source_render])
    compare_tree(source_render / "src", from_spec / "src",
                 f"{name}: source/--from-spec parity")
    compare_tree(source_render / "src", golden / "src",
                 f"{name}: source Solidity golden")

    if committed_scenario:
        compare_tree(source_render / "test", golden / "test",
                     f"{name}: Foundry harness golden")
        if ((source_render / "foundry.toml").read_bytes() !=
                (golden / "foundry.toml").read_bytes()):
            raise CheckError(f"{name}: stale foundry.toml golden")
        expected_files = {
            Path("foundry.toml"),
            *(Path("src") / path for path in files_under(golden / "src")),
            *(Path("test") / path for path in files_under(golden / "test")),
        }
        actual_files = {path.relative_to(golden) for path in golden.rglob("*") if path.is_file()}
        if actual_files != expected_files:
            raise CheckError(f"{name}: unexpected committed bundle files: "
                             f"{sorted(map(str, actual_files - expected_files))}")
        if forge and solc:
            run([forge, "test", "--root", source_render, "--use", solc],
                env=forge_env())
    else:
        actual_files = {path.relative_to(golden) for path in golden.rglob("*") if path.is_file()}
        expected_files = {Path("src") / path for path in files_under(golden / "src")}
        if actual_files != expected_files:
            raise CheckError(
                f"{name}: source-only golden must contain only the production src bundle")
        if forge and solc:
            run([forge, "build", "--root", from_spec, "--use", solc],
                env=forge_env())
    return (
        from_spec / "src",
        golden / "src",
        {
            "name": name,
            "classification": (
                "scenario-bearing" if committed_scenario else "source-only-supported"
            ),
        },
    )


# The five weakenings the meta-gate () executes independently as tamper probes.
PROBES = (
    "deleted-golden",
    "stale-bytes",
    "removed-manifest-member",
    "removed-ctest-invocation",
    "removed-forge-acceptance",
)


def assert_ctest_wired(ctest_text):
    if "curated-solidity-goldens" not in ctest_text or "check_solidity_goldens.py" not in ctest_text:
        raise CheckError("curated-solidity-goldens CTest invocation is missing")


def assert_forge_acceptance_wired(run_sh, acc_cmake):
    if ("curated-solidity)" not in run_sh or "check_solidity_goldens.py" not in run_sh or
            "--forge" not in run_sh or "--solc" not in run_sh or
            "acceptance-curated-solidity" not in acc_cmake):
        raise CheckError("Forge/solc curated-solidity acceptance invocation is missing")


def apply_probe(probe, repo, gen):
    """Apply exactly one weakening and run the check it should defeat. Raises
    CheckError iff the gate correctly bites (the probe FAILED as expected)."""
    manifest_path = repo / "docs" / "m6-curated-example-corpus.json"
    if probe == "removed-manifest-member":
        manifest = load_manifest(manifest_path)
        mutated = dict(manifest)
        mutated["examples"] = manifest["examples"][:-1]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(mutated, handle)
            path = handle.name
        try:
            load_manifest(path)
        finally:
            Path(path).unlink()
        return
    if probe == "removed-ctest-invocation":
        assert_ctest_wired("")   # a cmake without the invocation must bite
        return
    if probe == "removed-forge-acceptance":
        assert_forge_acceptance_wired("", "")
        return
    if probe in ("deleted-golden", "stale-bytes"):
        manifest = load_manifest(manifest_path)
        members = hydrate_members(repo, manifest)
        with tempfile.TemporaryDirectory(prefix="curated-solidity-probe-") as work:
            generated, golden, _ = check_example(
                repo, gen, Path(work), manifest["examples"][0],
                members[manifest["examples"][0]])
            probe_dir = Path(work) / "tampered-golden"
            shutil.copytree(golden, probe_dir)
            victim = one_file(probe_dir, ".sol")
            if probe == "deleted-golden":
                victim.unlink()
            else:
                victim.write_text(victim.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            compare_tree(generated, probe_dir, probe)
        return
    raise CheckError(f"unknown probe {probe!r}")


def run_probe(probe, repo, gen):
    if probe not in PROBES:
        print(f"unknown curated-solidity probe {probe!r}", file=sys.stderr)
        return 2
    try:
        apply_probe(probe, repo, gen)
    except CheckError:
        print(f"probe-failed-as-expected:{probe}")
        return 1
    print(f"probe unexpectedly passed:{probe}")
    return 0


def selftest(repo, gen):
    failures = []
    for probe in PROBES:
        if run_probe(probe, repo, gen) != 1:
            failures.append(f"probe {probe!r} did not fail for its intended reason")
    if failures:
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        raise CheckError("curated-solidity selftest probes did not all bite")


def discover_gen(repo):
    env = os.environ.get("NEUTRINO_GEN")
    if env and Path(env).is_file():
        return env
    for candidate in (repo / "out/tools/neutrino-gen/neutrino-gen",
                      repo / "build/tools/neutrino-gen/neutrino-gen"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    found = shutil.which("neutrino-gen")
    if found:
        return found
    raise CheckError("neutrino-gen not found (build it, set NEUTRINO_GEN, or pass --gen)")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--gen")
    parser.add_argument("--work", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--forge")
    parser.add_argument("--solc")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--probe")
    args = parser.parse_args()
    # --selftest / --probe are self-sufficient (like the other build-tier gates): the
    # repo root, the production neutrino-gen, and a work dir are auto-discovered.
    repo = (args.repo or Path(__file__).resolve().parents[2]).resolve()
    manifest_path = args.manifest or repo / "docs" / "m6-curated-example-corpus.json"
    try:
        gen = args.gen or discover_gen(repo)
        if args.probe:
            return run_probe(args.probe, repo, gen)
        work = args.work or Path(tempfile.mkdtemp(prefix="curated-solidity-"))
        manifest = load_manifest(manifest_path)
        members = hydrate_members(repo, manifest)
        work.mkdir(parents=True, exist_ok=True)
        classifications = []
        for name in manifest["examples"]:
            _, _, classification = check_example(
                repo, gen, work, name, members[name], profile=args.profile,
                forge=args.forge, solc=args.solc)
            classifications.append(classification)
        (work / "classification.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "kind": "neutrino.curated-solidity-classification",
                    "members": classifications,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if args.selftest:
            selftest(repo, gen)
    except (CheckError, OSError) as exc:
        print(f"curated Solidity golden gate FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"curated Solidity golden gate OK: {len(manifest['examples'])} manifest members; "
          "source/spec freshness, production source parity, and committed bytes verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
