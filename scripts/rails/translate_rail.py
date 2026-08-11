#!/usr/bin/env python3
"""D4 / Phase 25 — apply a reviewed Lower-Layer translation map (lower / lift).

Bidirectional Lower-Layer mapping for one rail profile, driven entirely by the reviewed
`neutrino.translation-map` artifact — no hidden adapter code. Fail-closed: refuses to run
unless the map's translationMapHash matches its canonical recomputation, and surfaces
every lossy mapping explicitly.

  lower  core capability (canonical IR projection) -> rail-shaped projection fixture
         (which core value/party slot feeds each rail field; pacs.009).
  lift   rail status fixture (pacs.002) -> canonical runtime-evidence interpretation
         (status code-list -> evidence.runtimeState; UETR -> correlation; reason -> diag).

A rail status code absent from the reviewed code-list is REJECTED, never silently passed;
mandatory non-semantic fields are preserved in extensionData; declared `rejects` fields are
refused if present.

  translate_rail.py lower --map MAP --capability CAP.json --out OUT.json
  translate_rail.py lift  --map MAP --status STATUS.json  --out OUT.json

Exit 0 ok / 1 mapping error / 2 usage. Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys


class RailError(Exception):
    pass


def _canonical_hash(doc: dict) -> str:
    body = {k: v for k, v in doc.items() if k != "translationMapHash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _load_map(path: str) -> dict:
    m = json.load(open(path, encoding="utf-8"))
    if m.get("kind") != "neutrino.translation-map":
        raise RailError("not a neutrino.translation-map")
    # A reviewed map must be hash-pinned: the hash is required AND must match — an unpinned
    # (missing-hash) map must never drive lower/lift.
    embedded = m.get("translationMapHash")
    if not isinstance(embedded, str) or not embedded:
        raise RailError("translation map is not hash-pinned (translationMapHash missing); refusing to apply")
    if embedded != _canonical_hash(m):
        raise RailError("translationMapHash mismatch; refusing to apply a tampered map")
    return m


def _get_path(obj, path: str):
    cur = obj
    for seg in path.split("/"):
        if not isinstance(cur, dict) or seg not in cur:
            return None
        cur = cur[seg]
    return cur


def _resolve_carry(carry: str, cap: dict):
    typed = cap.get("typedInputs", [])
    entries = cap.get("entries", [])
    if carry in ("value.amount", "value.currency"):
        ty = "money" if carry == "value.amount" else "currency"
        names = [t["name"] for t in typed if t.get("type") == ty]
        if len(names) != 1:
            raise RailError(f"capability has {len(names)} '{ty}' inputs; cannot carry {carry}")
        return {"slot": names[0], "type": ty}
    if carry in ("party.debtor", "party.creditor"):
        kind = "debit" if carry == "party.debtor" else "credit"
        ents = [e for e in entries if e.get("kind") == kind]
        if len(ents) != 1:
            raise RailError(f"capability has {len(ents)} '{kind}' entries; cannot carry {carry}")
        e = ents[0]
        return {"role": e.get("owner"), "slot": (e.get("party") or {}).get("input")}
    raise RailError(f"unsupported lower carries '{carry}' for this capability shape")


def cmd_lower(m: dict, cap: dict) -> dict:
    fields = []
    for rule in m["lower"]:
        fields.append({
            "railField": rule["to"],
            "carries": rule["carries"],
            "source": _resolve_carry(rule["carries"], cap),
            "lossiness": rule["lossiness"],
        })
    return {
        "kind": "neutrino.rail-projection",
        "rail": m["rail"],
        "profile": m["profiles"]["lower"],
        "capability": cap.get("capability"),
        "fields": fields,
        "extensionData": [{"railField": p["field"], "extension": p["extension"]} for p in m["preservesAs"]],
        "rejected": [{"railField": r["field"], "reason": r["reason"]} for r in m["rejects"]],
        "lossyFields": sorted(f["railField"] for f in fields if f["lossiness"] != "lossless"),
    }


def cmd_lift(m: dict, status: dict) -> dict:
    out = {
        "kind": "neutrino.runtime-evidence-interpretation",
        "rail": m["rail"],
        "profile": m["profiles"]["liftStatus"],
        "runtimeState": None,
        "correlationId": None,
        "diagnostics": [],
        "extensionData": {},
        "lossyFields": [],
    }
    # a declared reject field that is actually present must fail closed.
    for r in m["rejects"]:
        if _get_path(status, r["field"]) is not None:
            raise RailError(f"rail field '{r['field']}' is present but declared rejected: {r['reason']}")
    for rule in m["liftStatus"]:
        raw = _get_path(status, rule["from"])
        if raw is None:
            continue  # field absent in this message
        if rule["lossiness"] != "lossless":
            out["lossyFields"].append(rule["from"])
        if rule["to"] == "evidence.runtimeState":
            code_list = rule["codeList"]
            if raw not in code_list:
                raise RailError(f"status code {raw!r} is not in the reviewed code-list; refusing to interpret")
            out["runtimeState"] = code_list[raw]
            out["extensionData"][rule["from"]] = raw  # preserve the raw rail status
        elif rule["to"] == "evidence.correlationId":
            out["correlationId"] = raw
        elif rule["to"] == "diagnostics.reasonCode":
            out["diagnostics"].append({"reasonCode": raw})
        elif rule["to"] == "diagnostics.additionalInfo":
            out["diagnostics"].append({"additionalInfo": raw})
    out["lossyFields"] = sorted(out["lossyFields"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    lo = sub.add_parser("lower")
    lo.add_argument("--map", required=True)
    lo.add_argument("--capability", required=True)
    lo.add_argument("--out", required=True)
    li = sub.add_parser("lift")
    li.add_argument("--map", required=True)
    li.add_argument("--status", required=True)
    li.add_argument("--out", required=True)
    try:
        args = ap.parse_args()
    except SystemExit:
        return 2

    try:
        m = _load_map(args.map)
        if args.cmd == "lower":
            result = cmd_lower(m, json.load(open(args.capability, encoding="utf-8")))
        else:
            result = cmd_lift(m, json.load(open(args.status, encoding="utf-8")))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}")
        return 2
    except RailError as exc:
        print(f"mapping error: {exc}")
        return 1

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"{args.cmd}: wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
