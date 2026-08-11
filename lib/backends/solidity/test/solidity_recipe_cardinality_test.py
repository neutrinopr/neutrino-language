#!/usr/bin/env python3
"""A deleted nested signature must make the real recipe generator fail."""

import argparse
import pathlib
import subprocess
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tblgen", required=True)
    args = parser.parse_args()
    repo = pathlib.Path(args.repo)
    source = (
        repo / "lib/backends/solidity/recipes/SolidityIdiomRecipes.td"
    ).read_text()
    needle = '              Emit<"GuardAcceptedExecutionClaimSignature", []>\n'
    if source.count(needle) != 1:
        raise SystemExit("signature mutation anchor drift")
    mutated = source.replace(needle, "", 1)
    with tempfile.TemporaryDirectory() as directory:
        td = pathlib.Path(directory) / "SolidityIdiomRecipes.td"
        out = pathlib.Path(directory) / "solidity_recipes.inc"
        td.write_text(mutated)
        proc = subprocess.run(
            [
                "python3",
                str(repo / "scripts/generators/gen_backend_idiom_recipes.py"),
                "--td",
                str(td),
                "--tblgen",
                args.tblgen,
                "-I",
                str(repo / "lib/backends"),
                "--symbol",
                "solidity",
                "-o",
                str(out),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    if proc.returncode == 0:
        raise SystemExit("deleted signature incorrectly passed generation")
    if "cardinality" not in proc.stderr:
        raise SystemExit("mutation failed for the wrong reason:\n" + proc.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
