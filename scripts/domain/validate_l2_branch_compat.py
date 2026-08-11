#!/usr/bin/env python3
"""Validate branch-boundary compatibility across multiple L2 sidecars ().

Strategy 's value is participant-specific L2 semantics that still **compose at the
agreement boundary**. The single-sidecar validator (validate_l2_domain_semantics.py, )
checks one sidecar and its internal participant branches; this validator checks two or more
sidecars that refine the **same L1 capability** against EACH OTHER, on the facts they share.

Branch-boundary compatibility contract (minimal):
  - same L1 capability: every sidecar's l1.capability (and `implements`, qualified or its
    unqualified tail) must name the one shared capability — a sidecar refining/tracing to a
    different capability is rejected (L2X-2001).
  - shared evidence facts: where two sidecars declare an evidenceRequirement with the same
    `name` (e.g. proof_of_delivery), their `required` and `schemaRef` must agree (L2X-2002).
  - terminal outcome compatibility: where two sidecars expose a concept with the same
    `name`, its `kind` and `traces` (relation + to) must agree — the same action/state means
    the same thing at the boundary (L2X-2003).
  - shared value/currency facts: where two sidecars declare a parameter with the same
    `name`, its `type` must agree (L2X-2004).

Participant-specific is preserved: branches need NOT expose every concept/parameter — only
the INTERSECTION (shared names) is checked. This validator makes no runtime claim and does
no M4 evidence admission; it pins static cross-sidecar agreement only. The codes are the
L2X-2xxx family, distinct from the single-sidecar L2-1xxx codes. Standard library only.

  validate_l2_branch_compat.py --sidecar A.l2.json --sidecar B.l2.json [--sidecar C ...]
Exit 0 ok / 1 incompatible / 2 usage.
"""
from __future__ import annotations

import argparse
import json
import sys

TAXONOMY = {
    "L2X-2001": ("ERR_L2X_CAPABILITY", "capability", "error"),
    "L2X-2002": ("ERR_L2X_EVIDENCE", "evidence", "error"),
    "L2X-2003": ("ERR_L2X_OUTCOME", "outcome", "error"),
    "L2X-2004": ("ERR_L2X_PARAMETER", "parameter", "error"),
}


class Report:
    def __init__(self, capability=None):
        self.capability = capability
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
            "kind": "neutrino.l2-branch-compat-validation",
            "ok": not self.diags,
            "capability": self.capability,
            "diagnostics": sorted(self.diags, key=lambda d: (d["code"], d.get("where", ""), d["message"])),
        }


def _str(v):
    return isinstance(v, str) and v != ""


def _tail(cap):
    return cap.rsplit(".", 1)[-1] if isinstance(cap, str) else cap


def validate(sidecars: list[tuple], r: Report) -> None:
    """sidecars: list of (label, artifact-dict)."""
    # The shared capability anchor is the first sidecar's l1.capability.
    ref_cap = None
    for label, a in sidecars:
        if isinstance(a, dict) and isinstance(a.get("l1"), dict) and _str(a["l1"].get("capability")):
            ref_cap = a["l1"]["capability"]
            break
    r.capability = ref_cap

    # --- same L1 capability (L2X-2001) ---
    for label, a in sidecars:
        if not isinstance(a, dict):
            r.add("L2X-2001", f"{label}: not a JSON object", where=label)
            continue
        l1 = a.get("l1") if isinstance(a.get("l1"), dict) else {}
        cap = l1.get("capability")
        if not _str(cap):
            r.add("L2X-2001", f"{label}: l1.capability is required", where=label)
        elif ref_cap is not None and cap != ref_cap:
            r.add("L2X-2001",
                  f"{label}: l1.capability {cap!r} != shared capability {ref_cap!r} — "
                  "these sidecars refine different L1 capabilities", where=label)
        impl = a.get("implements")
        if _str(impl) and ref_cap is not None and impl not in (ref_cap, _tail(ref_cap)):
            r.add("L2X-2001",
                  f"{label}: implements {impl!r} does not name the shared capability "
                  f"{ref_cap!r} (nor its unqualified name {_tail(ref_cap)!r})", where=label)

    # --- build cross-sidecar indexes keyed by shared name ---
    evidence: dict[str, list] = {}
    concepts: dict[str, list] = {}
    params: dict[str, list] = {}
    for label, a in sidecars:
        if not isinstance(a, dict):
            continue
        for e in a.get("evidenceRequirements") or []:
            if isinstance(e, dict) and _str(e.get("name")):
                evidence.setdefault(e["name"], []).append(
                    (label, e.get("required", None), e.get("schemaRef", None)))
        for c in a.get("concepts") or []:
            if isinstance(c, dict) and _str(c.get("name")):
                tr = c.get("traces") if isinstance(c.get("traces"), dict) else {}
                concepts.setdefault(c["name"], []).append(
                    (label, c.get("kind"), tr.get("relation"), tr.get("to")))
        for p in a.get("parameters") or []:
            if isinstance(p, dict) and _str(p.get("name")):
                params.setdefault(p["name"], []).append((label, p.get("type")))

    # --- shared evidence facts agree (L2X-2002) ---
    for name, occ in evidence.items():
        if len(occ) < 2:
            continue  # participant-specific evidence is fine
        facts = {(req, ref) for _, req, ref in occ}
        if len(facts) > 1:
            detail = "; ".join(f"{lbl}: required={req!r} schemaRef={ref!r}" for lbl, req, ref in occ)
            r.add("L2X-2002",
                  f"evidence {name!r} is declared incompatibly across branches ({detail}) — "
                  "branches that claim the same boundary fact must agree on required/schemaRef",
                  where=name)

    # --- shared concept/outcome compatibility (L2X-2003) ---
    for name, occ in concepts.items():
        if len(occ) < 2:
            continue  # participant-specific concept is fine
        shapes = {(kind, rel, to) for _, kind, rel, to in occ}
        if len(shapes) > 1:
            detail = "; ".join(f"{lbl}: kind={kind!r} relation={rel!r} to={to!r}"
                               for lbl, kind, rel, to in occ)
            r.add("L2X-2003",
                  f"concept {name!r} has incompatible shape across branches ({detail}) — "
                  "the same boundary outcome must agree on kind and traces", where=name)

    # --- shared value/currency facts consistently typed (L2X-2004) ---
    for name, occ in params.items():
        if len(occ) < 2:
            continue  # participant-specific parameter is fine
        types = {t for _, t in occ}
        if len(types) > 1:
            detail = "; ".join(f"{lbl}: type={t!r}" for lbl, t in occ)
            r.add("L2X-2004",
                  f"parameter {name!r} is typed incompatibly across branches ({detail}) — "
                  "a shared value/currency boundary fact must be consistently typed", where=name)


def main() -> int:
    ap = argparse.ArgumentParser(description="validate branch-boundary compatibility across L2 sidecars ()")
    ap.add_argument("--sidecar", action="append", default=[], metavar="FILE",
                    help="an L2 domain-semantics sidecar (repeat; at least two)")
    args = ap.parse_args()
    if len(args.sidecar) < 2:
        print(json.dumps({"schemaVersion": 1, "kind": "neutrino.l2-branch-compat-validation",
                          "ok": False, "diagnostics": [
                              {"code": "L2X-2001", "symbol": "ERR_L2X_CAPABILITY", "category": "capability",
                               "severity": "error", "message": "at least two --sidecar artifacts are required"}]},
                         indent=2))
        return 2
    sidecars = []
    for path in args.sidecar:
        try:
            sidecars.append((path, json.load(open(path))))
        except (OSError, json.JSONDecodeError) as e:
            print(json.dumps({"schemaVersion": 1, "kind": "neutrino.l2-branch-compat-validation",
                              "ok": False, "diagnostics": [
                                  {"code": "L2X-2001", "symbol": "ERR_L2X_CAPABILITY", "category": "capability",
                                   "severity": "error", "message": f"cannot read sidecar {path}: {e}"}]}, indent=2))
            return 2
    r = Report()
    validate(sidecars, r)
    out = r.to_json()
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
