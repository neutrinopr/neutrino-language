"""[74] M5 forward sample (): core_promo_campaign L1/L2/L3. Ported verbatim from the retired
run_cpp_tests.sh [74] block ( S5l). L1 balances + lowers and the slot regenerates byte-identically
(determinism); the reimbursement_mismatch L1 negative FAILS to translate (assert balanced -> not
balanced); the L2 sidecar validates tied to the generated primitives, with total-outlay budget +
exactly-one-attribution + no-double-redemption as guards/invariants; over_budget -> L2-1008,
invalid_attribution -> L2-1007, double_redemption -> L2-1008; and L3 binds the Sponsor slot -> complete.

Usage: check_sample_promo_campaign.py <scripts-dir> <examples-dir> <neutrino-translate> <neutrino-gen>
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m3lib import M3  # noqa: E402

NAME = "core_promo_campaign"
HERE = os.path.dirname(os.path.abspath(__file__))
INPUTS = os.path.join(HERE, "Inputs", NAME)
m = M3(*sys.argv[1:5])
slot = m.lower_and_slot_files(NAME,
                              os.path.join(INPUTS, "source", f"{NAME}.neu"),
                              os.path.join(INPUTS, "scenario", f"{NAME}_happy_path.json"))

# committed generated artifacts must regenerate byte-identically (determinism).
if slot:
    for f in ("capability.json", "capability.lock", "binding-topology.json", "operations.json",
              "compensation.json", "transcript.json", "envelope.schema.json"):
        committed = os.path.join(INPUTS, "generated", "slot", f)
        m.check(open(committed, "rb").read() == open(os.path.join(slot, f), "rb").read(),
                f"committed generated slot/{f} drifted from a fresh generation")

# the reimbursement-mismatch L1 negative must FAIL to translate (assert balanced -> not balanced).
neg = os.path.join(INPUTS, "negatives", "reimbursement_mismatch.neu")
if subprocess.run([m.translate, neg, "-o", os.path.join(m.tmp, "spc_neg.mlir")],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
    m.fails.append("reimbursement-mismatch source translated (expected 'not balanced')")

m.l2_positive(m.l2(NAME + ".l2.json"))
negdir = m.l2("negatives", NAME)
m.l2_exact(os.path.join(negdir, "over_budget.l2.json"), "L2-1008")
m.l2_exact(os.path.join(negdir, "invalid_attribution.l2.json"), "L2-1007")
m.l2_exact(os.path.join(negdir, "double_redemption.l2.json"), "L2-1008")

m.l3_status(m.manifest(NAME + ".l3.binding.json"), "complete")

m.finish("74", "L1 balances + lowers, slot regenerates byte-stable; L2 validates tied to the generated "
               "primitives (budget / exactly-one-attribution / no-double-redemption); reimbursement_mismatch "
               "-> not balanced, over_budget -> L2-1008, invalid_attribution -> L2-1007, double_redemption "
               "-> L2-1008; L3 Sponsor -> complete")
