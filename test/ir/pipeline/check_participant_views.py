"""[82] M5 (): participant views derived from the spec — scenario-free, capability+source
provenance, no invented semantics. Ported verbatim from the retired run_cpp_tests.sh [82] block ().
The stdlib validator mirrors the normative participant-view.schema.json; views need NO --scenario and are
scenario-independent; every committed view fixture (nv>=26) regenerates byte-identically from source alone
and its capability identity / lifecycle ops / specContract / per-field source AND the input/effect
semantics at each specPath cross-check the domain's capability-spec.json (a view invents nothing the spec
lacks); the validator fails closed on a tampered hash (view.hash_mismatch), an unknown field
(view.unknown_field), a missing/mistyped nested field and a line-0 span (view.schema) and an invented
input name (view.contract_mismatch); and the core_document_escrow guarded participants (EscrowAgent/Seller)
include their when-guard input dep (agreed_amount) while the unguarded Buyer does not.

Usage: check_participant_views.py <neutrino-gen> <examples-dir>
"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

GEN, EXAMPLES = sys.argv[1:3]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
GENDIR = tempfile.mkdtemp(prefix="vw82.")
TRV = os.path.join(REPO, "scripts", "validators", "validate_participant_view.py")

sys.path.insert(0, os.path.join(REPO, "test", "ir", "pipeline"))
from pipeline_inputs import (PipelineInputError, resolve_core_fixture,  # noqa: E402
                             view_golden_fixtures)


def fail(msg):
    print("[82] FAIL: " + msg, file=sys.stderr)
    sys.exit(1)


def gen(*args):
    """Run $GEN with args; return the returncode (stdout/stderr suppressed)."""
    return subprocess.run([GEN] + list(args),
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


# 0. validator alignment (CI has no JSON-Schema lib): the stdlib validator's field set
#    mirrors the normative schema's required set (like the sibling validators).
try:
    sys.path.insert(0, os.path.join(REPO, "scripts", "validators"))
    import validate_participant_view as V
    sch = json.load(open(os.path.join(REPO, "docs", "schemas", "participant-view.schema.json")))
    assert set(sch["required"]) == V.TOP_FIELDS, "top-level required set"
    assert sch["properties"]["schemaVersion"]["const"] == V.SCHEMA_VERSION, "schemaVersion const"
    assert sch["properties"]["capability"]["properties"]["capabilityHash"]["pattern"] == V.HEX64.pattern, "hash pattern"
except AssertionError as e:
    fail("validate_participant_view diverges from the schema: " + str(e))

# 1. slot-style: views need NO --scenario, and are scenario-INDEPENDENT (changing only
#    test realization can't change capability-level view semantics — the drift acceptance).
VWSRC = os.path.join(REPO, "test", "ir", "domain", "Inputs", "core_flexible_binding", "source", "core_flexible_binding.neu")
VWSC = os.path.join(REPO, "test", "ir", "domain", "Inputs", "core_flexible_binding", "scenario", "core_flexible_binding_happy_path.json")
if gen("--target=views", VWSRC, "-o", os.path.join(GENDIR, "vw_ns")) != 0:
    fail("views required a scenario")
gen("--target=views", "--scenario=" + VWSC, VWSRC, "-o", os.path.join(GENDIR, "vw_sc"))
for f in sorted(glob.glob(os.path.join(GENDIR, "vw_ns", "*.json"))):
    bn = os.path.basename(f)
    if bn in ("manifest.json", "diagnostics.json"):
        continue
    if open(f, "rb").read() != open(os.path.join(GENDIR, "vw_sc", bn), "rb").read():
        fail("view %s differs with vs without a scenario (scenario dependency leaked)" % bn)

# 2. every committed view fixture REGENERATES byte-identically (from source alone) AND its
#    capability identity + lifecycle ops + per-field provenance all cross-check against the
#    domain's committed capability-spec.json — so views never invent semantics the spec doesn't carry.
#    NOTE (/): migrating GenViews onto the spec (GenViewsSpec.cpp) was byte-identical for
#    37 of 39 views; the 2 guarded core_document_escrow views (EscrowAgent/Seller) GAINED their
#    when-guard input dep (agreed_amount) the old ProcedureView renderer omitted — a completeness
#    fix for guarded legs, pinned as a named invariant below (not just a fixture byte-match).
#    : this loop used to glob `examples/domains/*`. Every production domain moved
#    to a receipt-verified published pack, so the glob went silently empty and only the
#    one explicitly-appended synthetic survived -- "too few view fixtures checked (3)".
#    The portfolio is now resolved through the same receipt-verifying boundary
#    established, at the manifest's pinned coordinates (plus the  document-escrow
#    synthetic), so a domain can only enter this corpus through a verified surface and
#    a corpus that shrinks fails closed instead of passing on the survivors.
nv = 0
try:
    view_fixtures = view_golden_fixtures(REPO)
except PipelineInputError as error:
    fail(str(error))
if len(view_fixtures) < 10:
    fail("view-golden corpus collapsed: only %d fixtures pin committed views "
         "(need >=10) -- an empty or shrunken corpus must fail closed, not pass"
         % len(view_fixtures))
for fixture in view_fixtures:
    d = str(fixture.root)
    src = str(fixture.source)
    if gen("--target=views", src, "-o", os.path.join(GENDIR, "vwloop")) != 0:
        fail("views emit " + os.path.basename(os.path.normpath(d)))
    spec_path = os.path.join(d, "generated", "capability-spec", "capability-spec.json")
    for vf in sorted(glob.glob(os.path.join(d, "generated", "views", "*.json"))):
        bn = os.path.basename(vf)
        if open(os.path.join(GENDIR, "vwloop", bn), "rb").read() != open(vf, "rb").read():
            fail("view %s drifted for %s (regenerate with --target=views)"
                 % (bn, os.path.basename(os.path.normpath(d))))
        try:
            spec = json.load(open(spec_path))
            view = json.load(open(vf))
            # capability identity links to the spec
            assert view["capability"]["capabilityHash"] == spec["identity"]["capabilityHash"], "capabilityHash != spec"
            # visibleOperations are the spec's lifecycle operation vocabulary (not invented)
            ops, seen = [], set()
            for t in spec["lifecycle"]["transitions"]:
                if t["name"] not in seen:
                    ops.append(t["name"])
                    seen.add(t["name"])
            assert view["visibleOperations"] == ops, "visibleOperations %s != spec ops %s" % (view["visibleOperations"], ops)
            # specContract is READ from (equals) the spec's actual schemaVersion (not a literal)
            assert view["provenance"]["specContract"] == {"kind": "neutrino.capability-spec", "schemaVersion": spec["schemaVersion"]}
            # D11: every requiredInput / evidenceObligation specPath+source MATCHES the spec sourceMap
            smap = {e["specPath"]: e for e in spec["sourceMap"]}
            for item in view["requiredInputs"] + view["evidenceObligations"]:
                pp = item["specPath"]
                assert pp in smap, "specPath %s not in spec sourceMap" % pp
                if "source" in item:
                    assert item["source"] == smap[pp]["source"], "source %s != spec %s for %s" % (item["source"], smap[pp]["source"], pp)
            # and the item's SEMANTICS match the spec element AT that path (not just that the
            # path exists): requiredInputs.name/type == spec.inputs[i]; evidenceObligations
            # leg/kind/ledger == spec.effects[i]. So a view can't emit a value the spec lacks.
            def idx(pp, prefix):
                m = re.fullmatch(re.escape(prefix) + r"\[(\d+)\]", pp)
                return int(m.group(1)) if m else None
            for item in view["requiredInputs"]:
                i = idx(item["specPath"], "inputs")
                assert i is not None, item["specPath"]
                pin = spec["inputs"][i]
                assert item["name"] == pin["name"] and item["type"] == pin["type"], "requiredInput %s != spec.inputs[%d] %s" % (item, i, pin)
            for item in view["evidenceObligations"]:
                i = idx(item["specPath"], "effects")
                assert i is not None, item["specPath"]
                eff = spec["effects"][i]
                assert item["leg"] == eff["name"] and item["kind"] == eff["kind"] and item["ledger"] == eff["ledger"], "obligation %s != spec.effects[%d] %s" % (item, i, eff)
        except AssertionError as e:
            fail("view provenance/semantics do not match the spec for %s/%s: %s"
                 % (os.path.basename(os.path.normpath(d)), bn, str(e)))
        # and the stdlib validator (what  / an auditor runs) accepts it + cross-checks the spec.
        if subprocess.run([sys.executable, TRV, vf, "--spec", spec_path],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
            p = subprocess.run([sys.executable, TRV, vf, "--spec", spec_path], capture_output=True, text=True)
            sys.stderr.write(p.stdout + p.stderr)
            fail("validate_participant_view rejected committed view %s/%s"
                 % (os.path.basename(os.path.normpath(d)), bn))
        nv += 1
if nv < 26:
    fail("too few view fixtures checked (%d views across the %d resolved fixtures; "
         "need >=26) -- the corpus may not shrink" % (nv, len(view_fixtures)))

# validator negatives: a mismatched capabilityHash and an unknown field fail closed.
_FB = resolve_core_fixture(REPO, "core_flexible_binding")
VF0 = sorted(glob.glob(str(_FB.root / "generated" / "views" / "*.json")))[0]
FBSPEC = str(_FB.capability_spec)


def run_validator(view_path, spec_path=None):
    """Run the stdlib validator; return (returncode, combined stdout+stderr)."""
    cmd = [sys.executable, TRV, view_path]
    if spec_path:
        cmd += ["--spec", spec_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


v = json.load(open(VF0))
v['capability']['capabilityHash'] = '0' * 64
json.dump(v, open(os.path.join(GENDIR, "vw_badhash.json"), "w"))
rc, out = run_validator(os.path.join(GENDIR, "vw_badhash.json"), FBSPEC)
if rc == 0:
    fail("view validator accepted a capabilityHash that does not match the spec")
if '"view.hash_mismatch"' not in out:
    sys.stderr.write(out)
    fail("tampered view hash did not emit view.hash_mismatch")

v = json.load(open(VF0))
v['bogus'] = 1
json.dump(v, open(os.path.join(GENDIR, "vw_unknown.json"), "w"))
rc, out = run_validator(os.path.join(GENDIR, "vw_unknown.json"))
if '"view.unknown_field"' not in out:
    sys.stderr.write(out)
    fail("unknown view field did not emit view.unknown_field")

# nested-shape enforcement: a missing required nested field (participant.name) fails closed.
v = json.load(open(VF0))
del v['participant']['name']
json.dump(v, open(os.path.join(GENDIR, "vw_noname.json"), "w"))
rc, out = run_validator(os.path.join(GENDIR, "vw_noname.json"))
if rc == 0:
    fail("view validator accepted a participant with no name")
if '"view.schema"' not in out:
    sys.stderr.write(out)
    fail("missing participant.name did not emit view.schema")

# value correspondence: an invented requiredInputs name (specPath/source intact) fails closed
# against the spec — the view can't claim a field value the spec doesn't carry.
v = json.load(open(VF0))
v['requiredInputs'][0]['name'] = 'INVENTED_NOT_IN_SPEC'
json.dump(v, open(os.path.join(GENDIR, "vw_invent.json"), "w"))
rc, out = run_validator(os.path.join(GENDIR, "vw_invent.json"), FBSPEC)
if rc == 0:
    fail("view validator accepted a requiredInput name the spec does not carry")
if '"view.contract_mismatch"' not in out:
    sys.stderr.write(out)
    fail("invented input name did not emit view.contract_mismatch")

# nested OPTIONAL-field type enforcement: a non-string optional field fails closed.
v = json.load(open(VF0))
v['participant']['org'] = 123
json.dump(v, open(os.path.join(GENDIR, "vw_badopt.json"), "w"))
rc, out = run_validator(os.path.join(GENDIR, "vw_badopt.json"))
if rc == 0:
    fail("view validator accepted a non-string participant.org")
if '"view.schema"' not in out:
    sys.stderr.write(out)
    fail("non-string optional field did not emit view.schema")

# source-span minimum: line must be >= 1 (a 0/absent location must not be claimed as a real span).
v = json.load(open(VF0))
v['requiredInputs'][0]['source'] = {'line': 0, 'column': 1}
json.dump(v, open(os.path.join(GENDIR, "vw_badsrc.json"), "w"))
rc, out = run_validator(os.path.join(GENDIR, "vw_badsrc.json"))
if rc == 0:
    fail("view validator accepted a source span with line 0")
if '"view.schema"' not in out:
    sys.stderr.write(out)
    fail("source line 0 did not emit view.schema")

# guard dependency ( review): a guarded leg () depends on the values its `when` predicate
# compares, so a participant that authorizes a guarded leg must list those in requiredInputs (else a
# consumer of the narrowed view can't evaluate whether its obligation fires). core_document_escrow
# guards escrow_release/seller_settlement on `amount >= agreed_amount`, so EscrowAgent + Seller must
# include agreed_amount; Buyer (unguarded legs) must NOT (no obligation leakage).
CEV = os.path.join(REPO, "test", "ir", "samples", "Inputs", "core_document_escrow", "generated", "views")
for p in ("EscrowAgent", "Seller"):
    names = {r['name'] for r in json.load(open(os.path.join(CEV, p + ".json")))['requiredInputs']}
    if 'agreed_amount' not in names:
        fail("guarded participant %s is missing the guard dependency agreed_amount" % p)
buyer_names = {r['name'] for r in json.load(open(os.path.join(CEV, "Buyer.json")))['requiredInputs']}
if 'agreed_amount' in buyer_names:
    fail("unguarded participant Buyer leaked the guard dependency agreed_amount")

print("[82] OK: %d views regenerate byte-identically with no --scenario + are scenario-independent; "
      "capabilityHash/lifecycle ops/specContract/per-field source AND the input/effect semantics at each "
      "specPath cross-check the spec; guarded participants include their when-guard input deps "
      "(agreed_amount) while unguarded ones don't; the stdlib validator accepts every committed view + "
      "fails closed on a tampered hash / bad shape — views project from the spec and invent nothing" % nv)
