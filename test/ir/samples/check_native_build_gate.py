"""[69] M3 native build gate (). Ported verbatim from the retired run_cpp_tests.sh [69] block (
S5l). A claimed generated native-code artifact must build with its native toolchain, and committed
native-target code may not be mislabelled as non-native. The committed portfolio passes the --run gate
(no committed native-target artifacts today, so no solc needed); --summary-out creates its parent dir +
summary; a committed .sol classified non-native is rejected; and a native-validated-but-UNCOMPILABLE .sol
fails the --run gate deterministically (broken Solidity if solc is present, fail-closed if absent).

Usage: check_native_build_gate.py <native_build_gate.py> <examples-dir>
"""
import os
import subprocess
import sys
import tempfile

NBG, EXAMPLES = sys.argv[1:3]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []
tmp = tempfile.mkdtemp(prefix="nbg69.")
PORT = "examples/m3-sample-portfolio.json"


def run(*args):
    return subprocess.run([sys.executable, NBG, *args],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


# the REAL gate runs --run (compiles committed native-target code); the committed portfolio passes.
if run("--run", "--repo-root", REPO, "--portfolio", PORT) != 0:
    fails.append("native build gate (--run) rejected the committed portfolio")

# --summary-out into a not-yet-existing dir must create the parent + emit the summary.
summary = os.path.join(tmp, "nbg_sub", "native-build-summary.json")
if run("--run", "--repo-root", REPO, "--portfolio", PORT, "--summary-out", summary) != 0 or not os.path.isfile(summary):
    fails.append("native build gate --summary-out did not create its parent dir / summary")


def temp_repo(sol_name, sol_body, classification, validator):
    root = tempfile.mkdtemp(prefix="nbg69r.")
    os.makedirs(os.path.join(root, "gen"))
    open(os.path.join(root, "gen", sol_name), "w").write(sol_body)
    open(os.path.join(root, "portfolio.json"), "w").write(
        '{ "kind": "neutrino.m3-sample-portfolio", "schemaVersion": 1, "samples": [\n'
        '  { "id": "x", "status": "current-valid", "validation": [\n'
        f'    {{ "path": "gen/{sol_name}", "classification": "{classification}", "validator": "{validator}",'
        ' "gateIssue": "urn:neutrino:gate:native-build-v1" } ] } ] }\n')
    return root


# fail-closed: a committed native-target file (.sol) classified as non-native must be rejected.
r1 = temp_repo("X.sol", "// SPDX-License-Identifier: MIT\npragma solidity ^0.8.0;\ncontract X {}\n",
               "future-profile-deferred", "none")
if run("--repo-root", r1, "--portfolio", "portfolio.json") == 0:
    fails.append("native build gate accepted committed Solidity classified as future-profile-deferred")

# fail-closed: a native-validated but UNCOMPILABLE .sol must fail the --run gate (solc present or not).
r2 = temp_repo("Broken.sol", "pragma solidity ^0.8.0;\ncontract Broken { thisIsNotSolidity }\n",
               "native-validated", "solc")
if run("--run", "--repo-root", r2, "--portfolio", "portfolio.json") == 0:
    fails.append("native build gate (--run) accepted an uncompilable native-validated Solidity artifact")

if fails:
    print("[69] native-build-gate contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[69] OK: committed portfolio passes the --run gate; a committed .sol mislabelled non-native is "
      "rejected; a native-validated-but-uncompilable .sol fails the --run gate")
