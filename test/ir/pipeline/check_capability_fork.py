"""[20] capability fork: scaffold a new version from an existing source (migration assist). Ported
verbatim from the retired run_cpp_tests.sh [20] block ( S5n). fork_capability.py --bump minor
scaffolds a new .neu (0.1.0 -> 0.2.0) that translates and whose slot capability carries 0.2.0, with a
neutrino.capability-fork provenance manifest; and a non-semver current version is a usage error caught
BEFORE any write (exit 2, no output file).

Usage: check_capability_fork.py <neutrino-gen> <neutrino-translate> <fork_capability.py> <src.neu> <scenario.json>
"""
import os
import subprocess
import sys
import tempfile

GEN, TRANSLATE, FORK, SRC, SCEN = sys.argv[1:6]
fails = []
tmp = tempfile.mkdtemp(prefix="fork20.")


def ok(cmd):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


fork_neu = os.path.join(tmp, "fork.neu")
fork_manifest = os.path.join(tmp, "fork-manifest.json")
if not ok([sys.executable, FORK, "--source", SRC, "--bump", "minor",
           "--out", fork_neu, "--manifest", fork_manifest]):
    fails.append("fork")
else:
    if not ok([TRANSLATE, fork_neu, "-o", os.path.join(tmp, "fork.mlir")]):
        fails.append("forked source did not translate")
    fslot = os.path.join(tmp, "fslot")
    if not ok([GEN, "--target=slot", "--scenario=" + SCEN, fork_neu, "-o", fslot]):
        fails.append("slot gen on fork")
    elif '"capabilityVersion": "0.2.0"' not in open(os.path.join(fslot, "capability.json")).read():
        fails.append("forked capability did not carry 0.2.0")
    if '"kind": "neutrino.capability-fork"' not in open(fork_manifest).read():
        fails.append("fork manifest missing")

# a non-semver current version is a usage error caught BEFORE any write (exit 2, no output file).
devsrc = os.path.join(tmp, "devsrc.neu")
open(devsrc, "w").write('procedure p {\n    trigger t\n    version "dev"\n}\n')
forkdev = os.path.join(tmp, "forkdev.neu")
rc = subprocess.run([sys.executable, FORK, "--source", devsrc, "--version", "1.0.0", "--out", forkdev],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
if rc != 2:
    fails.append(f"non-semver current version exit={rc} (want 2)")
if os.path.exists(forkdev):
    fails.append("fork wrote output despite non-semver failure")

if fails:
    print("[20] capability-fork contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[20] OK: 0.1.0 -> 0.2.0 fork translates; capability carries 0.2.0; provenance recorded; "
      "non-semver -> exit 2, no write")
