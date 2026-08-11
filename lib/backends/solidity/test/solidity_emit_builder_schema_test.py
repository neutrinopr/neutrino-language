#!/usr/bin/env python3
"""Prove a target-node schema change cannot retain a stale Emit builder ABI."""

import argparse
import pathlib
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tblgen", required=True)
    args = parser.parse_args()

    repo = pathlib.Path(args.repo)
    source = (
        repo / "lib/backends/solidity/model/SolidityTargetNodes.td"
    ).read_text(encoding="utf-8")
    source = source.replace(
        "def Require    : SolNode<",
        'def FSchemaProbe : PrinterField<"schemaProbe", 2>;\n'
        "def Require    : SolNode<",
        1,
    ).replace(
        "[FCondition, FMessage], /*generated=*/1> {",
        "[FCondition, FMessage, FSchemaProbe], /*generated=*/1> {",
        1,
    )
    if source.count("FSchemaProbe") != 2:
        raise SystemExit("schema mutation did not apply exactly once")

    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp)
        td = work / "SolidityTargetNodes.td"
        td.write_text(source, encoding="utf-8")
        command = [
            sys.executable,
            str(repo / "scripts/generators/backend_recipe_gen.py"),
            "--profile",
            "solidity-emit-builders",
            "--td",
            str(td),
            "--tblgen",
            args.tblgen,
            "-I",
            str(repo / "lib/backends"),
            "--decls",
            str(work / "decls.inc"),
            "--defs",
            str(work / "defs.inc"),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        output = result.stdout + result.stderr
        if result.returncode == 0:
            raise SystemExit("added schema field retained a stale builder ABI")
        if "BuilderOrder/schema mismatch" not in output:
            raise SystemExit(
                "schema mutation failed outside the builder ABI coupling:\n"
                + output
            )

    print("PASS: added scalar field invalidates stale generated builder ABI")


if __name__ == "__main__":
    main()
