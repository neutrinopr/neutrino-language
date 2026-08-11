#!/usr/bin/env python3
"""D4 / Phase 25 — neutrino.translation-map validation + hash pinning.

A Lower-Layer translation map is an EXPLICIT, reviewed artifact (not hidden adapter
code): it must be fail-closed before it can drive a lower/lift projection. This gate
(standard library only; the authoritative spec is
docs/schemas/translation-map.schema.json):

  1. validates the structure fail-closed — unknown fields rejected, lossiness/`to`
     enums checked, required fields present;
  2. requires accepted provenance (a reviewed map cannot ride on proposed/rejected
     provenance) and acknowledged lossiness on every mapping — no mapping may be silently
     lossy. An active lower/liftStatus mapping may not be `unsupported` (that belongs in
     `rejects`); `preservesAs` must be `lossy-preserved-in-extensionData`;
  3. requires a reviewed code-list for an `evidence.runtimeState` lift (a status code not
     in the list is rejected at apply time, never silently passed);
  4. computes translationMapHash over the canonical JSON (sort_keys, compact separators,
     hash field removed) and verifies any embedded value.

Exit 0 ok / 1 violations / 2 usage.

  validate_translation_map.py FILE
"""
from __future__ import annotations

import hashlib
import json
import sys

LOSSINESS = {"lossless", "lossy-preserved-in-extensionData", "unsupported"}
LOWER_CARRIES = {"value.amount", "value.currency", "party.debtor", "party.creditor", "evidence.correlationId"}
LIFT_TO = {"evidence.runtimeState", "evidence.correlationId", "diagnostics.reasonCode", "diagnostics.additionalInfo"}


def canonical_hash(doc: dict) -> str:
    body = {k: v for k, v in doc.items() if k != "translationMapHash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_translation_map.py FILE")
        return 2
    try:
        d = json.load(open(sys.argv[1], encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot read translation map: {exc}")
        return 2

    errors: list[str] = []

    def need(obj, key, where):
        if key not in obj:
            errors.append(f"{where}: missing '{key}'")
            return False
        return True

    def no_unknown(obj, allowed, where):
        for k in obj:
            if k not in allowed:
                errors.append(f"{where}: unknown field '{k}'")

    def nonempty(v):
        return isinstance(v, str) and v != ""

    if not isinstance(d, dict):
        print("error: top-level must be an object")
        return 1
    top = ["kind", "rail", "version", "profiles", "provenance", "lower", "liftStatus", "preservesAs", "rejects"]
    for k in top:
        need(d, k, "map")
    no_unknown(d, set(top) | {"translationMapHash"}, "map")
    if d.get("kind") != "neutrino.translation-map":
        errors.append("map: kind must be 'neutrino.translation-map'")
    for k in ("rail", "version"):
        if not nonempty(d.get(k)):
            errors.append(f"map: '{k}' must be a non-empty string")

    prof = d.get("profiles", {})
    if isinstance(prof, dict):
        no_unknown(prof, {"lower", "liftStatus"}, "profiles")
        for k in ("lower", "liftStatus"):
            if not nonempty(prof.get(k)):
                errors.append(f"profiles: '{k}' must be a non-empty string")
    else:
        errors.append("map: profiles must be an object")

    prov = d.get("provenance", {})
    if isinstance(prov, dict):
        no_unknown(prov, {"source", "standardVersion", "reviewer", "status"}, "provenance")
        for k in ("source", "standardVersion", "reviewer"):
            if not nonempty(prov.get(k)):
                errors.append(f"provenance: '{k}' must be a non-empty string")
        if prov.get("status") != "accepted":
            errors.append("provenance.status must be 'accepted' for a reviewed map")
    else:
        errors.append("map: provenance must be an object")

    # The array sections must actually be arrays — a non-array container (e.g. "lower": {})
    # must fail closed, not be silently iterated as empty.
    for fld in ("lower", "liftStatus", "preservesAs", "rejects"):
        if fld in d and not isinstance(d[fld], list):
            errors.append(f"map: '{fld}' must be an array")

    for i, m in enumerate(d.get("lower", []) if isinstance(d.get("lower"), list) else []):
        w = f"lower[{i}]"
        if not isinstance(m, dict):
            errors.append(f"{w}: must be an object"); continue
        no_unknown(m, {"carries", "to", "lossiness"}, w)
        if m.get("carries") not in LOWER_CARRIES:
            errors.append(f"{w}: carries must be one of {sorted(LOWER_CARRIES)}")
        if not nonempty(m.get("to")):
            errors.append(f"{w}: 'to' (rail field) must be a non-empty string")
        ls = m.get("lossiness")
        if ls not in LOSSINESS:
            errors.append(f"{w}: lossiness must be one of {sorted(LOSSINESS)}")
        elif ls == "unsupported":
            errors.append(f"{w}: an active lower mapping cannot be 'unsupported' (use 'rejects')")

    for i, m in enumerate(d.get("liftStatus", []) if isinstance(d.get("liftStatus"), list) else []):
        w = f"liftStatus[{i}]"
        if not isinstance(m, dict):
            errors.append(f"{w}: must be an object"); continue
        no_unknown(m, {"from", "to", "codeList", "lossiness"}, w)
        if not nonempty(m.get("from")):
            errors.append(f"{w}: 'from' (rail field) must be a non-empty string")
        if m.get("to") not in LIFT_TO:
            errors.append(f"{w}: 'to' must be one of {sorted(LIFT_TO)}")
        ls = m.get("lossiness")
        if ls not in LOSSINESS:
            errors.append(f"{w}: lossiness must be one of {sorted(LOSSINESS)}")
        elif ls == "unsupported":
            errors.append(f"{w}: an active lift mapping cannot be 'unsupported' (use 'rejects')")
        if m.get("to") == "evidence.runtimeState":
            cl = m.get("codeList")
            if not isinstance(cl, dict) or not cl or any(not nonempty(v) for v in cl.values()):
                errors.append(f"{w}: evidence.runtimeState requires a non-empty codeList with non-empty values")
        elif "codeList" in m:
            errors.append(f"{w}: codeList only applies to evidence.runtimeState")

    for i, m in enumerate(d.get("preservesAs", []) if isinstance(d.get("preservesAs"), list) else []):
        w = f"preservesAs[{i}]"
        if not isinstance(m, dict):
            errors.append(f"{w}: must be an object"); continue
        no_unknown(m, {"field", "extension", "lossiness"}, w)
        if not nonempty(m.get("field")) or not nonempty(m.get("extension")):
            errors.append(f"{w}: 'field' and 'extension' must be non-empty strings")
        if m.get("lossiness") != "lossy-preserved-in-extensionData":
            errors.append(f"{w}: lossiness must be 'lossy-preserved-in-extensionData'")

    for i, m in enumerate(d.get("rejects", []) if isinstance(d.get("rejects"), list) else []):
        w = f"rejects[{i}]"
        if not isinstance(m, dict):
            errors.append(f"{w}: must be an object"); continue
        no_unknown(m, {"field", "reason"}, w)
        if not nonempty(m.get("field")) or not nonempty(m.get("reason")):
            errors.append(f"{w}: 'field' and 'reason' must be non-empty strings")

    # A reviewed map MUST be hash-pinned — the hash is required, not optional.
    embedded = d.get("translationMapHash")
    if not (isinstance(embedded, str) and len(embedded) == 64 and all(c in "0123456789abcdef" for c in embedded)):
        errors.append("translationMapHash is required (64-char lowercase hex) — a reviewed map must be hash-pinned")
    elif embedded != canonical_hash(d):
        errors.append(f"translationMapHash {embedded} != computed {canonical_hash(d)}")

    if errors:
        for e in errors:
            print(f"  - {e}")
        print(f"translation-map check: {len(errors)} problem(s)")
        return 1
    print(f"translation-map check: OK ({len(d.get('lower', []))} lower, {len(d.get('liftStatus', []))} lift, "
          f"{len(d.get('preservesAs', []))} preserve, {len(d.get('rejects', []))} reject)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
