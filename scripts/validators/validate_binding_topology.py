#!/usr/bin/env python3
"""D1b / Phase 22B — neutrino.slot-binding-topology validation.

The base organization -> participant -> slot artifact lets a later Binding Manifest
name and validate an (organizationId, participantId, slotId) triple, so it must be
fail-closed and internally consistent. This gate:

  1. validates the artifact's structure fail-closed — unknown fields rejected,
     required fields present, lateBindingMode/minAssurance enumerated. The
     authoritative spec is docs/schemas/slot-binding-topology.schema.json; this
     validator enforces it with the standard library only (no runtime dependency,
     matching the repo's other checkers), and a self-test keeps the two aligned;
  2. enforces cross-references and invariants that the schema alone cannot express:
       - every slotId is globally unique and equals `<capability>#<participantId>`;
       - crossOrganization is true iff >= 2 distinct named organizations appear;
       - a `fixed` slot has no allowedRuntimes, no authorizedBinder, minAssurance A1
         (static generation never claims above A1);
       - a `to_be_bound` slot's authorizedBinder (when present) names its org.

This artifact is advisory model metadata and is EXCLUDED from capabilityHash, so it
is not hash-pinned here; it must still be shape-valid and consistent.

Exit 0 ok / 1 violations / 2 usage.

  validate_binding_topology.py FILE
"""
from __future__ import annotations

import json
import sys

MODES = {"fixed", "to_be_bound"}
ASSURANCE = {"A1", "A2", "A3", "A4"}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_binding_topology.py FILE")
        return 2
    try:
        doc = json.load(open(sys.argv[1], encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot read binding-topology: {exc}")
        return 2

    errors: list[str] = []

    def req(obj, key, where):
        if key not in obj:
            errors.append(f"{where}: missing '{key}'")
            return False
        return True

    def no_unknown(obj, allowed, where):
        for k in obj:
            if k not in allowed:
                errors.append(f"{where}: unknown field '{k}'")

    def nonempty_str(v):
        return isinstance(v, str) and v != ""

    if not isinstance(doc, dict):
        print("error: top-level must be an object")
        return 1

    top = ["kind", "schemaVersion", "capability", "capabilityVersion", "procedure",
           "organizations", "crossOrganization"]
    for k in top:
        req(doc, k, "topology")
    no_unknown(doc, set(top), "topology")
    if doc.get("kind") != "neutrino.slot-binding-topology":
        errors.append("topology: kind must be 'neutrino.slot-binding-topology'")
    if doc.get("schemaVersion") != 1:
        errors.append("topology: schemaVersion must be 1")
    cap = doc.get("capability")
    for k in ("capability", "capabilityVersion", "procedure"):
        if not nonempty_str(doc.get(k)):
            errors.append(f"topology: '{k}' must be a non-empty string")
    if not isinstance(doc.get("crossOrganization"), bool):
        errors.append("topology: crossOrganization must be a boolean")

    seen_slot_ids: set[str] = set()
    named_orgs: set[str] = set()
    orgs = doc.get("organizations", [])
    if not isinstance(orgs, list):
        errors.append("topology: organizations must be an array")
        orgs = []
    elif not orgs:
        # This artifact is emitted only when participants are declared, so an empty
        # topology is never valid output — fail closed rather than pass a no-op file.
        errors.append("topology: organizations must be non-empty (the artifact exists only when participants are declared)")

    for oi, org in enumerate(orgs):
        ow = f"organizations[{oi}]"
        if not isinstance(org, dict):
            errors.append(f"{ow}: must be an object")
            continue
        no_unknown(org, {"organizationId", "participants"}, ow)
        req(org, "organizationId", ow)
        oid = org.get("organizationId")
        if oid is not None and not nonempty_str(oid):
            errors.append(f"{ow}: organizationId must be a non-empty string or null")
        if isinstance(oid, str):
            named_orgs.add(oid)
        parts = org.get("participants", [])
        if not isinstance(parts, list) or not parts:
            errors.append(f"{ow}: participants must be a non-empty array")
            parts = []
        for pi, p in enumerate(parts):
            pw = f"{ow}.participants[{pi}]"
            if not isinstance(p, dict):
                errors.append(f"{pw}: must be an object")
                continue
            no_unknown(p, {"participantId", "role", "slots"}, pw)
            pid = p.get("participantId")
            if not nonempty_str(pid):
                errors.append(f"{pw}: participantId must be a non-empty string")
            if not nonempty_str(p.get("role")):
                errors.append(f"{pw}: role must be a non-empty string")
            slots = p.get("slots", [])
            if not isinstance(slots, list) or not slots:
                errors.append(f"{pw}: slots must be a non-empty array")
                slots = []
            for si, s in enumerate(slots):
                sw = f"{pw}.slots[{si}]"
                if not isinstance(s, dict):
                    errors.append(f"{sw}: must be an object")
                    continue
                no_unknown(s, {"slotId", "lateBindingMode", "allowedRuntimes",
                               "minAssurance", "evidenceProfile", "authorizedBinder"}, sw)
                sid = s.get("slotId")
                if not nonempty_str(sid):
                    errors.append(f"{sw}: slotId must be a non-empty string")
                else:
                    if sid in seen_slot_ids:
                        errors.append(f"{sw}: duplicate slotId '{sid}'")
                    seen_slot_ids.add(sid)
                    if nonempty_str(cap) and nonempty_str(pid) and sid != f"{cap}#{pid}":
                        errors.append(f"{sw}: slotId '{sid}' != '{cap}#{pid}'")
                mode = s.get("lateBindingMode")
                if mode not in MODES:
                    errors.append(f"{sw}: lateBindingMode must be one of {sorted(MODES)}")
                runtimes = s.get("allowedRuntimes")
                if not isinstance(runtimes, list) or any(not nonempty_str(r) for r in runtimes):
                    errors.append(f"{sw}: allowedRuntimes must be an array of non-empty strings")
                    runtimes = []
                if s.get("minAssurance") not in ASSURANCE:
                    errors.append(f"{sw}: minAssurance must be one of {sorted(ASSURANCE)}")
                ep = s.get("evidenceProfile", "MISSING")
                if ep == "MISSING":
                    errors.append(f"{sw}: missing 'evidenceProfile' (use null if unset)")
                elif ep is not None and not nonempty_str(ep):
                    errors.append(f"{sw}: evidenceProfile must be a non-empty string or null")
                # mode-specific invariants
                if mode == "fixed":
                    if runtimes:
                        errors.append(f"{sw}: a fixed slot must not declare allowedRuntimes")
                    if "authorizedBinder" in s:
                        errors.append(f"{sw}: a fixed slot must not declare authorizedBinder")
                    if s.get("minAssurance") != "A1":
                        errors.append(f"{sw}: a fixed slot's minAssurance must be A1 (static generation claims no more)")
                if "authorizedBinder" in s:
                    ab = s.get("authorizedBinder")
                    if not nonempty_str(ab):
                        errors.append(f"{sw}: authorizedBinder must be a non-empty string")
                    elif oid is None:
                        errors.append(f"{sw}: authorizedBinder set but the organization is unscoped (null) — a binder must name an org")
                    elif ab != oid:
                        errors.append(f"{sw}: authorizedBinder '{ab}' must name the owning organization '{oid}'")

    expected_cross = len(named_orgs) > 1
    if isinstance(doc.get("crossOrganization"), bool) and doc["crossOrganization"] != expected_cross:
        errors.append(f"topology: crossOrganization={doc['crossOrganization']} but {len(named_orgs)} named org(s) present")

    if errors:
        for e in errors:
            print(f"  - {e}")
        print(f"binding-topology check: {len(errors)} problem(s)")
        return 1
    print(f"binding-topology check: OK ({len(seen_slot_ids)} slot(s), {len(named_orgs)} named org(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
