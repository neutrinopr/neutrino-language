"""[75d] M5 S3 (): evidence-anchor scorecard — the 2 M5-expressible shapes compile through the
capability-spec path (byte-stable), are legality-green, and the render gap is proven fail-closed. Ported
verbatim from the retired run_cpp_tests.sh [75d] block ( S5n). The scorecard gate passes (expressible
== the classification M5 set; capability-specs validate + legality-green; M6 not translated); each
committed capability-spec regenerates byte-identically from source alone; and the value-less
evidence-anchor render gap fails closed with the scorecard's expectedGenError, emitting NO artifact for
EVERY renderGap.target.

Usage: check_m5_scorecard.py <neutrino-gen> <examples-dir>
"""
import json
import os
import re
import subprocess
import sys
import tempfile

GEN, EXAMPLES = sys.argv[1:3]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []
tmp = tempfile.mkdtemp(prefix="scorecard75d.")
SC = os.path.join(EXAMPLES, "m5-scorecard")

# the scorecard gate.
if subprocess.run([sys.executable, os.path.join(REPO, "scripts", "samples", "check_m5_scorecard.py")],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
    fails.append("m5 scorecard gate")

scorecard = json.load(open(os.path.join(SC, "scorecard.json")))
expected_gen_err = scorecard["renderGap"]["expectedGenError"]
rg_targets = scorecard["renderGap"]["targets"]
# Targets the tool exposes that the CORE registry does not declare are externally
# packaged ( retired core Solidity dispatch); they own their target profile.
def _external_targets():
    reg = os.path.join(REPO, "include", "Neutrino", "TargetRegistry.def")
    try:
        declared = set(re.findall(r'NEUTRINO_TARGET\(\s*"([^"]+)"', open(reg).read()))
    except OSError:
        return set()
    listed = subprocess.run([GEN, "--list-targets"], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL).stdout.decode().split()
    return {t for t in listed if t not in declared} if declared else set()


EXT = {"solidity": "sol", "postgres": "sql"}

for d in ("hash_anchor", "merkle_evidence_anchor"):
    src = os.path.join(SC, d, "source", d + ".neu")
    scn = os.path.join(SC, d, "scenario", d + "_happy.json")
    # the committed capability-spec regenerates byte-identically from source alone.
    out = os.path.join(tmp, "sc_" + d)
    if subprocess.run([GEN, "--target=capability-spec", src, "-o", out],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        fails.append(f"capability-spec emit {d}")
        continue
    committed = os.path.join(SC, d, "generated", "capability-spec", "capability-spec.json")
    if open(os.path.join(out, "capability-spec.json"), "rb").read() != open(committed, "rb").read():
        fails.append(f"{d} capability-spec.json drifted from committed")
    # RENDER GAP: a value-less evidence anchor is legal but does NOT render — every declared target
    # fails closed with the scorecard's expectedGenError and emits no target artifact.
    for t in rg_targets:
        ext = EXT.get(t)
        if ext is None:
            fails.append(f"renderGap target '{t}' has no known artifact extension in [75d]")
            continue
        tout = os.path.join(tmp, f"sc_{t}_{d}")
        # An externally packaged target is bound to its verified package profile and
        # REFUSES a caller-supplied --profile, so passing one here would surface the
        # override refusal instead of the render gap this check is about. Core
        # targets still take their committed profile.
        profile = ([] if t in _external_targets() else
                   ["--profile=" + os.path.join(EXAMPLES, "target-profiles",
                                                t + ".target-profile.json")])
        r = subprocess.run([GEN, "--target=" + t, "--scenario=" + scn, *profile,
                            src, "-o", tout], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if expected_gen_err not in r.stderr.decode("utf-8", "replace"):
            fails.append(f"{d}/{t} render-gap error changed — expected the scorecard's '{expected_gen_err}'")
        if os.path.isdir(tout) and any(f.endswith("." + ext) for _, _, fs in os.walk(tout) for f in fs):
            fails.append(f"{d}/{t} unexpectedly produced a .{ext} (render gap closed for {t}?)")

if fails:
    print("[75d] m5-scorecard contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[75d] OK: HashAnchor + MerkleEvidenceAnchor capability-specs regenerate byte-identically + are "
      "legality-green; the value-less evidence-anchor render gap fails closed with the scorecard's "
      "expectedGenError and emits NO artifact for every renderGap.target; M6 frontier named + not translated")
