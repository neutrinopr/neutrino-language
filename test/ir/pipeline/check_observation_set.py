"""[75b] M5 S0 (): neutrino.domain-observation-set — deterministic corpus-extraction shape validator
+ trust boundary. Ported verbatim from the retired run_cpp_tests.sh [75b] block (). The stdlib
validator mirrors the NORMATIVE docs/schemas/domain-observation-set.schema.json (fields/patterns/consts
aligned; no AI-trust field declared anywhere); the committed observation set validates + emits
diagnostics/report (--out); and bad kind/schemaVersion, missing/unknown field, malformed content-hash
binding, unknown dimension + value, duplicate id, inverted span, and an AI-trust field
(confidence/reviewStatus/model) all fail closed with stable observation.* codes.

Usage: check_observation_set.py <examples-dir>
"""
import json
import os
import subprocess
import sys
import copy
import tempfile

EXAMPLES = sys.argv[1]
repo = os.path.dirname(os.path.abspath(EXAMPLES))
gendir = tempfile.mkdtemp(prefix="obs75b.")

try:
    V = os.path.join(repo, "scripts", "corpus", "validate_domain_observation_set.py")
    FIXTURE = os.path.join(repo, "examples", "domain-observation-set", "observation-set.json")
    base = json.load(open(FIXTURE))

    # Schema alignment: docs/schemas/domain-observation-set.schema.json is the NORMATIVE shape; the
    # stdlib validator must mirror it (CI runs the script, not a JSON-Schema lib). Assert the
    # validator's field sets / patterns / consts equal the schema's, so they cannot drift.
    sys.path.insert(0, os.path.join(repo, "scripts", "corpus"))
    import validate_domain_observation_set as VM
    sch = json.load(open(os.path.join(repo, "docs", "schemas", "domain-observation-set.schema.json")))
    sp = sch["properties"]
    defs = sch["$defs"]
    assert sp["kind"]["const"] == VM.KIND, "kind const"
    assert sp["schemaVersion"]["const"] == VM.SCHEMA_VERSION, "schemaVersion const"
    assert set(sch["required"]) == VM.TOP_FIELDS, "top-level fields"
    assert set(sp["corpusRef"]["required"]) == VM.CORPUS_REF_FIELDS == set(sp["corpusRef"]["properties"]), "corpusRef fields"
    assert set(sp["extractor"]["required"]) == VM.EXTRACTOR_FIELDS == set(sp["extractor"]["properties"]), "extractor fields"
    assert set(defs["provenance"]["required"]) == VM.PROVENANCE_REQUIRED, "provenance required"
    assert set(defs["provenance"]["properties"]) == VM.PROVENANCE_FIELDS, "provenance fields"
    assert set(defs["provenance"]["properties"]["span"]["properties"]) == VM.SPAN_FIELDS, "span fields"
    assert set(defs["observation"]["required"]) == VM.OBSERVATION_REQUIRED, "observation required"
    assert set(defs["observation"]["properties"]) == VM.OBSERVATION_FIELDS, "observation fields"
    assert defs["contentHash"]["pattern"] == VM.CONTENT_HASH_RE.pattern, "contentHash pattern"
    assert defs["observation"]["properties"]["id"]["pattern"] == VM.OBSERVATION_ID_RE.pattern, "observation id pattern"
    assert sp["dimensions"]["propertyNames"]["pattern"] == VM.DIMENSION_NAME_RE.pattern, "dimension name pattern"
    # The trust boundary is beyond-schema (additionalProperties:false enforces it structurally), but
    # the schema must never DECLARE an AI-trust field as an allowed property anywhere.
    declared = set()
    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("properties"), dict):
                declared.update(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(sch)
    assert not (declared & VM.FORBIDDEN_AI_FIELDS), ("schema declares a forbidden AI field", declared & VM.FORBIDDEN_AI_FIELDS)

    def run(doc=None, path=None, out=None):
        if path is None:
            path = tempfile.mktemp(suffix=".json"); json.dump(doc, open(path, "w"))
        cmd = [sys.executable, V, path] + (["--out", out] if out else [])
        p = subprocess.run(cmd, capture_output=True, text=True)
        return p.returncode, json.loads(p.stdout)

    # Positive: the committed observation set validates, exit 0, no diagnostics; --out writes the
    # machine-readable diagnostics.json + report S1/S2 (samples/) can consume.
    outdir = os.path.join(gendir, "obs_ok")
    rc, d = run(path=FIXTURE, out=outdir)
    assert rc == 0 and d["ok"] and d["diagnostics"] == [], ("positive", rc, d)
    rep = json.load(open(os.path.join(outdir, "observation-set.report.json")))
    dj = json.load(open(os.path.join(outdir, "diagnostics.json")))
    assert rep["ok"] and rep["observations"] == len(base["observations"]) and dj["ok"], ("positive report", rep, dj)

    # Committed negative fixtures: each fails closed (exit 1) with its specific code — the
    # acceptance-named categories (missing provenance, corpus hash binding, dimension vocabulary,
    # and the AI-trust boundary).
    committed = {
        "missing_provenance.json":      "observation.missing_field",
        "bad_content_hash.json":        "observation.bad_hash",
        "unknown_dimension_value.json": "observation.unknown_dimension_value",
        "unknown_dimension.json":       "observation.unknown_dimension",
        "ai_confidence_field.json":     "observation.ai_field_forbidden",
    }
    negdir = os.path.join(repo, "examples", "domain-observation-set", "negatives")
    for fn, code in committed.items():
        rc, d = run(path=os.path.join(negdir, fn))
        codes = {x["code"] for x in d["diagnostics"]}
        assert rc == 1 and d["ok"] is False and code in codes, (fn, rc, codes)

    # Inline-derived negatives for the remaining codes (kept DRY rather than a file per code):
    # mutate the committed fixture and assert the specific code fires.
    def mut(fn):
        d = copy.deepcopy(base); fn(d); return d

    inline = [
        ("observation.bad_kind",         lambda d: d.__setitem__("kind", "neutrino.something-else")),
        ("observation.schema_version",   lambda d: d.__setitem__("schemaVersion", 2)),
        ("observation.missing_field",    lambda d: d.pop("extractor")),
        ("observation.unknown_field",    lambda d: d.__setitem__("stray", True)),
        ("observation.ai_field_forbidden", lambda d: d["extractor"].__setitem__("model", "gpt")),
        ("observation.duplicate_id",     lambda d: d["observations"][1].__setitem__("id", d["observations"][0]["id"])),
        ("observation.span_inverted",    lambda d: d["observations"][0]["provenance"]["span"].update({"startLine": 99, "endLine": 1})),
    ]
    for code, fn in inline:
        rc, d = run(mut(fn))
        codes = {x["code"] for x in d["diagnostics"]}
        assert rc == 1 and d["ok"] is False and code in codes, (code, rc, codes)

    # A malformed file (not JSON) fails closed with observation.io, never a crash.
    bad = os.path.join(gendir, "obs_notjson.json"); open(bad, "w").write("{ not json")
    rc, d = run(path=bad)
    assert rc == 1 and d["ok"] is False and d["diagnostics"][0]["code"] == "observation.io", ("io", rc, d)
except AssertionError as e:
    print("[75b] FAIL: domain-observation-set validator: " + str(e), file=sys.stderr)
    sys.exit(1)
print("[75b] OK: validator mirrors the normative schema [fields/patterns/consts aligned; no AI field "
      "declared]; committed observation set validates + emits diagnostics/report; bad kind/schemaVersion, "
      "missing/unknown field, malformed content-hash binding, unknown dimension + value, duplicate id, "
      "inverted span, AI-trust field (confidence/reviewStatus/model), malformed-file all fail closed with "
      "stable observation.* codes")
