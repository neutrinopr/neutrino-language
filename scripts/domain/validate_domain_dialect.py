#!/usr/bin/env python3
"""D1 / Phase 22 — neutrino.domain-dialect validation + hash pinning.

A reviewed domain dialect (Upper-Layer vocabulary + Lower-Layer translation maps)
must be fail-closed before it can enter the compiler pipeline. This gate:

  1. validates the artifact's structure fail-closed — unknown fields rejected,
     layers/edge-types/lossiness/kinds enumerated, required fields present. The
     authoritative spec is docs/schemas/domain-dialect.schema.json; this validator
     enforces it with the standard library only (no runtime dependency, matching
     the repo's other checkers and CI), and a test keeps the two aligned.
  2. enforces cross-references: every mappingGraph edge endpoint resolves to a
     node, ids are unique, and every term/template provenanceRef resolves to an edge;
  3. requires provenance for promoted Upper-Layer (L2) vocabulary — no stale,
     ambiguous, or provenance-free terms/templates;
  4. computes domainDialectHash = sha256 over the canonical JSON (sort_keys,
     compact separators) with the hash field removed, and verifies any embedded
     value matches;
  5. rejects domain vocabulary that REDEFINES a core construct — a term/template
     name or a term alias equal to a reserved core keyword/type (dialect.redefines_core),
     so a dialect may reference/expand core but never shadow it. See docs/domains/DIALECT_PROMOTION.md.

YAML is accepted as authoring input when PyYAML is available; it is normalized to
canonical JSON before hashing (the hash is over the JSON, never the YAML text).

Emits a deterministic domain-dialect.report.json + diagnostics.json. `ok` is true
iff there are no error diagnostics. Exit 0 ok / 1 violations / 2 usage.

  validate_domain_dialect.py --dialect FILE --out DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

LAYERS = {"L1", "L2", "L3", "L4"}
EDGE_TYPES = {"cites", "expandsTo", "lowersTo", "liftsFrom", "preservesAs", "rejects"}
DIRECTIONS = {"expand", "lower", "lift", "preserve", "reject"}
LOSSINESS = {"lossless", "lossy-preserved-in-extensionData", "unsupported"}
NODE_KINDS = {"sourceField", "capabilityConcept", "coreConstruct", "railField", "extensionField"}
INPUT_TYPES = {"string", "party", "money", "currency", "number", "evidence"}
OBLIGATION_KINDS = {"debit", "credit"}
STATUS = {"proposed", "accepted", "rejected"}
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

# The complete core value-model type vocabulary: the INPUT_TYPES enum (single
# shared source) plus the numeric aliases the translator accepts (View.cpp
# isNumericType: decimal/int/integer/uint) and timestamp/time. See
# docs/process/COMPATIBILITY.md / VALUE_MODEL.md. A superset on purpose — the redefine-core
# gate must not be bypassable via a value-type word that is valid in core .neu but
# not in the requiredInputs enum (e.g. decimal, timestamp).
CORE_VALUE_TYPES = INPUT_TYPES | {"decimal", "int", "integer", "uint", "timestamp", "time"}

# Reserved core DSL constructs (statement + field + connector keywords + the full
# value-type vocabulary — mirrors the .neu grammar; kept in sync via the D7
# redefine-core test). Domain vocabulary must not REDEFINE these: a term/template
# NAME or a term ALIAS equal to one of these would silently shadow base semantics
# (e.g. an alias "debit" rebinding the core leg keyword, or "decimal" a value type).
# Templates legitimately *reference* core via expandsTo/obligation.kind (enumerated
# separately) — this guards the naming surface, not those references. See
# docs/domains/DIALECT_PROMOTION.md.
RESERVED_CORE = {
    "procedure", "agreement", "participant", "input", "compute", "debit", "credit",
    "allow", "assert", "trigger", "version",
    "role", "org", "capabilities", "binding", "bind_runtimes", "bind_min_assurance",
    "ledger", "owner", "party", "amount", "currency", "idempotency_key",
    "between", "with", "and", "as", "balanced",
} | CORE_VALUE_TYPES


def diag(code: str, message: str, severity: str = "error") -> dict:
    return {"code": code, "severity": severity, "message": message}


def load_artifact(path: str) -> dict:
    """Load a dialect from JSON (always) or YAML (if PyYAML is present)."""
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    if path.endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise RuntimeError("YAML authoring input needs PyYAML; convert to JSON") from exc
        return yaml.safe_load(text)
    return json.loads(text)


def canonical_hash(dialect: dict) -> str:
    """sha256 over canonical JSON with domainDialectHash removed — never the YAML text."""
    body = {k: v for k, v in dialect.items() if k != "domainDialectHash"}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


class V:
    """Fail-closed structural validator (mirrors domain-dialect.schema.json)."""

    def __init__(self) -> None:
        self.out: list = []

    def err(self, loc: str, msg: str) -> None:
        self.out.append(diag("dialect.schema", f"{loc}: {msg}"))

    def obj(self, loc, val, required=(), allowed=()) -> bool:
        if not isinstance(val, dict):
            self.err(loc, "must be an object")
            return False
        for k in required:
            if k not in val:
                self.err(loc, f"missing required field '{k}'")
        for k in val:
            if k not in allowed:
                self.err(loc, f"unknown field '{k}'")
        return True

    def nonempty_str(self, loc, val) -> None:
        if not isinstance(val, str) or not val:
            self.err(loc, "must be a non-empty string")

    def enum(self, loc, val, choices) -> None:
        if val not in choices:
            self.err(loc, f"must be one of {sorted(choices)}")

    def str_list(self, loc, val) -> None:
        if not isinstance(val, list) or any(not isinstance(x, str) or not x for x in val):
            self.err(loc, "must be an array of non-empty strings")

    def provenance(self, loc, val) -> None:
        if not self.obj(loc, val, ("source", "status"),
                        ("source", "standardVersion", "excerptHash", "reviewer", "status")):
            return
        self.nonempty_str(f"{loc}.source", val.get("source"))
        self.enum(f"{loc}.status", val.get("status"), STATUS)

    def rail_entry(self, loc, val) -> None:
        if not self.obj(loc, val, ("lossiness",), ("field", "concept", "lossiness")):
            return
        self.enum(f"{loc}.lossiness", val.get("lossiness"), LOSSINESS)

    def map_of(self, loc, val) -> dict:
        """An object-map field. Absent -> {}; present-but-not-an-object -> a schema
        error and {} (so iteration is safe and a non-object container fails closed)."""
        if val is None:
            return {}
        if not isinstance(val, dict):
            self.err(loc, "must be an object")
            return {}
        return val

    def validate(self, d) -> list:
        if not self.obj("(root)", d, ("kind", "domain", "version", "mappingGraph"),
                        ("kind", "domain", "version", "capabilitySpecVersion", "terms", "templates",
                         "translationMaps", "mappingGraph", "domainDialectHash")):
            return self.out
        if d.get("kind") != "neutrino.domain-dialect":
            self.err("kind", "must be 'neutrino.domain-dialect'")
        self.nonempty_str("domain", d.get("domain"))
        if not isinstance(d.get("version"), str) or not SEMVER.match(d.get("version") or ""):
            self.err("version", "must be a semantic version X.Y.Z")
        # Optional capability-spec contract pin (R3/) — form only; check_artifact_pins.py
        # enforces the VALUE against the emitted contract version.
        if "capabilitySpecVersion" in d and not (
                isinstance(d.get("capabilitySpecVersion"), str)
                and re.match(r"^v[0-9]+$", d.get("capabilitySpecVersion") or "")):
            self.err("capabilitySpecVersion", "must match ^v[0-9]+$")
        if "domainDialectHash" in d and not (isinstance(d["domainDialectHash"], str) and SHA256.match(d["domainDialectHash"])):
            self.err("domainDialectHash", "must be a 64-char lowercase hex sha256")

        for name, t in self.map_of("terms", d.get("terms")).items():
            loc = f"terms.{name}"
            if self.obj(loc, t, ("layer",), ("layer", "role", "aliases", "provenanceRefs")):
                self.enum(f"{loc}.layer", t.get("layer"), LAYERS)
                if "role" in t:
                    self.nonempty_str(f"{loc}.role", t["role"])
                if "aliases" in t:
                    self.str_list(f"{loc}.aliases", t["aliases"])
                if "provenanceRefs" in t:
                    self.str_list(f"{loc}.provenanceRefs", t["provenanceRefs"])

        for name, t in self.map_of("templates", d.get("templates")).items():
            loc = f"templates.{name}"
            if not self.obj(loc, t, ("layer", "expandsTo"),
                            ("layer", "expandsTo", "provenanceRefs", "participants", "requiredInputs", "obligations")):
                continue
            self.enum(f"{loc}.layer", t.get("layer"), LAYERS)
            self.nonempty_str(f"{loc}.expandsTo", t.get("expandsTo"))
            if "provenanceRefs" in t:
                self.str_list(f"{loc}.provenanceRefs", t["provenanceRefs"])
            for pname, p in self.map_of(f"{loc}.participants", t.get("participants")).items():
                if self.obj(f"{loc}.participants.{pname}", p, ("role",), ("role",)):
                    self.nonempty_str(f"{loc}.participants.{pname}.role", p.get("role"))
            for iname, ity in self.map_of(f"{loc}.requiredInputs", t.get("requiredInputs")).items():
                self.enum(f"{loc}.requiredInputs.{iname}", ity, INPUT_TYPES)
            obs = t.get("obligations")
            if "obligations" in t and not isinstance(obs, list):
                self.err(f"{loc}.obligations", "must be an array")
            for i, o in enumerate(obs or []):
                oloc = f"{loc}.obligations[{i}]"
                if self.obj(oloc, o, ("name", "participant", "kind", "ledger"),
                            ("name", "participant", "kind", "ledger")):
                    self.nonempty_str(f"{oloc}.name", o.get("name"))
                    self.nonempty_str(f"{oloc}.participant", o.get("participant"))
                    self.enum(f"{oloc}.kind", o.get("kind"), OBLIGATION_KINDS)
                    self.nonempty_str(f"{oloc}.ledger", o.get("ledger"))

        for name, m in self.map_of("translationMaps", d.get("translationMaps")).items():
            loc = f"translationMaps.{name}"
            if not self.obj(loc, m, ("provenance",), ("provenance", "lower", "lift", "extensionData")):
                continue
            self.provenance(f"{loc}.provenance", m.get("provenance"))
            for side in ("lower", "lift"):
                for fname, fe in self.map_of(f"{loc}.{side}", m.get(side)).items():
                    self.rail_entry(f"{loc}.{side}.{fname}", fe)
            for ename, ed in self.map_of(f"{loc}.extensionData", m.get("extensionData")).items():
                eloc = f"{loc}.extensionData.{ename}"
                if self.obj(eloc, ed, ("preserve", "reason"), ("preserve", "reason")):
                    if not isinstance(ed.get("preserve"), bool):
                        self.err(f"{eloc}.preserve", "must be a boolean")
                    self.nonempty_str(f"{eloc}.reason", ed.get("reason"))

        g = d.get("mappingGraph")
        if self.obj("mappingGraph", g, ("nodes", "edges"), ("nodes", "edges")):
            nodes = g.get("nodes")
            edges = g.get("edges")
            if not isinstance(nodes, list):
                self.err("mappingGraph.nodes", "must be an array")
            for i, n in enumerate(nodes or []):
                nloc = f"mappingGraph.nodes[{i}]"
                if self.obj(nloc, n, ("id", "layer", "kind"), ("id", "layer", "kind")):
                    self.nonempty_str(f"{nloc}.id", n.get("id"))
                    self.enum(f"{nloc}.layer", n.get("layer"), LAYERS)
                    self.enum(f"{nloc}.kind", n.get("kind"), NODE_KINDS)
            if not isinstance(edges, list):
                self.err("mappingGraph.edges", "must be an array")
            for i, e in enumerate(edges or []):
                eloc = f"mappingGraph.edges[{i}]"
                if not self.obj(eloc, e, ("id", "type", "from", "to", "provenance"),
                                ("id", "type", "from", "to", "direction", "lossiness", "provenance")):
                    continue
                self.nonempty_str(f"{eloc}.id", e.get("id"))
                self.enum(f"{eloc}.type", e.get("type"), EDGE_TYPES)
                self.nonempty_str(f"{eloc}.from", e.get("from"))
                self.nonempty_str(f"{eloc}.to", e.get("to"))
                if "direction" in e:
                    self.enum(f"{eloc}.direction", e["direction"], DIRECTIONS)
                if "lossiness" in e:
                    self.enum(f"{eloc}.lossiness", e["lossiness"], LOSSINESS)
                self.provenance(f"{eloc}.provenance", e.get("provenance"))

        # D7 redefine-core gate: domain vocabulary must not shadow a core construct.
        for name, t in self.map_of("terms", d.get("terms")).items():
            if name in RESERVED_CORE:
                self.out.append(diag("dialect.redefines_core",
                                     f"terms.{name}: term name redefines core construct '{name}'"))
            if isinstance(t, dict):
                for a in (t.get("aliases") or []):
                    if a in RESERVED_CORE:
                        self.out.append(diag("dialect.redefines_core",
                                             f"terms.{name}.aliases: alias '{a}' redefines core construct"))
        for name in self.map_of("templates", d.get("templates")):
            if name in RESERVED_CORE:
                self.out.append(diag("dialect.redefines_core",
                                     f"templates.{name}: template name redefines core construct '{name}'"))
        return self.out


def crossref_diagnostics(dialect: dict) -> list:
    """A reviewed neutrino.domain-dialect is accepted vocabulary, so cross-references must
    resolve AND the provenance backing accepted L2 vocabulary / translation maps must itself
    be 'accepted' — not merely 'proposed' or 'rejected'. Runs only after the shape is sound.
    """
    out = []
    graph = dialect.get("mappingGraph", {})
    node_ids, edge_ids, edge_status = set(), set(), {}
    for n in graph.get("nodes", []):
        nid = n.get("id")
        if nid in node_ids:
            out.append(diag("dialect.duplicate_id", f"duplicate mappingGraph node id: {nid}"))
        node_ids.add(nid)
    for e in graph.get("edges", []):
        eid = e.get("id")
        if eid in edge_ids:
            out.append(diag("dialect.duplicate_id", f"duplicate mappingGraph edge id: {eid}"))
        edge_ids.add(eid)
        edge_status[eid] = (e.get("provenance") or {}).get("status")
        for end in ("from", "to"):
            if e.get(end) not in node_ids:
                out.append(diag("dialect.dangling_edge_ref",
                                f"edge {eid}: '{end}' references unknown node id: {e.get(end)}"))

    for kind in ("terms", "templates"):
        container = dialect.get(kind)
        for name, item in (container if isinstance(container, dict) else {}).items():
            refs = item.get("provenanceRefs") or []
            if item.get("layer") == "L2" and not refs:
                out.append(diag("dialect.missing_provenance",
                                f"{kind[:-1]} '{name}' is L2 but has no provenanceRefs (mapping-graph edge)"))
            for r in refs:
                if r not in edge_ids:
                    out.append(diag("dialect.unknown_provenance_ref",
                                    f"{kind[:-1]} '{name}': provenanceRef '{r}' is not a mappingGraph edge id"))
                elif item.get("layer") == "L2" and edge_status.get(r) != "accepted":
                    out.append(diag("dialect.unaccepted_provenance",
                                    f"{kind[:-1]} '{name}': provenanceRef '{r}' has status '{edge_status.get(r)}' "
                                    f"(reviewed L2 vocabulary requires accepted provenance)"))

    tmaps = dialect.get("translationMaps")
    for name, m in (tmaps if isinstance(tmaps, dict) else {}).items():
        status = (m.get("provenance") or {}).get("status") if isinstance(m, dict) else None
        if status != "accepted":
            out.append(diag("dialect.unaccepted_provenance",
                            f"translationMap '{name}': provenance status '{status}' "
                            f"(a reviewed dialect requires accepted translation-map provenance)"))
    return sorted(out, key=lambda d: (d["code"], d["message"]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate + hash-pin a neutrino.domain-dialect artifact")
    ap.add_argument("--dialect", required=True, help="dialect artifact (.json, or .yaml/.yml with PyYAML)")
    ap.add_argument("--out", required=True, help="output dir for the report + diagnostics")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    try:
        dialect = load_artifact(args.dialect)
    except (OSError, ValueError, RuntimeError) as exc:
        json.dump({"ok": False, "diagnostics": [diag("dialect.io", str(exc))]},
                  open(os.path.join(args.out, "diagnostics.json"), "w"), indent=2, sort_keys=True)
        return 2

    diagnostics: list = []
    digest = None
    if not isinstance(dialect, dict):
        diagnostics.append(diag("dialect.schema", "top-level artifact must be a JSON object"))
    else:
        diagnostics += sorted(V().validate(dialect), key=lambda d: d["message"])
        # Cross-references only make sense once the shape is structurally sound.
        if not any(d["code"] == "dialect.schema" for d in diagnostics):
            diagnostics += crossref_diagnostics(dialect)
        digest = canonical_hash(dialect)
        embedded = dialect.get("domainDialectHash")
        if embedded is not None and embedded != digest:
            diagnostics.append(diag("dialect.hash_mismatch",
                                    f"embedded domainDialectHash {embedded} != computed {digest}"))

    errors = [d for d in diagnostics if d.get("severity") == "error"]
    ok = not errors
    report = {
        "kind": "neutrino.domain-dialect-validation",
        "domain": dialect.get("domain") if isinstance(dialect, dict) else None,
        "version": dialect.get("version") if isinstance(dialect, dict) else None,
        "domainDialectHash": digest,
        "counts": {
            "terms": len(dialect.get("terms", {})) if isinstance(dialect, dict) else 0,
            "templates": len(dialect.get("templates", {})) if isinstance(dialect, dict) else 0,
            "translationMaps": len(dialect.get("translationMaps", {})) if isinstance(dialect, dict) else 0,
            "nodes": len(dialect.get("mappingGraph", {}).get("nodes", [])) if isinstance(dialect, dict) else 0,
            "edges": len(dialect.get("mappingGraph", {}).get("edges", [])) if isinstance(dialect, dict) else 0,
        },
        "ok": ok,
    }
    json.dump(report, open(os.path.join(args.out, "domain-dialect.report.json"), "w"),
              indent=2, sort_keys=True)
    json.dump({"ok": ok, "diagnostics": sorted(diagnostics, key=lambda d: (d["code"], d["message"]))},
              open(os.path.join(args.out, "diagnostics.json"), "w"), indent=2, sort_keys=True)
    # On success, emit the validated artifact as normalized JSON so downstream
    # consumers (e.g. neutrino_lang.py dialect) read the validator's own parse rather
    # than re-reading the source — which would mis-handle a valid YAML-authored dialect.
    if ok and isinstance(dialect, dict):
        json.dump(dialect, open(os.path.join(args.out, "domain-dialect.normalized.json"), "w"),
                  indent=2, sort_keys=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
