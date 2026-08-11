"""[75] M5 (): neutrino-solidity-samples classification.json — translator-owned shape validator.
Ported verbatim from the retired run_cpp_tests.sh [75] block (). The stdlib validator mirrors the
NORMATIVE docs/schemas/solidity-classification.schema.json (fields/pattern/const aligned); the committed
real classification validates + emits diagnostics/report (--out); and every committed + inline-derived
negative (unknown/missing top+sample field, schemaVersion, missing/unknown dimension, bad+duplicate
profileId, profileVersion mismatch, duplicate contract, unknown scalar+characteristic value,
source/contract mismatch, malformed-file) fails closed with its stable classification.* code.

Usage: check_solidity_classification.py <examples-dir>
"""
import json
import os
import subprocess
import sys
import copy
import tempfile

EXAMPLES = sys.argv[1]
repo = os.path.dirname(os.path.abspath(EXAMPLES))
gendir = tempfile.mkdtemp(prefix="cls75.")

try:
    V = os.path.join(repo, "scripts", "corpus", "validate_solidity_classification.py")
    FIXTURE = os.path.join(repo, "examples", "solidity-classification", "classification.json")
    base = json.load(open(FIXTURE))

    # Schema alignment (F2 of the  review): docs/schemas/solidity-classification.schema.json is
    # the NORMATIVE shape; the stdlib validator must mirror it (CI runs the script, not a JSON-Schema
    # lib). Assert the validator's field sets / pattern / const equal the schema's, so they can't drift.
    sys.path.insert(0, os.path.join(repo, "scripts", "corpus"))
    import validate_solidity_classification as VM
    sch = json.load(open(os.path.join(repo, "docs", "schemas", "solidity-classification.schema.json")))
    sprops = sch["properties"]
    assert sprops["schemaVersion"]["const"] == VM.SCHEMA_VERSION, "schemaVersion const"
    assert (set(sch["required"]) | {"dimensionDocs"}) == VM.TOP_FIELDS, "top-level fields"
    assert set(sprops["dimensions"]["required"]) == set(VM.DIMENSIONS), "dimensions"
    assert set(sprops["samples"]["items"]["required"]) == VM.SAMPLE_FIELDS, "sample fields"
    assert sch["$defs"]["profileId"]["pattern"] == VM.PROFILE_ID_RE.pattern, "profileId pattern"

    def run(doc=None, path=None, out=None):
        if path is None:
            path = tempfile.mktemp(suffix=".json"); json.dump(doc, open(path, "w"))
        cmd = [sys.executable, V, path] + (["--out", out] if out else [])
        p = subprocess.run(cmd, capture_output=True, text=True)
        return p.returncode, json.loads(p.stdout)

    # Positive: the committed real classification validates, exit 0, no diagnostics; and --out
    # writes the machine-readable diagnostics.json + report the samples repo /  can consume.
    outdir = os.path.join(gendir, "cls_ok")
    rc, d = run(path=FIXTURE, out=outdir)
    assert rc == 0 and d["ok"] and d["diagnostics"] == [], ("positive", rc, d)
    rep = json.load(open(os.path.join(outdir, "classification.report.json")))
    dj = json.load(open(os.path.join(outdir, "diagnostics.json")))
    assert rep["ok"] and rep["samples"] == len(base["samples"]) and dj["ok"], ("positive report", rep, dj)

    # Committed negative fixtures: each must fail closed (exit 1) with its specific code —
    # these are the acceptance-named categories (profile id/version, unknown+missing fields,
    # dimensions) the fast tier also iterates.
    committed = {
        "bad_profile_id.json":          "classification.bad_profile_id",
        "profile_version_mismatch.json": "classification.profile_version_mismatch",
        "unknown_field.json":           "classification.unknown_field",
        "missing_required_field.json":  "classification.missing_field",
        "unknown_dimension_value.json": "classification.unknown_dimension_value",
    }
    negdir = os.path.join(repo, "examples", "solidity-classification", "negatives")
    for fn, code in committed.items():
        rc, d = run(path=os.path.join(negdir, fn))
        codes = {x["code"] for x in d["diagnostics"]}
        assert rc == 1 and d["ok"] is False and code in codes, (fn, rc, codes)

    # Inline-derived negatives for the remaining codes (kept DRY rather than committing a file
    # per code): mutate the committed fixture and assert the specific code fires.
    def mut(fn):
        d = copy.deepcopy(base); fn(d); return d

    def set_sample(d, i, **kw):
        d["samples"][i].update(kw)

    inline = [
        ("classification.missing_field",            lambda d: d.pop("dimensions")),
        ("classification.schema_version",           lambda d: d.__setitem__("schemaVersion", 1)),
        ("classification.missing_dimension",        lambda d: d["dimensions"].pop("evidenceStyle")),
        ("classification.unknown_dimension",        lambda d: d["dimensions"].__setitem__("extra", ["x"])),
        ("classification.duplicate_profile_id",     lambda d: set_sample(d, 1, profileId=base["samples"][0]["profileId"])),
        ("classification.duplicate_contract",       lambda d: set_sample(d, 1, contract=base["samples"][0]["contract"], source=base["samples"][0]["source"])),
        ("classification.unknown_dimension_value",  lambda d: set_sample(d, 0, characteristics=["idempotent", "bogus"])),
        ("classification.source_contract_mismatch", lambda d: set_sample(d, 0, source="src/Wrong.sol")),
    ]
    for code, fn in inline:
        rc, d = run(mut(fn))
        codes = {x["code"] for x in d["diagnostics"]}
        assert rc == 1 and d["ok"] is False and code in codes, (code, rc, codes)

    # A malformed file (not JSON) fails closed with classification.io, never a crash.
    bad = os.path.join(gendir, "cls_notjson.json"); open(bad, "w").write("{ not json")
    rc, d = run(path=bad)
    assert rc == 1 and d["ok"] is False and d["diagnostics"][0]["code"] == "classification.io", ("io", rc, d)
except AssertionError as e:
    print("[75] FAIL: classification validator: " + str(e), file=sys.stderr)
    sys.exit(1)
print("[75] OK: validator mirrors the normative schema [fields/pattern/const aligned]; committed "
      "classification validates + emits diagnostics/report; unknown/missing top+sample field, "
      "schemaVersion, missing/unknown dimension, bad+duplicate profileId, profileVersion mismatch, "
      "duplicate contract, unknown scalar+characteristic value, source/contract mismatch, "
      "malformed-file all fail closed with stable codes")
