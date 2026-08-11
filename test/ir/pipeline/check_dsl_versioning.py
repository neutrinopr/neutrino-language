"""[19] DSL versioning: a declared version flows source -> IR -> capability identity (default 0.1.0).
Ported verbatim from the retired run_cpp_tests.sh [19] block ( S5n). A declared `version "9.9.9"`
reaches the IR (version attribute) and the slot capability identity (capabilityVersion); an undeclared
version defaults to 0.1.0; a non-SemVer version is rejected at the frontend AND at the ProcedureOp IR
verifier (a hand-written .mlir cannot fail open); and a half-quoted version (one stray quote) is rejected,
not silently normalized.

Usage: check_dsl_versioning.py <neutrino-gen> <neutrino-translate> <neutrino-opt> <src.neu> <scenario.json>
"""
import os
import re
import subprocess
import sys
import tempfile

GEN, TRANSLATE, OPT, SRC, SCEN = sys.argv[1:6]
fails = []
tmp = tempfile.mkdtemp(prefix="ver19.")
PROC = re.compile(r"^procedure .*\{")


def inject_version(text, version_line):
    """Append a version line after the `procedure ... {` header (the awk '1; /.../{print}' shape)."""
    out = []
    for line in text.splitlines():
        out.append(line)
        if PROC.match(line):
            out.append(version_line)
    return "\n".join(out) + "\n"


def write(name, content):
    p = os.path.join(tmp, name)
    open(p, "w").write(content)
    return p


def ok(cmd):
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


src_text = open(SRC).read()

# declared 9.9.9 flows to IR + capability.
ver_neu = write("ver.neu", inject_version(src_text, '    version "9.9.9"'))
ver_mlir = os.path.join(tmp, "ver.mlir")
if not ok([TRANSLATE, ver_neu, "-o", ver_mlir]):
    fails.append("versioned source did not translate")
elif 'version = "9.9.9"' not in open(ver_mlir).read():
    fails.append("version attribute missing from IR")
vslot = os.path.join(tmp, "vslot")
if not ok([GEN, "--target=slot", "--scenario=" + SCEN, ver_neu, "-o", vslot]):
    fails.append("slot gen on versioned source")
elif '"capabilityVersion": "9.9.9"' not in open(os.path.join(vslot, "capability.json")).read():
    fails.append("declared version did not reach the capability identity")

# undeclared defaults to 0.1.0.
dslot = os.path.join(tmp, "dslot")
subprocess.run([GEN, "--target=slot", "--scenario=" + SCEN, SRC, "-o", dslot],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
if '"capabilityVersion": "0.1.0"' not in open(os.path.join(dslot, "capability.json")).read():
    fails.append("undeclared version did not default to 0.1.0")

# non-SemVer rejected at the frontend.
badver = write("badver.neu", inject_version(src_text, '    version "dev"'))
if ok([TRANSLATE, badver, "-o", os.path.join(tmp, "badver.mlir")]):
    fails.append("frontend accepted a non-SemVer version")

# non-SemVer rejected at the IR verifier (hand-written .mlir).
if os.path.isfile(ver_mlir):
    badver_hand = write("badver_hand.mlir", open(ver_mlir).read().replace('version = "9.9.9"', 'version = "dev"'))
    if ok([OPT, badver_hand]):
        fails.append("IR verifier accepted a non-SemVer version (fail open)")

# half-quoted version (one stray quote) rejected.
halfver = write("halfver.neu", inject_version(src_text, '    version "1.2.3'))
if ok([TRANSLATE, halfver, "-o", os.path.join(tmp, "halfver.mlir")]):
    fails.append("frontend accepted a half-quoted version")

if fails:
    print("[19] dsl-versioning contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[19] OK: declared 9.9.9 flows to IR + capability; undeclared defaults to 0.1.0; non-SemVer + "
      "half-quoted rejected at frontend; non-SemVer rejected at IR verifier")
