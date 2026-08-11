"""[66] M3 sample (): core_document_escrow L1/L2/L3 + branch-compat. Ported verbatim from the retired
run_cpp_tests.sh [66] block ( S5l). L1 lowers; the release + refund L2 sidecars validate and compose
at the boundary; document evidence (bill_of_lading / inspection_certificate / quality_report) is distinct
from proof_of_delivery; bad-evidence / undeclared-timeout / free-form-guard + L3 missing-timeout /
type-mismatch + an incompatible release/refund outcome each fail closed; L3 binds EscrowAgent -> complete.

Usage: check_sample_conditional_escrow.py <scripts-dir> <examples-dir> <neutrino-translate> <neutrino-gen>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m3lib import M3  # noqa: E402

SAMPLE = "core_document_escrow"
HERE = os.path.dirname(os.path.abspath(__file__))
INPUTS = os.path.join(HERE, "Inputs", SAMPLE)
m = M3(*sys.argv[1:5])
m.lower_and_slot_files(SAMPLE,
                       os.path.join(INPUTS, "source", f"{SAMPLE}.neu"),
                       os.path.join(INPUTS, "scenario", f"{SAMPLE}_happy_path.json"))
release = m.l2(f"{SAMPLE}.release.l2.json")
refund = m.l2(f"{SAMPLE}.refund.l2.json")

m.l2_positive(release, "L2 release")
m.l2_positive(refund, "L2 refund")
m.compat_positive(release, refund)

# document evidence, distinct from core_installment_fulfillment's proof_of_delivery.
ev = {e["name"] for e in json.load(open(release))["evidenceRequirements"]}
m.check({"bill_of_lading", "inspection_certificate", "quality_report"} <= ev and "proof_of_delivery" not in ev,
        f"release evidence set unexpected: {sorted(ev)}")

negdir = m.l2("negatives", SAMPLE)
m.l2_exact(os.path.join(negdir, "doc_evidence_bad_shape.l2.json"), "L2-1001")
m.l2_exact(os.path.join(negdir, "undeclared_timeout_param.l2.json"), "L2-1008")
m.l2_exact(os.path.join(negdir, "freeform_guard.l2.json"), "L2-1006")

m.l3_status(m.manifest(f"{SAMPLE}.l3.binding.json"), "complete")
m.l3_invalid(m.manifest("negatives", "cde_missing_required_timeout.l3.binding.json"), "NEU-4002")
m.l3_invalid(m.manifest("negatives", "cde_param_type_mismatch.l3.binding.json"), "NEU-4003")

# branch-compat negative: a VALID single sidecar whose release/refund terminal outcome is incompatible.
bn = m.l2("branch-compat", SAMPLE, "negatives", "outcome_incompatible.refund.l2.json")
m.check(m.run_l2(bn)[1]["ok"] is True, "branch-compat negative should be a valid single sidecar")
m.compat_exact(release, bn, "L2X-2003")

m.finish("66", "L1 lowers; release+refund L2 validate and compose; document evidence distinct from "
               "proof_of_delivery; bad-evidence / undeclared-timeout / free-form-guard + L3 "
               "missing-timeout / type-mismatch + incompatible release/refund outcome fail closed; "
               "L3 EscrowAgent -> complete")
