"""[68] M3 sample: regulated-evidence L1/L2/L3 contract (test-only synthetic fixture).

L1 lives under test/ir/samples/Inputs/ (outside live examples/domains discovery).
L2/L3 live under examples/l2-domain-semantics and examples/binding-manifests with the
same synthetic identity. Preserves clinical_data/provenance/signature evidence set
and L2/L3 diagnostic codes without naming any externalized production domain.

Usage: check_sample_clinical.py <scripts-dir> <examples-dir> <neutrino-translate> <neutrino-gen>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m3lib import M3  # noqa: E402

SAMPLE = "core_regulated_evidence_sample"
HERE = os.path.dirname(os.path.abspath(__file__))
INPUTS = os.path.join(HERE, "Inputs", SAMPLE)

m = M3(*sys.argv[1:5])
src = os.path.join(INPUTS, "source", f"{SAMPLE}.neu")
scen = os.path.join(INPUTS, "scenario", f"{SAMPLE}_happy_path.json")
m.lower_and_slot_files(SAMPLE, src, scen)
sidecar = m.l2(f"{SAMPLE}.l2.json")
m.l2_positive(sidecar)

ev = {e["name"] for e in json.load(open(sidecar))["evidenceRequirements"]}
m.check({"clinical_data", "provenance", "signature"} <= ev
        and "proof_of_delivery" not in ev and "bill_of_lading" not in ev,
        f"clinical evidence set unexpected: {sorted(ev)}")

negdir = m.l2("negatives", SAMPLE)
m.l2_exact(os.path.join(negdir, "concern_profile_metadata_unsupported.l2.json"), "L2-1001")
m.l2_exact(os.path.join(negdir, "evidence_clinical_data_bad_shape.l2.json"), "L2-1001")
m.l2_exact(os.path.join(negdir, "undeclared_consent_param.l2.json"), "L2-1008")
m.l2_exact(os.path.join(negdir, "freeform_invariant.l2.json"), "L2-1006")

m.l3_status(m.manifest(f"{SAMPLE}.l3.binding.json"), "complete")
m.l3_invalid(m.manifest("negatives", "cres_missing_required_consent.l3.binding.json"), "NEU-4002")
m.l3_invalid(m.manifest("negatives", "cres_profile_mismatch.l3.binding.json"), "NEU-3002")

m.finish("68", "L1 lowers; L2 validates with clinical_data/provenance/signature evidence; "
               "concern-profile-metadata / bad-evidence / undeclared-param / free-form-invariant + L3 "
               "missing-consent / profile-mismatch fail closed; L3 Verifier -> complete")
