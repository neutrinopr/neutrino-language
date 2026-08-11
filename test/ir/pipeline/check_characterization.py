"""[43] T9-R0 characterization: solidity/postgres golden + schema-hash bridge vector (no drift). Ported
verbatim from the retired run_cpp_tests.sh [43] block ( S5n). Every deterministic generated source
file for sponsored_offer_agreement + merchant_sponsored_installment byte-matches the committed
domain-major golden (no missing AND no extra artifact; manifest.json/diagnostics.json are the only
allowed non-golden outputs); and the capabilityHash — the Fabric EnvelopeHeader.schema_hash bridge — is
pinned to its exact value AND decodes to exactly 32 bytes.

Usage: check_characterization.py <neutrino-gen> <examples-dir>
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pipeline_inputs import PipelineInputError, resolve_pipeline_inputs

GEN, EXAMPLES = sys.argv[1:3]
REPO = Path(EXAMPLES).resolve().parent
fails = []
tmp = tempfile.mkdtemp(prefix="char43.")
try:
    INPUTS = resolve_pipeline_inputs(REPO)
except PipelineInputError as error:
    print("[43] characterization contract FAILED:", file=sys.stderr)
    print("    FAIL: " + str(error), file=sys.stderr)
    raise SystemExit(1)


def files_under(root):
    out = []
    for dirpath, _, names in os.walk(root):
        for n in names:
            out.append(os.path.relpath(os.path.join(dirpath, n), root))
    return out


def characterize(dom, tgt):
    fixture = INPUTS[dom]
    d = str(fixture.root)
    src = str(fixture.source)
    scn = str(fixture.scenario)
    golden = os.path.join(d, "generated", tgt)
    out = os.path.join(tmp, f"char_{dom}_{tgt}")
    if subprocess.run([GEN, "--target=" + tgt, "--scenario=" + scn, src, "-o", out],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        fails.append(f"gen {tgt} for {dom}")
        return
    # Foundry execution scaffolding (foundry.toml, test/*.t.sol) was re-homed to the
    # Web3 runtime/demo layer by M7_BACKEND_PACKAGE_BOUNDARY_ADR section 9
    # (2026-07-31); the external Solidity package emits compilable sources and its
    # manifest, not scaffolding. The goldens stay committed as the record of that
    # artifact family, but core characterization no longer asserts them here.
    def rehomed_harness(rel):
        return rel == "foundry.toml" or rel.startswith("test/")

    # every committed golden file byte-matches.
    for f in files_under(golden):
        if tgt == "solidity" and rehomed_harness(f):
            continue
        gp, op = os.path.join(golden, f), os.path.join(out, f)
        if not (os.path.isfile(op) and open(gp, "rb").read() == open(op, "rb").read()):
            fails.append(f"{tgt}/{dom}/{f} drifted from the committed golden")
    # any NEW deterministic file must be in the golden set (manifest/diagnostics
    # excluded; the dispatch receipt is per-invocation provenance, not a render).
    for f in files_under(out):
        if f in ("manifest.json", "diagnostics.json", "backend-dispatch-receipt.json"):
            continue
        if not os.path.isfile(os.path.join(golden, f)):
            fails.append(f"{tgt}/{dom} emitted {f}, which is not in the committed golden (extra artifact)")


for tgt in ("solidity", "postgres"):
    characterize("sponsored_offer_agreement", tgt)
    characterize("merchant_sponsored_installment", tgt)

# schema-hash bridge vector: pin the exact capabilityHash AND that it decodes to 32 bytes.
lock = os.path.join(INPUTS["sponsored_offer_agreement"].root,
                    "generated", "slot", "capability.lock")
h = json.load(open(lock))["capabilityHash"]
PIN = "1eda342a1203b264e667ac1c49e1115e82963f1d978afe231cb735bfeb3e4b54"
if not (h == PIN and len(bytes.fromhex(h)) == 32):
    fails.append("schema-hash bridge vector drifted")

if fails:
    print("[43] characterization contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[43] OK: solidity + postgres generated source byte-match committed golden for 2 domains, no "
      "missing AND no extra deterministic artifact; capabilityHash schema-hash bridge vector pinned + "
      "decodes to 32 bytes")
