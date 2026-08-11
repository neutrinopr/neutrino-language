#!/usr/bin/env python3
"""Execute the backend-free core contract end to end, in a fresh isolated build.

WHY THIS EXISTS (). Every part of the core-only contract was already
implemented and correct -- `NEUTRINO_CORE_ONLY`, `cmake/NeutrinoCoreOnly.cmake`,
`check_core_only_export.py` -- but nothing ever RAN it. `NeutrinoCoreOnly.cmake`
is included only under `if(NEUTRINO_CORE_ONLY)`, so the `core-only*` targets and
ctest rows exist only inside a core-only configure, and no Makefile target and no
workflow ever performed that configure. The gate proving "a clean backend-free
core configures, builds and runs with the production backend trees absent" could
therefore only run in a configuration nobody created. Its entrypoint, not its
logic, was the gap: an unexecuted gate reports nothing and rots silently.

This script is that entrypoint, and it is deliberately thin. It adds no new
policy and duplicates no existing check -- it configures, builds, installs and
then calls the checks that already exist, so there is exactly one authority for
what the core export is. What it *does* add is an independent, entrypoint-level
assertion that no backend entered the candidate: `--check-candidate` verifies the
copied candidate tree, and this verifies the CONFIGURED BUILD GRAPH, which is
where a link edge would appear. Those are different failure surfaces, and a
backend can only reach the core through one of them.

REQUIRES A CLEAN TRACKED TREE. The derive step binds the export to the source Git
identity and refuses a dirty tree (`core_export.dirty_source`) -- an export
derived from uncommitted edits would describe a head that does not exist. Commit
first; this is the gate working, not a defect.

Run: `make core-only-verify` (or invoke directly with --llvm-prefix).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


# The production backend libraries. None of these may appear in a core-only
# build graph -- as a link edge, a compiled source, or a target.
FORBIDDEN_LIBRARIES = (
    "NeutrinoBackendSolidity",
    "NeutrinoBackendPostgres",
    "NeutrinoBackendOracle",
)
# Source trees that are backend-owned. A core-only build must compile nothing
# from them.
FORBIDDEN_SOURCE_DIRS = ("lib/backends/",)


class VerifyError(RuntimeError):
    pass


def run(command: list[str], cwd: Path | None = None) -> None:
    print("+ " + " ".join(str(c) for c in command), flush=True)
    completed = subprocess.run(command, cwd=cwd)
    if completed.returncode != 0:
        raise VerifyError(
            f"command failed with exit {completed.returncode}: "
            + " ".join(str(c) for c in command)
        )


def assert_no_backend_in_build_graph(build_dir: Path) -> None:
    """Fail if a backend library or source reached the configured build graph.

    Reads the generated ninja file rather than asking CMake, because the ninja
    file is what will actually be executed: a target that is declared but never
    linked cannot smuggle a backend in, and one that is linked cannot hide.
    """
    ninja = build_dir / "build.ninja"
    if not ninja.is_file():
        raise VerifyError(f"no build.ninja in {build_dir}; configure did not run")
    text = ninja.read_text(encoding="utf-8", errors="replace")

    offenders: list[str] = []
    for library in FORBIDDEN_LIBRARIES:
        # Match the library as a path component or bare token, not as a
        # substring of a comment mentioning it.
        if re.search(rf"(^|[\s/]){re.escape(library)}(\.|[\s/]|$)", text, re.M):
            offenders.append(f"backend library in build graph: {library}")
    for directory in FORBIDDEN_SOURCE_DIRS:
        if re.search(rf"[\s/]{re.escape(directory)}", text):
            offenders.append(f"backend source tree compiled: {directory}")

    if offenders:
        raise VerifyError(
            "the core-only build graph is not backend-free:\n  "
            + "\n  ".join(sorted(set(offenders)))
        )
    print("OK: no backend library or backend source in the core-only build graph")


def assert_install_is_backend_free(prefix: Path) -> None:
    """Fail if an installed artifact names a production backend."""
    offenders = [
        str(path.relative_to(prefix))
        for path in sorted(prefix.rglob("*"))
        if path.is_file()
        and any(library.lower() in path.name.lower() for library in FORBIDDEN_LIBRARIES)
    ]
    if offenders:
        raise VerifyError(
            "backend artifacts were installed into the core prefix:\n  "
            + "\n  ".join(offenders)
        )
    installed = sum(1 for path in prefix.rglob("*") if path.is_file())
    if installed == 0:
        raise VerifyError(f"nothing was installed into {prefix}")
    print(f"OK: {installed} installed files, none naming a production backend")


def verify(source_root: Path, llvm_prefix: Path, keep: bool) -> None:
    mlir_dir = llvm_prefix / "lib/cmake/mlir"
    llvm_dir = llvm_prefix / "lib/cmake/llvm"
    for path in (mlir_dir, llvm_dir):
        if not path.is_dir():
            raise VerifyError(f"missing CMake package dir: {path}")

    workspace = Path(tempfile.mkdtemp(prefix="core-only-verify."))
    build_dir = workspace / "build"
    prefix = workspace / "install"
    print(f"isolated workspace: {workspace}")
    try:
        # 1. Configure a FRESH isolated build with the backend-free core graph.
        #    Fresh matters: a reused tree can inherit a cache in which the
        #    backends were configured, which is exactly what this proves absent.
        run([
            "cmake", "-S", str(source_root), "-B", str(build_dir), "-G", "Ninja",
            f"-DMLIR_DIR={mlir_dir}", f"-DLLVM_DIR={llvm_dir}",
            "-DNEUTRINO_CORE_ONLY=ON", "-DCMAKE_BUILD_TYPE=Release",
        ])

        # 2. The configured graph must already be backend-free -- checked before
        #    building, so a failure names the cause instead of a link error.
        assert_no_backend_in_build_graph(build_dir)

        # 3. Build the core and run the core-only ctest rows (contract validator,
        #    export selftest, runtime check, release-receipt selftest).
        run(["cmake", "--build", str(build_dir), "--target", "core-only", "-j2"])

        # 4. Derive the export from configured facts, then rebuild from the exact
        #    backend-free candidate. `--check-candidate` also refuses any
        #    reach-back from the candidate into the full source tree.
        run(["cmake", "--build", str(build_dir),
             "--target", "core-only-export-check", "-j2"])

        # 5. Install the core component and confirm the prefix is backend-free.
        run(["cmake", "--install", str(build_dir), "--prefix", str(prefix),
             "--component", "NeutrinoCore"])
        assert_install_is_backend_free(prefix)

        print("\ncore-only-verify: PASS "
              "(configured, built, checked, installed; backend-free)")
    finally:
        if keep:
            print(f"workspace kept at {workspace}")
        else:
            shutil.rmtree(workspace, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path,
                        default=Path(__file__).resolve().parents[2])
    parser.add_argument("--llvm-prefix", type=Path,
                        default=os.environ.get("LLVM_PREFIX", ""))
    parser.add_argument("--keep", action="store_true",
                        help="retain the isolated workspace for inspection")
    args = parser.parse_args()
    if not str(args.llvm_prefix):
        parser.error("--llvm-prefix (or LLVM_PREFIX) is required")
    try:
        verify(args.source_root.resolve(), Path(args.llvm_prefix).resolve(),
               args.keep)
    except VerifyError as error:
        print(f"core-only-verify: FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
