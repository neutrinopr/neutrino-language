#!/usr/bin/env python3
"""D1a / Phase 22A — proposal-only dataset-analysis artifact validation.

AI-assisted dataset analysis (external tooling) may PROPOSE domain vocabulary, but its
outputs are never trusted compiler inputs. This gate validates the three proposal-side
artifacts fail-closed, shape-only — the translator never calls an LLM:

  - neutrino.domain-corpus-manifest        (what may be read, and as what authority)
  - neutrino.domain-analysis-run-manifest  (who/what ran, with which inputs/output)
  - neutrino.domain-vocabulary-proposal    (candidate terms + mapping-graph edges)

Authoritative specs: docs/schemas/domain-{corpus-manifest,analysis-run-manifest,
vocabulary-proposal}.schema.json. Validation is standard-library only (a tiny
fail-closed JSON-Schema subset interpreter), matching the repo's other checkers.

Translator-owned rules enforced beyond the schema:
  - corpus: a decompiled-binary source must be licenseApproved; a domain-authority
    source must be public or licenseApproved (no private/confidential or
    license-disallowed source as authority for accepted domain logic);
  - proposal: status/reviewStatus/edge-status are all 'proposed' (a proposal may not
    claim accepted dialect status — enforced by the schema consts); candidate terms
    must be cited; with --corpus, a citation naming a corpus source must name one
    permitted as domain-authority.

Emits a deterministic <kind>.report.json + diagnostics.json. ok iff no errors.
Exit 0 ok / 1 violations / 2 usage.

  validate_domain_proposal.py --artifact FILE [--corpus FILE] --out DIR
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DIR = os.path.join(HERE, "..", "..", "docs", "schemas")  # corpus/ -> repo/docs ()
SCHEMA_BY_KIND = {
    "neutrino.domain-corpus-manifest": ("corpus", "domain-corpus-manifest.schema.json"),
    "neutrino.domain-analysis-run-manifest": ("run", "domain-analysis-run-manifest.schema.json"),
    "neutrino.domain-vocabulary-proposal": ("proposal", "domain-vocabulary-proposal.schema.json"),
}


def diag(code: str, message: str, severity: str = "error") -> dict:
    return {"code": code, "severity": severity, "message": message}


def _resolve(root: dict, ref: str):
    cur = root
    for part in ref.lstrip("#/").split("/"):
        cur = cur[part]
    return cur


def vschema(node, schema, root, loc, errs):
    """Fail-closed validation against the JSON-Schema subset used by our schemas:
    type/const/enum/pattern/minLength/minItems/required/properties/items/$ref,
    additionalProperties:false."""
    if "$ref" in schema:
        schema = _resolve(root, schema["$ref"])
    if "const" in schema:
        if node != schema["const"]:
            errs.append(f"{loc}: must equal {schema['const']!r}")
        return
    if "enum" in schema:
        if node not in schema["enum"]:
            errs.append(f"{loc}: must be one of {schema['enum']}")
        return
    t = schema.get("type")
    if t == "object":
        if not isinstance(node, dict):
            errs.append(f"{loc}: must be an object")
            return
        for r in schema.get("required", []):
            if r not in node:
                errs.append(f"{loc}: missing required field '{r}'")
        props = schema.get("properties", {})
        if schema.get("additionalProperties", True) is False:
            for k in node:
                if k not in props:
                    errs.append(f"{loc}: unknown field '{k}'")
        for k, v in node.items():
            if k in props:
                vschema(v, props[k], root, f"{loc}.{k}", errs)
    elif t == "array":
        if not isinstance(node, list):
            errs.append(f"{loc}: must be an array")
            return
        if "minItems" in schema and len(node) < schema["minItems"]:
            errs.append(f"{loc}: must have at least {schema['minItems']} item(s)")
        item = schema.get("items")
        if item:
            for i, x in enumerate(node):
                vschema(x, item, root, f"{loc}[{i}]", errs)
    elif t == "string":
        if not isinstance(node, str):
            errs.append(f"{loc}: must be a string")
            return
        if "minLength" in schema and len(node) < schema["minLength"]:
            errs.append(f"{loc}: must be a non-empty string")
        if "pattern" in schema and not re.match(schema["pattern"], node):
            errs.append(f"{loc}: must match {schema['pattern']}")
    elif t == "boolean":
        if not isinstance(node, bool):
            errs.append(f"{loc}: must be a boolean")


def corpus_rules(corpus: dict) -> list:
    """A decompiled-binary source must be licenseApproved; a domain-authority source
    must be public or licenseApproved."""
    out = []
    for s in corpus.get("sources", []):
        sid = s.get("id")
        if s.get("sourceType") == "decompiled-binary" and not s.get("licenseApproved"):
            out.append(diag("corpus.decompiled_unreviewed",
                            f"source '{sid}': decompiled-binary requires licenseApproved=true"))
        if s.get("allowedUse") == "domain-authority" and s.get("sensitivity") != "public" and not s.get("licenseApproved"):
            out.append(diag("corpus.authority_not_permitted",
                            f"source '{sid}': domain-authority requires a public or licenseApproved source"))
    return out


def proposal_rules(proposal: dict, corpus: dict | None) -> list:
    """Fail-closed citation authority. A proposal's candidate terms are derived from the
    corpus, so every citation source must name a corpus source permitted as domain-authority.

    Every source of authority in the proposal — candidate-term citations AND candidate-edge
    provenance — must name a corpus source permitted as domain-authority.

    Fail-closed posture (do NOT pass when authority cannot be established):
      - no corpus supplied -> authority is unverifiable (the proposal cannot be cleared);
      - the supplied corpus must be the proposal's own (corpusRef == corpusId);
      - a source NOT declared in the corpus is rejected (unknown source), not silently allowed;
      - a declared source that is not domain-authority is rejected.
    """
    out = []
    if corpus is None:
        # Omitting --corpus must not yield a green proposal: authority is unverifiable.
        return [diag("proposal.authority_unverifiable",
                     "a vocabulary proposal must be validated against its corpus (--corpus) to "
                     "verify citation authority; refusing to clear it without one")]
    if proposal.get("corpusRef") != corpus.get("corpusId"):
        out.append(diag("proposal.corpus_mismatch",
                        f"proposal.corpusRef {proposal.get('corpusRef')!r} does not match the supplied "
                        f"corpus {corpus.get('corpusId')!r}"))
    sources = corpus.get("sources", []) if isinstance(corpus.get("sources"), list) else []
    corpus_ids = {s.get("id") for s in sources}
    authority = {
        s.get("id") for s in sources
        if s.get("allowedUse") == "domain-authority" and (s.get("sensitivity") == "public" or s.get("licenseApproved"))
    }

    def check_source(src, where):
        if src not in corpus_ids:
            out.append(diag("proposal.unknown_source", f"{where}: source {src!r} is not declared in the corpus"))
        elif src not in authority:
            out.append(diag("proposal.source_authority", f"{where}: source {src!r} is not permitted as domain-authority"))

    for term in proposal.get("candidateTerms", []):
        name = term.get("term")
        for c in term.get("citations", []):
            check_source(c.get("source"), f"candidate term '{name}' citation")
    for edge in proposal.get("candidateEdges", []):
        check_source((edge.get("provenance") or {}).get("source"), f"candidate edge '{edge.get('id')}' provenance")
    return sorted(out, key=lambda d: (d["code"], d["message"]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate proposal-only domain analysis artifacts")
    ap.add_argument("--artifact", required=True, help="corpus-manifest / analysis-run-manifest / vocabulary-proposal JSON")
    ap.add_argument("--corpus", help="corpus manifest to cross-check a proposal's citation authority")
    ap.add_argument("--out", required=True, help="output dir for the report + diagnostics")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    try:
        artifact = json.load(open(args.artifact, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        json.dump({"ok": False, "diagnostics": [diag("artifact.io", str(exc))]},
                  open(os.path.join(args.out, "diagnostics.json"), "w"), indent=2, sort_keys=True)
        return 2

    kind = artifact.get("kind") if isinstance(artifact, dict) else None
    if kind not in SCHEMA_BY_KIND:
        json.dump({"ok": False, "diagnostics": [diag("artifact.kind", f"unknown or missing kind: {kind!r}")]},
                  open(os.path.join(args.out, "diagnostics.json"), "w"), indent=2, sort_keys=True)
        return 2
    prefix, schema_file = SCHEMA_BY_KIND[kind]
    schema = json.load(open(os.path.join(SCHEMA_DIR, schema_file), encoding="utf-8"))

    shape_errs: list = []
    vschema(artifact, schema, schema, "(root)", shape_errs)
    diagnostics = [diag(f"{prefix}.schema", m) for m in sorted(shape_errs)]

    # Translator-owned rules only run once the shape is sound.
    if not diagnostics:
        if kind == "neutrino.domain-corpus-manifest":
            diagnostics += corpus_rules(artifact)
        elif kind == "neutrino.domain-vocabulary-proposal":
            corpus = None
            if args.corpus:
                try:
                    corpus = json.load(open(args.corpus, encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    diagnostics.append(diag("artifact.io", f"--corpus: {exc}"))
            diagnostics += proposal_rules(artifact, corpus)

    errors = [d for d in diagnostics if d.get("severity") == "error"]
    ok = not errors
    report = {"kind": f"{kind}-validation", "artifactKind": kind, "ok": ok}
    json.dump(report, open(os.path.join(args.out, f"{prefix}.report.json"), "w"), indent=2, sort_keys=True)
    json.dump({"ok": ok, "diagnostics": sorted(diagnostics, key=lambda d: (d["code"], d["message"]))},
              open(os.path.join(args.out, "diagnostics.json"), "w"), indent=2, sort_keys=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
