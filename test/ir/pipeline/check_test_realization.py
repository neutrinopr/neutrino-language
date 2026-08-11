"""[79] M5 WP2 (): test-realization companion — folded once, byte-stable, OUTSIDE the
capabilityHash. Ported verbatim from the retired run_cpp_tests.sh [79] block (). The committed
fixture matches the normative test-realization.schema.json (required set / consts / hash pattern) and
the companion regenerates byte-identically from (source, scenario); it carries every input/compute/event/
ledger case the backends derive; its capabilityHash is INVARIANT under a scenario-only change and EQUALS
the spec's source-alone capabilityHash; the stdlib validator mirrors the schema; every committed
realization fixture (nr>=10) regenerates + validates + hash-cross-checks its domain's spec; eventChain is
the IR-derived choreography even without expect.events; and the validator fails closed on a tampered
reference (realization.hash_mismatch) and an unknown field (realization.unknown_field).

Usage: check_test_realization.py <neutrino-gen> <examples-dir>
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from pipeline_inputs import (PipelineInputError, committed_realization_fixtures,
                             resolve_pipeline_inputs)

GEN, EXAMPLES = sys.argv[1:3]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
GENDIR = tempfile.mkdtemp(prefix="tr79.")
TRV = os.path.join(REPO, "scripts", "validators", "validate_test_realization.py")

fails = []


def fail(msg):
    print("[79] FAIL: " + msg, file=sys.stderr)
    sys.exit(1)

try:
    INPUTS = resolve_pipeline_inputs(Path(REPO))
except PipelineInputError as error:
    fail(str(error))
MSI_FIXTURE = INPUTS["merchant_sponsored_installment"]
MSI = str(MSI_FIXTURE.root)
MSISRC = str(MSI_FIXTURE.source)
MSISC = str(MSI_FIXTURE.scenario)
MSITR = str(MSI_FIXTURE.test_realization)


def gen(*args):
    """Run $GEN with args; return the returncode (stdout/stderr suppressed)."""
    return subprocess.run([GEN] + list(args),
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


# 0. schema alignment (CI has no JSON-Schema lib): the committed fixture matches the
#    normative schema's required set (additionalProperties:false), consts, and hash pattern.
try:
    sch = json.load(open(os.path.join(REPO, "docs", "schemas", "test-realization.schema.json")))
    tr = json.load(open(MSITR))
    req = set(sch["required"])
    assert set(tr) == req, "field set %s != required %s" % (set(tr), req)
    assert tr["schemaVersion"] == 1 and tr["kind"] == "neutrino.test-realization"
    assert re.fullmatch(sch["properties"]["capabilityHash"]["pattern"], tr["capabilityHash"]), "hash pattern"
except AssertionError as e:
    fail("test-realization fixture diverges from schema: " + str(e))

# 1. the companion REGENERATES byte-identically from (source, scenario).
if gen("--target=test-realization", "--scenario=" + MSISC, MSISRC, "-o", os.path.join(GENDIR, "tr")) != 0:
    fail("test-realization emit")
if open(os.path.join(GENDIR, "tr", "test-realization.json"), "rb").read() != open(MSITR, "rb").read():
    fail("test-realization.json drifted from fixture (regenerate with --target=test-realization)")

# 2. carries EVERY case the backends derive: every declared input + compute, plus the event
#    chain and ledger deltas — nothing a renderer needs is missing.
try:
    src = open(MSISRC).read()
    tr = json.load(open(os.path.join(GENDIR, "tr", "test-realization.json")))
    inputs = set(re.findall(r'input\s+(\w+)\s*:', src))
    computes = set(re.findall(r'compute\s+(\w+)\s*=', src))
    assert set(tr["inputs"]) == inputs, "inputs %s != %s" % (set(tr["inputs"]), inputs)
    assert set(tr["computed"]) == computes, "computed %s != %s" % (set(tr["computed"]), computes)
    assert tr["eventChain"] and tr["ledgerDeltas"], "empty eventChain/ledgerDeltas"
except AssertionError as e:
    fail("realization missing cases the backends derive: " + str(e))

# 3. HASH SCOPE (the headline  acceptance): changing ONLY scenario values must NOT change
#    capabilityHash. Build a variant scenario (different, still-consistent values) and compare.
#    principal=222222, subsidy_pct=10 → subsidy = round(principal * 10 / 100) = 22222
#    (expect.computed must match evaluation — ; top-level keys are not loadScenario fields).
s = json.load(open(MSISC))
s['inputs']['principal'] = 222222
s['inputs']['transaction_id'] = 'txn-variant'
s['expect']['computed'] = {'subsidy': 22222}
s['expect']['ledger'] = {
    'acquirer.merchant_balance': -22222,
    'issuer.promotional_receivable': 22222,
}
json.dump(s, open(os.path.join(GENDIR, "tr_variant.json"), "w"))
if gen("--target=test-realization", "--scenario=" + os.path.join(GENDIR, "tr_variant.json"),
       MSISRC, "-o", os.path.join(GENDIR, "tr2")) != 0:
    fail("variant test-realization emit")
try:
    a = json.load(open(os.path.join(GENDIR, "tr", "test-realization.json")))
    b = json.load(open(os.path.join(GENDIR, "tr2", "test-realization.json")))
    assert a["capabilityHash"] == b["capabilityHash"], "capabilityHash changed with the scenario!"
    assert a["inputs"] != b["inputs"], "the variant scenario did not actually differ"
except AssertionError as e:
    fail("a scenario-only change moved capabilityHash (hash-scope violated): " + str(e))

# 4. the realization's capabilityHash equals the spec's own (source-alone) capabilityHash.
gen("--target=capability-spec", MSISRC, "-o", os.path.join(GENDIR, "trspec"))
p = json.load(open(os.path.join(GENDIR, "trspec", "capability-spec.json")))["identity"]["capabilityHash"]
t = json.load(open(os.path.join(GENDIR, "tr", "test-realization.json")))["capabilityHash"]
if p != t:
    fail("realization capabilityHash != spec capabilityHash")

# 5. validator alignment (CI has no JSON-Schema lib): the stdlib validator's field set
#    mirrors the normative schema's required set (like the spec validator, [76]).
try:
    sys.path.insert(0, os.path.join(REPO, "scripts", "validators"))
    import validate_test_realization as V
    sch = json.load(open(os.path.join(REPO, "docs", "schemas", "test-realization.schema.json")))
    assert set(sch["required"]) == V.TOP_FIELDS, "top-level required set"
    assert sch["properties"]["schemaVersion"]["const"] == V.SCHEMA_VERSION, "schemaVersion const"
    assert sch["properties"]["capabilityHash"]["pattern"] == V.HEX64.pattern, "hash pattern"
except AssertionError as e:
    fail("validate_test_realization diverges from the schema: " + str(e))

# 6. EVERY committed realization fixture regenerates byte-identically, VALIDATES, and its
#    capabilityHash cross-checks against that domain's committed spec (the beyond-schema
#    invariant a JSON-Schema can't express: the reference points at a real capability).
nr = 0
for fixture in committed_realization_fixtures(Path(REPO), INPUTS):
    d = str(fixture.root)
    trf = str(fixture.test_realization)
    src = str(fixture.source)
    sc = str(fixture.scenario)
    spec = str(fixture.capability_spec)
    if gen("--target=test-realization", "--scenario=" + sc, src, "-o", os.path.join(GENDIR, "trloop")) != 0:
        fail("test-realization emit " + os.path.basename(os.path.normpath(d)))
    if open(os.path.join(GENDIR, "trloop", "test-realization.json"), "rb").read() != open(trf, "rb").read():
        fail("test-realization.json drifted for " + os.path.basename(os.path.normpath(d)))
    if subprocess.run([sys.executable, TRV, trf, "--spec", spec],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        pp = subprocess.run([sys.executable, TRV, trf, "--spec", spec], capture_output=True, text=True)
        sys.stderr.write(pp.stdout + pp.stderr)
        fail("committed realization invalid / hash mismatch for " + os.path.basename(os.path.normpath(d)))
    nr += 1
if nr < 10:
    fail("too few realization fixtures checked (%d)" % nr)

# 7. eventChain is the IR-DERIVED choreography, not the scenario's optional expect.events:
#    a scenario with expect.events REMOVED still realizes a non-empty eventChain == spec chain.
s = json.load(open(MSISC))
s.pop('expect', None)
s.pop('events', None)
json.dump(s, open(os.path.join(GENDIR, "tr_noev.json"), "w"))
if gen("--target=test-realization", "--scenario=" + os.path.join(GENDIR, "tr_noev.json"),
       MSISRC, "-o", os.path.join(GENDIR, "tr_noev")) != 0:
    fail("emit realization for a scenario without expect.events")
try:
    a = json.load(open(os.path.join(GENDIR, "tr_noev", "test-realization.json")))
    ref = json.load(open(MSITR))
    assert a["eventChain"] and a["eventChain"] == ref["eventChain"], \
        "eventChain %s != IR chain %s" % (a["eventChain"], ref["eventChain"])
except AssertionError as e:
    fail("eventChain empty/wrong without expect.events (regression): " + str(e))

# 8. the validator fails closed on a tampered reference (hash_mismatch) and a bad shape.
t = json.load(open(MSITR))
t['capabilityHash'] = '0' * 64
json.dump(t, open(os.path.join(GENDIR, "tr_badhash.json"), "w"))
r = subprocess.run([sys.executable, TRV, os.path.join(GENDIR, "tr_badhash.json"),
                    "--spec", os.path.join(MSI, "generated", "capability-spec", "capability-spec.json")],
                   capture_output=True, text=True)
badhash_out = r.stdout + r.stderr
if r.returncode == 0:
    fail("validator accepted a capabilityHash that does not match the spec")
if '"realization.hash_mismatch"' not in badhash_out:
    sys.stderr.write(badhash_out)
    fail("tampered reference did not emit realization.hash_mismatch")
t = json.load(open(MSITR))
t['bogus'] = 1
json.dump(t, open(os.path.join(GENDIR, "tr_unknown.json"), "w"))
r = subprocess.run([sys.executable, TRV, os.path.join(GENDIR, "tr_unknown.json")],
                   capture_output=True, text=True)
unknown_out = r.stdout + r.stderr
if '"realization.unknown_field"' not in unknown_out:
    sys.stderr.write(unknown_out)
    fail("unknown field did not emit realization.unknown_field")

print("[79] OK: %d realization fixtures regenerate byte-identically + validate + hash cross-checks the "
      "spec; carries every input/compute/event/ledger case; capabilityHash INVARIANT under scenario "
      "changes and equals the spec's; eventChain is the IR choreography even without expect.events; "
      "validator fails closed on tampered hash / bad shape; renderers consume the fold, byte-stable [43]"
      % nr)
