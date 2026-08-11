"""[9] neutrino-bundle: input bundle -> output bundle (agent contract). Ported verbatim from the retired
run_cpp_tests.sh [9] block ( S5n). A valid input bundle produces ok:true + per-target manifests +
input hashes; an unknown target marks the bundle not-ok (non-zero); a malformed target entry is a usage
error (exit 2); a path-traversal target is a usage error (exit 2) that writes nothing outside the output
bundle; and a generator killed by a signal is NOT reported as success — the bundle synthesizes minimal
ok:false manifest/diagnostics (generator.aborted) so an agent following the refs finds the failure, not
a dead link.

Usage: check_bundle.py <neutrino-bundle> <neutrino-gen> <src.neu> <scenario.json>
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

BUNDLE, GEN, SRC, SCEN = sys.argv[1:5]
fails = []
tmp = tempfile.mkdtemp(prefix="bundle9.")
IN = os.path.join(tmp, "in")
os.makedirs(IN)
shutil.copyfile(SRC, os.path.join(IN, "source.neu"))
shutil.copyfile(SCEN, os.path.join(IN, "scenario.json"))


def set_targets(obj):
    open(os.path.join(IN, "target.json"), "w").write(obj)


def run_bundle(out, gen=GEN):
    return subprocess.run([BUNDLE, IN, "-o", out], env=dict(os.environ, NEUTRINO_GEN=gen),
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def read(out, *rel):
    p = os.path.join(out, *rel)
    return open(p).read() if os.path.isfile(p) else None


# valid bundle -> ok:true + per-target manifests + input hashes.
set_targets('{ "targets": ["solidity", "postgres"] }\n')
out = os.path.join(tmp, "out")
if run_bundle(out) != 0:
    fails.append("bundle run failed")
else:
    bj = read(out, "bundle.json") or ""
    if '"ok": true' not in bj:
        fails.append("bundle not ok")
    if not read(out, "solidity", "manifest.json"):
        fails.append("missing solidity manifest")
    if not read(out, "postgres", "manifest.json"):
        fails.append("missing postgres manifest")
    if '"sha256"' not in bj:
        fails.append("bundle missing input hashes")

# an unknown target fails catalog admission before creating the output bundle.
set_targets('{ "targets": ["cobol"] }\n')
out2 = os.path.join(tmp, "out2")
if run_bundle(out2) != 2:
    fails.append("unknown target did not fail catalog admission")
if os.path.exists(out2):
    fails.append("unknown target created an output bundle")

# a malformed target entry -> usage error (exit 2).
set_targets('{ "targets": ["solidity", 123, "postgres"] }\n')
if run_bundle(os.path.join(tmp, "out3")) != 2:
    fails.append("malformed target entry did not exit 2")

# a path-traversal target -> usage error (exit 2), nothing written outside the output bundle.
set_targets('{ "targets": ["../escape"] }\n')
esc = os.path.join(tmp, "escape_probe")
os.makedirs(os.path.join(esc, "out"))
if run_bundle(os.path.join(esc, "out")) != 2:
    fails.append("path-traversal target did not exit 2")
if os.path.exists(os.path.join(esc, "escape")):
    fails.append("wrote outside the output bundle")

# a generator killed by a signal is NOT success; refs resolve to synthesized ok:false.
kgen = os.path.join(tmp, "killgen.sh")
open(kgen, "w").write("#!/usr/bin/env bash\nkill -TERM $$\n")
os.chmod(kgen, os.stat(kgen).st_mode | stat.S_IEXEC)
set_targets('{ "targets": ["solidity"] }\n')
out4 = os.path.join(tmp, "out4")
if run_bundle(out4, gen=kgen) == 0:
    fails.append("signal-killed generator reported success")
if '"ok": false' not in (read(out4, "bundle.json") or ""):
    fails.append("killed generator bundle ok:true")
if not read(out4, "solidity", "manifest.json"):
    fails.append("killed-generator manifest ref dangles")
sd = read(out4, "solidity", "diagnostics.json") or ""
if '"ok": false' not in sd:
    fails.append("synthesized diagnostics not ok:false")
if '"generator.aborted"' not in sd:
    fails.append("synthesized diagnostics missing generator.aborted code")

if fails:
    print("[9] bundle contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[9] OK: ok + manifests; failure/malformed/traversal/signal all fail; crash refs resolve to "
      "ok:false bundle")
