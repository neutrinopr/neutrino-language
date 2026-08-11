"""[76] M5 WP1d (): canonical spec --target=capability-spec (scenario-free, schema-valid,
byte+hash-stable, lifecycle projection). Ported verbatim from the retired run_cpp_tests.sh [76] block
(). The stdlib validator mirrors the normative capability-spec.schema.json and emits a bind-able
`neutrino.capability-spec-validation` report naming the spec's identity (/, incl. the optional
signature envelope). Every committed sample spec regenerates byte-identically from source ALONE (no
--scenario, np>=10) and validates backend-independently; a scenario-required target fails closed without
--scenario; canonicalization is byte-stable under a benign in-block field reorder and keeps capabilityHash
stable (specHash tracking) under a line-shifting reformat and a non-ASCII round-trip; renaming moves both
hashes while an envelope-only change moves only specHash; the slot lifecycle + on-chain surface project
from the spec's one lifecycle machine; and every top-level AND nested array section + a dead-end state
fail closed even with recomputed hashes.

Usage: check_capability_spec.py <neutrino-gen> <examples-dir>
"""
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from pipeline_inputs import (PipelineInputError, committed_capability_fixtures,
                             resolve_pipeline_inputs)

GEN, EXAMPLES = sys.argv[1:3]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
GENDIR = tempfile.mkdtemp(prefix="spec76.")
SPECV = os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py")


def fail(msg):
    print("[76] FAIL: " + msg, file=sys.stderr)
    sys.exit(1)

try:
    INPUTS = resolve_pipeline_inputs(Path(REPO))
except PipelineInputError as error:
    fail(str(error))
SOA_FIXTURE = INPUTS["sponsored_offer_agreement"]
MSI_FIXTURE = INPUTS["merchant_sponsored_installment"]
PAYOUT_FIXTURE = INPUTS["channel_verified_payout"]


def gen_spec(src, out):
    """$GEN --target=capability-spec <src> -o <out>; return True on success (rc==0)."""
    return subprocess.run([GEN, "--target=capability-spec", src, "-o", out],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


# 0. schema alignment: the stdlib validator must mirror the normative schema (CI runs the
#    script, not a JSON-Schema lib) — assert field set / const / enums / hash pattern agree.
try:
    sys.path.insert(0, os.path.join(REPO, "scripts", "validators"))
    import validate_capability_spec as VM
    sch = json.load(open(os.path.join(REPO, "docs", "schemas", "capability-spec.schema.json")))
    # The validator mirrors BOTH capability-spec contracts: the frozen v1
    # (schemaVersion 1..3, no obligations) and the additive v2 (: adds the
    # top-level obligations section + schemaVersion 4). required/categories/hash
    # are identical across v1 and v2; only the schemaVersion enum and the
    # obligations $def differ, so those align against v2 (the validator's full
    # accepted surface).
    schv2 = json.load(open(os.path.join(REPO, "docs", "schemas", "capability-spec-v2.schema.json")))
    assert set(sch["required"]) == set(schv2["required"]) == VM.TOP_FIELDS, "top-level required set"
    assert set(schv2["properties"]["schemaVersion"]["enum"]) == VM.SCHEMA_VERSIONS, "schemaVersion enum"
    assert set(sch["properties"]["schemaVersion"]["enum"]) == {1, 2, 3}, "v1 enum stays frozen"
    assert set(sch["$defs"]["valueCategory"]["enum"]) == VM.CATEGORIES, "value categories"
    assert sch["properties"]["identity"]["properties"]["capabilityHash"]["pattern"] == VM.HEX64.pattern, "hash pattern"
    # obligations mirror (): v2's obligation $def admits exactly the fields the
    # validator enforces (statuses is version-derived, NOT on the wire).
    assert set(schv2["$defs"]["obligation"]["required"]) == {
        "version", "name", "obligor", "beneficiary", "authority", "effects", "when"}, "obligation required set"
    assert schv2["$defs"]["obligation"]["additionalProperties"] is False, "obligation is fail-closed"
    assert "obligations" not in sch["properties"], "v1 must NOT admit obligations (it stays frozen)"
except AssertionError as e:
    fail("validator diverges from capability-spec.schema.json: " + str(e))

# 0b. report identity (): the validator's stdout report is a bind-able
#     `neutrino.capability-spec-validation` that NAMES the validated spec's identity (capabilityHash
#     + specHash), so a downstream consumer (build-tools ADMIT) can require an ok report FOR a
#     specific spec. A valid spec -> ok:true naming its own hash; a tampered spec -> ok:false.
SOA_SPEC = str(SOA_FIXTURE.capability_spec)
try:
    spec = json.load(open(SOA_SPEC))
    r = json.loads(subprocess.run([sys.executable, SPECV, SOA_SPEC], capture_output=True, text=True).stdout)
    assert r["kind"] == "neutrino.capability-spec-validation", r.get("kind")
    assert r["ok"] is True and r["capabilityHash"] == spec["identity"]["capabilityHash"], "ok report must name the spec's capabilityHash"
    assert r["specHash"] == spec["identity"]["specHash"], "report must name the spec's specHash"
    # : the report is a version-pinned translator->build-tools contract. The emitter constants must
    # match the committed schema's const pins, and the emitted report must conform to the schema.
    sch = json.load(open(os.path.join(REPO, "docs", "schemas", "capability-spec-validation.schema.json")))
    assert sch["properties"]["kind"]["const"] == VM.REPORT_KIND == r["kind"], "report kind pin"
    assert sch["properties"]["schemaVersion"]["const"] == VM.REPORT_SCHEMA_VERSION == r["schemaVersion"], "report schemaVersion pin"
    assert set(sch["required"]) <= set(r), ("report missing a required field", set(sch["required"]) - set(r))
    assert set(r) <= set(sch["properties"]), ("report has a field not in the schema", set(r) - set(sch["properties"]))
    # : the schema must ALSO admit the optional BUILD signature envelope, so a SIGNED
    # capability-spec-validation.json stays inside the v1 contract (additionalProperties:false).
    for f in ("signer", "signature", "signatureSuite"):
        assert f in sch["properties"], ("schema does not allow the signature envelope field", f)
    signed = dict(r); signed.update({"signer": "buildco", "signatureSuite": "ed25519", "signature": "AA=="})
    assert set(signed) <= set(sch["properties"]), ("signed report has a field not in the schema", set(signed) - set(sch["properties"]))
    # tampered spec: ok:false (so a consumer refuses to ground admission in it), still a valid report shape.
    t = dict(spec); t["procedure"] = "tampered"
    open(GENDIR + "/rep_tampered.json", "w").write(json.dumps(t))
    rt = json.loads(subprocess.run([sys.executable, SPECV, GENDIR + "/rep_tampered.json"], capture_output=True, text=True).stdout)
    assert rt["ok"] is False and rt["schemaVersion"] == VM.REPORT_SCHEMA_VERSION, "a tampered spec must report ok:false with a versioned report"
except AssertionError as e:
    fail("validator report does not carry the bind-able spec identity / conform to its schema (/): " + str(e))

# 1. every committed sample spec REGENERATES byte-identically from source ALONE (no --scenario)
#    and validates independently of any backend (pure stdlib, no gen).
np = 0
for fixture in committed_capability_fixtures(Path(REPO), INPUTS):
    d = str(fixture.root)
    src = str(fixture.source)
    committed_spec = str(fixture.capability_spec)
    if not gen_spec(src, os.path.join(GENDIR, "specchk")):
        fail("spec emit " + os.path.basename(os.path.normpath(d)))
    regen = os.path.join(GENDIR, "specchk", "capability-spec.json")
    if open(regen, "rb").read() != open(committed_spec, "rb").read():
        fail("capability-spec.json drifted from fixture for " + os.path.basename(os.path.normpath(d))
             + " (regenerate with --target=capability-spec)")
    if subprocess.run([sys.executable, SPECV, committed_spec],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        p = subprocess.run([sys.executable, SPECV, committed_spec], capture_output=True, text=True)
        sys.stderr.write(p.stdout + p.stderr)
        fail("committed spec invalid for " + os.path.basename(os.path.normpath(d)))
    np += 1
if np < 10:
    fail("too few spec fixtures checked (%d)" % np)

# 2. --target=capability-spec needs no --scenario; passing a scenario-required target without one fails closed.
if subprocess.run([GEN, "--target=capability",
                   str(SOA_FIXTURE.source),
                   "-o", os.path.join(GENDIR, "specns")],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
    fail("a scenario-required target ran without --scenario")

# 3. canonicalization has two levels ( F3): (3a) reordering block fields WITHOUT moving any
#    statement line yields a BYTE-IDENTICAL spec; (3b) reformatting that SHIFTS lines leaves the
#    semantic capabilityHash STABLE (it excludes sourceMap + targetRequirements) while specHash
#    (the whole-spec digest) tracks the shift.
SOA = str(SOA_FIXTURE.root)
SOA_SRC = str(SOA_FIXTURE.source)
SOA_COMMITTED = os.path.join(SOA, "generated", "capability-spec", "capability-spec.json")

# (3a) permute the seven debit-block field lines, SAME line count -> no statement moves.
src = open(SOA_SRC).read()
variant = src.replace(
'''        ledger          = "sponsor.commitment"
        owner           = "sponsor"
        participant     = "Sponsor"
        party           = %sponsor_id
        amount          = %contribution
        currency        = %currency
        idempotency_key = %offer_id''',
'''        currency        = %currency
        ledger          = "sponsor.commitment"
        idempotency_key = %offer_id
        owner           = "sponsor"
        participant     = "Sponsor"
        amount          = %contribution
        party           = %sponsor_id''')
soa_canon_src = os.path.join(GENDIR, "soa_canon.neu")
open(soa_canon_src, "w").write(variant)
gen_spec(soa_canon_src, os.path.join(GENDIR, "soa_canon"))
if open(os.path.join(GENDIR, "soa_canon", "capability-spec.json"), "rb").read() != open(SOA_COMMITTED, "rb").read():
    fail("(3a) benign in-block field reorder changed the canonical spec")

# (3b) blank lines shift statement lines -> capabilityHash stable, specHash differs.
soa_reflow_src = os.path.join(GENDIR, "soa_reflow.neu")
open(soa_reflow_src, "w").write(open(SOA_SRC).read().replace("    input offer_id", "\n\n    input offer_id"))
gen_spec(soa_reflow_src, os.path.join(GENDIR, "soa_reflow"))
a = json.load(open(SOA_COMMITTED))["identity"]
b = json.load(open(os.path.join(GENDIR, "soa_reflow", "capability-spec.json")))["identity"]
if not (a["capabilityHash"] == b["capabilityHash"] and a["specHash"] != b["specHash"]):
    fail("(3b) line-shifting reformat did not keep capabilityHash stable / move specHash")

# (3c/F5) a non-ASCII string literal round-trips: the spec validates (llvm raw UTF-8 == the
# validator's ensure_ascii=False canonical form, so the recomputed hashes match).
soa_utf8_src = os.path.join(GENDIR, "soa_utf8.neu")
open(soa_utf8_src, "w").write(open(SOA_SRC).read().replace('"sponsor.commitment"', '"sponsor.commitmént"'))
gen_spec(soa_utf8_src, os.path.join(GENDIR, "soa_utf8"))
if subprocess.run([sys.executable, SPECV, os.path.join(GENDIR, "soa_utf8", "capability-spec.json")],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
    p = subprocess.run([sys.executable, SPECV, os.path.join(GENDIR, "soa_utf8", "capability-spec.json")],
                       capture_output=True, text=True)
    sys.stderr.write(p.stdout + p.stderr)
    fail("(F5) non-ASCII spec failed validation (canonical-form encoding mismatch)")

# 4. rename negative: renaming an identity-bearing name changes BOTH capabilityHash and specHash.
soa_rename_src = os.path.join(GENDIR, "soa_rename.neu")
open(soa_rename_src, "w").write(
    open(SOA_SRC).read().replace("sponsored_offer_agreement", "sponsored_offer_agreement_v2"))
gen_spec(soa_rename_src, os.path.join(GENDIR, "soa_rename"))
a = json.load(open(SOA_COMMITTED))["identity"]
b = json.load(open(os.path.join(GENDIR, "soa_rename", "capability-spec.json")))["identity"]
if not (a["capabilityHash"] != b["capabilityHash"] and a["specHash"] != b["specHash"]):
    fail("rename did not change the spec/capability hash")

# 4b. envelope invariance (): capabilityHash is a PURE semantic identity — mutating an envelope
#     discriminator (kind / schemaVersion) must NOT move capabilityHash (so a future envelope rename
#     never re-churns the corpus), while the whole-artifact specHash DOES track the byte change.
try:
    def sha(o): return hashlib.sha256(json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    def caphash(p):  # preimage: whole spec minus identity/sourceMap/targetRequirements/kind/schemaVersion
        return sha({k: v for k, v in p.items() if k not in ("identity", "sourceMap", "targetRequirements", "kind", "schemaVersion")})
    def spechash(p):  # whole-artifact digest: everything minus identity.specHash
        b = dict(p); b["identity"] = {"capabilityHash": p["identity"]["capabilityHash"]}; return sha(b)
    p = json.load(open(SOA_COMMITTED))
    mut = dict(p); mut["kind"] = "__envelope_mutation_probe__"; mut["schemaVersion"] = 99  # envelope-only change (values guaranteed distinct from the real envelope)
    assert caphash(mut) == caphash(p), "capabilityHash moved on an envelope-only change"
    assert spechash(mut) != spechash(p), "specHash did not track the envelope change"
except AssertionError as e:
    fail("(4b) envelope discriminator leaked into capabilityHash (or specHash ignored it): " + str(e))

# 5. lifecycle projection: the slot lifecycle + the on-chain surface project from the spec's ONE machine.
try:
    spec = json.load(open(os.path.join(SOA, "generated", "capability-spec", "capability-spec.json")))
    ops = json.load(open(os.path.join(SOA, "generated", "slot", "operations.json")))
    comp = json.load(open(os.path.join(SOA, "generated", "slot", "compensation.json")))
    tr = {t["name"] for t in spec["lifecycle"]["transitions"]}
    op_names = {o["operation"] for o in ops["operations"]}
    assert tr == op_names, ("transitions != slot operations", tr, op_names)
    # the spec's posting transition(s) are exactly the slot's compensable operations
    posting = {t["name"] for t in spec["lifecycle"]["transitions"] if "post" in t["effects"]}
    assert posting == set(comp.get("compensable", {})), ("posting != compensable", posting, set(comp.get("compensable", {})))
    # the on-chain surface projects the single posting transition as its state-changing entrypoint
    sol = "".join(open(f).read() for f in glob.glob(os.path.join(SOA, "generated", "solidity", "src", "*.sol")))
    assert len(posting) == 1 and re.search(r"function\s+execute", sol), ("solidity surface", posting)
except AssertionError as e:
    fail("lifecycle projection mismatch: " + str(e))

# 6. fail-closed negatives: EVERY array section the schema requires — top-level
#    AND nested — must be rejected even with recomputed hashes (the stdlib validator is the
#    schema mirror), and a dead-end non-terminal state must fail. Participant/compute arrays are
#    exercised on fixtures that actually have them.
try:
    import copy
    V = os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py")
    spec = json.load(open(SOA_COMMITTED))
    part_spec = json.load(open(PAYOUT_FIXTURE.capability_spec))  # has participants
    comp_spec = json.load(open(MSI_FIXTURE.capability_spec))  # has computes
    assert part_spec["participants"] and comp_spec["computes"], "fixtures lack participants/computes"
    def compact(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    def rehash(p):
        core = copy.deepcopy(p)
        for k in ("identity", "sourceMap", "targetRequirements"):
            core.pop(k, None)
        cap = hashlib.sha256(compact(core).encode()).hexdigest()
        b = copy.deepcopy(p); b["identity"] = {"capabilityHash": cap}
        ph = hashlib.sha256(compact(b).encode()).hexdigest()
        p["identity"] = {"capabilityHash": cap, "specHash": ph}; return p
    def run(p):
        f = tempfile.mktemp(suffix=".json"); json.dump(p, open(f, "w"))
        r = subprocess.run([sys.executable, V, f], capture_output=True, text=True)
        return r.returncode, {d["code"] for d in json.loads(r.stdout)["diagnostics"]}
    def setpath(p, path, val):
        cur = p
        for k in path[:-1]:
            cur = cur[k]
        cur[path[-1]] = val
        return p
    def assert_nonarray(base, path):
        t = rehash(setpath(copy.deepcopy(base), path, {}))
        rc, codes = run(t)
        assert rc == 1 and "spec.schema" in codes, ("non-array " + ".".join(map(str, path)), rc, codes)
    # top-level array sections
    for sec in ("inputs", "computes", "effects", "invariants", "participants", "sourceMap"):
        assert_nonarray(spec, [sec])
    # nested array sections (schema mirror, not top-level-only)
    for path in (["topology", "allowedOrgPairs"], ["targetRequirements", "unsupportedConstructs"],
                 ["targetRequirements", "requirements"], ["lifecycle", "states"],
                 ["lifecycle", "transitions"], ["lifecycle", "instanceKey", "fields"],
                 ["lifecycle", "transitions", 0, "guards"], ["lifecycle", "transitions", 0, "effects"]):
        assert_nonarray(spec, path)
    # computes[].deps on a compute-bearing fixture; participant arrays on a participant-bearing one.
    assert_nonarray(comp_spec, ["computes", 0, "deps"])
    for field in ("capabilities", "bindRuntimes"):
        assert_nonarray(part_spec, ["participants", 0, field])
    # dead-end non-terminal state
    dead = copy.deepcopy(spec)
    dead["lifecycle"]["transitions"] = [x for x in dead["lifecycle"]["transitions"]
                                        if not (x["name"] == "CLOSE" and x["from"] == "COMPENSATED")]
    rc, codes = run(rehash(dead))
    assert rc == 1 and "spec.dead_end_state" in codes, ("dead-end", rc, codes)
except AssertionError as e:
    fail("spec validator missed a non-array section / dead-end state: " + str(e))

print("[76] OK: %d sample specs regenerate byte-identically from source alone + validate "
      "backend-independently; scenario-required target fails closed without --scenario; in-block field "
      "reorder is byte-stable and line-shifting reformat keeps capabilityHash stable while specHash tracks "
      "it; non-ASCII literal round-trips; rename changes capability+spec hash; slot lifecycle + on-chain "
      "surface project from the spec's one lifecycle machine; every top-level AND nested array section + a "
      "dead-end state fail closed even with recomputed hashes" % np)
