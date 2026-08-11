#!/usr/bin/env python3
"""Completeness + integrity gate for the core contract bundle ().

Fails CLOSED unless the committed docs/core-contract-bundle.json is a faithful,
current projection of the authoritative contracts, and the core contract set has
not silently drifted:

  (a) INTEGRITY — the bundle's `bundleDigest` recomputes over its canonical body;
  (b) DIGEST-CURRENT — every bundled contract's (and the taxonomy's) `sha256`
      equals the current committed file, so changing a contract without
      regenerating the bundle fails;
  (c) COMPLETENESS — every docs/schemas/*.schema.json is classified as either a
      CORE contract (registered in the bundle) or an explicitly NON-core schema.
      Adding a new schema without registering it in the bundle OR allow-listing
      it as non-core fails here; and the bundle registers EXACTLY the core set.

Determinism + the digest's release-manifest visibility are pinned separately by
the regeneration byte-match (test/ir/bundle/bundle_completeness.test). Standard
library only.

  check_core_contract_bundle.py            # gate the committed bundle
  check_core_contract_bundle.py --selftest # embedded mutation checks
Exit 0 ok / 1 violations / 2 usage.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "scripts", "generators"))
sys.path.insert(0, os.path.join(REPO, "scripts", "validators"))
import make_core_contract_bundle as gen  # noqa: E402
import verify_domain_pack as verifier  # noqa: E402

BUNDLE = "docs/core-contract-bundle.json"
# The PRIOR bundle is read from an IMMUTABLE reference — the integration base in
# git — NOT a same-tree file (which a PR could edit to fake the prior release).
# CI sets NEUTRINO_BUNDLE_BASE to the PR base; default to origin/main.
BASE_REF = os.environ.get("NEUTRINO_BUNDLE_BASE", "origin/main")

_UNSET = object()
_BASE_ERROR = object()  # base ref unresolvable/unreadable/unparseable -> fail closed
# The JSON-Schema keywords the bundled schemas are ALLOWED to use — every one
# must be handled by the released verifier's validator (verify_domain_pack.py),
# so an external consumer can actually enforce the contract. A schema keyword
# outside this set means the verifier would silently ignore it.
COVERED_KEYWORDS = verifier.SUPPORTED_KEYWORDS

# The CORE contract set is the generator's registry (single source of truth).
CORE = [rel for _, _, rel in gen.CONTRACTS]

# docs/schemas that are deliberately NOT part of the external core-contract
# bundle (internal run manifests, superseded/legacy contracts, and the compat/
# proposal side artifacts). Every schema must be in CORE or here — an
# unclassified schema fails completeness, so a new core contract cannot skip
# bundle registration.
NON_CORE = [
    "docs/schemas/agreement-identity.schema.json",
    "docs/schemas/backend-idiom-composition-inventory.schema.json",
    "docs/schemas/component-compatibility-manifest.schema.json",
    "docs/schemas/core-feature-example-matrix.schema.json",
    "docs/schemas/core-contract-bundle.schema.json",  # the bundle's OWN meta-contract
    "docs/schemas/dialect-expansion-manifest.schema.json",
    "docs/schemas/domain-analysis-run-manifest.schema.json",
    "docs/schemas/domain-corpus-manifest.schema.json",
    "docs/schemas/domain-vocabulary-proposal.schema.json",
    "docs/schemas/forge-toolchain-receipt.schema.json",
    "docs/schemas/l2-domain-semantics.schema.json",  # v1, superseded by v2
    "docs/schemas/m6-curated-example-corpus.schema.json",
    "docs/schemas/m7-core-export-overlays.schema.json",
    # Producer/packaging contracts, not domain-pack conformance surface: they
    # describe how the core is INSTALLED and how a release is attested, which a
    # domain pack never validates against.
    "docs/schemas/m7-core-installed-export.schema.json",
    "docs/schemas/m7-core-release-receipt.schema.json",
    "docs/schemas/m7-core-export-report.schema.json",
    "docs/schemas/observation-binding.schema.json",
    "docs/schemas/pressure-loop-register.schema.json",
    "docs/schemas/security-primitive-carveout-registry.schema.json",
    "docs/schemas/semantic-authority-report.schema.json",
    "docs/schemas/semantic-convergence-report.schema.json",
    "docs/schemas/solidity-classification.schema.json",
    "docs/schemas/source-neutral-backend-witness-report.schema.json",
    "docs/schemas/sovereign-lowering-envelope.schema.json",
    "docs/schemas/translation-map.schema.json",
    "docs/schemas/translator-compatibility-manifest.schema.json",
]


def _sha256(root, rel):
    with open(os.path.join(root, rel), "rb") as f:
        return "sha256:" + hashlib.sha256(f.read()).hexdigest()


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def check(root, bundle_rel=BUNDLE, base=_UNSET):
    fails = []
    bundle = json.load(open(os.path.join(root, bundle_rel), encoding="utf-8"))

    # (a) integrity.
    body = {k: v for k, v in bundle.items() if k != "bundleDigest"}
    recomputed = "sha256:" + hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
    if bundle.get("bundleDigest") != recomputed:
        fails.append(f"[bundle.digest] bundleDigest {bundle.get('bundleDigest')} != recomputed {recomputed}")

    # (b) digest-current for every contract + the taxonomy.
    for c in bundle.get("contracts", []):
        rel = c["path"]
        if not os.path.exists(os.path.join(root, rel)):
            fails.append(f"[bundle.missing] contract file {rel!r} does not exist")
        elif _sha256(root, rel) != c["sha256"]:
            fails.append(f"[bundle.stale] contract {rel!r} sha256 differs from the committed file (regenerate the bundle)")
    # The taxonomy is a PUBLISHED artifact (the bundle pins its path + digest), so
    # its ABSENCE is an integrity failure, not a skipped check — a staged tree that
    # drops docs/diagnostic-taxonomy.json must fail, exactly like a missing contract.
    tax = bundle.get("diagnosticTaxonomy")
    if tax is not None:
        tp = tax.get("path")
        if not isinstance(tp, str) or not tp:
            fails.append("[bundle.malformed] diagnosticTaxonomy publishes no 'path' (the bundle pins its digest)")
        elif not os.path.exists(os.path.join(root, tp)):
            fails.append(f"[bundle.missing] diagnostic taxonomy file {tp!r} does not exist (the bundle publishes its path + digest)")
        elif _sha256(root, tp) != tax.get("sha256"):
            fails.append("[bundle.stale] diagnostic taxonomy sha256 differs from the committed file (regenerate the bundle)")

    # The closed semantic-feature vocabulary is a PUBLISHED artifact too (path +
    # digest + pinned semanticProfileVersion) — absence/tamper is a hard failure,
    # and its version must not drift from the bundle's versions.semanticProfileVersion
    # nor from the artifact's own pinned version (vocabulary/bundle drift).
    voc = bundle.get("semanticVocabulary")
    if voc is not None:
        vp = voc.get("path")
        if not isinstance(vp, str) or not vp:
            fails.append("[bundle.malformed] semanticVocabulary publishes no 'path' (the bundle pins its digest)")
        elif not os.path.exists(os.path.join(root, vp)):
            fails.append(f"[bundle.missing] semantic vocabulary file {vp!r} does not exist (the bundle publishes its path + digest)")
        elif _sha256(root, vp) != voc.get("sha256"):
            fails.append("[bundle.stale] semantic vocabulary sha256 differs from the committed file (regenerate the bundle)")
        else:
            art = json.load(open(os.path.join(root, vp), encoding="utf-8"))
            bundle_spv = (bundle.get("versions") or {}).get("semanticProfileVersion")
            if voc.get("semanticProfileVersion") != bundle_spv:
                fails.append(f"[bundle.version] semanticVocabulary.semanticProfileVersion {voc.get('semanticProfileVersion')!r} "
                             f"!= versions.semanticProfileVersion {bundle_spv!r}")
            if art.get("semanticProfileVersion") != voc.get("semanticProfileVersion"):
                fails.append("[bundle.stale] the vocabulary artifact's semanticProfileVersion differs from the bundle's "
                             "pinned value (regenerate the bundle)")

    # (c) completeness: every schema classified; bundle registers exactly CORE.
    on_disk = {os.path.relpath(p, root) for p in glob.glob(os.path.join(root, "docs/schemas/*.schema.json"))}
    classified = set(CORE) | set(NON_CORE)
    for rel in sorted(on_disk - classified):
        fails.append(f"[bundle.unclassified] schema {rel!r} is neither a registered CORE contract nor allow-listed NON-core "
                     "(register it in the bundle generator's CONTRACTS or add it to the gate's NON_CORE)")
    for rel in sorted(classified - on_disk):
        fails.append(f"[bundle.phantom] classified schema {rel!r} does not exist on disk")
    registered = {c["path"] for c in bundle.get("contracts", [])}
    if registered != set(CORE):
        for rel in sorted(set(CORE) - registered):
            fails.append(f"[bundle.unregistered] CORE contract {rel!r} is missing from the bundle")
        for rel in sorted(registered - set(CORE)):
            fails.append(f"[bundle.extra] bundle registers {rel!r} which is not a CORE contract")

    # (d) dialect coverage: every JSON-Schema keyword the bundled schemas use must
    # be handled by the released verifier's validator — both the keyword NAME and
    # the FORM/VALUE it appears in. A keyword name in SUPPORTED_KEYWORDS whose
    # form the validator only partially implements (e.g. `format: email` when only
    # `date-time` is enforced, or a boolean/array `items` when only object-schema
    # `items` is) would be SILENTLY IGNORED by an external consumer, so it fails.
    used = set()
    for c in bundle.get("contracts", []):
        p = os.path.join(root, c["path"])
        if os.path.exists(p):
            schema = json.load(open(p, encoding="utf-8"))
            _collect_keywords(schema, used)
            for v in _collect_dialect(schema, []):
                fails.append(f"[bundle.dialect] contract {c['path']!r}: {v} — the released verifier would "
                             "otherwise silently ignore or mishandle it (fix the schema, or implement the form "
                             "in verify_domain_pack.py)")
    for kw in sorted(used - COVERED_KEYWORDS):
        fails.append(f"[bundle.keyword] bundled schemas use JSON-Schema keyword {kw!r} which "
                     "verify_domain_pack.py does not validate (add it to the validator + SUPPORTED_KEYWORDS)")

    # (e) version evolution: the bundle's public surface may not change without a
    # bundleVersion bump, and a REMOVED/re-versioned contract requires a MAJOR
    # bump. Compared against the IMMUTABLE prior bundle from the integration base.
    # Fail CLOSED if that base cannot be resolved/read — an unavailable base is
    # NOT the same as a genuine first introduction (which is a base commit that
    # specifically lacks the bundle path).
    if base is _UNSET:
        base = _base_bundle(root)
    if base is _BASE_ERROR:
        fails.append(f"[bundle.base] cannot resolve the version-evolution base {BASE_REF!r} "
                     "(fetch it, or set NEUTRINO_BUNDLE_BASE to an available ref); refusing to pass "
                     "without the immutable prior bundle to diff against")
    else:
        fails.extend(_check_version_evolution(bundle, base))
    return fails


# JSON-Schema keys whose VALUE(s) are themselves subschemas — used to walk
# schema positions (so property names / enum values are not mistaken for keywords).
_SUB = {"additionalProperties", "items", "propertyNames", "not", "if", "then", "else"}
_SUB_LIST = {"oneOf", "anyOf", "allOf", "prefixItems"}
_SUB_MAP = {"properties", "$defs", "definitions", "patternProperties", "dependentSchemas"}


def _collect_keywords(node, found):
    if not isinstance(node, dict):
        return
    for k, v in node.items():
        found.add(k)
        if k in _SUB_MAP and isinstance(v, dict):
            for sub in v.values():
                _collect_keywords(sub, found)
        elif k in _SUB_LIST and isinstance(v, list):
            for sub in v:
                _collect_keywords(sub, found)
        elif k in _SUB:
            _collect_keywords(v, found)


# Draft 2020-12 FORM contract for every keyword the verifier supports — the
# ALLOWED value-shape of each, so a covered keyword used in a form the released
# validator would silently ignore (or crash on) is rejected, not just an unknown
# keyword name. Categories: metadata strings; single subschema; array/map of
# subschemas; typed scalars. Keywords NOT listed here that appear in a schema are
# caught by the keyword-coverage check instead.
_KNOWN_TYPES = frozenset({"object", "array", "string", "integer", "number", "boolean", "null"})
_META_STRING = ("$id", "$schema", "$comment", "title", "description")
_SCHEMA_VALUE = ("not", "if", "then", "else", "propertyNames")     # a single subschema
_SCHEMA_ARRAY = ("oneOf", "anyOf", "allOf")                         # array of subschemas
_SCHEMA_MAP = ("properties", "$defs")                              # name -> subschema
_NONNEG_INT = ("minLength", "minItems", "minProperties")
# The complete set of keywords _form_violation dispatches on. A selftest asserts
# this EQUALS verify_domain_pack.SUPPORTED_KEYWORDS, so a keyword added to the
# supported dialect without a form rule fails closed — the form contract cannot
# silently fall behind the keyword set.
_DIALECT_HANDLED = (frozenset(_META_STRING) | frozenset(_SCHEMA_VALUE) | frozenset(_SCHEMA_ARRAY)
                    | frozenset(_SCHEMA_MAP) | frozenset(_NONNEG_INT)
                    | {"$ref", "type", "required", "enum", "const", "pattern", "format",
                       "minimum", "maximum", "uniqueItems", "additionalProperties", "items"})


def _is_subschema(v):
    # A Draft 2020-12 schema is an object or a boolean (true/false), both of which
    # the verifier's _validate handles.
    return isinstance(v, dict) or isinstance(v, bool)


def _form_violation(k, v):
    """The dialect-form violation string for keyword k with value v, or None if the
    form is one the released verifier enforces correctly."""
    if k in _META_STRING:
        return None if isinstance(v, str) else f"{k} must be a string"
    if k == "$ref":
        return None if isinstance(v, str) and v.startswith("#/") else \
            f"$ref {v!r} must be a local '#/…' JSON-pointer string (the only form the verifier resolves)"
    if k == "type":
        if isinstance(v, str):
            return None if v in _KNOWN_TYPES else f"type {v!r} is not a known type name ({sorted(_KNOWN_TYPES)})"
        if isinstance(v, list):
            if not v:
                return "type array must be non-empty"
            bad = [t for t in v if not (isinstance(t, str) and t in _KNOWN_TYPES)]
            if bad:
                return f"type array has invalid name(s) {bad}"
            if len(v) != len(set(v)):
                return "type array must have unique names"
            return None
        return f"type {v!r} must be a type name or an array of them"
    if k == "required":
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            return "required must be an array of property-name strings"
        return None if len(v) == len(set(v)) else "required must have unique property names"
    if k == "enum":
        return None if isinstance(v, list) and v else "enum must be a non-empty array"
    if k == "const":
        return None  # any JSON value
    if k == "pattern":
        if not isinstance(v, str):
            return "pattern must be a string"
        try:
            re.compile(v)
        except re.error as e:
            return f"pattern {v!r} is not a valid regex ({e})"
        return None
    if k == "format":
        return None if isinstance(v, str) and v in verifier.SUPPORTED_FORMATS \
            else f"format {v!r} (verifier enforces only {sorted(verifier.SUPPORTED_FORMATS)})"
    if k in {"minimum", "maximum"}:
        return None if isinstance(v, (int, float)) and not isinstance(v, bool) else f"{k} must be a number"
    if k in _NONNEG_INT:
        return None if isinstance(v, int) and not isinstance(v, bool) and v >= 0 \
            else f"{k} must be a non-negative integer"
    if k == "uniqueItems":
        return None if isinstance(v, bool) else "uniqueItems must be a boolean"
    if k == "additionalProperties":
        return None if isinstance(v, (bool, dict)) else "additionalProperties must be a boolean or an object schema"
    if k == "items":
        return None if isinstance(v, dict) \
            else f"a non-object `items` ({type(v).__name__}); the verifier enforces only object-schema items"
    if k in _SCHEMA_VALUE:
        return None if _is_subschema(v) else f"{k} must be a schema (object or boolean)"
    if k in _SCHEMA_ARRAY:
        # Draft 2020-12 requires a NON-EMPTY array — an empty applicator is a silent
        # accept-all in the verifier (e.g. `for s in schema.get("allOf", [])`).
        return None if isinstance(v, list) and v and all(_is_subschema(s) for s in v) \
            else f"{k} must be a non-empty array of schemas"
    if k in _SCHEMA_MAP:
        return None if isinstance(v, dict) and all(_is_subschema(s) for s in v.values()) \
            else f"{k} must be an object mapping names to schemas"
    return None  # unknown keyword -> keyword-coverage check owns it


def _collect_dialect(node, out):
    """Flag every use of a SUPPORTED keyword whose value has a FORM/VALUE the
    released verifier does not enforce correctly — the constraint would otherwise
    be silently ignored (or crash the validator). Covers the whole supported
    dialect, not a hand-picked subset."""
    if not isinstance(node, dict):
        return out
    for k, v in node.items():
        msg = _form_violation(k, v)
        if msg is not None:
            out.append(msg)
    for k, v in node.items():
        if k in _SUB_MAP and isinstance(v, dict):
            for sub in v.values():
                _collect_dialect(sub, out)
        elif k in _SUB_LIST and isinstance(v, list):
            for sub in v:
                _collect_dialect(sub, out)
        elif k in _SUB and _is_subschema(v):
            _collect_dialect(v, out)
    return out


def _git(root, *args):
    """Run git; return (returncode, stdout bytes). A missing git / OS error is a
    non-zero return (fail closed), never an exception the caller must guard."""
    try:
        r = subprocess.run(["git", "-C", root, *args],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return r.returncode, r.stdout
    except OSError:
        return 1, b""


def _base_bundle(root):
    """The prior bundle read from the IMMUTABLE integration base (git). Returns:
      - the parsed bundle dict, when the base commit carries it;
      - None, ONLY when the base ref resolves but specifically lacks the bundle
        path (a genuine first introduction);
      - _BASE_ERROR, when the base ref cannot be resolved, or its bundle blob
        cannot be read/parsed — an unavailable base must fail closed, not be
        mistaken for a first introduction.
    """
    # (1) the base ref itself must resolve to a commit.
    rc, _ = _git(root, "rev-parse", "--verify", "--quiet", f"{BASE_REF}^{{commit}}")
    if rc != 0:
        return _BASE_ERROR
    # (2) is the bundle path present at that commit? (absent -> first introduction)
    rc, _ = _git(root, "cat-file", "-e", f"{BASE_REF}:{BUNDLE}")
    if rc != 0:
        return None
    # (3) read + parse it; any failure here is fail-closed, not first-introduction.
    rc, out = _git(root, "show", f"{BASE_REF}:{BUNDLE}")
    if rc != 0:
        return _BASE_ERROR
    try:
        return json.loads(out)
    except ValueError:
        return _BASE_ERROR


# Bundle fields normalized OUT of the versioned PUBLIC surface because they are
# genuinely BUILD-DERIVED (the current translator's own version values, which
# move on every tool release) or self-referential (the digest of everything
# else). EVERYTHING NOT listed here — identity (bundleId/kind/schemaVersion),
# canonicalization + hash rules, the compatibility POLICY, the full contract
# records (name/contractId/family/path/sha256), and the taxonomy metadata
# (categories/path/sha256) — is versioned: changing it without a bundleVersion
# bump fails closed. New public fields are included by default (fail toward
# requiring a bump), not silently ignored.
_SURFACE_EXCLUDE_TOP = ("bundleDigest", "bundleVersion", "versions")


def _surface(b):
    """A canonical string over the bundle's versioned PUBLIC surface — the whole
    bundle minus the build-derived/self-referential fields above (and the current
    translator version nested under translatorCompatibility)."""
    s = {k: v for k, v in b.items() if k not in _SURFACE_EXCLUDE_TOP}
    tc = s.get("translatorCompatibility")
    if isinstance(tc, dict):
        # Keep the negotiation POLICY (public, versioned); drop the current tool
        # version value (build-derived).
        s["translatorCompatibility"] = {k: v for k, v in tc.items() if k != "toolVersion"}
    return _canonical(s)


def _semver(v):
    try:
        return [int(x) for x in str(v).split(".")]
    except ValueError:
        return None


def _check_version_evolution(bundle, base):
    if base is None:
        return []  # no prior bundle in the base -> first release of this surface
    if _surface(bundle) == _surface(base):
        return []  # public surface unchanged
    cv, bv = _semver(bundle.get("bundleVersion")), _semver(base.get("bundleVersion"))
    if cv is None or bv is None or cv <= bv:
        return [f"[bundle.version] the bundle's public surface changed but bundleVersion "
                f"{bundle.get('bundleVersion')!r} was not bumped above the base {base.get('bundleVersion')!r}"]
    base_c = {c["name"]: c["contractId"] for c in base.get("contracts", [])}
    cur_c = {c["name"]: c["contractId"] for c in bundle.get("contracts", [])}
    removed = sorted(set(base_c) - set(cur_c))
    reversioned = sorted(n for n in base_c if n in cur_c and cur_c[n] != base_c[n])
    if (removed or reversioned) and cv[0] <= bv[0]:
        return [f"[bundle.version] a BREAKING bundle change (removed {removed} / re-versioned "
                f"{reversioned}) requires a MAJOR bundleVersion bump above {base.get('bundleVersion')!r}"]
    return []


def _probe_validator():
    """Semantic mutation probes — for each supported keyword, a valid instance
    passes and a violating one is caught (not just keyword-name discovery)."""
    V = verifier
    probes = [
        ("type", {"type": "string"}, "x", 1),
        ("const bool!=num", {"const": 1}, 1, True),
        ("enum", {"enum": ["a", "b"]}, "a", "c"),
        ("enum bool!=num", {"enum": [1]}, 1, True),
        ("pattern", {"type": "string", "pattern": "^x$"}, "x", "y"),
        ("minLength", {"type": "string", "minLength": 2}, "xx", "x"),
        ("format date-time", {"type": "string", "format": "date-time"},
         "2026-07-15T00:00:00Z", "2026-99-99T00:00:00Z"),
        ("minimum", {"type": "integer", "minimum": 1}, 1, 0),
        ("minItems", {"type": "array", "minItems": 1}, [1], []),
        ("minProperties", {"type": "object", "minProperties": 1}, {"a": 1}, {}),
        ("uniqueItems num!=bool", {"type": "array", "uniqueItems": True}, [1, True], [1, 1]),
        ("required", {"type": "object", "required": ["a"]}, {"a": 1}, {}),
        ("additionalProperties", {"type": "object", "additionalProperties": False,
                                  "properties": {"a": {}}}, {"a": 1}, {"b": 1}),
        ("propertyNames", {"type": "object", "propertyNames": {"pattern": "^a$"}}, {"a": 1}, {"b": 1}),
        ("oneOf", {"oneOf": [{"type": "integer"}, {"type": "string"}]}, 1, True),
        ("anyOf", {"anyOf": [{"type": "integer"}, {"type": "string"}]}, "x", True),
        ("not", {"not": {"type": "integer"}}, "x", 1),
        ("if/then", {"if": {"type": "integer"}, "then": {"minimum": 5}}, 5, 1),
        ("$ref", {"$defs": {"pos": {"type": "integer", "minimum": 1}}, "$ref": "#/$defs/pos"}, 3, 0),
        ("union type", {"type": ["integer", "string"]}, "x", True),
        ("unknown type fail-closed", {"type": "bogus"}, None, "anything"),
    ]
    bad = []
    for name, schema, good, invalid in probes:
        if good is not None:
            dg = []
            V._validate(good, schema, "p", dg, schema)
            if dg:
                bad.append(f"{name}: valid instance rejected: {dg}")
        di = []
        V._validate(invalid, schema, "p", di, schema)
        if not di:
            bad.append(f"{name}: violating instance NOT caught")
    return bad


def _selftest():
    import copy
    import tempfile
    fails = []
    real = json.load(open(os.path.join(REPO, BUNDLE), encoding="utf-8"))
    if check(REPO):
        fails.append(f"committed bundle rejected: {check(REPO)}")

    vpath = real["semanticVocabulary"]["path"]

    def with_bundle(mutate, extra_schema=None, schema_edit=None, resync=False,
                    omit_taxonomy=False, omit_vocabulary=False, vocab_edit=None):
        d = tempfile.mkdtemp(prefix="bundlegate.")
        os.makedirs(os.path.join(d, "docs", "schemas"))
        for _, _, rel in gen.CONTRACTS:
            os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
            open(os.path.join(d, rel), "w").write(open(os.path.join(REPO, rel)).read())
        tp = real["diagnosticTaxonomy"]["path"]
        if not omit_taxonomy:
            os.makedirs(os.path.dirname(os.path.join(d, tp)), exist_ok=True)
            open(os.path.join(d, tp), "w").write(open(os.path.join(REPO, tp)).read())
        if not omit_vocabulary:
            os.makedirs(os.path.dirname(os.path.join(d, vpath)), exist_ok=True)
            if vocab_edit:  # re-serialize only when mutating (sha changes on purpose)
                art = json.load(open(os.path.join(REPO, vpath), encoding="utf-8"))
                vocab_edit(art)
                json.dump(art, open(os.path.join(d, vpath), "w"))
            else:  # byte-exact copy so the committed digest stays current
                open(os.path.join(d, vpath), "w").write(open(os.path.join(REPO, vpath)).read())
        for rel in NON_CORE:
            os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
            src = os.path.join(REPO, rel)
            open(os.path.join(d, rel), "w").write(open(src).read() if os.path.exists(src) else "{}")
        if extra_schema:
            open(os.path.join(d, extra_schema), "w").write("{}")
        if schema_edit:
            rel, mut = schema_edit
            obj = json.load(open(os.path.join(d, rel)))
            mut(obj)
            json.dump(obj, open(os.path.join(d, rel), "w"))
        b = copy.deepcopy(real)
        if resync:
            # Re-pin the digests to the STAGED files so the tree is internally
            # consistent — the intended SEMANTIC gate is then the sole failure
            # (not an incidental bundle.stale from an unrefreshed schema edit).
            for c in b["contracts"]:
                if os.path.exists(os.path.join(d, c["path"])):
                    c["sha256"] = _sha256(d, c["path"])
            if not omit_taxonomy and os.path.exists(os.path.join(d, tp)):
                b["diagnosticTaxonomy"]["sha256"] = _sha256(d, tp)
            if not omit_vocabulary and os.path.exists(os.path.join(d, vpath)):
                b["semanticVocabulary"]["sha256"] = _sha256(d, vpath)
        mutate(b)
        json.dump(b, open(os.path.join(d, BUNDLE), "w"), indent=2, sort_keys=True)
        return d

    def resign(b):
        b.pop("bundleDigest", None)
        b["bundleDigest"] = "sha256:" + hashlib.sha256(_canonical(b).encode()).hexdigest()

    # each entry: (name, bundle-mutator, extra_schema, schema_edit, base). `base`
    # is the IMMUTABLE prior bundle (None = no prior; a synthetic dict exercises
    # version evolution — the real gate reads it from git, so a PR cannot fake it).
    reversioned = copy.deepcopy(real)
    reversioned["contracts"][0]["contractId"] = reversioned["contracts"][0]["contractId"] + "-x"
    # a base whose contract PATH differs — current==real stays fully valid, so the
    # ONLY thing that can fire is version evolution seeing the surface move.
    moved_base = copy.deepcopy(real)
    moved_base["contracts"][0]["path"] = "docs/schemas/other-path.schema.json"
    cases = [
        ("tampered digest", lambda b: b.update({"bundleDigest": "sha256:" + "0" * 64}), None, None, None),
        ("dropped contract", lambda b: (b.__setitem__("contracts", b["contracts"][:-1]), resign(b)), None, None, None),
        ("stale contract sha", lambda b: (b["contracts"][0].__setitem__("sha256", "sha256:" + "0" * 64), resign(b)), None, None, None),
        # surface changed vs the immutable prior but bundleVersion not bumped:
        ("content change no bump",
         lambda b: (b["contracts"][0].__setitem__("contractId", b["contracts"][0]["contractId"] + "-x"), resign(b)),
         None, None, real),
        # canonicalization/hash rules are PUBLIC + versioned — changing them at the
        # same bundleVersion must fail ( versions the canonicalization rules):
        ("canonicalization change no bump",
         lambda b: (b["canonicalization"].__setitem__("json", "TAMPERED"), resign(b)),
         None, None, real),
        # the compatibility NEGOTIATION POLICY is public + versioned too:
        ("compat policy change no bump",
         lambda b: (b["translatorCompatibility"]["policy"].__setitem__("toolVersion", "changed"), resign(b)),
         None, None, real),
        # a contract path move is a surface change (not invisible) — current is
        # unchanged/valid, the base carries the other path:
        ("contract path change no bump", lambda b: resign(b), None, None, moved_base),
        # a breaking (re-versioned contract) change with only a MINOR bump:
        ("breaking needs major",
         lambda b: (b.__setitem__("bundleVersion", "1.1.0"), resign(b)),
         None, None, reversioned),
    ]
    for name, mutate, extra, sedit, base in cases:
        d = with_bundle(mutate, extra, sedit)
        if not check(d, base=base):
            fails.append(f"mutation not caught: {name}")

    # A newly introduced schema must be rejected for the CLASSIFICATION gap,
    # not merely because some incidental bundle check also happened to fail.
    unclassified = check(
        with_bundle(
            resign,
            extra_schema="docs/schemas/brand-new.schema.json",
        ),
        base=None,
    )
    if not any("[bundle.unclassified]" in failure
               and "brand-new.schema.json" in failure
               for failure in unclassified):
        fails.append(
            "unclassified new schema did not fail with its exact "
            f"bundle.unclassified identity: {unclassified}"
        )

    # NO FALSE POSITIVE: a build-derived translator-version refresh (the current
    # tool version values) is NOT a public-surface change, so it must NOT demand a
    # bundleVersion bump — otherwise every tool release would force one.
    d = with_bundle(lambda b: (b["versions"].__setitem__("toolVersion", "0.9.9"),
                               b["translatorCompatibility"].__setitem__("toolVersion", "0.9.9"),
                               resign(b)))
    if check(d, base=real):
        fails.append("translator-version refresh wrongly flagged as a surface change (over-fires the bump gate)")

    # FAIL CLOSED on an unavailable base: an explicit _BASE_ERROR must be rejected,
    # and an unresolvable ref must map to _BASE_ERROR (not a silent first-intro).
    if not check(REPO, base=_BASE_ERROR):
        fails.append("an unavailable version-evolution base was not fail-closed")
    saved = globals().get("BASE_REF")
    try:
        globals()["BASE_REF"] = "neutrino-definitely-missing-base-ref"
        if _base_bundle(REPO) is not _BASE_ERROR:
            fails.append("an unresolvable base ref did not map to _BASE_ERROR (fails open)")
    finally:
        globals()["BASE_REF"] = saved

    # GATE-TRAVERSING semantic probes (through check(), not only direct validator
    # probes): each stages an internally-consistent tree (digests resynced) so the
    # SOLE remaining failure is the intended semantic gate, asserted by CODE.
    bp = "docs/schemas/binding-policy.schema.json"

    def gate_fails(**kw):
        return check(with_bundle(resign, resync=True, **kw), base=None)

    # Dialect probes ACROSS keyword categories (schema-array, array-of-strings,
    # numeric, type-name, $ref, format, items) — a malformed FORM of a covered
    # keyword must be `bundle.dialect`, so the check cannot regress to a two-case
    # list. Each injects the malformed schema as a property and runs the real gate.
    def _inject(prop_schema):
        return (bp, lambda s: s.setdefault("properties", {}).__setitem__("_probe", prop_schema))

    dialect_probes = [
        ("format value", {"type": "string", "format": "email"}),
        ("non-object items", {"type": "array", "items": True}),
        ("oneOf not an array", {"oneOf": {"type": "string"}}),
        ("empty allOf (silent accept-all)", {"allOf": []}),
        ("empty oneOf", {"oneOf": []}),
        ("empty anyOf", {"anyOf": []}),
        ("enum not an array", {"enum": "ab"}),
        ("minimum not a number", {"minimum": "1"}),
        ("required not a string array", {"type": "object", "required": "x"}),
        ("non-unique required", {"type": "object", "required": ["x", "x"]}),
        ("unknown type name", {"type": "strng"}),
        ("empty type array", {"type": []}),
        ("non-unique type array", {"type": ["string", "string"]}),
        ("non-local $ref", {"$ref": "http://example/x"}),
        ("non-integer minItems", {"type": "array", "minItems": "1"}),
    ]
    for name, ps in dialect_probes:
        f = gate_fails(schema_edit=_inject(ps))
        if not any("bundle.dialect" in x for x in f):
            fails.append(f"dialect probe not caught by the gate ({name}): {f}")

    # STRUCTURAL completeness: every supported keyword has a form rule, so the
    # dialect contract cannot silently fall behind the keyword set (this is what
    # stops the check regressing to a hand-picked subset).
    missing_rule = verifier.SUPPORTED_KEYWORDS - _DIALECT_HANDLED
    extra_rule = _DIALECT_HANDLED - verifier.SUPPORTED_KEYWORDS
    if missing_rule:
        fails.append(f"supported keyword(s) have NO dialect form rule: {sorted(missing_rule)}")
    if extra_rule:
        fails.append(f"dialect form rule for non-supported keyword(s): {sorted(extra_rule)}")

    # an UNCOVERED keyword name -> bundle.keyword (specific, through the real gate).
    f = gate_fails(schema_edit=(bp, lambda s: s.__setitem__("maxLength", 5)))
    if not any("bundle.keyword" in x for x in f):
        fails.append(f"uncovered keyword not caught specifically by the gate (got {f})")

    # the PUBLISHED taxonomy file is ABSENT -> bundle.missing (integrity is not
    # conditional on the file already existing).
    f = check(with_bundle(resign, resync=True, omit_taxonomy=True), base=None)
    if not any("bundle.missing" in x for x in f):
        fails.append(f"missing published taxonomy file not caught by the gate (got {f})")

    # the PUBLISHED semantic vocabulary is ABSENT -> bundle.missing.
    f = check(with_bundle(resign, resync=True, omit_vocabulary=True), base=None)
    if not any("bundle.missing" in x for x in f):
        fails.append(f"missing published semantic vocabulary not caught by the gate (got {f})")

    # the vocabulary artifact's pinned version DRIFTS from the bundle -> bundle.stale.
    f = check(with_bundle(resign, resync=True,
                          vocab_edit=lambda a: a.__setitem__("semanticProfileVersion", 999)), base=None)
    if not any("bundle.stale" in x or "bundle.version" in x for x in f):
        fails.append(f"vocabulary version drift not caught by the gate (got {f})")

    # a tampered vocabulary (digest no longer current) -> bundle.stale.
    f = check(with_bundle(resign, vocab_edit=lambda a: a["features"].append("x:tampered")), base=None)
    if not any("bundle.stale" in x for x in f):
        fails.append(f"tampered semantic vocabulary not caught by the gate (got {f})")

    fails.extend(f"validator probe: {p}" for p in _probe_validator())

    if fails:
        for f in fails:
            print(f"[bundle.selftest] {f}", file=sys.stderr)
        return 1
    print("ok (selftest)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    fails = check(REPO)
    if fails:
        for f in fails:
            print(f"  - {f}")
        print(f"core-contract-bundle gate: {len(fails)} problem(s)")
        return 1
    print(f"core-contract-bundle gate OK: {len(gen.CONTRACTS)} core contracts registered, digests current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
