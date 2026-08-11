"""[4] neutrino-emit produces the events inspection projection; retired sql/contract fail closed ().
Ported verbatim from the retired run_cpp_tests.sh [4] block ( S5n). The events projection renders
(names MerchantSubsidyDebited); the naive raw-MLIR sql/contract projections are retired — each must fail
closed with the  retirement diagnostic (a neutrino-gen pointer), not emit a pseudo-backend artifact.

Usage: check_emit_projection.py <neutrino-emit> <src.neu>
"""
import subprocess
import sys

EMIT, SRC = sys.argv[1:3]
fails = []


def emit(kind):
    return subprocess.run([EMIT, f"--kind={kind}", SRC], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


if b"MerchantSubsidyDebited" not in emit("events").stdout:
    fails.append("events inspection projection did not render")

for kind in ("sql", "contract"):
    r = emit(kind)
    if r.returncode == 0:
        fails.append(f"--kind={kind} should be retired () but succeeded")
if b"retired ()" not in emit("sql").stdout:
    fails.append("--kind=sql lacks the  retirement diagnostic")

if fails:
    print("[4] emit-projection contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[4] OK: events inspection projection renders; sql/contract retired -> fail closed with a "
      "neutrino-gen pointer")
