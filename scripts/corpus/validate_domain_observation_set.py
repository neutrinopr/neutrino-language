#!/usr/bin/env python3
"""M5 S0 () — neutrino.domain-observation-set validation.

The **deterministic middle stage** of domain-dataset extraction: source-agnostic FACTS a
corpus extractor (Solidity, SWIFT/Prowide, future FHIR) reads out of a governed corpus,
between `neutrino.domain-corpus-manifest` (governed input) and
`neutrino.domain-vocabulary-proposal` (AI-assisted candidates). This validator is the
translator-owned checker for that shape, so S1 (the Solidity extractor,
neutrino-solidity-samples) and S2 (corpus-to-dialect generation, ) build against a
frozen contract rather than prose.

The normative shape is `docs/schemas/domain-observation-set.schema.json`; this validator
**mirrors** it (CI runs this script, not a JSON-Schema library) AND enforces the
cross-references JSON Schema cannot express:

  - every observation's `dimension` is a declared key of the top-level `dimensions` block;
  - every observation's `value` is a member of that dimension's controlled vocabulary;
  - observation `id`s are unique across the set;
  - `corpusRef.contentHash` binds the set to exact corpus content (well-formed sha256);
  - a provenance `span`, when present, is non-inverted (startLine <= endLine).

And — the **trust boundary** this stage exists to enforce — it rejects AI-trust metadata with
a dedicated diagnostic: observations are DETERMINISTIC facts, so `confidence`, `reviewStatus`,
`model`, `prompt`, `temperature`, and `citations` do NOT belong here (that metadata is the
later `neutrino.domain-vocabulary-proposal` stage). `extractor` is a deterministic `tool` +
`version` identity, never a model/prompt identity.

Fail-closed: any unknown field, missing required field, forbidden AI-trust field, malformed
content hash, unknown dimension / dimension value, duplicate id, or inverted span is an error
diagnostic. Diagnostics are machine-readable `{code, severity, message}` under the
`observation.*` code family, registered in the shared failure taxonomy
(docs/diagnostic-taxonomy.json) with emitter=validator, and stable (sorted).

Emits a deterministic `observation-set.report.json` + `diagnostics.json` when `--out DIR` is
given, and prints `{ok, diagnostics}` to stdout. `ok` is true iff there are no error
diagnostics. Exit 0 ok / 1 violations / 2 usage.

  validate_domain_observation_set.py FILE [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

SCHEMA_VERSION = 1
KIND = "neutrino.domain-observation-set"

# Field sets — kept in sync with the normative schema by the full-tier self-test, which asserts
# each set equals the schema's `required` / `properties` keys (CI runs this script, not jsonschema).
TOP_FIELDS = {"kind", "schemaVersion", "corpusRef", "extractor", "dimensions", "observations"}
CORPUS_REF_FIELDS = {"corpusId", "contentHash"}
EXTRACTOR_FIELDS = {"tool", "version"}
PROVENANCE_FIELDS = {"source", "construct", "constructKind", "span"}
PROVENANCE_REQUIRED = {"source", "construct"}
SPAN_FIELDS = {"startLine", "endLine"}
OBSERVATION_FIELDS = {"id", "dimension", "value", "provenance", "note"}
OBSERVATION_REQUIRED = {"id", "dimension", "value", "provenance"}

# The trust boundary: these are AI-assisted-proposal fields. They MUST NOT appear anywhere in a
# deterministic observation set — a fact carries no confidence/review/model metadata. Rejected
# with the dedicated `observation.ai_field_forbidden` code (not the generic unknown-field code)
# so the diagnostic explains WHY: this metadata belongs to neutrino.domain-vocabulary-proposal.
FORBIDDEN_AI_FIELDS = {"confidence", "reviewStatus", "model", "prompt", "temperature", "citations"}

CONTENT_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
OBSERVATION_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
DIMENSION_NAME_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")


def diag(code: str, message: str, severity: str = "error") -> dict:
    return {"code": code, "severity": severity, "message": message}


def _nonempty_str(v) -> bool:
    return isinstance(v, str) and v != ""


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _check_fields(out: list, where: str, obj: dict, allowed: set, required: set) -> None:
    """Fail-closed field check shared by every object level: an unknown key is an error
    (or `ai_field_forbidden` for an AI-trust field), and every required key must be present."""
    for k in sorted(set(obj) - allowed):
        if k in FORBIDDEN_AI_FIELDS:
            out.append(diag("observation.ai_field_forbidden",
                            f"{where}: forbidden AI-trust field '{k}' — observations are deterministic "
                            f"facts; confidence/reviewStatus/model/prompt/temperature/citations belong to "
                            f"the neutrino.domain-vocabulary-proposal stage, not here"))
        else:
            out.append(diag("observation.unknown_field", f"{where}: unknown field '{k}'"))
    for k in sorted(required - set(obj)):
        out.append(diag("observation.missing_field", f"{where}: missing '{k}'"))


def validate(doc) -> list:
    out: list = []

    if not isinstance(doc, dict):
        return [diag("observation.schema", "top-level must be a JSON object")]

    _check_fields(out, "top-level", doc, TOP_FIELDS, TOP_FIELDS)

    if "kind" in doc and doc.get("kind") != KIND:
        out.append(diag("observation.bad_kind", f"kind must be '{KIND}', got {doc.get('kind')!r}"))
    if doc.get("schemaVersion") != SCHEMA_VERSION:
        out.append(diag("observation.schema_version",
                        f"schemaVersion must be {SCHEMA_VERSION}, got {doc.get('schemaVersion')!r}"))

    # corpusRef: binds the set to the EXACT corpus content (corpusId + well-formed content hash).
    cref = doc.get("corpusRef")
    if isinstance(cref, dict):
        _check_fields(out, "corpusRef", cref, CORPUS_REF_FIELDS, CORPUS_REF_FIELDS)
        if "corpusId" in cref and not _nonempty_str(cref.get("corpusId")):
            out.append(diag("observation.schema", "corpusRef.corpusId must be a non-empty string"))
        ch = cref.get("contentHash")
        if "contentHash" in cref and not (_nonempty_str(ch) and CONTENT_HASH_RE.match(ch)):
            out.append(diag("observation.bad_hash",
                            f"corpusRef.contentHash must match sha256:<64 hex>, got {ch!r}"))
    elif "corpusRef" in doc:
        out.append(diag("observation.schema", "corpusRef must be an object"))

    # extractor: a DETERMINISTIC tool+version identity — never a model/prompt identity.
    ext = doc.get("extractor")
    if isinstance(ext, dict):
        _check_fields(out, "extractor", ext, EXTRACTOR_FIELDS, EXTRACTOR_FIELDS)
        for k in ("tool", "version"):
            if k in ext and not _nonempty_str(ext.get(k)):
                out.append(diag("observation.schema", f"extractor.{k} must be a non-empty string"))
    elif "extractor" in doc:
        out.append(diag("observation.schema", "extractor must be an object"))

    # dimensions: the controlled vocabulary per dimension (generalizes classification.json's
    # fixed block to an open map). `vocab[name]` is what each observation value is checked against.
    vocab: dict = {}
    dims = doc.get("dimensions")
    if isinstance(dims, dict):
        if not dims:
            out.append(diag("observation.schema", "dimensions must declare at least one dimension"))
        for name, values in dims.items():
            if not DIMENSION_NAME_RE.match(name):
                out.append(diag("observation.schema",
                                f"dimensions: '{name}' must match {DIMENSION_NAME_RE.pattern}"))
            if (not isinstance(values, list) or not values
                    or any(not _nonempty_str(v) for v in values)):
                out.append(diag("observation.schema",
                                f"dimensions.{name} must be a non-empty array of non-empty strings"))
                continue
            if len(set(values)) != len(values):
                out.append(diag("observation.schema", f"dimensions.{name} has duplicate values"))
            vocab[name] = set(values)
    elif "dimensions" in doc:
        out.append(diag("observation.schema", "dimensions must be an object"))

    # observations: each a deterministic fact bound to a corpus construct via provenance.
    observations = doc.get("observations")
    if not isinstance(observations, list) or not observations:
        if "observations" in doc:
            out.append(diag("observation.schema", "observations must be a non-empty array"))
        observations = []

    seen_ids: dict = {}
    for i, o in enumerate(observations):
        oid = o.get("id") if isinstance(o, dict) and _nonempty_str(o.get("id")) else None
        where = f"observations[{i}] ({oid})" if oid else f"observations[{i}]"
        if not isinstance(o, dict):
            out.append(diag("observation.schema", f"observations[{i}] must be an object"))
            continue

        _check_fields(out, where, o, OBSERVATION_FIELDS, OBSERVATION_REQUIRED)

        oid_raw = o.get("id")
        if _nonempty_str(oid_raw):
            if not OBSERVATION_ID_RE.match(oid_raw):
                out.append(diag("observation.schema",
                                f"{where}: id '{oid_raw}' must match {OBSERVATION_ID_RE.pattern}"))
            if oid_raw in seen_ids:
                out.append(diag("observation.duplicate_id", f"{where}: duplicate id '{oid_raw}'"))
            seen_ids[oid_raw] = i
        elif "id" in o:
            out.append(diag("observation.schema", f"{where}: id must be a non-empty string"))

        if "note" in o and not _nonempty_str(o.get("note")):
            out.append(diag("observation.schema", f"{where}: note must be a non-empty string"))

        # (dimension, value) must be drawn from the declared controlled vocabulary — the
        # cross-reference JSON Schema cannot express.
        dim = o.get("dimension")
        val = o.get("value")
        if _nonempty_str(dim):
            if dim not in vocab and isinstance(dims, dict):
                out.append(diag("observation.unknown_dimension",
                                f"{where}: dimension '{dim}' is not declared in dimensions"))
            elif dim in vocab:
                if not _nonempty_str(val):
                    out.append(diag("observation.schema", f"{where}: value must be a non-empty string"))
                elif val not in vocab[dim]:
                    out.append(diag("observation.unknown_dimension_value",
                                    f"{where}: value '{val}' not in dimensions.{dim}"))
        elif "dimension" in o:
            out.append(diag("observation.schema", f"{where}: dimension must be a non-empty string"))

        _validate_provenance(out, where, o.get("provenance"))

    return sorted(out, key=lambda d: (d["code"], d["message"]))


def _validate_provenance(out: list, where: str, prov) -> None:
    """Provenance is REQUIRED on every observation (absence is caught as a missing field by the
    caller); when present it must point at a source construct, with an optional non-inverted span."""
    if prov is None:
        return  # missing provenance already reported as observation.missing_field
    if not isinstance(prov, dict):
        out.append(diag("observation.schema", f"{where}: provenance must be an object"))
        return
    _check_fields(out, f"{where}.provenance", prov, PROVENANCE_FIELDS, PROVENANCE_REQUIRED)
    for k in ("source", "construct", "constructKind"):
        if k in prov and not _nonempty_str(prov.get(k)):
            out.append(diag("observation.schema", f"{where}.provenance.{k} must be a non-empty string"))
    span = prov.get("span")
    if span is None:
        return
    if not isinstance(span, dict):
        out.append(diag("observation.schema", f"{where}.provenance.span must be an object"))
        return
    _check_fields(out, f"{where}.provenance.span", span, SPAN_FIELDS, SPAN_FIELDS)
    start, end = span.get("startLine"), span.get("endLine")
    for k, v in (("startLine", start), ("endLine", end)):
        if k in span and not (_is_int(v) and v >= 1):
            out.append(diag("observation.schema", f"{where}.provenance.span.{k} must be an integer >= 1"))
    if _is_int(start) and _is_int(end) and start > end:
        out.append(diag("observation.span_inverted",
                        f"{where}.provenance.span: startLine {start} > endLine {end}"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a neutrino.domain-observation-set document")
    ap.add_argument("file", help="path to the domain-observation-set JSON")
    ap.add_argument("--out", help="output dir for observation-set.report.json + diagnostics.json")
    args = ap.parse_args()

    doc = None
    try:
        doc = json.load(open(args.file, encoding="utf-8"))
        diagnostics = validate(doc)
    except (OSError, ValueError) as exc:
        diagnostics = [diag("observation.io", f"cannot read observation set: {exc}")]

    errors = [d for d in diagnostics if d.get("severity") == "error"]
    ok = not errors
    n_obs = len(doc.get("observations", [])) if isinstance(doc, dict) else 0
    report = {"ok": ok, "file": os.path.basename(args.file), "observations": n_obs,
              "diagnostics": diagnostics}

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        json.dump(report, open(os.path.join(args.out, "observation-set.report.json"), "w"),
                  indent=2, sort_keys=True)
        json.dump({"ok": ok, "diagnostics": diagnostics},
                  open(os.path.join(args.out, "diagnostics.json"), "w"), indent=2, sort_keys=True)

    json.dump({"ok": ok, "diagnostics": diagnostics}, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
