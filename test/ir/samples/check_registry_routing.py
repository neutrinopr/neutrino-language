"""[62] backend registry routing (). Ported verbatim from the retired run_cpp_tests.sh [62] block
( S5l). Every target from `--list-targets` (>=7) routes through the TargetRegistry to a real emit
whose manifest.json records that target; an unregistered target is refused (non-zero) with an error whose
usage list derives from the registry (names solidity + views) — so target discovery has one source.

Usage: check_registry_routing.py <neutrino-gen> <src.neu> <scenario.json>
"""
import os
import subprocess
import sys
import tempfile

GEN, SRC, SCEN = sys.argv[1:4]
fails = []
tmp = tempfile.mkdtemp(prefix="reg62.")

targets = [t for t in subprocess.run([GEN, "--list-targets"], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL).stdout.decode().splitlines() if t.strip()]
if len(targets) < 7:
    fails.append(f"--list-targets returned {len(targets)} target(s) (want >=7)")

for t in targets:
    od = os.path.join(tmp, "reg_" + t)
    if subprocess.run([GEN, "--target=" + t, "--scenario=" + SCEN, SRC, "-o", od],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        fails.append(f"registered target '{t}' did not emit through the registry")
        continue
    mf = os.path.join(od, "manifest.json")
    if not (os.path.isfile(mf) and f'"target": "{t}"' in open(mf).read()):
        fails.append(f"target '{t}' manifest missing/not routed ({mf})")

# an unregistered target is refused, and the error lists the registered targets (single source).
r = subprocess.run([GEN, "--target=does_not_exist", "--scenario=" + SCEN, SRC, "-o", os.path.join(tmp, "reg_bogus")],
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
out = r.stdout.decode("utf-8", "replace")
if r.returncode == 0:
    fails.append("unknown target 'does_not_exist' was accepted")
elif not ("solidity" in out and "views" in out):
    fails.append("unknown-target error did not derive its list from the registry")

if fails:
    print("[62] registry-routing contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print(f"[62] OK: {len(targets)} registered targets all route through TargetRegistry to a manifest; "
      "unknown target refused with the registry-derived usage list")
