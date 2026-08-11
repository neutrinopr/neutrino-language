"""[5] neutrino-gen writes manifest + diagnostics for a valid scenario. Ported verbatim from the retired
run_cpp_tests.sh [5] block ( S5n). A valid solidity generation writes a manifest.json recording the
target + artifact sha256 hashes, and a diagnostics.json with ok:true.

Usage: check_gen_manifest.py <neutrino-gen> <src.neu> <scenario.json>
"""
import os
import subprocess
import sys
import tempfile

GEN, SRC, SCEN = sys.argv[1:4]
fails = []
out = tempfile.mkdtemp(prefix="gen5.")

if subprocess.run([GEN, "--target=solidity", "--scenario=" + SCEN, SRC, "-o", out],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
    print("[5] FAIL: generation", file=sys.stderr)
    sys.exit(1)

manifest = open(os.path.join(out, "manifest.json")).read()
if '"target": "solidity"' not in manifest:
    fails.append("manifest target")
if '"sha256"' not in manifest:
    fails.append("manifest hashes")
if '"ok": true' not in open(os.path.join(out, "diagnostics.json")).read():
    fails.append("diagnostics ok")

if fails:
    print("[5] gen-manifest contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[5] OK: manifest.json (target + sha256) + diagnostics.json ok")
