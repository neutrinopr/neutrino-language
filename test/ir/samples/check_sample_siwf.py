"""[63] M3 sample (): core_installment_fulfillment L1/L2/L3. Ported verbatim from the
retired run_cpp_tests.sh [63] block ( S5l). L1 lowers; the L2 sidecar validates (proof_of_delivery
declared as an evidence requirement — M4 owns admission); L2 bad-evidence-shape / undeclared-param and
L3 missing-required / param-not-in-L2 fail closed; L3 binds the Issuer slot -> status complete.

Usage: check_sample_siwf.py <scripts-dir> <examples-dir> <neutrino-translate> <neutrino-gen>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m3lib import M3  # noqa: E402

m = M3(*sys.argv[1:5])
SAMPLE = "core_installment_fulfillment"
HERE = os.path.dirname(os.path.abspath(__file__))
INPUTS = os.path.join(HERE, "Inputs", SAMPLE)
m.lower_and_slot_files(SAMPLE, os.path.join(INPUTS, "source", f"{SAMPLE}.neu"),
                       os.path.join(INPUTS, "scenario", f"{SAMPLE}_happy_path.json"))
m.l2_positive(m.l2("core_installment_fulfillment.l2.json"))
negdir = m.l2("negatives", "core_installment_fulfillment")
m.l2_exact(os.path.join(negdir, "evidence_proof_of_delivery_bad_shape.l2.json"), "L2-1001")
m.l2_exact(os.path.join(negdir, "undeclared_parameter.l2.json"), "L2-1008")
m.l3_status(m.manifest("core_installment_fulfillment.l3.binding.json"), "complete")
m.l3_invalid(m.manifest("negatives", "siwf_missing_required_param.l3.binding.json"), "NEU-4002")
m.l3_invalid(m.manifest("negatives", "siwf_param_not_in_l2.l3.binding.json"), "NEU-4001")
m.finish("63", "L1 lowers; L2 validates (proof_of_delivery evidence requirement); bad-evidence-shape / "
               "undeclared-param + L3 missing-required / param-not-in-L2 fail closed; L3 Issuer -> complete")
