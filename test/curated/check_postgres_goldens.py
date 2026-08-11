#!/usr/bin/env python3
"""Validate curated PostgreSQL goldens through governed production paths."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Dict, Iterable, Sequence


class CheckError(RuntimeError):
    pass


def run(argv: Sequence[object], *, expect: int = 0) -> subprocess.CompletedProcess:
    command = [str(arg) for arg in argv]
    proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != expect:
        raise CheckError(
            f"command returned {proc.returncode}, expected {expect}: {' '.join(command)}\n"
            f"{proc.stdout}{proc.stderr}"
        )
    return proc


def run_input(argv: Sequence[object], data: bytes) -> subprocess.CompletedProcess:
    command = [str(arg) for arg in argv]
    proc = subprocess.run(
        command,
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise CheckError(
            f"command returned {proc.returncode}: {' '.join(command)}\n"
            f"{proc.stdout.decode(errors='replace')}{proc.stderr.decode(errors='replace')}"
        )
    return proc


def files_under(root: Path) -> Dict[Path, bytes]:
    if not root.is_dir():
        raise CheckError(f"missing directory: {root}")
    return {
        path.relative_to(root): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def compare_tree(generated: Path, golden: Path, description: str) -> None:
    generated_files = files_under(generated)
    golden_files = files_under(golden)
    if generated_files.keys() != golden_files.keys():
        missing = sorted(str(path) for path in generated_files.keys() - golden_files.keys())
        extra = sorted(str(path) for path in golden_files.keys() - generated_files.keys())
        raise CheckError(
            f"{description}: file set differs; missing golden={missing}, extra golden={extra}"
        )
    stale = [
        str(path)
        for path in generated_files
        if generated_files[path] != golden_files[path]
    ]
    if stale:
        raise CheckError(f"{description}: stale golden bytes: {stale}")


def load_manifest(repo: Path, manifest_path: Path) -> dict:
    sys.path.insert(0, str(repo / "scripts" / "gates"))
    import check_m6_curated_example_corpus as corpus

    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckError(f"cannot load curated corpus manifest {manifest_path}: {exc}") from exc
    errors = corpus.validate_manifest(raw, repo=repo)
    if errors:
        raise CheckError("curated corpus manifest is invalid: " + "; ".join(errors))
    return manifest


def hydrate_members(repo: Path, manifest: dict):
    sys.path.insert(0, str(repo / "scripts" / "gates"))
    import m6_pack_resolver

    return m6_pack_resolver.resolve_members(manifest, repo=repo)


def scenario_for(domain: Path) -> Path | None:
    scenarios = sorted((domain / "scenario").glob("*.json"))
    if len(scenarios) > 1:
        raise CheckError(
            f"{domain.name}: curated golden generation needs one unambiguous scenario, "
            f"found {len(scenarios)}"
        )
    return scenarios[0] if scenarios else None


def compare_selected(generated: Path, golden: Path, names: Iterable[str], description: str) -> None:
    with tempfile.TemporaryDirectory(prefix="curated-postgres-selected-") as td:
        selected = Path(td)
        for name in names:
            path = generated / name
            if not path.is_file():
                raise CheckError(f"{description}: generator omitted {name}")
            (selected / name).write_bytes(path.read_bytes())
        compare_tree(selected, golden, description)


def compare_ordinary_artifacts(left: Path, right: Path, description: str) -> None:
    """Compare the complete renderer artifact set while ignoring invocation provenance."""
    def observed(directory: Path) -> dict[str, tuple[bytes, str, str]]:
        try:
            manifest = json.loads(
                (directory / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckError(f"{description}: cannot read manifest in {directory}: {exc}")
        entries = manifest.get("artifacts")
        if not isinstance(entries, list):
            raise CheckError(f"{description}: malformed artifact manifest in {directory}")
        result = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise CheckError(f"{description}: malformed artifact entry in {directory}")
            name = Path(str(entry.get("path", ""))).name
            path = directory / name
            digest = entry.get("sha256")
            kind = entry.get("type")
            if (
                not name
                or name in result
                or not path.is_file()
                or not isinstance(digest, str)
                or not isinstance(kind, str)
            ):
                raise CheckError(f"{description}: invalid artifact entry in {directory}")
            result[name] = (path.read_bytes(), digest, kind)
        emitted = {
            path.name
            for path in directory.iterdir()
            if path.is_file() and path.name not in {"diagnostics.json", "manifest.json"}
        }
        if emitted != set(result):
            raise CheckError(
                f"{description}: emitted files differ from manifest in {directory}"
            )
        return result

    if observed(left) != observed(right):
        raise CheckError(f"{description}: ordinary artifact sets or bytes differ")


def diagnostics(directory: Path) -> list[dict]:
    try:
        data = json.loads((directory / "diagnostics.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckError(f"cannot read generator diagnostics in {directory}: {exc}") from exc
    items = data.get("diagnostics")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise CheckError(f"malformed generator diagnostics in {directory}")
    return items


UNSUPPORTED_MESSAGE = re.compile(
    r"^required feature '([^']+)' \(([^)]+)\) is not supported by target '([^']+)'$"
)


def validate_contested_refusal(
    directory: Path, spec: Path, source: Path, profile: Path
) -> dict:
    """Require the architect-approved contested-terminal refusal, not any exit 6."""
    items = diagnostics(directory)
    if len(items) != 1:
        raise CheckError(
            "contested source-only accounting requires exactly one diagnostic, "
            f"found {len(items)}"
        )
    item = items[0]
    match = UNSUPPORTED_MESSAGE.fullmatch(str(item.get("message", "")))
    if (
        item.get("code") != "legality.unsupported_feature"
        or item.get("severity") != "error"
        or match is None
    ):
        raise CheckError("contested source-only accounting has the wrong diagnostic identity")
    feature, primitive, target = match.groups()
    try:
        spec_data = json.loads(spec.read_text(encoding="utf-8"))
        profile_data = json.loads(profile.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckError(f"cannot validate contested refusal origin: {exc}") from exc
    lifecycle = spec_data.get("lifecycle", {})
    terminals = lifecycle.get("terminalStates", {})
    contested_state = terminals.get("contested")
    states = lifecycle.get("states", [])
    contested_origin = any(
        state.get("name") == contested_state
        and state.get("terminal") is True
        and state.get("terminalKind") == "contested"
        for state in states
        if isinstance(state, dict)
    )
    source_text = source.read_text(encoding="utf-8")
    if (
        feature != "terminal:contested"
        or primitive != "terminal projection"
        or target != profile_data.get("profileId")
        or not contested_state
        or not contested_origin
        or re.search(r'\bfallback\s*=\s*"escalate"', source_text) is None
    ):
        raise CheckError(
            "contested source-only accounting does not originate at the approved "
            f"terminal primitive: feature={feature!r}, primitive={primitive!r}, "
            f"target={target!r}, state={contested_state!r}"
        )
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckError(f"cannot read refused-render manifest: {exc}") from exc
    output_files = {
        path.relative_to(directory)
        for path in directory.rglob("*")
        if path.is_file()
    }
    if manifest.get("artifacts") != [] or output_files != {
        Path("diagnostics.json"),
        Path("manifest.json"),
    }:
        raise CheckError(
            "contested refusal emitted renderer artifacts: "
            f"manifest={manifest.get('artifacts')!r}, files={sorted(map(str, output_files))}"
        )
    return {
        "unsupportedFeature": feature,
        "primitive": primitive,
        "sourceTerminalState": contested_state,
    }


def parse_source_only_procedures(schema: Path, procedures: Sequence[Path]) -> None:
    """Load source-only procedures into a real server to exercise PostgreSQL parsing."""
    started = run(
        [
            "docker",
            "run",
            "-d",
            "-e",
            "POSTGRES_PASSWORD=test",
            "-e",
            "POSTGRES_USER=test",
            "-e",
            "POSTGRES_DB=neutrino",
            "postgres:16-alpine",
        ]
    )
    container = started.stdout.strip()
    if not container:
        raise CheckError("docker did not return a PostgreSQL container id")
    psql = [
        "docker",
        "exec",
        "-i",
        container,
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "test",
        "-d",
        "neutrino",
    ]
    try:
        for _ in range(60):
            ready = subprocess.run(
                psql + ["-tAq", "-c", "SELECT 1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise CheckError("PostgreSQL did not become ready for source-only SQL parsing")
        run_input(psql + ["-q"], schema.read_bytes())
        for procedure in procedures:
            run_input(psql + ["-q"], procedure.read_bytes())
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def check_example(repo: Path, gen: Path, profile: Path, work: Path, name: str, member) -> dict:
    domain = member.root
    source = member.source_path
    spec = member.spec_path
    golden = domain / "generated" / "postgres"
    if not source.is_file() or not spec.is_file():
        raise CheckError(f"{name}: missing canonical source or capability-spec")

    example_work = work / name
    shutil.rmtree(example_work, ignore_errors=True)
    example_work.mkdir(parents=True)
    source_spec = example_work / "source-spec"
    run([gen, "--target=capability-spec", source, "-o", source_spec])
    generated_spec = source_spec / "capability-spec.json"
    if generated_spec.read_bytes() != spec.read_bytes():
        raise CheckError(f"{name}: committed capability-spec is stale relative to source")

    scenario = scenario_for(domain)
    from_spec = example_work / "from-spec"
    run(
        [
            gen,
            "--target=postgres",
            "--from-spec",
            f"--profile={profile}",
            spec,
            "-o",
            from_spec,
        ],
    )

    if scenario is None:
        raise CheckError(f"{name}: source-only member reached scenario-bearing path")

    source_render = example_work / "source-render"
    run(
        [
            gen,
            "--target=postgres",
            f"--profile={profile}",
            f"--scenario={scenario}",
            source,
            "-o",
            source_render,
        ]
    )
    expected = ["procedure.sql", "schema.sql", "reconciliation.sql", "run_db_test.sh"]
    compare_selected(
        source_render,
        golden,
        expected,
        f"{name}: source PostgreSQL bundle golden",
    )
    if (source_render / "procedure.sql").read_bytes() != (
        from_spec / "procedure.sql"
    ).read_bytes():
        raise CheckError(f"{name}: source/--from-spec procedure bytes differ")
    if not os.access(golden / "run_db_test.sh", os.X_OK):
        raise CheckError(f"{name}: committed run_db_test.sh is not executable")
    return {"name": name, "classification": "scenario-bearing"}


def check_source_only_with_unsupported_accounting(
    repo: Path, gen: Path, profile: Path, work: Path, name: str, member
) -> dict:
    domain = member.root
    if scenario_for(domain) is not None:
        return check_example(repo, gen, profile, work, name, member)
    source = member.source_path
    spec = member.spec_path
    if not source.is_file() or not spec.is_file():
        raise CheckError(f"{name}: missing canonical source or capability-spec")
    example_work = work / name
    shutil.rmtree(example_work, ignore_errors=True)
    example_work.mkdir(parents=True)
    source_spec = example_work / "source-spec"
    run([gen, "--target=capability-spec", source, "-o", source_spec])
    if (source_spec / "capability-spec.json").read_bytes() != spec.read_bytes():
        raise CheckError(f"{name}: committed capability-spec is stale relative to source")
    from_spec = example_work / "from-spec"
    from_source = example_work / "from-source-spec"
    command = [
        gen,
        "--target=postgres",
        "--from-spec",
        f"--profile={profile}",
        spec,
        "-o",
        from_spec,
    ]
    proc = subprocess.run(
        [str(arg) for arg in command],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    golden = domain / "generated" / "postgres"
    if proc.returncode == 0:
        # A source-only member deliberately has no scenario, so the direct
        # production path is .neu -> freshly emitted capability-spec ->
        # PostgreSQL. Render that live source projection independently from
        # the committed-spec path and require the complete ordinary artifact
        # sets, normalized manifest identities, and bytes to agree.
        run(
            [
                gen,
                "--target=postgres",
                "--from-spec",
                f"--profile={profile}",
                source_spec / "capability-spec.json",
                "-o",
                from_source,
            ]
        )
        compare_ordinary_artifacts(
            from_source,
            from_spec,
            f"{name}: source/from-spec PostgreSQL ordinary artifact parity",
        )
        compare_selected(
            from_source,
            golden,
            ["procedure.sql"],
            f"{name}: source-only PostgreSQL procedure golden",
        )
        return {"name": name, "classification": "source-only-supported"}
    if proc.returncode != 6:
        raise CheckError(
            f"{name}: PostgreSQL source-only render failed with unexpected exit "
            f"{proc.returncode}: {proc.stdout}{proc.stderr}"
        )
    refusal = validate_contested_refusal(from_spec, spec, source, profile)
    if golden.exists():
        raise CheckError(f"{name}: unsupported PostgreSQL member must not carry a golden")
    return {
        "name": name,
        "classification": "source-only-unsupported",
        **refusal,
    }


PROBES = {
    "deleted-golden",
    "stale-golden",
    "removed-manifest-member",
    "wrong-unsupported-feature",
    # The scenario-free supported member carries only procedure.sql. Its golden
    # is never selected by first_golden, so this probe pins it explicitly.
    "source-only-procedure-tamper",
    # A scenario-bearing supported member must retain the complete behavioral
    # bundle. Keeping procedure.sql while deleting schema/reconciliation/runner
    # must not let it collapse into the source-only-supported class.
    "scenario-bundle-procedure-only",
    # The scenario-free unsupported member's exact terminal:contested refusal
    # must carry NO renderer artifact. This probe
    # fabricates a PostgreSQL artifact in the refusal bundle and asserts the
    # no-artifact contract bites.
    "unsupported-fabricated-artifact",
}

def first_golden(manifest: dict, members: dict) -> Path:
    for name in manifest["examples"]:
        golden = members[name].root / "generated" / "postgres"
        if golden.is_dir() and any(golden.glob("*.sql")):
            return golden
    raise CheckError("curated corpus has no PostgreSQL golden for non-vacuous probes")


def run_probe(repo: Path, manifest_path: Path, probe: str) -> int:
    if probe not in PROBES:
        print(f"unknown curated PostgreSQL probe {probe!r}", file=sys.stderr)
        return 2
    try:
        manifest = load_manifest(repo, manifest_path)
        members = hydrate_members(repo, manifest)
        source_only = [
            name for name in manifest["examples"]
            if members[name].scenario_dir is None
        ]
        supported_source_only = [
            name for name in source_only
            if (members[name].root / "generated/postgres/procedure.sql").is_file()
        ]
        unsupported_source_only = [
            name for name in source_only
            if not (members[name].root / "generated/postgres").exists()
        ]
        if len(supported_source_only) != 1 or len(unsupported_source_only) != 1:
            raise CheckError("source-only PostgreSQL dispositions are not uniquely classified")
        if probe == "removed-manifest-member":
            sys.path.insert(0, str(repo / "scripts" / "gates"))
            import check_m6_curated_example_corpus as corpus

            mutated = dict(manifest)
            mutated["examples"] = manifest["examples"][:-1]
            errors = corpus.validate_manifest(corpus.canonical_pretty(mutated), repo=repo)
            if not any(
                "exactly 7 members" in error
                or "membership or variance pairs differ" in error
                for error in errors
            ):
                raise CheckError("removed manifest member did not bite")
        elif probe == "wrong-unsupported-feature":
            name = unsupported_source_only[0]
            domain = members[name].root
            with tempfile.TemporaryDirectory(prefix="curated-postgres-probe-") as td:
                refused = Path(td)
                (refused / "diagnostics.json").write_text(
                    json.dumps(
                        {
                            "diagnostics": [
                                {
                                    "code": "legality.unsupported_feature",
                                    "message": "required feature 'terminal:aborted' "
                                    "(terminal projection) is not supported by target "
                                    "'target.postgres.v1'",
                                    "severity": "error",
                                }
                            ],
                            "ok": False,
                        }
                    ),
                    encoding="utf-8",
                )
                (refused / "manifest.json").write_text(
                    json.dumps({"artifacts": [], "ok": False}), encoding="utf-8"
                )
                try:
                    validate_contested_refusal(
                        refused,
                        domain / "generated" / "capability-spec" / "capability-spec.json",
                        domain / "source" / f"{name}.neu",
                        repo / "examples" / "target-profiles" / "postgres.target-profile.json",
                    )
                except CheckError:
                    pass
                else:
                    raise CheckError("wrong unsupported feature did not bite")
        elif probe == "source-only-procedure-tamper":
            name = supported_source_only[0]
            golden = members[name].root / "generated" / "postgres"
            if not (golden / "procedure.sql").is_file():
                raise CheckError("source-only supported procedure.sql golden missing")
            with tempfile.TemporaryDirectory(prefix="curated-postgres-probe-") as td:
                pristine = Path(td) / "generated"
                shutil.copytree(golden, pristine)
                # Altering procedure.sql must fail the source-only-supported
                # comparison (compare_selected/compare_tree), and deleting it must
                # too — the two forms the architect named.
                for form in ("altered", "deleted"):
                    candidate = Path(td) / form
                    shutil.rmtree(candidate, ignore_errors=True)
                    shutil.copytree(golden, candidate)
                    proc = candidate / "procedure.sql"
                    if form == "altered":
                        proc.write_bytes(proc.read_bytes() + b"\n")
                    else:
                        proc.unlink()
                    try:
                        compare_tree(pristine, candidate, f"deadline-procedure-{form}")
                    except CheckError:
                        continue
                    raise CheckError(f"{form} deadline procedure.sql did not bite")
        elif probe == "scenario-bundle-procedure-only":
            scenario_member = next(
                name
                for name in manifest["examples"]
                if members[name].scenario_dir is not None
            )
            golden = members[scenario_member].root / "generated" / "postgres"
            expected = [
                "procedure.sql",
                "schema.sql",
                "reconciliation.sql",
                "run_db_test.sh",
            ]
            if not all((golden / name).is_file() for name in expected):
                raise CheckError(
                    f"{scenario_member}: committed scenario bundle is incomplete"
                )
            with tempfile.TemporaryDirectory(
                prefix="curated-postgres-procedure-only-"
            ) as td:
                generated = Path(td) / "generated"
                weakened = Path(td) / "procedure-only"
                shutil.copytree(golden, generated)
                weakened.mkdir()
                shutil.copy2(golden / "procedure.sql", weakened / "procedure.sql")
                try:
                    compare_selected(
                        generated,
                        weakened,
                        expected,
                        f"{scenario_member}: scenario bundle weakened to procedure-only",
                    )
                except CheckError:
                    pass
                else:
                    raise CheckError(
                        "scenario-bearing procedure-only weakening did not bite"
                    )
        elif probe == "unsupported-fabricated-artifact":
            name = unsupported_source_only[0]
            domain = members[name].root
            profile = repo / "examples" / "target-profiles" / "postgres.target-profile.json"
            profile_id = json.loads(profile.read_text(encoding="utf-8")).get("profileId")
            with tempfile.TemporaryDirectory(prefix="curated-postgres-probe-") as td:
                refused = Path(td)
                # A refusal whose diagnostic identity is otherwise EXACT (so the
                # probe bites only on the no-artifact contract, not the wrong
                # diagnostic), but which fabricates a PostgreSQL artifact.
                (refused / "diagnostics.json").write_text(
                    json.dumps(
                        {
                            "diagnostics": [
                                {
                                    "code": "legality.unsupported_feature",
                                    "message": "required feature 'terminal:contested' "
                                    "(terminal projection) is not supported by target "
                                    f"'{profile_id}'",
                                    "severity": "error",
                                }
                            ],
                            "ok": False,
                        }
                    ),
                    encoding="utf-8",
                )
                (refused / "procedure.sql").write_text(
                    "-- fabricated PostgreSQL artifact\n", encoding="utf-8"
                )
                (refused / "manifest.json").write_text(
                    json.dumps({"artifacts": ["procedure.sql"], "ok": False}),
                    encoding="utf-8",
                )
                try:
                    validate_contested_refusal(
                        refused,
                        domain / "generated" / "capability-spec" / "capability-spec.json",
                        domain / "source" / f"{name}.neu",
                        profile,
                    )
                except CheckError:
                    pass
                else:
                    raise CheckError("fabricated contested artifact did not bite")
        else:
            golden = first_golden(manifest, members)
            with tempfile.TemporaryDirectory(prefix="curated-postgres-probe-") as td:
                generated = Path(td) / "generated"
                candidate = Path(td) / "golden"
                shutil.copytree(golden, generated)
                shutil.copytree(golden, candidate)
                victim = sorted(candidate.glob("*.sql"))[0]
                if probe == "deleted-golden":
                    victim.unlink()
                else:
                    victim.write_bytes(victim.read_bytes() + b"\n")
                try:
                    compare_tree(generated, candidate, probe)
                except CheckError:
                    pass
                else:
                    raise CheckError(f"{probe} did not bite")
    except CheckError as exc:
        print(f"curated PostgreSQL probe FAILED: {exc}", file=sys.stderr)
        return 2
    print(f"probe-failed-as-expected:{probe}")
    return 1


def probe_failures(repo: Path, manifest_path: Path, runner=run_probe) -> list[str]:
    failures = []
    for probe in sorted(PROBES):
        if runner(repo, manifest_path, probe) != 1:
            failures.append(probe)
    return failures


def selftest(repo: Path, manifest_path: Path) -> int:
    failures = probe_failures(repo, manifest_path)
    if failures:
        print(f"curated PostgreSQL selftest FAILED: {failures}", file=sys.stderr)
        return 1
    injected = sorted(PROBES)[0]

    def one_non_biting(_repo: Path, _manifest: Path, probe: str) -> int:
        return 0 if probe == injected else 1

    if injected not in probe_failures(repo, manifest_path, one_non_biting):
        print(
            "curated PostgreSQL selftest FAILED: aggregate accepted a non-biting probe",
            file=sys.stderr,
        )
        return 1
    print(f"curated PostgreSQL selftest OK ({len(PROBES)} probes fail closed)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--gen", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--real-postgres", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--probe", choices=sorted(PROBES))
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    manifest_path = args.manifest or repo / "docs" / "m6-curated-example-corpus.json"
    if args.probe:
        return run_probe(repo, manifest_path, args.probe)
    if args.selftest:
        return selftest(repo, manifest_path)
    if not args.gen or not args.work or not args.profile:
        parser.error("--gen, --work and --profile are required for the golden gate")
    try:
        manifest = load_manifest(repo, manifest_path)
        members = hydrate_members(repo, manifest)
        args.work.mkdir(parents=True, exist_ok=True)
        counts = {
            "scenario-bearing": 0,
            "source-only-supported": 0,
            "source-only-unsupported": 0,
        }
        classifications = []
        scenario_schema = None
        source_only_procedures = []
        for name in manifest["examples"]:
            entry = check_source_only_with_unsupported_accounting(
                repo, args.gen.resolve(), args.profile.resolve(), args.work, name,
                members[name],
            )
            classification = entry["classification"]
            classifications.append(entry)
            counts[classification] += 1
            if args.real_postgres and classification == "scenario-bearing":
                run(["bash", args.work / name / "source-render" / "run_db_test.sh"])
                if scenario_schema is None:
                    scenario_schema = args.work / name / "source-render" / "schema.sql"
            elif classification == "source-only-supported":
                source_only_procedures.append(
                    args.work / name / "from-spec" / "procedure.sql"
                )
        if args.real_postgres and source_only_procedures:
            if scenario_schema is None:
                raise CheckError(
                    "source-only SQL parsing needs a governed scenario-bearing schema"
                )
            parse_source_only_procedures(scenario_schema, source_only_procedures)
        if sum(counts.values()) != len(manifest["examples"]):
            raise CheckError("covered curated members do not equal manifest membership")
        if counts["scenario-bearing"] < 5:
            raise CheckError("scenario-bearing PostgreSQL coverage fell below five members")
        if counts["source-only-supported"] != 1:
            raise CheckError("expected exactly one source-only supported member")
        if counts["source-only-unsupported"] != 1:
            raise CheckError("expected exactly one source-only unsupported member")
        (args.work / "classification.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "kind": "neutrino.curated-postgres-classification",
                    "members": classifications,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except (CheckError, OSError) as exc:
        print(f"curated PostgreSQL golden gate FAILED: {exc}", file=sys.stderr)
        return 1
    print(
        "curated PostgreSQL golden gate OK: "
        f"{len(manifest['examples'])} manifest members; "
        f"{counts['scenario-bearing']} scenario-bearing full bundles, "
        f"{counts['source-only-supported']} source-only procedures, "
        f"{counts['source-only-unsupported']} source-only unsupported"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
