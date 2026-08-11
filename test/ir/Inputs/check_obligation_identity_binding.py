""" P1-1 witness: an obligation is bound into the COORDINATION IDENTITY — the
replay keyClaim the reference evaluator (and every rail) derives — not only into
the capability-spec hash. Stripping the obligation op MUST change the key claim;
if it does not, the identity does not bind the undertaking and a replay/execution
claim would ignore it (exactly the hole the R1b review flagged).

Usage: check_obligation_identity_binding.py <neutrino-gen> <src.mlir> <scenario.json>
"""
import json
import os
import subprocess
import sys
import tempfile

GEN, SRC, SCEN = sys.argv[1:4]
tmp = tempfile.mkdtemp(prefix="oblid811.")


def key_claim(src):
    out = os.path.join(tmp, os.path.basename(src) + ".trace")
    r = subprocess.run([GEN, "--target=coordination-trace", "--scenario=" + SCEN, src, "-o", out],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode:
        sys.exit("trace failed for " + src + "\n" + r.stderr.decode("utf-8", "replace"))
    t = json.load(open(os.path.join(out, "coordination-trace.json")))
    return sorted(t["nextState"]["keyClaim"].values())


with_ob = key_claim(SRC)
without_src = os.path.join(tmp, "no_obligation.mlir")
open(without_src, "w").write(
    "\n".join(ln for ln in open(SRC).read().splitlines() if "neutrino.obligation" not in ln))
without_ob = key_claim(without_src)

if with_ob == without_ob:
    sys.exit("FAIL: the coordination identity does NOT bind the obligation — the replay "
             "keyClaim is identical with and without the obligation op (%s)" % with_ob)
print("OK: obligation bound into the coordination identity — keyClaim with=%s without=%s"
      % (with_ob, without_ob))
