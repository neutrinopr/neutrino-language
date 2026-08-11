"""[70] M3 sample (): core_hybrid_compute_sample L1/L2/L3. Ported verbatim from the retired
run_cpp_tests.sh [70] block ( S5l). L1 lowers; the L2 sidecar validates with hybrid evidence
(input_hash / compute_output / verification_proof), distinct from the strategy  samples; L3 status is
'deferred' (EVM core concrete + conventional jvm adapters deferred); missing-core / orphan-adapter /
assurance-degraded + L2 bad-evidence / undeclared-param fail closed; and the deferred-exemption is
SCOPED — a CONCRETE jvm binding under the evm.v1 profile still fails NEU-3002.

Usage: check_sample_pay_for_compute.py <scripts-dir> <examples-dir> <neutrino-translate> <neutrino-gen>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m3lib import M3  # noqa: E402

m = M3(*sys.argv[1:5])
SAMPLE = "core_hybrid_compute_sample"
HERE = os.path.dirname(os.path.abspath(__file__))
INPUTS = os.path.join(HERE, "Inputs", SAMPLE)
m.lower_and_slot_files(SAMPLE, os.path.join(INPUTS, "source", f"{SAMPLE}.neu"),
                       os.path.join(INPUTS, "scenario", f"{SAMPLE}_happy_path.json"))
sidecar = m.l2("core_hybrid_compute_sample.l2.json")
m.l2_positive(sidecar)

ev = {e["name"] for e in json.load(open(sidecar))["evidenceRequirements"]}
m.check({"input_hash", "compute_output", "verification_proof"} <= ev
        and "proof_of_delivery" not in ev and "clinical_data" not in ev,
        f"hybrid evidence set unexpected: {sorted(ev)}")

negdir = m.l2("negatives", "core_hybrid_compute_sample")
m.l2_exact(os.path.join(negdir, "evidence_bad_shape.l2.json"), "L2-1001")
m.l2_exact(os.path.join(negdir, "undeclared_param.l2.json"), "L2-1008")

m.l3_status(m.manifest("core_hybrid_compute_sample.l3.binding.json"), "deferred")
m.l3_invalid(m.manifest("negatives", "chc_missing_evm_core_binding.l3.binding.json"), "NEU-1004")
m.l3_invalid(m.manifest("negatives", "chc_orphan_adapter_binding.l3.binding.json"), "NEU-1003")
m.l3_invalid(m.manifest("negatives", "chc_settlement_assurance_degraded.l3.binding.json"), "NEU-2001")

# deferred-exemption is SCOPED: a CONCRETE conventional (jvm) binding under evm.v1 must still fail
# NEU-3002 — only deferred bindings (runtime/profile not yet pinned) are exempt.
man = json.load(open(m.manifest("core_hybrid_compute_sample.l3.binding.json")))
for b in man["bindings"]:
    if b["participantId"] == "Processor":
        b.pop("deferred", None)
concrete = os.path.join(m.tmp, "chc_concrete.l3.json")
json.dump(man, open(concrete, "w"))
rc, d = m.run_l3(concrete)
codes = {x["code"] for x in d["diagnostics"]} if d else set()
m.check(rc == 1 and d and d["ok"] is False and "NEU-3002" in codes,
        f"concrete jvm under evm.v1 must fail NEU-3002: rc={rc} codes={sorted(codes)}")

m.finish("70", "L1 lowers; L2 validates with input_hash/compute_output/verification_proof evidence; "
               "L3 status deferred (EVM core concrete + jvm adapters deferred); missing-core / "
               "orphan-adapter / assurance-degraded + L2 bad-evidence / undeclared-param fail closed; "
               "a concrete jvm binding under evm.v1 still fails NEU-3002")
