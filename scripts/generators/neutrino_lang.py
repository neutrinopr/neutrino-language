#!/usr/bin/env python3
"""D8 / Phase 27 (foundation) — language intelligence as deterministic JSON.

The console editor must get its grammar, completion data, red-squiggle diagnostics,
and outline from the translator, not from a separate frontend parser. Implemented
here: static **language metadata**, **parser diagnostics**, capability **preview**
(composed from gen artifacts), document **symbols** (a renderer over
`neutrino-emit --kind=symbols`, whose ranges the C++ front-end owns), and **hover**
(resolves the enclosing symbol from those ranges + static construct docs), and
**completions** (static grammar affordances from metadata + in-scope %references
from the outline), and **dialect** (domain-dialect registry/status/provenance from
the committed, validator-verified artifacts). The console stays a renderer, never a
second parser. See `docs/language/LANGUAGE_INTELLIGENCE.md` for the full contract.

The JSON is versioned (`schemaVersion`) and stable. Diagnostics come from the real
`neutrino-translate` front-end (no parser logic is reimplemented here): this tool
only runs it and structures its output. Likewise the language **metadata**'s grammar
facts (keywords, value types, operators, functions) are the compiler's, loaded from
the committed `docs/language-metadata.json` (emitted by `neutrino-translate
--language-metadata`); this tool adds only the editor-presentation layer and holds no
grammar list of its own — the M5 Python Boundary Policy (D10, docs/process/M5_DECISIONS_ADR.md).

  neutrino_lang.py metadata --json
  neutrino_lang.py diagnostics FILE.neu [--translate PATH] --json

Exit 0 on a successful analysis (the JSON `ok` field conveys file validity); 2 on
usage error (missing translate binary, unreadable file).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SCHEMA_VERSION = 1

# --- M5 Python Boundary Policy (D10, docs/process/M5_DECISIONS_ADR.md) ---------------------
# Python owns NO grammar/language list. The keyword vocabulary, governed value types,
# operators, and functions are the COMPILER's — emitted by
# `neutrino-translate --language-metadata` into the committed, hash-pinned
# docs/language-metadata.json (source: lib/LanguageMetadata.cpp, value types from the
# typed value model ValueModel/). This tool CONSUMES that file; it only adds the
# editor-presentation layer below (literal classes, snippets, range convention), which
# is not a semantic rule. A drift test (self-test [37]) regenerates the file from the
# compiler and byte-matches it, and asserts this tool's metadata matches the compiler's.

# Editor-presentation only — how literals/snippets render in the console. NOT grammar
# truth (no keyword/type/operator list lives here); snippets derive their type choices
# from the compiler-emitted valueTypes so they cannot drift.
LITERAL_CLASSES = [
    {"name": "string", "description": "double-quoted string literal", "example": "\"sponsor.commitment\""},
    {"name": "reference", "description": "%-prefixed reference to a declared input or computed value",
     "pattern": "%[A-Za-z_][A-Za-z0-9_]*", "example": "%contribution"},
    {"name": "number", "description": "integer or decimal literal", "example": "2500"},
]
# Source ranges are 1-based; columns are line-level (column 1) until the front-end
# emits column info — see endColumn==1.
RANGE_CONVENTION = {"oneBased": True, "columnsAvailable": False}


def _snippets(value_types: list) -> list:
    """Editor snippets. The `input` type-choice is built from the compiler-emitted
    valueTypes so the snippet's offered types never diverge from the grammar."""
    choices = ",".join(value_types)
    return [
        {"prefix": "procedure",
         "body": "procedure ${1:name} {\n    trigger ${2:event}\n    $0\n    assert balanced\n}"},
        {"prefix": "participant",
         "body": "participant ${1:Name} {\n    role = \"${2:role}\"\n    org  = \"${3:org}\"\n}"},
        {"prefix": "input", "body": "input ${1:name} : ${2|" + choices + "|}"},
        {"prefix": "debit",
         "body": "debit ${1:name} {\n    ledger          = \"${2:ledger}\"\n    owner           = \"${3:org}\"\n    party           = %${4:party}\n    amount          = %${5:amount}\n    currency        = %${6:currency}\n    idempotency_key = %${7:key}\n}"},
    ]


def _compiler_metadata_path() -> str:
    """The committed, compiler-emitted language metadata: docs/language-metadata.json
    (override with NEUTRINO_LANGUAGE_METADATA). Read from disk, not by invoking a tool,
    so the console works WITHOUT the compiler toolchain (M5 D10)."""
    env = os.environ.get("NEUTRINO_LANGUAGE_METADATA")
    if env:
        return env
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "docs", "language-metadata.json")


_METADATA_CACHE = None


def language_metadata() -> dict:
    """Full language metadata the `metadata` command emits: the COMPILER-owned grammar
    facts (keywords / keywordCategories / valueTypes / operators / functions and the
    file-level facts) loaded verbatim from the committed docs/language-metadata.json,
    PLUS the editor-presentation layer this tool owns (literalClasses, snippets,
    rangeConvention). Fail-closed: a missing / malformed / non-language-metadata file
    raises, so the tool never fabricates grammar Python does not own (M5 D10).

    Note: the `schemaVersion` in the returned dict is the compiler artifact's — it
    governs the compiler-owned fields ONLY. The presentation layer added here is not
    covered by it (see docs/language/LANGUAGE_INTELLIGENCE.md, "Versioning scope")."""
    global _METADATA_CACHE
    if _METADATA_CACHE is not None:
        return _METADATA_CACHE
    path = _compiler_metadata_path()
    with open(path) as f:
        base = json.load(f)
    if not isinstance(base, dict) or base.get("kind") != "neutrino.language-metadata":
        raise ValueError(f"{path}: not a neutrino.language-metadata artifact")
    for key in ("keywords", "keywordCategories", "valueTypes", "operators", "functions"):
        if key not in base:
            raise ValueError(f"{path}: missing compiler-owned field '{key}'")
    md = dict(base)
    md["literalClasses"] = LITERAL_CLASSES
    md["snippets"] = _snippets(base["valueTypes"])
    md["rangeConvention"] = RANGE_CONVENTION
    _METADATA_CACHE = md
    return md

# Stable diagnostic codes, mapped from the front-end's message text (ordered).
DIAG_CODES = [
    ("missing required field", "parse.missing_field"),
    ("declared more than once", "parse.duplicate_name"),
    ('must be a "literal" or %reference', "parse.bad_value"),
    ("is not a declared input or computed value", "parse.unresolved_reference"),
    ("unexpected statement", "parse.unexpected_statement"),
]
DIAG_LINE = re.compile(r"^(?P<file>.*?):(?P<line>\d+): (?P<sev>error|warning): (?P<msg>.*)$")


def classify(message: str) -> str:
    for needle, code in DIAG_CODES:
        if needle in message:
            return code
    return "parse.error"


def cmd_metadata() -> int:
    try:
        md = language_metadata()
    except (OSError, ValueError) as e:
        json.dump({"error": f"language metadata unavailable: {e}"},
                  sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 2
    json.dump(md, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def cmd_diagnostics(path: str, translate: str | None) -> int:
    translate = translate or os.environ.get("NEUTRINO_TRANSLATE")
    if not translate or not os.path.exists(translate):
        json.dump({"error": "neutrino-translate not found (pass --translate or set NEUTRINO_TRANSLATE)"},
                  sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 2
    if not os.path.exists(path):
        json.dump({"error": f"no such file: {path}"}, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 2

    proc = subprocess.run([translate, path, "-o", os.devnull], capture_output=True, text=True)
    diagnostics = []
    for line in proc.stderr.splitlines():
        m = DIAG_LINE.match(line.strip())
        if not m:
            continue
        ln = int(m.group("line"))
        diagnostics.append({
            "code": classify(m.group("msg")),
            "severity": m.group("sev"),
            "message": m.group("msg"),
            "range": {"start": {"line": ln, "column": 1}, "end": {"line": ln, "column": 1}},
        })
    # A non-zero exit with no parseable diagnostic (a crash, an unexpected error format,
    # an I/O failure) must NOT come back as ok:false with an empty list — that is a silent
    # failure for the editor. Synthesize a translate.failed diagnostic so ok:false always
    # carries at least one explanation.
    if proc.returncode != 0 and not any(d["severity"] == "error" for d in diagnostics):
        tail = next((ln.strip() for ln in reversed(proc.stderr.splitlines()) if ln.strip()), "")
        diagnostics.append({
            "code": "translate.failed",
            "severity": "error",
            "message": tail or f"neutrino-translate exited with code {proc.returncode} and no diagnostic output",
            "range": {"start": {"line": 1, "column": 1}, "end": {"line": 1, "column": 1}},
        })
    diagnostics.sort(key=lambda d: (d["range"]["start"]["line"], d["code"], d["message"]))
    ok = proc.returncode == 0 and not any(d["severity"] == "error" for d in diagnostics)
    json.dump({"schemaVersion": SCHEMA_VERSION, "file": path, "ok": ok, "diagnostics": diagnostics},
              sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


# Lowering backends are security-gated (an insecure capability must not produce a
# deployable artifact without --allow-insecure); analysis targets never are.
GATED_BACKENDS = {"solidity", "postgres", "slot", "views"}


def _emit(obj: dict) -> int:
    json.dump(obj, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def _fail_envelope(path: str, diagnostics: list, extra: dict | None = None) -> int:
    """Versioned, shape-stable failure envelope (preview/symbols): ok:false +
    diagnostics, never an unversioned {"error":...} the console would special-case.
    `extra` carries command-specific empty fields (e.g. symbols: [])."""
    obj = {"schemaVersion": SCHEMA_VERSION, "file": path, "ok": False}
    if extra:
        obj.update(extra)
    obj["diagnostics"] = diagnostics
    return _emit(obj)


def _diag(code: str, message: str) -> dict:
    return {"code": code, "severity": "error", "message": message}


def _read_json(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _gen(gen: str, target: str, scenario: str, src: str, outdir: str, extra=()):
    return subprocess.run([gen, "--target=" + target, "--scenario=" + scenario,
                           src, "-o", outdir, *extra], capture_output=True, text=True)


def _gen_diagnostics(outdir: str, proc) -> list:
    """The diagnostics neutrino-gen wrote for a failed run (it always writes
    diagnostics.json), or a synthesized fallback so ok:false is never silent."""
    d = _read_json(os.path.join(outdir, "diagnostics.json"))
    if isinstance(d, dict) and isinstance(d.get("diagnostics"), list) and d["diagnostics"]:
        return [{"code": x.get("code", "gen.error"), "severity": x.get("severity", "error"),
                 "message": x.get("message", "")} for x in d["diagnostics"]]
    tail = next((ln.strip() for ln in reversed((proc.stderr or "").splitlines()) if ln.strip()), "")
    return [{"code": "gen.failed", "severity": "error",
             "message": tail or f"neutrino-gen exited with code {proc.returncode}"}]


def cmd_preview(path: str, translate: str | None, gen: str | None, scenario: str | None) -> int:
    """Capability preview: what the capability *is*, composed only from real
    compiler artifacts (security report + slot capability lock/model). No source
    is re-parsed here. capabilityHash lives in the slot capability.lock, emitted by
    the gated `slot` target, so preview runs it with --allow-insecure (inspection
    must work even for an insecure capability; the security findings are reported)."""
    gen = gen or os.environ.get("NEUTRINO_GEN")
    if not gen or not os.path.exists(gen):
        return _fail_envelope(path, [_diag("preview.no_gen",
                             "neutrino-gen not found (pass --gen or set NEUTRINO_GEN)")])
    if not scenario or not os.path.exists(scenario):
        return _fail_envelope(path, [_diag("preview.no_scenario",
                             "a scenario is required for capability preview (pass --scenario)")])
    if not os.path.exists(path):
        return _fail_envelope(path, [_diag("preview.no_source", f"no such file: {path}")])

    tmp = tempfile.mkdtemp(prefix="neutrino-preview.")
    try:
        secdir = os.path.join(tmp, "security")
        slotdir = os.path.join(tmp, "slot")
        r_sec = _gen(gen, "security", scenario, path, secdir)
        r_slot = _gen(gen, "slot", scenario, path, slotdir, extra=("--allow-insecure",))

        cap = _read_json(os.path.join(slotdir, "capability.json"))
        lock = _read_json(os.path.join(slotdir, "capability.lock"))
        sec = _read_json(os.path.join(secdir, "security.json"))
        topo = _read_json(os.path.join(slotdir, "binding-topology.json"))

        # If the target-neutral slot capability could not be produced, the source
        # did not lower to a valid capability — surface diagnostics, never an
        # empty ok.
        if cap is None:
            failed = r_slot if r_slot.returncode != 0 else r_sec
            failed_dir = slotdir if r_slot.returncode != 0 else secdir
            return _fail_envelope(path, _gen_diagnostics(failed_dir, failed))

        # FAIL CLOSED on the trust verdict: a preview is a security-bearing artifact,
        # so a missing/unparseable security report must NOT come back ok:true with
        # security:null (that would let the console render a "successful" preview
        # without the Capability Security Pass verdict it must show). Refuse it.
        if not (isinstance(sec, dict) and isinstance(sec.get("categories"), list) and sec["categories"]):
            diags = (_gen_diagnostics(secdir, r_sec) if r_sec.returncode != 0
                     else [_diag("preview.security_unavailable",
                                 "security report missing or unparseable; refusing a preview "
                                 "without the Capability Security Pass verdict")])
            return _fail_envelope(path, diags)

        ir = {
            "inputs": len(cap.get("typedInputs", [])),
            "computes": len(cap.get("computed", [])),
            "participants": len(cap.get("declaredParticipants", [])),
            "legs": len(cap.get("entries", [])),
        }

        # FAIL CLOSED on capability identity: the capabilityHash IS the Fabric
        # schema-hash bridge, so an ok:true preview without a valid 64-hex hash is
        # another fail-open identity case. Require capability.lock to parse and carry
        # a 64-lowercase-hex digest, even if capability.json was produced.
        cap_hash = (lock or {}).get("capabilityHash")
        if not (isinstance(cap_hash, str) and re.fullmatch(r"[0-9a-f]{64}", cap_hash)):
            diags = (_gen_diagnostics(slotdir, r_slot) if r_slot.returncode != 0
                     else [_diag("preview.capability_hash_unavailable",
                                 "capability.lock missing or capabilityHash not a 64-hex digest; "
                                 "refusing a preview without a valid capability identity")])
            return _fail_envelope(path, diags)

        cats = sec["categories"]
        statuses = {c.get("status") for c in cats}
        status = ("violation" if "violation" in statuses
                  else "advisory" if "advisory" in statuses else "pass")
        security = {"status": status,
                    "findings": [{"category": c.get("category"), "status": c.get("status"),
                                  "findings": c.get("findings", [])} for c in cats]}

        backends = [{"target": b, "available": True, "gated": b in GATED_BACKENDS}
                    for b in cap.get("backends", [])]

        labels = []
        if isinstance(topo, dict):
            for org in topo.get("organizations", []):
                for p in org.get("participants", []):
                    for slot in p.get("slots", []):
                        if slot.get("minAssurance"):
                            labels.append({"participant": p.get("participantId"),
                                           "minAssurance": slot["minAssurance"],
                                           "earnedAt": "realization"})
        assurance = {"labels": labels}

        capability = {
            "procedure": cap.get("procedure"),
            "version": cap.get("capabilityVersion"),
            "capabilityHash": cap_hash,
            "ir": ir,
            "security": security,
            "backends": backends,
            "assurance": assurance,
        }
        return _emit({"schemaVersion": SCHEMA_VERSION, "file": path, "ok": True,
                      "capability": capability})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_symbols(path: str, emit: str | None) -> int:
    """Document outline: a thin renderer over `neutrino-emit --kind=symbols`. The
    C++ front-end owns the source ranges (the console never re-parses); this only
    wraps that output in the versioned file/ok/diagnostics envelope. On a source
    that does not lower, the front-end's parser diagnostics are structured (same
    shape/codes as `diagnostics`), so ok:false never comes back empty."""
    symbols, diagnostics = _run_symbols(path, emit)
    if symbols is None:
        return _emit({"schemaVersion": SCHEMA_VERSION, "file": path, "ok": False,
                      "symbols": [], "diagnostics": diagnostics})
    return _emit({"schemaVersion": SCHEMA_VERSION, "file": path, "ok": True,
                  "symbols": symbols})


# Static, translator-owned descriptions of each declaration kind. This is doc
# metadata (the language's own vocabulary), NOT parsing — hover composes it over the
# front-end's symbols/ranges. Dialect-term docs are layered in by .
KIND_DOCS = {
    "procedure": "Capability procedure: the coordinated business operation that lowers to backend artifacts.",
    "participant": "Declared participant: an actor/organization authorized in the capability (role, org, optional late-binding policy).",
    "input": "Typed input the capability requires at invocation (e.g. party, money, currency, evidence).",
    "compute": "Derived value computed from inputs or other computed values.",
    "debit": "Ledger debit leg: moves value out of an owner's ledger, bound to a participant and an idempotency key.",
    "credit": "Ledger credit leg: moves value into an owner's ledger, bound to a participant and an idempotency key.",
    "allow": "Org-pair coordination policy (the topology gate): permits two organizations to coordinate, optionally constraining each side's role.",
}


def _run_symbols(path: str, emit: str | None):
    """Fetch the front-end document outline via `neutrino-emit --kind=symbols`.
    Returns (symbols_list, diagnostics): symbols_list is None on failure (the
    structured diagnostics explain why). Shared by `symbols` and `hover`, so both
    stay renderers over the front-end's ranges (no DSL parsing here). Fail-closed:
    only output carrying the real emitter envelope marker is trusted."""
    emit = emit or os.environ.get("NEUTRINO_EMIT")
    if not emit or not os.path.exists(emit):
        return None, [_diag("symbols.no_emit",
                            "neutrino-emit not found (pass --emit or set NEUTRINO_EMIT)")]
    if not os.path.exists(path):
        return None, [_diag("symbols.no_source", f"no such file: {path}")]

    proc = subprocess.run([emit, "--kind=symbols", path], capture_output=True, text=True)
    if proc.returncode == 0:
        try:
            doc = json.loads(proc.stdout)
        except ValueError:
            doc = None
        if (isinstance(doc, dict) and doc.get("kind") == "neutrino.document-symbols"
                and isinstance(doc.get("symbols"), list)):
            return doc["symbols"], []

    diagnostics = []
    for line in proc.stderr.splitlines():
        m = DIAG_LINE.match(line.strip())
        if not m:
            continue
        ln = int(m.group("line"))
        diagnostics.append({
            "code": classify(m.group("msg")),
            "severity": m.group("sev"),
            "message": m.group("msg"),
            "range": {"start": {"line": ln, "column": 1}, "end": {"line": ln, "column": 1}},
        })
    if not diagnostics:
        tail = next((ln.strip() for ln in reversed(proc.stderr.splitlines()) if ln.strip()), "")
        diagnostics.append(_diag("symbols.failed",
                                 tail or f"neutrino-emit exited with code {proc.returncode}"))
    diagnostics.sort(key=lambda d: (d.get("range", {}).get("start", {}).get("line", 0),
                                    d["code"], d["message"]))
    return None, diagnostics


def _symbol_at(symbols: list, line: int):
    """Deepest outline symbol whose range contains `line` (ranges are line-level, so
    a child is preferred over its enclosing procedure). Pure lookup over the
    front-end's ranges — no source scanning."""
    for proc in symbols:
        r = proc.get("range", {})
        if r.get("start", {}).get("line", 0) <= line <= r.get("end", {}).get("line", 0):
            for child in proc.get("children", []):
                cr = child.get("range", {})
                if cr.get("start", {}).get("line", 0) <= line <= cr.get("end", {}).get("line", 0):
                    return child
            return proc
    return None


def _static_completions() -> list:
    """Static language affordances from the compiler-emitted language metadata
    (keywords by category, value types) plus the editor snippets. No source needed;
    grammar comes from docs/language-metadata.json, never a Python-held list (M5 D10)."""
    md = language_metadata()
    items = []
    for category, kws in md["keywordCategories"].items():
        for kw in kws:
            items.append({"label": kw, "kind": "keyword", "category": category})
    for vt in md["valueTypes"]:
        items.append({"label": vt, "kind": "type"})
    for sn in md["snippets"]:
        items.append({"label": sn["prefix"], "kind": "snippet", "insertText": sn["body"]})
    return items


def cmd_completions(path: str | None, emit: str | None) -> int:
    """Completions for the editor. Without a file: scope=static — the language's
    grammar affordances (keywords/types/snippets) from METADATA. With a file: those
    plus source-specific in-scope `%references` (declared inputs + computes) resolved
    from the front-end `symbols` outline. Composition only — no DSL parsing here.
    A file that does not lower fails closed (ok:false + diagnostics)."""
    try:
        static = _static_completions()
    except (OSError, ValueError) as e:
        return _emit({"schemaVersion": SCHEMA_VERSION, "file": path, "ok": False,
                      "completions": [],
                      "diagnostics": [_diag("completions.no_metadata",
                                            f"language metadata unavailable: {e}")]})
    if not path:
        return _emit({"schemaVersion": SCHEMA_VERSION, "scope": "static", "ok": True,
                      "completions": static})
    symbols, diagnostics = _run_symbols(path, emit)
    if symbols is None:
        return _emit({"schemaVersion": SCHEMA_VERSION, "file": path, "ok": False,
                      "completions": [], "diagnostics": diagnostics})
    refs = []
    for proc in symbols:
        for child in proc.get("children", []):
            if child.get("kind") in ("input", "compute"):
                refs.append({"label": "%" + child.get("name", ""), "kind": "reference",
                             "detail": child.get("kind")})
    return _emit({"schemaVersion": SCHEMA_VERSION, "file": path, "ok": True,
                  "completions": static + refs})


def cmd_hover(path: str, line: int, column: int, emit: str | None) -> int:
    """Hover info at a position: resolve the enclosing symbol from the front-end's
    outline (translator-owned ranges) and compose its static doc. Never parses .neu.
    `hover` is null when no symbol covers the position (valid — e.g. blank/comment);
    ok:false only when the source does not lower / artifacts are missing."""
    symbols, diagnostics = _run_symbols(path, emit)
    pos = {"line": line, "column": column}
    if symbols is None:
        return _emit({"schemaVersion": SCHEMA_VERSION, "file": path, "ok": False,
                      "position": pos, "hover": None, "diagnostics": diagnostics})
    sym = _symbol_at(symbols, line)
    hover = None
    if sym is not None:
        kind = sym.get("kind")
        hover = {"kind": kind, "name": sym.get("name"), "range": sym.get("range"),
                 "contents": KIND_DOCS.get(kind, f"{kind} declaration")}
    return _emit({"schemaVersion": SCHEMA_VERSION, "file": path, "ok": True,
                  "position": pos, "hover": hover})


# A term/template is only as trustworthy as its weakest provenance edge, so the
# rolled-up status takes the worst across its provenance (rejected > proposed >
# accepted). Statuses are the artifact's own (schema enum), never invented here.
_STATUS_RANK = {"accepted": 0, "proposed": 1, "rejected": 2}


def _worst_status(statuses: list) -> str:
    present = [s for s in statuses if s]
    if not present:
        return "unknown"
    return max(present, key=lambda s: _STATUS_RANK.get(s, 3))


def _validate_dialect(path: str, validate: str | None):
    """Validate a domain-dialect artifact with the translator-owned
    validate_domain_dialect.py (schema + provenance + domainDialectHash), returning
    (artifact, diagnostics). artifact is None on any failure — missing, malformed,
    stale/hash-mismatched, unknown-field — so dialect rendering is fail-closed and
    never re-implements validation/parsing here."""
    validate = validate or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # generators/ -> scripts/
        "domain", "validate_domain_dialect.py")
    if not os.path.exists(validate):
        return None, [_diag("dialect.no_validator", f"validator not found: {validate}")]
    if not os.path.exists(path):
        return None, [_diag("dialect.no_dialect", f"no such dialect artifact: {path}")]
    tmp = tempfile.mkdtemp(prefix="neutrino-dialect.")
    try:
        proc = subprocess.run([sys.executable, validate, "--dialect", path, "--out", tmp],
                              capture_output=True, text=True)
        report = _read_json(os.path.join(tmp, "diagnostics.json"))
        if proc.returncode == 0 and isinstance(report, dict) and report.get("ok") is True:
            # Read the validator's normalized parse, not the source — so a valid
            # YAML-authored dialect is handled (the validator accepts YAML; this
            # wrapper does not re-parse the source as JSON).
            artifact = _read_json(os.path.join(tmp, "domain-dialect.normalized.json"))
            if isinstance(artifact, dict) and artifact.get("kind") == "neutrino.domain-dialect":
                return artifact, []
            return None, [_diag("dialect.malformed",
                                "validator did not emit a normalized neutrino.domain-dialect artifact")]
        diags = []
        if isinstance(report, dict) and isinstance(report.get("diagnostics"), list):
            diags = [{"code": d.get("code", "dialect.invalid"), "severity": "error",
                      "message": d.get("message", "")} for d in report["diagnostics"]]
        if not diags:
            tail = next((ln.strip() for ln in reversed((proc.stderr or "").splitlines()) if ln.strip()), "")
            diags = [_diag("dialect.invalid", tail or f"validator exited with code {proc.returncode}")]
        return None, diags
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_dialect(path: str, validate: str | None) -> int:
    """Domain-dialect registry: surfaces each term/template with its rolled-up
    review status and resolved provenance, read only from the committed,
    validator-verified artifact (status/provenance come from the mappingGraph
    edges the term references). Composition only — no domain parsing. Fail-closed:
    a missing/stale/malformed/hash-mismatched artifact returns ok:false."""
    artifact, diagnostics = _validate_dialect(path, validate)
    if artifact is None:
        return _emit({"schemaVersion": SCHEMA_VERSION, "dialect": path, "ok": False,
                      "registry": {"terms": [], "templates": []}, "diagnostics": diagnostics})

    edges = {e.get("id"): e for e in artifact.get("mappingGraph", {}).get("edges", [])}

    def provenance(refs):
        out = []
        for ref in refs or []:
            e = edges.get(ref)
            if e:
                p = e.get("provenance", {})
                out.append({"ref": ref, "source": p.get("source"),
                            "status": p.get("status"), "reviewer": p.get("reviewer")})
        return out

    terms = []
    for name, t in sorted(artifact.get("terms", {}).items()):
        prov = provenance(t.get("provenanceRefs", []))
        terms.append({"name": name, "kind": "term", "layer": t.get("layer"),
                      "role": t.get("role"), "aliases": t.get("aliases", []),
                      "status": _worst_status([p["status"] for p in prov]),
                      "provenance": prov})
    templates = []
    for name, t in sorted(artifact.get("templates", {}).items()):
        prov = provenance(t.get("provenanceRefs", []))
        templates.append({"name": name, "kind": "template", "layer": t.get("layer"),
                          "expandsTo": t.get("expandsTo"),
                          "status": _worst_status([p["status"] for p in prov]),
                          "provenance": prov})

    return _emit({"schemaVersion": SCHEMA_VERSION, "dialect": path, "ok": True,
                  "domain": artifact.get("domain"), "version": artifact.get("version"),
                  "domainDialectHash": artifact.get("domainDialectHash"),
                  "registry": {"terms": terms, "templates": templates}})


def main() -> int:
    ap = argparse.ArgumentParser(description="Neutrino language intelligence (metadata + diagnostics) as JSON")
    sub = ap.add_subparsers(dest="cmd", required=True)
    mp = sub.add_parser("metadata", help="static language metadata")
    mp.add_argument("--json", action="store_true", help="(default; JSON is the only output)")
    dp = sub.add_parser("diagnostics", help="parser diagnostics for a file")
    dp.add_argument("file", help="path to a .neu source file")
    dp.add_argument("--translate", help="path to the neutrino-translate binary (or set NEUTRINO_TRANSLATE)")
    dp.add_argument("--json", action="store_true", help="(default; JSON is the only output)")
    pp = sub.add_parser("preview", help="capability preview (composed from compiler artifacts)")
    pp.add_argument("file", help="path to a .neu source file")
    pp.add_argument("--gen", help="path to the neutrino-gen binary (or set NEUTRINO_GEN)")
    pp.add_argument("--translate", help="path to the neutrino-translate binary (reserved; gen lowers the source)")
    pp.add_argument("--scenario", help="scenario JSON (required: gen validates it against the procedure)")
    pp.add_argument("--json", action="store_true", help="(default; JSON is the only output)")
    sp = sub.add_parser("symbols", help="document outline with front-end source ranges")
    sp.add_argument("file", help="path to a .neu source file")
    sp.add_argument("--emit", help="path to the neutrino-emit binary (or set NEUTRINO_EMIT)")
    sp.add_argument("--json", action="store_true", help="(default; JSON is the only output)")
    hp = sub.add_parser("hover", help="hover info at a position (over the front-end outline)")
    hp.add_argument("file", help="path to a .neu source file")
    hp.add_argument("--line", type=int, required=True, help="1-based line of the hover position")
    hp.add_argument("--column", type=int, default=1, help="1-based column (line-level ranges; default 1)")
    hp.add_argument("--emit", help="path to the neutrino-emit binary (or set NEUTRINO_EMIT)")
    hp.add_argument("--json", action="store_true", help="(default; JSON is the only output)")
    cp = sub.add_parser("completions", help="completions: static grammar + in-scope %references")
    cp.add_argument("file", nargs="?", help="optional .neu source for in-scope %references")
    cp.add_argument("--emit", help="path to the neutrino-emit binary (or set NEUTRINO_EMIT); needed with a file")
    cp.add_argument("--json", action="store_true", help="(default; JSON is the only output)")
    dlp = sub.add_parser("dialect", help="domain-dialect registry/status/provenance (validated artifact)")
    dlp.add_argument("dialect", help="path to a neutrino.domain-dialect artifact")
    dlp.add_argument("--validate", help="path to validate_domain_dialect.py (default: sibling script)")
    dlp.add_argument("--json", action="store_true", help="(default; JSON is the only output)")
    args = ap.parse_args()
    if args.cmd == "metadata":
        return cmd_metadata()
    if args.cmd == "preview":
        return cmd_preview(args.file, args.translate, args.gen, args.scenario)
    if args.cmd == "symbols":
        return cmd_symbols(args.file, args.emit)
    if args.cmd == "hover":
        return cmd_hover(args.file, args.line, args.column, args.emit)
    if args.cmd == "completions":
        return cmd_completions(args.file, args.emit)
    if args.cmd == "dialect":
        return cmd_dialect(args.dialect, args.validate)
    return cmd_diagnostics(args.file, args.translate)


if __name__ == "__main__":
    sys.exit(main())
