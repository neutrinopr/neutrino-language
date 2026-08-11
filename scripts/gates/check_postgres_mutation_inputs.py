#!/usr/bin/env python3
"""Reconcile configured PostgreSQL mutation inputs after package moves ().

The authority is the configured Ninja graph, not a source-tree spelling scan.
Every PostgreSQL mutation command must consume the package-owned production
model or target-node schema.  This catches stale paths after a package move
before Ninja reports the first missing dependency.
"""

from __future__ import annotations

import argparse
import pathlib
import shlex
import tempfile


class CheckError(RuntimeError):
    pass


def _configured_records(build_ninja: pathlib.Path):
    records = []
    current_outputs = ""
    for line in build_ninja.read_text(encoding="utf-8").splitlines():
        if line.startswith("build "):
            current_outputs = line[6:].split(":", 1)[0]
            continue
        if not line.startswith("  COMMAND = ") or (
                "-DSRC=" not in line and "-DTD=" not in line):
            continue
        command = line.removeprefix("  COMMAND = ")
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise CheckError(f"cannot parse configured mutation command: {exc}")
        for option, output_suffix, input_name in (
                ("-DSRC=", "PostgresModel_mutated.cpp", "PostgresModel.cpp"),
                ("-DTD=", "mutated_printer.inc", "PostgresTargetNodes.td")):
            inputs = [arg.removeprefix(option) for arg in argv
                      if arg.startswith(option)]
            if (output_suffix not in current_outputs or not inputs or
                    pathlib.Path(inputs[0]).name != input_name):
                continue
            if len(inputs) != 1:
                raise CheckError(
                    f"{current_outputs}: expected one configured {option[:-1]}, "
                    f"found {len(inputs)}")
            records.append(
                (current_outputs, option.removeprefix("-D").removesuffix("="),
                 pathlib.Path(inputs[0])))
    return records


def check(build_dir: pathlib.Path, source_root: pathlib.Path) -> int:
    build_ninja = build_dir / "build.ninja"
    if not build_ninja.is_file():
        raise CheckError(f"configured Ninja graph is missing: {build_ninja}")

    canonical_model = (
        source_root / "lib/backends/postgres/model/PostgresModel.cpp"
    ).resolve()
    canonical_td = (
        source_root / "lib/backends/postgres/model/PostgresTargetNodes.td"
    ).resolve()
    canonical = {"SRC": canonical_model, "TD": canonical_td}
    for kind, path in canonical.items():
        if not path.is_file():
            raise CheckError(
                f"canonical PostgreSQL {kind} mutation input is missing: {path}")

    records = _configured_records(build_ninja)
    if not records:
        raise CheckError(
            "configured graph contains no PostgreSQL mutation model inputs")

    surfaces = set()
    outputs = set()
    kinds = set()
    for output, kind, source in records:
        identity = (output, kind)
        if identity in outputs:
            raise CheckError(
                f"duplicate configured mutation input: {output} {kind}")
        outputs.add(identity)
        kinds.add(kind)

        resolved = source.resolve()
        if not resolved.is_file():
            raise CheckError(
                f"missing configured PostgreSQL mutation input: {source}")
        if resolved != canonical[kind]:
            raise CheckError(
                f"{output}: configured {kind} is {resolved}, "
                f"expected {canonical[kind]}")

        if "tools/neutrino-gen/" in output:
            surfaces.add("neutrino-gen")
        if "lib/backends/postgres/" in output:
            surfaces.add("backend")

    expected_surfaces = {"backend", "neutrino-gen"}
    if surfaces != expected_surfaces:
        raise CheckError(
            "configured mutation inputs do not cover both governed surfaces: "
            f"found {sorted(surfaces)}")
    if kinds != {"SRC", "TD"}:
        raise CheckError(
            f"configured mutation graph lacks an input kind: {sorted(kinds)}")

    print(
        "PASS: configured PostgreSQL mutation inputs resolve to package model "
        f"sources ({len(records)} configured inputs; "
        "backend + neutrino-gen)")
    return len(records)


def selftest() -> None:
    with tempfile.TemporaryDirectory(prefix="pg-mutation-inputs-") as tmp:
        root = pathlib.Path(tmp)
        source_root = root / "source"
        build_dir = root / "build"
        canonical = (
            source_root / "lib/backends/postgres/model/PostgresModel.cpp"
        )
        canonical.parent.mkdir(parents=True)
        canonical.write_text("// production model\n", encoding="utf-8")
        canonical_td = canonical.with_name("PostgresTargetNodes.td")
        canonical_td.write_text("// target nodes\n", encoding="utf-8")
        build_dir.mkdir()

        def graph(source: pathlib.Path) -> str:
            return "\n".join([
                "build tools/neutrino-gen/test/a/PostgresModel_mutated.cpp: "
                f"CUSTOM_COMMAND {source}",
                "  COMMAND = cmake "
                f"-DSRC={source} "
                "-DOUT=tools/neutrino-gen/test/a/PostgresModel_mutated.cpp "
                "-P gen_mutated_postgres_model_tu.cmake",
                "",
                "build tools/neutrino-gen/test/a/mutated_printer.inc: "
                f"CUSTOM_COMMAND {canonical_td}",
                "  COMMAND = python generator.py "
                f"-DTD={canonical_td} "
                "-o tools/neutrino-gen/test/a/mutated_printer.inc",
                "",
                "build lib/backends/postgres/test/b/"
                "PostgresModel_mutated.cpp: "
                f"CUSTOM_COMMAND {canonical}",
                "  COMMAND = cmake "
                f"-DSRC={canonical} "
                "-DOUT=lib/backends/postgres/test/b/"
                "PostgresModel_mutated.cpp "
                "-P gen_mutated_postgres_model_tu.cmake",
                "",
            ])

        ninja = build_dir / "build.ninja"
        ninja.write_text(graph(canonical), encoding="utf-8")
        check(build_dir, source_root)

        obsolete = (
            source_root / "lib/backends/postgres/provider/PostgresModel.cpp"
        )
        ninja.write_text(graph(obsolete), encoding="utf-8")
        try:
            check(build_dir, source_root)
        except CheckError as exc:
            if "missing configured PostgreSQL mutation input" not in str(exc):
                raise AssertionError(
                    f"obsolete-path probe failed for the wrong reason: {exc}")
        else:
            raise AssertionError(
                "obsolete PostgreSQL mutation source path was accepted")

    print("PASS: obsolete configured mutation-source probe failed as expected")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=pathlib.Path)
    parser.add_argument("--source-root", type=pathlib.Path)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    try:
        if args.selftest:
            selftest()
            return 0
        if args.build_dir is None or args.source_root is None:
            parser.error("--build-dir and --source-root are required")
        check(args.build_dir.resolve(), args.source_root.resolve())
    except CheckError as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
