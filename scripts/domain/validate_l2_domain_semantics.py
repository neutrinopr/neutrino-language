#!/usr/bin/env python3
"""Validate a neutrino.l2-domain-semantics artifact ().

M3 L2 Domain Semantics is a schema-first, reviewable sidecar (NOT source syntax):
industry lifecycle / invariants / evidence-requirements / failure-modes that refine
an L1 capability. This validator is deterministic and FAIL-CLOSED — it accepts a
valid artifact and rejects unsupported/ambiguous constructs. Output is a
machine-readable coded-diagnostics envelope, aligned with
validate_binding_manifest.py. Standard library only.

Core rules (beyond shape):
  - traceability: every concept.traces.to must resolve to an l1.primitives /
    l1.obligations entry or a declared failureModes[].name (L2-1003).
  - participant branches reference declared concepts (L2-1004).
  - parameters declare interfaces only — no concrete value / magic number (L2-1005).
  - a guard/invariant operand `param:<name>` must resolve to a declared parameter
    (L2-1008) — an undeclared parameter reference is a missing declaration.
  - guards/invariants use the minimum expression model — EXACTLY ONE of a structured
    `compare` (with a symbolic `right`, never a numeric literal) or a `predicateRef`;
    free-form/ambiguous expressions are rejected (L2-1006).
  - invariant.onFailure references a declared failure mode (L2-1007).

L2 only DECLARES evidence requirements; M4 runtime/admission verifies actual
evidence (this validator makes no runtime claim).

  validate_l2_domain_semantics.py --artifact FILE
Exit 0 ok / 1 violations / 2 usage.
"""
from __future__ import annotations

import argparse
import json
import sys

TAXONOMY = {
    "L2-1001": ("ERR_L2_SHAPE", "shape", "error"),
    "L2-1002": ("ERR_L2_IDENTITY", "identity", "error"),
    "L2-1003": ("ERR_L2_TRACEABILITY", "traceability", "error"),
    "L2-1004": ("ERR_L2_BRANCH", "branch", "error"),
    "L2-1005": ("ERR_L2_PARAMETER", "parameter", "error"),
    "L2-1006": ("ERR_L2_EXPRESSION", "expression", "error"),
    "L2-1007": ("ERR_L2_REFERENCE", "reference", "error"),
    "L2-1008": ("ERR_L2_PARAM_UNDECLARED", "parameter", "error"),
}

# A guard/invariant operand of the form `param:<name>` must resolve to a declared
# parameter — an undeclared parameter reference is a missing declaration (L2-1008),
# the fail-closed counterpart to the "no magic numbers" rule (L2-1005).
PARAM_PREFIX = "param:"

TOP_FIELDS = {"kind", "schemaVersion", "domain", "version", "implements", "coverage",
              "l1", "failureModes", "concepts", "participantBranches",
              "parameters", "evidenceRequirements", "guards", "invariants"}
OPS = {"<", "<=", "==", "!=", ">=", ">"}


class Report:
    def __init__(self, domain=None):
        self.domain = domain
        self.diags: list[dict] = []

    def add(self, code, message, *, where=None):
        symbol, category, severity = TAXONOMY[code]
        d = {"code": code, "symbol": symbol, "category": category,
             "severity": severity, "message": message}
        if where is not None:
            d["where"] = where
        self.diags.append(d)

    def to_json(self) -> dict:
        return {
            "schemaVersion": 1,
            "kind": "neutrino.l2-domain-semantics-validation",
            "ok": not self.diags,
            "domain": self.domain,
            "diagnostics": sorted(self.diags, key=lambda d: (d["code"], d.get("where", ""), d["message"])),
        }


def _str(v):
    return isinstance(v, str) and v != ""


def _list(v):
    return v if isinstance(v, list) else []


def _no_unknown(r, obj, allowed, where):
    """Enforce additionalProperties:false on a nested object (the schema marks every
    object closed; the validator must too, or typos/smuggled fields fail open)."""
    if isinstance(obj, dict):
        for k in obj:
            if k not in allowed:
                r.add("L2-1001", f"{where}: unknown field {k!r}", where=where)


def validate(a, r: Report) -> None:
    if not isinstance(a, dict):
        r.add("L2-1001", "artifact must be a JSON object")
        return
    for k in a:
        if k not in TOP_FIELDS:
            r.add("L2-1001", f"unknown field {k!r}", where=k)
    if a.get("kind") != "neutrino.l2-domain-semantics":
        r.add("L2-1001", "kind must be 'neutrino.l2-domain-semantics'")
    if a.get("schemaVersion") != 1:
        r.add("L2-1001", "schemaVersion must be 1")
    r.domain = a.get("domain") if _str(a.get("domain")) else None
    if not _str(a.get("domain")):
        r.add("L2-1001", "domain is required (non-empty string)")
    if "coverage" in a and a["coverage"] not in ("full", "partial"):
        r.add("L2-1001", "coverage must be 'full' or 'partial'")

    # --- identity (L2-1002) ---
    if not _str(a.get("implements")):
        r.add("L2-1002", "implements is required (the L1 capability/role this L2 refines)")
    l1 = a.get("l1") if isinstance(a.get("l1"), dict) else {}
    if not a.get("l1"):
        r.add("L2-1002", "l1 is required")
    _no_unknown(r, l1, {"capability", "primitives", "obligations"}, "l1")
    if not _str(l1.get("capability")):
        r.add("L2-1002", "l1.capability is required (non-empty string)")
    # `implements` names the refined L1 capability; `l1.capability` is the anchor the concepts
    # trace into. They must name the SAME capability, or the sidecar claims to refine one
    # capability while tracing into another (silently mis-tied to L1). `implements` may be
    # either the fully-qualified capability id or its unqualified tail (the bare procedure
    # name) — e.g. implements 'core_sponsored_offer' matches l1.capability
    # 'coordinate.core_sponsored_offer'. Anything else is a divergence.
    if _str(a.get("implements")) and _str(l1.get("capability")):
        cap = l1["capability"]
        if a["implements"] not in (cap, cap.rsplit(".", 1)[-1]):
            r.add("L2-1002",
                  f"implements {a['implements']!r} != l1.capability {cap!r} (nor its unqualified "
                  f"name {cap.rsplit('.', 1)[-1]!r}) — they must name the same L1 capability",
                  where="implements")

    # --- traceability anchors ---
    primitives = {x for x in _list(l1.get("primitives")) if _str(x)}
    obligations = {x for x in _list(l1.get("obligations")) if _str(x)}
    failure_names = set()
    for i, fm in enumerate(_list(a.get("failureModes"))):
        if not isinstance(fm, dict):
            r.add("L2-1001", "failureMode must be an object", where=f"failureModes[{i}]")
            continue
        _no_unknown(r, fm, {"name", "compensation"}, fm.get("name") or f"failureModes[{i}]")
        if _str(fm.get("name")):
            failure_names.add(fm["name"])
    anchors = primitives | obligations | failure_names

    # --- concepts: every concept must trace back (L2-1003) ---
    concept_names: set[str] = set()
    concepts = _list(a.get("concepts"))
    if not concepts:
        r.add("L2-1001", "concepts must be a non-empty array")
    for i, c in enumerate(concepts):
        if not isinstance(c, dict):
            r.add("L2-1001", "concept must be an object", where=f"concepts[{i}]")
            continue
        name = c.get("name")
        _no_unknown(r, c, {"name", "kind", "traces"}, name or f"concepts[{i}]")
        if _str(name):
            concept_names.add(name)
        else:
            r.add("L2-1001", "concept.name is required", where=f"concepts[{i}]")
        if c.get("kind") not in ("state", "action", "concept"):
            r.add("L2-1001", "concept.kind must be state|action|concept", where=name or f"concepts[{i}]")
        tr = c.get("traces") if isinstance(c.get("traces"), dict) else None
        if not tr:
            r.add("L2-1003", f"concept {name!r} has no traces back to L1", where=name)
            continue
        _no_unknown(r, tr, {"to", "relation"}, name or f"concepts[{i}].traces")
        if tr.get("relation") not in ("expands", "discharges", "protects", "failure"):
            r.add("L2-1001", "traces.relation must be expands|discharges|protects|failure", where=name)
        to = tr.get("to")
        if not _str(to):
            r.add("L2-1003", f"concept {name!r} traces.to is required", where=name)
        elif to not in anchors:
            r.add("L2-1003",
                  f"concept {name!r} traces to {to!r}, which is not an l1 primitive/obligation "
                  "or a declared failure mode", where=name)

    # --- participant branches reference declared concepts (L2-1004) ---
    for i, br in enumerate(_list(a.get("participantBranches"))):
        if not isinstance(br, dict):
            r.add("L2-1001", "participantBranch must be an object", where=f"participantBranches[{i}]")
            continue
        p = br.get("participant") or f"participantBranches[{i}]"
        _no_unknown(r, br, {"participant", "concepts"}, p)
        for cn in _list(br.get("concepts")):
            if cn not in concept_names:
                r.add("L2-1004", f"branch {p!r} references unknown concept {cn!r}", where=p)

    # --- parameters: interfaces only, no concrete value / magic number (L2-1005) ---
    param_names: set[str] = set()
    for i, p in enumerate(_list(a.get("parameters"))):
        if not isinstance(p, dict):
            r.add("L2-1001", "parameter must be an object", where=f"parameters[{i}]")
            continue
        pname = p.get("name") or f"parameters[{i}]"
        if _str(p.get("name")):
            param_names.add(p["name"])
        for k in p:
            if k not in ("name", "type", "required"):
                # any extra key (notably a concrete `value`/`default`) is a magic number
                r.add("L2-1005",
                      f"parameter {pname!r}: unexpected field {k!r} — parameters declare "
                      "interfaces only (no concrete values; those belong in L3/simulation)",
                      where=pname)
        if not _str(p.get("type")):
            r.add("L2-1001", f"parameter {pname!r}: type is required", where=pname)

    # --- evidence requirements: declarations only (shape) ---
    # An evidence requirement may optionally declare a `category` and `proofTags` (,
    # ChannelVerificationEarmark): the typed proof intent the requirement carries. L2 only
    # DECLARES it; M4 runtime/admission verifies the concrete proof. Proof tags are constrained.
    PROOF_TAGS = {"authority", "event", "liveness"}
    for i, e in enumerate(_list(a.get("evidenceRequirements"))):
        if not isinstance(e, dict):
            r.add("L2-1001", "evidenceRequirement must be an object", where=f"evidenceRequirements[{i}]")
            continue
        for k in e:
            if k not in ("name", "required", "schemaRef", "category", "proofTags"):
                r.add("L2-1001", f"evidenceRequirement: unknown field {k!r}", where=e.get("name"))
        if "category" in e and not _str(e.get("category")):
            r.add("L2-1001", "evidenceRequirement.category must be a non-empty string", where=e.get("name"))
        if "proofTags" in e:
            pt = e.get("proofTags")
            if not (isinstance(pt, list) and pt and all(isinstance(x, str) for x in pt)):
                r.add("L2-1001", "evidenceRequirement.proofTags must be a non-empty array of strings",
                      where=e.get("name"))
            else:
                bad = [x for x in pt if x not in PROOF_TAGS]
                if bad:
                    r.add("L2-1001", f"evidenceRequirement.proofTags has unknown tag(s) {bad} "
                          f"(allowed: {sorted(PROOF_TAGS)})", where=e.get("name"))

    # --- guards / invariants: minimum expression model (L2-1006), onFailure ref (L2-1007) ---
    def check_param_ref(operand, kind, where):
        """A `param:<name>` operand must resolve to a declared parameter (L2-1008)."""
        if isinstance(operand, str) and operand.startswith(PARAM_PREFIX):
            ref = operand[len(PARAM_PREFIX):]
            if ref not in param_names:
                r.add("L2-1008",
                      f"{kind} {where!r}: references parameter {ref!r} ({operand!r}) which is "
                      "not declared in parameters[] — declare it (no implicit parameters)",
                      where=where)

    def check_predicate(pr, kind, idx, allow_on_failure):
        where = (pr.get("name") if isinstance(pr, dict) else None) or f"{kind}[{idx}]"
        if not isinstance(pr, dict):
            r.add("L2-1001", f"{kind} must be an object", where=f"{kind}[{idx}]")
            return
        allowed = {"name", "compare", "predicateRef"} | ({"onFailure"} if allow_on_failure else set())
        for k in pr:
            if k not in allowed:
                r.add("L2-1001", f"{kind} {where!r}: unknown field {k!r}", where=where)
        has_cmp = "compare" in pr
        has_ref = "predicateRef" in pr
        if has_cmp == has_ref:
            r.add("L2-1006",
                  f"{kind} {where!r} must have EXACTLY ONE of compare / predicateRef "
                  "(free-form/ambiguous expressions are not supported)", where=where)
        if has_cmp:
            cmp = pr["compare"] if isinstance(pr["compare"], dict) else {}
            _no_unknown(r, cmp, {"left", "op", "right"}, where)
            if cmp.get("op") not in OPS:
                r.add("L2-1006", f"{kind} {where!r}: compare.op must be one of {sorted(OPS)}", where=where)
            if not _str(cmp.get("left")):
                r.add("L2-1006", f"{kind} {where!r}: compare.left must be a reference", where=where)
            else:
                check_param_ref(cmp["left"], kind, where)
            right = cmp.get("right")
            if isinstance(right, (int, float)) and not isinstance(right, bool):
                r.add("L2-1005",
                      f"{kind} {where!r}: compare.right is a numeric literal {right!r} — use a "
                      "declared parameter (no magic numbers)", where=where)
            elif not _str(right):
                r.add("L2-1006", f"{kind} {where!r}: compare.right must be a symbolic reference", where=where)
            else:
                check_param_ref(right, kind, where)
        if has_ref and not _str(pr.get("predicateRef")):
            r.add("L2-1006", f"{kind} {where!r}: predicateRef must be a non-empty string", where=where)
        if allow_on_failure and "onFailure" in pr:
            if pr["onFailure"] not in failure_names:
                r.add("L2-1007",
                      f"{kind} {where!r}: onFailure {pr['onFailure']!r} is not a declared failure mode",
                      where=where)

    for i, g in enumerate(_list(a.get("guards"))):
        check_predicate(g, "guard", i, allow_on_failure=False)
    for i, inv in enumerate(_list(a.get("invariants"))):
        check_predicate(inv, "invariant", i, allow_on_failure=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="validate a neutrino.l2-domain-semantics artifact ()")
    ap.add_argument("--artifact", required=True, help="path to the L2 domain-semantics JSON")
    args = ap.parse_args()
    try:
        artifact = json.load(open(args.artifact))
    except (OSError, json.JSONDecodeError) as e:
        print(json.dumps({"schemaVersion": 1, "kind": "neutrino.l2-domain-semantics-validation",
                          "ok": False, "diagnostics": [
                              {"code": "L2-1001", "symbol": "ERR_L2_SHAPE", "category": "shape",
                               "severity": "error", "message": f"cannot read artifact: {e}"}]}, indent=2))
        return 2
    r = Report()
    validate(artifact, r)
    out = r.to_json()
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
