#!/usr/bin/env python3
"""D2 / Phase 23 — sponsored-finance dialect expansion tool.

Proves the Upper-Layer path WITHOUT adding parser syntax: a reviewed, hash-pinned
`neutrino.domain-dialect` template is expanded into core `.neu` that the existing
translator accepts. The dialect (LLM/triangulation product) never enters the trusted
compiler path directly — this tool emits reviewable `.neu` plus an expansion manifest
that traces every generated construct back to a domain term + mapping-graph edge.

Fail-closed, standard library only:
  - refuses to expand unless the dialect's embedded domainDialectHash matches the
    canonical recomputation (same method as validate_domain_dialect.py), so a tampered
    dialect cannot be expanded;
  - derives each value-moving leg's operands from the template by explicit conventions
    and errors if the template violates them (see _operands), rather than guessing;
  - gates every field rendered into .neu through a strict identifier/ledger grammar
    (see _IDENT/_LEDGER), so a hash-valid dialect or a CLI arg cannot inject extra core
    source via a newline/quote/space in an input name, leg name, role, ledger,
    procedure, or trigger. The hash pin alone does not prevent this — the D1 schema only
    requires non-empty strings for these fields.

Conventions (the template stays minimal; the obligation schema is name/participant/
kind/ledger only):
  - owner            := role of the obligation's participant;
  - party            := the `party` input named `<role>_id`;
  - amount           := the single `money` input;
  - currency         := the single `currency` input;
  - idempotency_key  := the single `string` input;
  - `assert balanced`: emitted when the obligations contain >=1 debit and >=1 credit.

Expansion is deterministic/byte-stable: inputs keep the dialect's declared order, legs
keep the obligation order, and the manifest's edge lists are sorted.

  expand_dialect.py --dialect FILE --template ID --trigger NAME \\
      [--procedure NAME] --out-neu FILE --out-manifest FILE

Exit 0 ok / 1 expansion error / 2 usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys

# Anti-injection grammar gate. The hash pin only proves a dialect matches its OWN
# embedded hash; it does not constrain the grammar of fields rendered into .neu
# (the D1 schema only requires non-empty strings). Every value interpolated into the
# generated source — bare identifiers and quoted-string contents alike — is checked
# against a strict grammar, so a hash-valid dialect (or a CLI arg) cannot inject extra
# core source via a newline/quote/space in an input name, leg name, role, ledger,
# procedure, or trigger.
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")   # .neu identifiers (procedure/input/leg/trigger/owner-role)
_LEDGER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")  # dotted ledger path (rendered inside quotes)
_INPUT_TYPES = {"string", "party", "money", "currency", "number", "evidence"}


def _ident(value: str, what: str) -> str:
    if not isinstance(value, str) or not _IDENT.match(value):
        raise ExpansionError(f"{what} {value!r} is not a valid identifier (anti-injection gate)")
    return value


def _ledger(value: str, what: str) -> str:
    if not isinstance(value, str) or not _LEDGER.match(value):
        raise ExpansionError(f"{what} {value!r} is not a valid ledger path (anti-injection gate)")
    return value


def canonical_hash(dialect: dict) -> str:
    """sha256 over canonical JSON with domainDialectHash removed (matches the validator)."""
    body = {k: v for k, v in dialect.items() if k != "domainDialectHash"}
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


class ExpansionError(Exception):
    pass


def _unique_input(required: dict, ty: str, what: str) -> str:
    names = [n for n, t in required.items() if t == ty]
    if len(names) != 1:
        raise ExpansionError(
            f"template needs exactly one '{ty}' input for {what}, found {names or 'none'}")
    return names[0]


def _operands(template: dict):
    """Resolve the procedure-wide leg operands from requiredInputs (fail closed)."""
    required = template.get("requiredInputs", {})
    return {
        "amount": _unique_input(required, "money", "the leg amount"),
        "currency": _unique_input(required, "currency", "the leg currency"),
        "idempotency_key": _unique_input(required, "string", "the idempotency key"),
    }


def _party_input(required: dict, role: str) -> str:
    name = f"{role}_id"
    if required.get(name) != "party":
        raise ExpansionError(
            f"expected a 'party' input named '{name}' for role '{role}'")
    return name


def render_neu(dialect: dict, template_id: str, procedure: str, trigger: str) -> str:
    template = dialect.get("templates", {}).get(template_id)
    if template is None:
        raise ExpansionError(f"template '{template_id}' not found in dialect")
    if template.get("expandsTo") != "procedure":
        raise ExpansionError("only templates that expandsTo 'procedure' are supported")
    required = template.get("requiredInputs", {})
    participants = template.get("participants", {})
    obligations = template.get("obligations", [])
    ops = _operands(template)

    # Anti-injection gate: validate every field that gets rendered into .neu BEFORE
    # emitting a single line, so nothing partial is written for a bad dialect/arg.
    _ident(procedure, "procedure name")
    _ident(trigger, "trigger")
    for pname, pdef in participants.items():
        _ident(pname, "participant name")
        _ident((pdef or {}).get("role", ""), "participant role")
    for name, ty in required.items():
        _ident(name, "input name")
        if ty not in _INPUT_TYPES:
            raise ExpansionError(f"input {name!r} has unsupported type {ty!r}")
    for ob in obligations:
        if ob.get("kind") not in ("debit", "credit"):
            raise ExpansionError(f"obligation {ob.get('name')!r} has invalid kind {ob.get('kind')!r}")
        _ident(ob.get("name", ""), "obligation name")
        _ledger(ob.get("ledger", ""), "ledger")
        part = participants.get(ob.get("participant"))
        if not isinstance(part, dict):
            raise ExpansionError(f"obligation {ob.get('name')!r} names unknown participant {ob.get('participant')!r}")
        _ident(part.get("role", ""), "participant role")

    # Track the 1-based source span of each construct as it is emitted, so D3
    # domain-origin diagnostics can map a core .neu error line back to its construct.
    lines: list = []
    spans: dict = {}
    lines += [
        f"// Generated from the {dialect['domain']}@{dialect['version']} domain dialect"
        f" (template: {template_id}).",
        "// DO NOT EDIT — regenerate with scripts/domain/expand_dialect.py. Every construct traces",
        "// to a domain term + mapping-graph edge in the .expansion.json sidecar.",
        "",
    ]
    spans[f"procedure {procedure}"] = (len(lines) + 1, len(lines) + 1)
    lines += [
        f"procedure {procedure} {{",
        f"    trigger {trigger}",
        "",
    ]
    # Participant declarations (L1, from the template) — so the generated capability
    # carries the organization -> participant -> slot model (D1b binding-topology), and
    # the security pass binds every value-moving leg to a declared participant.
    for pname, pdef in participants.items():
        start = len(lines) + 1
        lines += [
            f"    participant {pname} {{",
            f'        role = "{pdef["role"]}"',
            "    }",
        ]
        spans[f"participant {pname}"] = (start, len(lines))
    if participants:
        lines.append("")
    for name, ty in required.items():
        lines.append(f"    input {name} : {ty}")
    has_debit = any(o["kind"] == "debit" for o in obligations)
    has_credit = any(o["kind"] == "credit" for o in obligations)
    for ob in obligations:
        part = participants.get(ob["participant"])
        if part is None:
            raise ExpansionError(f"obligation '{ob['name']}' names unknown participant '{ob['participant']}'")
        role = part["role"]
        party = _party_input(required, role)
        lines.append("")
        start = len(lines) + 1
        lines += [
            f"    {ob['kind']} {ob['name']} {{",
            f'        ledger = "{ob["ledger"]}"',
            f'        owner = "{role}"',
            f'        participant = "{ob["participant"]}"',
            f"        party = %{party}",
            f"        amount = %{ops['amount']}",
            f"        currency = %{ops['currency']}",
            f"        idempotency_key = %{ops['idempotency_key']}",
            "    }",
        ]
        spans[f"{ob['kind']} {ob['name']}"] = (start, len(lines))
    if has_debit and has_credit:
        lines += ["", "    assert balanced"]
    lines += ["}", ""]
    return "\n".join(lines), spans


def _edges_by_id(dialect: dict) -> dict:
    return {e["id"]: e for e in dialect.get("mappingGraph", {}).get("edges", [])}


def _term_by_role(dialect: dict, role: str):
    for name, term in dialect.get("terms", {}).items():
        if term.get("role") == role:
            return name, term
    return None, None


def build_manifest(dialect: dict, template_id: str, procedure: str,
                   neu_text: str, neu_basename: str, spans: dict) -> dict:
    template = dialect["templates"][template_id]
    edges = _edges_by_id(dialect)
    participants = template.get("participants", {})

    def span_of(construct: str) -> dict:
        s, e = spans[construct]
        return {"startLine": s, "endLine": e}

    def expand_edges_for(concept_name: str) -> list:
        return sorted(e["id"] for e in dialect["mappingGraph"]["edges"]
                      if e["type"] == "expandsTo" and e["from"] == f"concept:{concept_name}")

    def lower_edges_for(concept_name: str) -> list:
        return [e for e in dialect["mappingGraph"]["edges"]
                if e["type"] == "lowersTo" and e["from"] == f"concept:{concept_name}"]

    constructs = []
    used = set(template.get("provenanceRefs", []))
    constructs.append({
        "construct": f"procedure {procedure}",
        "fromTemplate": template_id,
        "edges": sorted(template.get("provenanceRefs", [])),
        "sourceSpan": span_of(f"procedure {procedure}"),
    })

    # Participant declarations + the org -> participant -> slot grouping. The slotId is
    # exactly the id D1b's binding-topology assigns to this generated .neu
    # ("coordinate.<procedure>#<participant>"), so the dialect's view and the compiler's
    # output can be cross-checked. Template participants carry no org (the dialect schema
    # allows only `role`), so organizationId is null here.
    cap = f"coordinate.{procedure}"
    grouping = []
    for pname, pdef in participants.items():
        role = pdef["role"]
        term_name, term = _term_by_role(dialect, role)
        term_edges = sorted(term.get("provenanceRefs", [])) if term else []
        if not term_edges:
            raise ExpansionError(f"participant role {role!r} has no backing term (cannot trace)")
        used.update(term_edges)
        constructs.append({
            "construct": f"participant {pname}",
            "participantTerm": term_name,
            "edges": term_edges,
            "sourceSpan": span_of(f"participant {pname}"),
        })
        grouping.append({
            "organizationId": pdef.get("org"),
            "participantId": pname,
            "role": role,
            "slotId": f"{cap}#{pname}",
            "termEdges": term_edges,
        })

    lower_prov = []
    for ob in template.get("obligations", []):
        role = participants[ob["participant"]]["role"]
        term_name, term = _term_by_role(dialect, role)
        term_edges = sorted(term.get("provenanceRefs", [])) if term else []
        exp_edges = expand_edges_for(ob["name"])
        c_edges = sorted(set(term_edges) | set(exp_edges))
        used.update(c_edges)
        constructs.append({
            "construct": f"{ob['kind']} {ob['name']}",
            "participantTerm": term_name,
            "edges": c_edges,
            "sourceSpan": span_of(f"{ob['kind']} {ob['name']}"),
        })
        for le in lower_edges_for(ob["name"]):
            used.add(le["id"])
            lower_prov.append({
                "concept": ob["name"],
                "edge": le["id"],
                "railField": le["to"],
                "source": le.get("provenance", {}).get("source"),
                "lossiness": le.get("lossiness"),
            })

    missing = sorted(eid for eid in used if eid not in edges)
    if missing:
        raise ExpansionError(f"manifest references edge ids absent from the dialect: {missing}")

    return {
        "kind": "neutrino.dialect-expansion-manifest",
        "schemaVersion": 1,
        "dialect": {
            "domain": dialect["domain"],
            "version": dialect["version"],
            "domainDialectHash": dialect.get("domainDialectHash"),
        },
        "template": {"id": template_id, "version": dialect["version"]},
        "generated": {
            "path": neu_basename,
            "sourceHash": hashlib.sha256(neu_text.encode("utf-8")).hexdigest(),
        },
        "constructs": constructs,
        "grouping": grouping,
        "edgesUsed": sorted(used),
        "lowerProvenance": lower_prov,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dialect", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--trigger", required=True)
    ap.add_argument("--procedure")
    ap.add_argument("--out-neu", required=True)
    ap.add_argument("--out-manifest", required=True)
    try:
        args = ap.parse_args()
    except SystemExit:
        return 2

    try:
        dialect = json.load(open(args.dialect, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot read dialect: {exc}")
        return 2

    try:
        if dialect.get("kind") != "neutrino.domain-dialect":
            raise ExpansionError("not a neutrino.domain-dialect")
        embedded = dialect.get("domainDialectHash")
        digest = canonical_hash(dialect)
        if embedded != digest:
            raise ExpansionError(
                f"dialect hash mismatch (embedded {embedded} != computed {digest}); refusing to expand")
        procedure = args.procedure or args.template
        neu_text, spans = render_neu(dialect, args.template, procedure, args.trigger)
        import os
        manifest = build_manifest(dialect, args.template, procedure, neu_text,
                                  os.path.basename(args.out_neu), spans)
    except ExpansionError as exc:
        print(f"expansion error: {exc}")
        return 1

    open(args.out_neu, "w", encoding="utf-8").write(neu_text)
    with open(args.out_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"expanded {args.template} -> {args.out_neu} (+ {args.out_manifest})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
