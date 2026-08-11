#!/usr/bin/env python3
"""M5 WP1d () — canonical executable capability spec validation.

The capability spec (`neutrino-gen --target=capability-spec`) is the ONLY frozen external contract
of the M5 architecture (ADR D1): every renderer, and the agents/network/console consumers,
build on it. It must therefore be validated **independently of any backend**, fail-closed.
This is that gate.

The normative shape is `docs/schemas/capability-spec.schema.json`; this validator **mirrors**
it (CI runs this stdlib script, not a JSON-Schema library) AND enforces the invariants a schema
cannot express:

  - `identity.capabilityHash` = sha256(compact(semantic core: spec \ identity \ sourceMap \ targetRequirements \ kind \ schemaVersion)); `identity.specHash`
    = sha256(compact(spec \\ identity.specHash)) — recomputed here, so any tamper / rename is
    caught (hash-stability, D6);
  - every compute `deps` entry and every `ref` operand resolves to a declared input/compute;
  - every effect `participant` (when non-null) resolves to a declared participant;
  - every lifecycle transition `from`/`to`, the `initialState`, and each `terminalStates` value
    resolve to a declared state; a state's `terminalKind` implies `terminal:true`.

`compact` is `json.dumps(sort_keys=True, separators=(",", ":"))` — the exact form the C++
emitter hashes (llvm json prints sorted-key compact), so the recomputed digests match byte-for
-byte. Diagnostics are machine-readable `{code, severity, message}` under the stable `spec.*`
family (shared failure-taxonomy direction, ), sorted.

Emits `spec.report.json` + `diagnostics.json` when `--out DIR` is given; prints the
`neutrino.capability-spec-validation` report — `{kind, schemaVersion, ok, capabilityHash,
specHash, diagnostics}` — to stdout. The report is a version-pinned translator->build-tools
contract (`docs/schemas/capability-spec-validation.schema.json`, `$id .../v1`, ). It names
the validated spec's identity so a consumer can BIND it to a specific capability-spec (): an
`ok:true` report attests the declared identity matches the spec's content (validate() recomputes
it, fail-closed). `ok` iff no error diagnostics. Exit 0 ok / 1 violations / 2 usage.

  validate_capability_spec.py FILE [--out DIR]
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys

# Supported spec schema versions (/): 1 (unguarded), 2 (any effect `when`), 3 (attestation).
SCHEMA_VERSIONS = {1, 2, 3, 4}
# The validation-report contract (): a translator->build-tools contract, so it is versioned +
# schema-pinned (docs/schemas/capability-spec-validation.schema.json, $id .../v1) — a consumer
# checks kind + schemaVersion before trusting the report so the shape cannot drift silently.
REPORT_KIND = "neutrino.capability-spec-validation"
REPORT_SCHEMA_VERSION = 1
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
CATEGORIES = {"money", "decimal", "party", "currency", "evidence", "string", "extension"}

TOP_FIELDS = {"schemaVersion", "kind", "specVersion", "procedure", "trigger", "identity",
              "inputs", "computes", "effects", "invariants", "participants", "topology",
              "lifecycle", "targetRequirements", "sourceMap"}

# Optional top-level sections — present only when the source declares the feature, so they stay OUT
# of TOP_FIELDS (the required set the schema mirror asserts). `attestations` (oracle S1, ) is
# rendered only when an evidence input carries an M-of-N attestation policy; an unattested spec omits
# it (byte-identical), so it is allowed-but-not-required.
OPTIONAL_TOP_FIELDS = {"attestations", "obligations"}

# Field-specific schema-rejection codes () for the binding/lifecycle enum fields, so a consumer/gate
# binds to a specific field rejection rather than the generic `spec.schema`. Per the settled "reuse
# existing semantic codes" direction, the four binding/attestation fields REUSE the existing ACTIVE
# kernel.binding.*/kernel.attest.* codes (now emitter Both), and only the three synthesized-lifecycle
# fields carry genuinely new spec.* codes (DiagnosticTaxonomy.def ordinals 199-201). All seven are
# structural — like `spec.schema`, they must block hash recomputation below.
FIELD_CODES = (
    "kernel.attest.invalid_assurance", "kernel.attest.invalid_independence",
    "kernel.binding.invalid_mode", "kernel.binding.invalid_assurance",
    "spec.terminal_kind", "spec.transition_idempotency", "spec.transition_effect",
)

# Mirror of the frozen leaf contract (Neutrino/Attestation.h): the accepted canonicalization modes,
# quorum-timeout fallbacks, and the optional observer-set trust metadata (oracle S6, ). Kept in
# sync with attestation{CanonicalizationModes,Fallbacks,AssuranceTiers,IndependenceModes}().
ATTEST_CANON_MODES = {"exact", "median"}
ATTEST_FALLBACKS = {"abort", "escalate"}
ATTEST_ASSURANCE_TIERS = {"A1", "A2", "A3", "A4"}
ATTEST_INDEPENDENCE = {"independent", "correlated"}


def diag(code: str, message: str, severity: str = "error") -> dict:
    return {"code": code, "severity": severity, "message": message}


def _compact(o) -> str:
    # ensure_ascii=False so non-ASCII stays raw UTF-8, matching the C++ emitter's llvm::json
    # compact print (which does NOT \u-escape). With the default ensure_ascii=True a single
    # non-ASCII byte in any literal (a ledger/party string the lexer allows) would make the
    # recomputed digest diverge — a false tamper alarm on a valid spec ( F5).
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _s(v) -> bool:
    return isinstance(v, str) and v != ""


def _validate_expr(node, where: str, out: list) -> None:
    if not isinstance(node, dict):
        out.append(diag("spec.schema", f"{where}: ast node must be an object"))
        return
    allowed = {"kind", "dtype", "num", "name", "op", "lhs", "rhs", "args"}
    for k in set(node) - allowed:
        out.append(diag("spec.unknown_field", f"{where}: unknown ast field '{k}'"))
    if node.get("dtype") not in CATEGORIES:
        out.append(diag("spec.bad_category", f"{where}: ast dtype '{node.get('dtype')}' not a value category"))
    kind = node.get("kind")
    if kind == "num":
        if not isinstance(node.get("num"), int) or isinstance(node.get("num"), bool):
            out.append(diag("spec.schema", f"{where}: num node needs integer 'num'"))
    elif kind == "var":
        if not _s(node.get("name")):
            out.append(diag("spec.schema", f"{where}: var node needs 'name'"))
    elif kind == "bin":
        if node.get("op") not in {"+", "-", "*", "/"}:
            out.append(diag("spec.schema", f"{where}: bin node op '{node.get('op')}' invalid"))
        _validate_expr(node.get("lhs"), where + ".lhs", out)
        _validate_expr(node.get("rhs"), where + ".rhs", out)
    elif kind == "call":
        if not _s(node.get("name")):
            out.append(diag("spec.schema", f"{where}: call node needs 'name'"))
        args = node.get("args")
        if not isinstance(args, list):
            out.append(diag("spec.schema", f"{where}: call node needs 'args' array"))
        else:
            for i, a in enumerate(args):
                _validate_expr(a, f"{where}.args[{i}]", out)
    elif kind == "cmp":
        # A guard comparison predicate (): op is a comparison, operands are values.
        if node.get("op") not in {"<", "<=", ">", ">=", "==", "!="}:
            out.append(diag("spec.schema", f"{where}: cmp node op '{node.get('op')}' invalid"))
        _validate_expr(node.get("lhs"), where + ".lhs", out)
        _validate_expr(node.get("rhs"), where + ".rhs", out)
    else:
        out.append(diag("spec.schema", f"{where}: ast kind '{kind}' invalid"))


def _expr_vars(node) -> set:
    # Collect the variable names referenced anywhere in an ast (var/bin/call/cmp).
    if not isinstance(node, dict):
        return set()
    if node.get("kind") == "var":
        return {node.get("name")} if isinstance(node.get("name"), str) else set()
    out = set()
    for child in ("lhs", "rhs"):
        out |= _expr_vars(node.get(child))
    for a in node.get("args", []) if isinstance(node.get("args"), list) else []:
        out |= _expr_vars(a)
    return out


def _str_array(container, key: str, where: str, out: list) -> None:
    # The schema mirror for a required array-of-non-empty-strings field. A non-array (or a
    # non-string element) fails closed rather than being silently coerced.
    v = container.get(key)
    if not isinstance(v, list) or any(not _s(x) for x in v):
        out.append(diag("spec.schema", f"{where}.{key} must be an array of non-empty strings"))


def _validate_source(src, where: str, out: list) -> None:
    # A source span is null or {line, column} with both 1-based integers ( F3).
    if src is None:
        return
    if not (isinstance(src, dict) and set(src) == {"line", "column"}
            and all(isinstance(src.get(x), int) and not isinstance(src.get(x), bool)
                    and src.get(x) >= 1 for x in ("line", "column"))):
        out.append(diag("spec.schema", f"{where}: source must be null or {{line, column}} (>=1)"))


def _validate_operand(op, where: str, out: list) -> None:
    if not isinstance(op, dict):
        out.append(diag("spec.schema", f"{where}: operand must be an object"))
        return
    for k in set(op) - {"kind", "value"}:
        out.append(diag("spec.unknown_field", f"{where}: unknown operand field '{k}'"))
    if op.get("kind") not in {"ref", "literal"}:
        out.append(diag("spec.schema", f"{where}: operand kind must be ref|literal"))
    if not _s(op.get("value")):
        out.append(diag("spec.schema", f"{where}: operand needs a non-empty value"))


def _exact_object(obj, allowed: set, where: str, out: list) -> bool:
    # Mirror one schema object with additionalProperties:false + a required key set: reject a
    # non-object, any unknown field, and any missing field (fail-closed like the top-level check).
    # Returns True iff `obj` is an object with EXACTLY `allowed` (so callers can then type its fields).
    if not isinstance(obj, dict):
        out.append(diag("spec.schema", f"{where}: must be an object"))
        return False
    ok = True
    for k in sorted(set(obj) - allowed):
        out.append(diag("spec.schema", f"{where}: unknown field '{k}'"))
        ok = False
    for k in sorted(allowed - set(obj)):
        out.append(diag("spec.schema", f"{where}: missing '{k}'"))
        ok = False
    return ok


def _str_or_null(v, where: str, out: list) -> None:
    if not (v is None or isinstance(v, str)):
        out.append(diag("spec.schema", f"{where} must be a string or null"))


def _validate_attestations(spec, out: list) -> None:
    # The attestation policies (oracle S1, ) — optional; when present it must be an array of
    # well-formed M-of-N policies. FULLY mirrors the schema's attestationPolicy $def (required field
    # sets + additionalProperties:false at every nested level) — CI/admission run THIS validator, not
    # a JSON-Schema lib, so a partial mirror would admit malformed contracts (recurring lesson). Only
    # the threshold M and the observer-set REFERENCE are portable; the concrete N/members are
    # binding-level and are caught here as unknown fields.
    if "attestations" not in spec:
        return
    arr = spec.get("attestations")
    if not isinstance(arr, list):
        out.append(diag("spec.schema", "attestations must be an array"))
        return
    for i, p in enumerate(arr):
        w = f"attestations[{i}]"
        if not _exact_object(p, {"input", "quorum", "observerSet", "canonicalization",
                                 "timeout", "fallback"}, w, out):
            continue
        if not _s(p.get("input")):
            out.append(diag("spec.schema", f"{w}.input must reference an evidence input"))
        q = p.get("quorum")
        if _exact_object(q, {"threshold"}, f"{w}.quorum", out):
            t = q.get("threshold")
            if not (isinstance(t, int) and not isinstance(t, bool) and t > 0):
                out.append(diag("spec.schema", f"{w}.quorum.threshold (M) must be a positive integer"))
        os_ = p.get("observerSet")
        # ref/role are required; assurance/independence (oracle S6, ) are OPTIONAL — the key is
        # present ONLY when declared, so a pre-S6 attestation keeps its exact {ref,role} shape (and
        # capabilityHash). Enforce the same additionalProperties:false as the schema: no key outside
        # the allowed set, both required keys present, each optional value in-set when present.
        if isinstance(os_, dict):
            for k in sorted(set(os_) - {"ref", "role", "assurance", "independence"}):
                out.append(diag("spec.schema", f"{w}.observerSet: unknown field '{k}'"))
            for k in sorted({"ref", "role"} - set(os_)):
                out.append(diag("spec.schema", f"{w}.observerSet: missing '{k}'"))
            if not _s(os_.get("ref")):
                out.append(diag("spec.schema", f"{w}.observerSet.ref must be a non-empty reference"))
            if "role" in os_:
                _str_or_null(os_.get("role"), f"{w}.observerSet.role", out)
            if "assurance" in os_ and os_["assurance"] not in ATTEST_ASSURANCE_TIERS:
                out.append(diag("kernel.attest.invalid_assurance", f"{w}.observerSet.assurance, when present, must be one of {sorted(ATTEST_ASSURANCE_TIERS)}"))
            if "independence" in os_ and os_["independence"] not in ATTEST_INDEPENDENCE:
                out.append(diag("kernel.attest.invalid_independence", f"{w}.observerSet.independence, when present, must be one of {sorted(ATTEST_INDEPENDENCE)}"))
        else:
            out.append(diag("spec.schema", f"{w}.observerSet: must be an object"))
        c = p.get("canonicalization")
        if _exact_object(c, {"mode", "tolerance"}, f"{w}.canonicalization", out):
            if c.get("mode") not in ATTEST_CANON_MODES:
                out.append(diag("spec.schema", f"{w}.canonicalization.mode must be one of {sorted(ATTEST_CANON_MODES)}"))
            _str_or_null(c.get("tolerance"), f"{w}.canonicalization.tolerance", out)
        _str_or_null(p.get("timeout"), f"{w}.timeout", out)
        if p.get("fallback") not in ATTEST_FALLBACKS:
            out.append(diag("spec.schema", f"{w}.fallback must be one of {sorted(ATTEST_FALLBACKS)}"))


def _validate_obligations(spec, out: list) -> None:
    # Obligations () — optional; when present, an array of well-formed first-class
    # undertakings mirroring the schema $def + assemblePlan's structural checks: a versioned
    # identity, obligor/scope, the ORDERED effect references, the lifecycle status vocabulary,
    # and the typed activation predicate (expr + ast). Order is part of identity, so `effects`
    # is validated as a non-empty ordered array (not a set).
    if "obligations" not in spec:
        return
    arr = spec.get("obligations")
    if not isinstance(arr, list):
        out.append(diag("spec.schema", "obligations must be an array"))
        return
    for i, o in enumerate(arr):
        w = f"obligations[{i}]"
        # `statuses` is version-DERIVED and NOT on the wire ( P1-3): the exact
        # object forbids it, so an injected/tampered vocabulary is rejected, not
        # silently trusted. The lifecycle vocabulary is defined by `version`.
        if not _exact_object(o, {"version", "name", "obligor", "beneficiary", "authority",
                                 "effects", "when"}, w, out):
            continue
        if o.get("version") != 1:
            out.append(diag("spec.schema_version", f"{w}.version must be 1 (the  obligation representation)"))
        for k in ("name", "obligor", "beneficiary", "authority"):
            if not _s(o.get(k)):
                out.append(diag("spec.schema", f"{w}.{k} must be a non-empty string"))
        _str_array(o, "effects", w, out)
        if isinstance(o.get("effects"), list) and not o["effects"]:
            out.append(diag("spec.schema", f"{w}.effects must be non-empty"))
        when = o.get("when")
        if not (isinstance(when, dict) and set(when) == {"expr", "ast"}):
            out.append(diag("spec.schema", f"{w}.when must be {{expr, ast}}"))
        else:
            if not _s(when.get("expr")):
                out.append(diag("spec.schema", f"{w}.when.expr must be a non-empty string"))
            _validate_expr(when.get("ast"), f"{w}.when.ast", out)


def validate(spec) -> list:
    out: list = []
    if not isinstance(spec, dict):
        return [diag("spec.schema", "top-level must be a JSON object")]

    for k in sorted(set(spec) - TOP_FIELDS - OPTIONAL_TOP_FIELDS):
        out.append(diag("spec.unknown_field", f"top-level: unknown field '{k}'"))
    for k in sorted(TOP_FIELDS - set(spec)):
        out.append(diag("spec.missing_field", f"top-level: missing '{k}'"))
    _validate_attestations(spec, out)
    _validate_obligations(spec, out)

    # Conditional versioning — MIRRORS lib/targets/CapabilitySpecTarget.cpp capabilitySpecSchemaVersion (/): an
    # attestation policy is schemaVersion 3 (a consumer that IGNORES it would deploy the coordination
    # WITHOUT the M-of-N guard — unsafe), and attestation SUBSUMES the `when` bump (3 whether or not the
    # spec also carries a `when`); any effect `when` guard alone is schemaVersion 2 (a v1 consumer must
    # refuse); an unguarded spec is 1.
    effs = spec.get("effects") if isinstance(spec.get("effects"), list) else []
    if spec.get("obligations"):
        #  P1-2: an obligation-bearing spec is schemaVersion 4 and validates
        # against the capability-spec/v2 contract (which admits `obligations`);
        # a pre-4 consumer must refuse it. Obligation subsumes attestation/guard.
        expected_version = 4
    elif spec.get("attestations"):
        expected_version = 3
    elif any(isinstance(e, dict) and e.get("when") is not None for e in effs):
        expected_version = 2
    else:
        expected_version = 1
    if spec.get("schemaVersion") != expected_version:
        reason = {1: "an unguarded spec is 1", 2: "a guarded spec is 2",
                  3: "an attested spec is 3", 4: "an obligation-bearing spec is 4"}[expected_version]
        out.append(diag("spec.schema_version",
                        f"schemaVersion must be {expected_version} ({reason})"))
    if spec.get("kind") != "neutrino.capability-spec":
        out.append(diag("spec.schema", "kind must be 'neutrino.capability-spec'"))
    if not (isinstance(spec.get("specVersion"), str) and SEMVER.match(spec.get("specVersion", ""))):
        out.append(diag("spec.schema", "specVersion must be a semver string"))
    if not _s(spec.get("procedure")):
        out.append(diag("spec.schema", "procedure must be a non-empty string"))
    if not (spec.get("trigger") is None or _s(spec.get("trigger"))):
        out.append(diag("spec.schema", "trigger must be a string or null"))

    # identity + hashes (recomputed below once structure is known-shaped).
    ident = spec.get("identity")
    if not isinstance(ident, dict) or set(ident) != {"capabilityHash", "specHash"}:
        out.append(diag("spec.schema", "identity must be {capabilityHash, specHash}"))
    else:
        for h in ("capabilityHash", "specHash"):
            if not (isinstance(ident[h], str) and HEX64.match(ident[h])):
                out.append(diag("spec.bad_hash", f"identity.{h} must be 64-hex"))

    # Every top-level array section MUST be an array. Without this a non-list section
    # (e.g. `computes: {}`) would be silently coerced to empty by the loops below and pass
    # as hash-valid — the frozen contract's gate must reject it.
    for key in ("inputs", "computes", "effects", "invariants", "participants", "sourceMap"):
        if key in spec and not isinstance(spec[key], list):
            out.append(diag("spec.schema", f"{key} must be an array"))

    # inputs
    input_names, compute_names = set(), set()
    for i, it in enumerate(spec.get("inputs", []) if isinstance(spec.get("inputs"), list) else []):
        w = f"inputs[{i}]"
        if not isinstance(it, dict):
            out.append(diag("spec.schema", f"{w}: must be an object")); continue
        for k in set(it) - {"name", "type", "category"}:
            out.append(diag("spec.unknown_field", f"{w}: unknown field '{k}'"))
        if not _s(it.get("name")):
            out.append(diag("spec.schema", f"{w}: name required"))
        else:
            input_names.add(it["name"])
        if not _s(it.get("type")):
            out.append(diag("spec.schema", f"{w}: type required"))
        if it.get("category") not in CATEGORIES:
            out.append(diag("spec.bad_category", f"{w}: category '{it.get('category')}' invalid"))

    # computes (+ ast). Collect names first so deps can resolve forward references too.
    computes = spec.get("computes", []) if isinstance(spec.get("computes"), list) else []
    for c in computes:
        if isinstance(c, dict) and _s(c.get("name")):
            compute_names.add(c["name"])
    declared = input_names | compute_names
    for i, c in enumerate(computes):
        w = f"computes[{i}]"
        if not isinstance(c, dict):
            out.append(diag("spec.schema", f"{w}: must be an object")); continue
        for k in set(c) - {"name", "expr", "category", "deps", "ast"}:
            out.append(diag("spec.unknown_field", f"{w}: unknown field '{k}'"))
        if not _s(c.get("expr")):
            out.append(diag("spec.schema", f"{w}: expr required"))
        if c.get("category") not in CATEGORIES:
            out.append(diag("spec.bad_category", f"{w}: category '{c.get('category')}' invalid"))
        deps = c.get("deps")
        if not isinstance(deps, list):
            out.append(diag("spec.schema", f"{w}: deps must be an array"))
        else:
            for d in deps:
                if d not in declared:
                    out.append(diag("spec.unresolved_dep", f"{w}: dep '{d}' is not a declared input/compute"))
        _validate_expr(c.get("ast"), f"{w}.ast", out)

    # effects (+ operands, ref resolution, participant resolution)
    participant_names = set()
    for p in (spec.get("participants", []) if isinstance(spec.get("participants"), list) else []):
        if isinstance(p, dict) and _s(p.get("name")):
            participant_names.add(p["name"])
    for i, e in enumerate(spec.get("effects", []) if isinstance(spec.get("effects"), list) else []):
        w = f"effects[{i}]"
        if not isinstance(e, dict):
            out.append(diag("spec.schema", f"{w}: must be an object")); continue
        allowed = {"kind", "name", "ledger", "owner", "participant", "party", "amount",
                   "currency", "idempotencyKey", "when", "memo"}
        for k in set(e) - allowed:
            out.append(diag("spec.unknown_field", f"{w}: unknown field '{k}'"))
        # Optional effect metadata (M5 token S3, ): a free-text memo/reference. Additive —
        # present only when declared; a non-empty string when present.
        if "memo" in e and not _s(e.get("memo")):
            out.append(diag("spec.schema", f"{w}.memo: must be a non-empty string"))
        # Optional conditional guard (): `when` is {expr, ast} where ast is a
        # cmp predicate. Additive + backward-compatible (absent on unguarded legs).
        when = e.get("when")
        if when is not None:
            if not isinstance(when, dict) or set(when) - {"expr", "ast"}:
                out.append(diag("spec.schema", f"{w}.when: must be an object {{expr, ast}}"))
            else:
                if not _s(when.get("expr")):
                    out.append(diag("spec.schema", f"{w}.when: expr required"))
                _validate_expr(when.get("ast"), f"{w}.when.ast", out)
                if isinstance(when.get("ast"), dict) and when["ast"].get("kind") != "cmp":
                    out.append(diag("spec.schema", f"{w}.when.ast: guard must be a cmp predicate"))
                # every guard variable must resolve to a declared input/compute — the frozen
                # external contract fails closed on a smuggled undeclared guard var, not only
                # the source parser.
                for vn in _expr_vars(when.get("ast")):
                    if vn not in declared:
                        out.append(diag("spec.unresolved_ref",
                                        f"{w}.when.ast: var '{vn}' is not a declared input/compute"))
        if e.get("kind") not in {"debit", "credit"}:
            out.append(diag("spec.schema", f"{w}: kind must be debit|credit"))
        for f in ("name", "ledger", "owner"):
            if not _s(e.get(f)):
                out.append(diag("spec.schema", f"{w}: {f} required"))
        part = e.get("participant")
        if part is not None:
            if not _s(part):
                out.append(diag("spec.schema", f"{w}: participant must be string|null"))
            elif part not in participant_names:
                out.append(diag("spec.unresolved_participant", f"{w}: participant '{part}' not declared"))
        for f in ("party", "amount", "currency", "idempotencyKey"):
            op = e.get(f)
            _validate_operand(op, f"{w}.{f}", out)
            if isinstance(op, dict) and op.get("kind") == "ref" and op.get("value") not in declared:
                out.append(diag("spec.unresolved_ref", f"{w}.{f}: ref '{op.get('value')}' not a declared input/compute"))

    # invariants
    for i, inv in enumerate(spec.get("invariants", []) if isinstance(spec.get("invariants"), list) else []):
        if not (isinstance(inv, dict) and inv.get("kind") == "balanced" and set(inv) == {"kind"}):
            out.append(diag("spec.schema", f"invariants[{i}]: must be {{kind: balanced}}"))

    # participants
    for i, p in enumerate(spec.get("participants", []) if isinstance(spec.get("participants"), list) else []):
        w = f"participants[{i}]"
        if not isinstance(p, dict):
            out.append(diag("spec.schema", f"{w}: must be an object")); continue
        allowed = {"name", "role", "org", "capabilities", "binding", "bindRuntimes", "bindMinAssurance"}
        for k in set(p) - allowed:
            out.append(diag("spec.unknown_field", f"{w}: unknown field '{k}'"))
        if not _s(p.get("name")):
            out.append(diag("spec.schema", f"{w}: name required"))
        if p.get("binding") not in {"fixed", "to_be_bound"}:
            out.append(diag("kernel.binding.invalid_mode", f"{w}: binding must be fixed|to_be_bound"))
        if p.get("bindMinAssurance") not in {"", "A1", "A2", "A3", "A4"}:
            out.append(diag("kernel.binding.invalid_assurance", f"{w}: bindMinAssurance invalid"))
        _str_array(p, "capabilities", w, out)
        _str_array(p, "bindRuntimes", w, out)

    # topology (previously unvalidated)
    topo = spec.get("topology")
    if not isinstance(topo, dict):
        out.append(diag("spec.schema", "topology must be an object"))
    else:
        for k in set(topo) - {"allowedOrgPairs"}:
            out.append(diag("spec.unknown_field", f"topology: unknown field '{k}'"))
        pairs = topo.get("allowedOrgPairs")
        if not isinstance(pairs, list):
            out.append(diag("spec.schema", "topology.allowedOrgPairs must be an array"))
        else:
            for i, pr in enumerate(pairs):
                w = f"topology.allowedOrgPairs[{i}]"
                if not isinstance(pr, dict):
                    out.append(diag("spec.schema", f"{w}: must be an object")); continue
                for k in set(pr) - {"orgA", "orgB", "roleA", "roleB"}:
                    out.append(diag("spec.unknown_field", f"{w}: unknown field '{k}'"))
                for k in ("orgA", "orgB"):
                    if not _s(pr.get(k)):
                        out.append(diag("spec.schema", f"{w}: {k} required"))
                for k in ("roleA", "roleB"):
                    if not isinstance(pr.get(k), str):
                        out.append(diag("spec.schema", f"{w}: {k} must be a string"))

    # sourceMap (was previously unvalidated)
    for i, sm in enumerate(spec.get("sourceMap", []) if isinstance(spec.get("sourceMap"), list) else []):
        w = f"sourceMap[{i}]"
        if not isinstance(sm, dict):
            out.append(diag("spec.schema", f"{w}: must be an object")); continue
        for k in set(sm) - {"specPath", "construct", "source"}:
            out.append(diag("spec.unknown_field", f"{w}: unknown field '{k}'"))
        if not _s(sm.get("specPath")):
            out.append(diag("spec.schema", f"{w}: specPath required"))
        if not _s(sm.get("construct")):
            out.append(diag("spec.schema", f"{w}: construct required"))
        if "source" not in sm:
            out.append(diag("spec.missing_field", f"{w}: missing 'source' (use null if unset)"))
        else:
            _validate_source(sm.get("source"), w, out)

    # lifecycle
    _validate_lifecycle(spec.get("lifecycle"), out)

    # targetRequirements (shape only; content is derived, cross-checks kept light)
    tr = spec.get("targetRequirements")
    if not isinstance(tr, dict):
        out.append(diag("spec.schema", "targetRequirements must be an object"))
    else:
        need = {"requirements", "evidenceStyle", "unsupportedConstructs"}
        for k in sorted(set(tr) - need):
            out.append(diag("spec.unknown_field", f"targetRequirements: unknown field '{k}'"))
        for k in sorted(need - set(tr)):
            out.append(diag("spec.missing_field", f"targetRequirements: missing '{k}'"))
        reqs = tr.get("requirements")
        if not isinstance(reqs, list):
            out.append(diag("spec.schema", "targetRequirements.requirements must be an array"))
        else:
            for i, r in enumerate(reqs):
                w = f"targetRequirements.requirements[{i}]"
                if not isinstance(r, dict):
                    out.append(diag("spec.schema", f"{w}: must be an object")); continue
                for k in set(r) - {"feature", "primitive", "source", "requirement", "fallback"}:
                    out.append(diag("spec.unknown_field", f"{w}: unknown field '{k}'"))
                for k in ("feature", "primitive"):
                    if not _s(r.get(k)):
                        out.append(diag("spec.schema", f"{w}: {k} required"))
                if r.get("requirement") not in {"required", "optional"}:
                    out.append(diag("spec.schema", f"{w}: requirement must be required|optional"))
                if not (r.get("fallback") is None or _s(r.get("fallback"))):
                    out.append(diag("spec.schema", f"{w}: fallback must be a string or null"))
                _validate_source(r.get("source"), w, out)
        if tr.get("evidenceStyle") not in {"single_hash", "batched_root"}:
            out.append(diag("spec.schema", "targetRequirements.evidenceStyle must be single_hash|batched_root"))
        _str_array(tr, "unsupportedConstructs", "targetRequirements", out)

    # hashes (only worth recomputing once the spec is otherwise structurally sound)
    if not any(d["code"].startswith(("spec.schema", "spec.missing_field", "spec.unknown_field"))
               or d["code"] in FIELD_CODES for d in out):
        _check_hashes(spec, out)

    return sorted(out, key=lambda d: (d["code"], d["message"]))


def _validate_lifecycle(lc, out: list) -> None:
    if not isinstance(lc, dict):
        out.append(diag("spec.schema", "lifecycle must be an object")); return
    need = {"instanceKey", "initialState", "states", "transitions", "terminalStates"}
    for k in sorted(set(lc) - need):
        out.append(diag("spec.unknown_field", f"lifecycle: unknown field '{k}'"))
    for k in sorted(need - set(lc)):
        out.append(diag("spec.missing_field", f"lifecycle: missing '{k}'"))

    ik = lc.get("instanceKey")
    if not isinstance(ik, dict) or not set(ik) <= {"fields", "declared"}:
        out.append(diag("spec.schema",
                        "lifecycle.instanceKey must be {fields: [...], "
                        "declared?: str}"))
    else:
        _str_array(ik, "fields", "lifecycle.instanceKey", out)
        # The explicit instance-key declaration is optional (absent for a
        # legacy effect-keyed coordination); a string when present.
        if "declared" in ik and not isinstance(ik["declared"], str):
            out.append(diag("spec.schema",
                            "lifecycle.instanceKey.declared must be a string"))

    if not isinstance(lc.get("states"), list):
        out.append(diag("spec.schema", "lifecycle.states must be an array"))
    if not isinstance(lc.get("transitions"), list):
        out.append(diag("spec.schema", "lifecycle.transitions must be an array"))

    states = {}
    for i, s in enumerate(lc.get("states", []) if isinstance(lc.get("states"), list) else []):
        if not isinstance(s, dict) or not _s(s.get("name")) or not isinstance(s.get("terminal"), bool):
            out.append(diag("spec.schema", f"lifecycle.states[{i}]: needs name + terminal bool")); continue
        for k in set(s) - {"name", "terminal", "terminalKind"}:
            out.append(diag("spec.unknown_field", f"lifecycle.states[{i}]: unknown field '{k}'"))
        if "terminalKind" in s:
            if s["terminalKind"] not in {"success", "aborted", "contested"}:
                out.append(diag("spec.terminal_kind", f"lifecycle.states[{i}]: terminalKind invalid"))
            if not s.get("terminal"):
                out.append(diag("spec.bad_terminal_state", f"lifecycle.states[{i}]: terminalKind on a non-terminal state"))
        states[s["name"]] = s

    if lc.get("initialState") not in states:
        out.append(diag("spec.bad_initial_state", f"lifecycle.initialState '{lc.get('initialState')}' is not a declared state"))
    froms = set()
    for i, t in enumerate(lc.get("transitions", []) if isinstance(lc.get("transitions"), list) else []):
        w = f"lifecycle.transitions[{i}]"
        if not isinstance(t, dict):
            out.append(diag("spec.schema", f"{w}: must be an object")); continue
        allowed = {"name", "from", "to", "effects", "guards", "idempotency", "evidence"}
        for k in set(t) - allowed:
            out.append(diag("spec.unknown_field", f"{w}: unknown field '{k}'"))
        if not _s(t.get("name")):
            out.append(diag("spec.schema", f"{w}: name required"))
        for endp in ("from", "to"):
            if t.get(endp) not in states:
                out.append(diag("spec.bad_transition", f"{w}: {endp} '{t.get(endp)}' is not a declared state"))
        froms.add(t.get("from"))
        if t.get("idempotency") not in {"reject", "noop_on_identical"}:
            out.append(diag("spec.transition_idempotency", f"{w}: idempotency must be reject|noop_on_identical"))
        if not isinstance(t.get("effects"), list):
            out.append(diag("spec.schema", f"{w}: effects must be an array"))
        else:
            for ef in t["effects"]:
                if ef not in {"post", "compensate", "reserve", "consume", "release"}:
                    out.append(diag("spec.transition_effect", f"{w}: effect '{ef}' invalid"))
        if not isinstance(t.get("guards"), list):
            out.append(diag("spec.schema", f"{w}: guards must be an array"))
        else:
            for gi, g in enumerate(t["guards"]):
                if not isinstance(g, dict) or set(g) - {"kind", "detail"} or g.get("kind") not in {"participant", "deadline", "sequence"}:
                    out.append(diag("spec.schema", f"{w}.guards[{gi}]: must be {{kind: participant|deadline|sequence, detail?}}"))
                elif "detail" in g and not isinstance(g["detail"], str):
                    out.append(diag("spec.schema", f"{w}.guards[{gi}]: detail must be a string"))
        ev = t.get("evidence")
        if not (ev is None or (isinstance(ev, dict) and set(ev) == {"style", "chained"}
                               and ev.get("style") in {"single_hash", "batched_root"}
                               and isinstance(ev.get("chained"), bool))):
            out.append(diag("spec.schema", f"{w}: evidence must be null or {{style, chained}}"))

    # No dead-end sinks: every NON-terminal state must have at least one outgoing
    # transition, so the executable machine can always reach a terminal (the
    # exit-completeness rule the kernel verifier enforces).
    for name, s in states.items():
        if not s.get("terminal") and name not in froms:
            out.append(diag("spec.dead_end_state",
                            f"lifecycle: non-terminal state '{name}' has no outgoing transition"))

    ts = lc.get("terminalStates")
    if not isinstance(ts, dict) or set(ts) != {"success", "aborted", "contested"}:
        out.append(diag("spec.schema", "lifecycle.terminalStates must be {success, aborted, contested}"))
    else:
        for k, v in ts.items():
            if v is not None and v not in states:
                out.append(diag("spec.bad_terminal_state", f"lifecycle.terminalStates.{k} '{v}' is not a declared state"))
            elif v is not None:
                s = states[v]
                if not s.get("terminal"):
                    out.append(diag("spec.bad_terminal_state",
                                    f"lifecycle.terminalStates.{k} '{v}' is not terminal"))
                elif s.get("terminalKind") != k:
                    out.append(diag("spec.bad_terminal_state",
                                    f"lifecycle.terminalStates.{k} '{v}' points to terminalKind "
                                    f"{s.get('terminalKind')!r}"))


def _check_hashes(spec: dict, out: list) -> None:
    ident = spec.get("identity", {})
    # capabilityHash covers the PRIMARY semantic content only. Excluded: identity, sourceMap, and
    # targetRequirements (derived, line-bearing projections;  F3/F4), AND the envelope
    # discriminators kind + schemaVersion (: kind is a constant document tag, schemaVersion is
    # a derived flag whose guard semantics are already hashed via the effects' `when`) — so the
    # identity is a PURE semantic identity, formatting- AND envelope-insensitive. specHash below
    # covers the whole artifact (envelope included).
    core = copy.deepcopy(spec)
    for _k in ("identity", "sourceMap", "targetRequirements", "kind", "schemaVersion"):
        core.pop(_k, None)
    cap = _sha(_compact(core))
    if ident.get("capabilityHash") != cap:
        out.append(diag("spec.hash_mismatch", "identity.capabilityHash does not match the recomputed digest"))
    body = copy.deepcopy(spec)
    body["identity"] = {"capabilityHash": ident.get("capabilityHash")}
    ph = _sha(_compact(body))
    if ident.get("specHash") != ph:
        out.append(diag("spec.hash_mismatch", "identity.specHash does not match the recomputed digest"))


def _selftest() -> int:
    # Non-vacuous mirror gate for the attestation-policy section (oracle S1, ): exercise
    # _validate_attestations DIRECTLY, so a hash mismatch cannot mask a schema hole (the function does
    # not touch hashes — the concern flagged is structurally eliminated). A well-formed policy
    # produces no diagnostic; each schema-invalid shape (missing required nested field, unknown field
    # at any level, binding-level N/members leak, bad enum) MUST produce a spec.schema error.
    def good():
        # Undeclared trust metadata (oracle S6, ): the observerSet keeps its exact pre-S6
        # {ref, role} shape — assurance/independence are OMITTED, not null, so the capabilityHash of
        # an existing attestation is unchanged. This valid case must pass with no diagnostic.
        return {"attestations": [{
            "input": "delivery_proof",
            "quorum": {"threshold": 2},
            "observerSet": {"ref": "delivery_oracles", "role": None},
            "canonicalization": {"mode": "exact", "tolerance": None},
            "timeout": "PT24H", "fallback": "abort"}]}

    def run(spec):
        out = []
        _validate_attestations(spec, out)
        return out

    fails = []
    if run(good()):
        fails.append(("a well-formed (undeclared-metadata) attestation policy was rejected", run(good())))

    # A policy DECLARING valid trust metadata (oracle S6, ) must also pass.
    declared = good()
    declared["attestations"][0]["observerSet"].update(
        {"assurance": "A3", "independence": "independent"})
    if run(declared):
        fails.append(("a policy with declared assurance/independence was rejected", run(declared)))

    cases = [
        ("missing timeout", lambda p: p.pop("timeout")),
        ("missing observerSet.role", lambda p: p["observerSet"].pop("role")),
        ("missing canonicalization.tolerance", lambda p: p["canonicalization"].pop("tolerance")),
        ("unknown policy field", lambda p: p.__setitem__("extra", 1)),
        ("unknown quorum field", lambda p: p["quorum"].__setitem__("n", 3)),
        ("binding-level members leak", lambda p: p["observerSet"].__setitem__("members", ["a"])),
        ("unknown observerSet field", lambda p: p["observerSet"].__setitem__("nodes", 3)),
        ("unknown canonicalization field", lambda p: p["canonicalization"].__setitem__("window", "1h")),
        ("non-positive quorum", lambda p: p["quorum"].__setitem__("threshold", 0)),
        ("unsupported fallback", lambda p: p.__setitem__("fallback", "degrade")),
        ("unsupported canonicalization mode", lambda p: p["canonicalization"].__setitem__("mode", "vibes")),
        # assurance/independence now carry FIELD-SPECIFIC codes () — assert the exact code, not prose.
        ("unsupported assurance tier", lambda p: p["observerSet"].__setitem__("assurance", "A9"),
         "kernel.attest.invalid_assurance"),
        ("null assurance (must be omitted, not null)", lambda p: p["observerSet"].__setitem__("assurance", None),
         "kernel.attest.invalid_assurance"),
        ("unsupported independence posture", lambda p: p["observerSet"].__setitem__("independence", "solo"),
         "kernel.attest.invalid_independence"),
        ("null independence (must be omitted, not null)",
         lambda p: p["observerSet"].__setitem__("independence", None), "kernel.attest.invalid_independence"),
        ("empty observer-set ref", lambda p: p["observerSet"].__setitem__("ref", "")),
        ("timeout wrong type", lambda p: p.__setitem__("timeout", 24)),
    ]
    for case in cases:
        name, mutate = case[0], case[1]
        expected = case[2] if len(case) > 2 else "spec.schema"
        spec = good()
        mutate(spec["attestations"][0])
        diags = run(spec)
        if not any(d["code"] == expected for d in diags):
            fails.append((f"schema-invalid shape not rejected with {expected}: {name}", diags))

    if fails:
        print("validate_capability_spec attestation-mirror selftest FAILED:", file=sys.stderr)
        for msg, diags in fails:
            print(f"    FAIL: {msg} -> {diags}", file=sys.stderr)
        return 1
    print(f"    PASS (attestation-policy schema mirror: valid passes; {len(cases)} schema-invalid "
          "shapes each rejected with its stable code — hash-independent, no masking)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a neutrino capability spec (--target=capability-spec output)")
    ap.add_argument("file", nargs="?", help="path to capability-spec.json")
    ap.add_argument("--out", help="output dir for spec.report.json + diagnostics.json")
    ap.add_argument("--selftest", action="store_true",
                    help="run the attestation-policy schema-mirror self-test () and exit")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if not args.file:
        ap.error("the following arguments are required: file")

    spec = None
    try:
        spec = json.load(open(args.file, encoding="utf-8"))
        diagnostics = validate(spec)
    except (OSError, ValueError) as exc:
        diagnostics = [diag("spec.io", f"cannot read spec: {exc}")]

    errors = [d for d in diagnostics if d.get("severity") == "error"]
    ok = not errors
    procedure = spec.get("procedure") if isinstance(spec, dict) else None
    # The validated spec's identity, so a consumer can BIND this report to a specific
    # capability-spec (): admission grounds in a *verified* spec only when a report it trusts
    # names the same capabilityHash the spec/lock carries. Because validate() recomputes both hashes
    # and fails closed on a mismatch (spec.hash_mismatch), an `ok:true` report attests that the
    # declared identity matches the spec's content — the content<->hash guarantee an orchestrator
    # cannot reproduce. Echoed as-declared (identity-typed via the schema mirror above); null when
    # the spec is unreadable / has no well-formed identity.
    ident = spec.get("identity") if isinstance(spec, dict) else None
    cap_hash = ident.get("capabilityHash") if isinstance(ident, dict) else None
    spec_hash = ident.get("specHash") if isinstance(ident, dict) else None
    report = {"kind": REPORT_KIND, "schemaVersion": REPORT_SCHEMA_VERSION, "ok": ok,
              "file": os.path.basename(args.file), "procedure": procedure,
              "capabilityHash": cap_hash, "specHash": spec_hash, "diagnostics": diagnostics}
    # stdout carries the identified, bind-able report (build-tools BUILD persists stdout as
    # capability-spec-validation.json): kind + schemaVersion + identity + verdict, so ADMIT can
    # require an ok report of a KNOWN version naming this spec's capabilityHash (: the report is a
    # translator->build-tools contract, version-pinned so it cannot drift silently).
    stdout_report = {"kind": REPORT_KIND, "schemaVersion": REPORT_SCHEMA_VERSION, "ok": ok,
                     "capabilityHash": cap_hash, "specHash": spec_hash, "diagnostics": diagnostics}

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        json.dump(report, open(os.path.join(args.out, "spec.report.json"), "w"), indent=2, sort_keys=True)
        json.dump({"ok": ok, "diagnostics": diagnostics},
                  open(os.path.join(args.out, "diagnostics.json"), "w"), indent=2, sort_keys=True)

    json.dump(stdout_report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
