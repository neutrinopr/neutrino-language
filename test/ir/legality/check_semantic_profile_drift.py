""": the committed target-profile files' `semanticProfile` blocks match the
C++ BUILTIN (the single source of truth, via --dump-semantic-profile) AND pin the
published semantic-profile contract version (--version-json semanticProfileVersion).
Ties files <-> builtin <-> the compatibility surface to one constant, fail-closed.

Usage: check_semantic_profile_drift.py <neutrino-gen> <examples-dir>
"""
import json
import os
import subprocess
import sys

GEN, EXAMPLES = sys.argv[1], sys.argv[2]
fails = []


def run(*args):
    r = subprocess.run([GEN, *args], capture_output=True, text=True)
    return r.returncode, r.stdout


rc, out = run("--version-json")
published = json.loads(out).get("semanticProfileVersion") if rc == 0 else None
if not isinstance(published, int):
    fails.append("--version-json did not publish an integer semanticProfileVersion")

for target in ("solidity", "postgres"):
    path = os.path.join(EXAMPLES, "target-profiles", f"{target}.target-profile.json")
    sp = json.load(open(path)).get("semanticProfile")
    if not sp:
        fails.append(f"{target}: committed profile carries no semanticProfile block")
        continue
    if sp.get("version") != published:
        fails.append(f"{target}: semanticProfile.version {sp.get('version')} != "
                     f"published semanticProfileVersion {published}")
    rc, out = run(f"--dump-semantic-profile={target}")
    builtin = json.loads(out) if rc == 0 else None
    if sp != builtin:
        fails.append(f"{target}: committed semanticProfile drifted from the C++ builtin\n"
                     f"  file    = {sp}\n  builtin = {builtin}")

if fails:
    print("[] FAIL semantic-profile drift:\n" + "\n".join(fails), file=sys.stderr)
    sys.exit(1)
print("[] OK: committed profiles match the C++ builtin (--dump-semantic-profile) "
      "and pin the published semanticProfileVersion (--version-json)")
