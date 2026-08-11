#!/usr/bin/env python3
"""M5 WP2 () — test-realization companion validation.

Validates `neutrino-gen --target=test-realization` output (test-realization.json):
the concrete backend test cases folded from a capability spec + a scenario, kept
OUTSIDE the capability hash scope.

Mirrors docs/schemas/test-realization.schema.json AND enforces the one
beyond-schema integrity invariant a JSON-Schema cannot express: `capabilityHash`
is a well-formed reference AND, when a capability-spec is provided (--spec), it MATCHES that
spec's identity.capabilityHash — so a stale or hand-edited reference (a
realization pointing at no real capability) fails closed. Codes come from the
shared failure taxonomy (docs/diagnostic-taxonomy.json, ): realization.*.

Stdlib only (no jsonschema); the fast tier runs this script, and self-test [78]
cross-checks its diag() codes against the taxonomy.
"""
import argparse
import json
import os
import re
import sys

SCHEMA_VERSION = 1
KIND = "neutrino.test-realization"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
TOP_FIELDS = {"schemaVersion", "kind", "capabilityHash", "scenario", "procedure",
              "inputs", "computed", "eventChain", "ledgerDeltas", "invariants"}


def diag(code: str, message: str, severity: str = "error") -> dict:
    return {"severity": severity, "code": code, "message": message}


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate(tr) -> list:
    out: list = []
    if not isinstance(tr, dict):
        return [diag("realization.schema", "top-level must be a JSON object")]

    keys = set(tr)
    for missing in sorted(TOP_FIELDS - keys):
        out.append(diag("realization.missing_field",
                        f"missing required field '{missing}'"))
    for unknown in sorted(keys - TOP_FIELDS):
        out.append(diag("realization.unknown_field",
                        f"unknown field '{unknown}'"))
    if out:
        return out

    if tr["schemaVersion"] != SCHEMA_VERSION:
        out.append(diag("realization.schema_version",
                        f"unsupported schemaVersion {tr['schemaVersion']!r}"))
    if tr["kind"] != KIND:
        out.append(diag("realization.schema", f"kind must be '{KIND}'"))
    for name in ("scenario", "procedure"):
        if not isinstance(tr[name], str) or not tr[name]:
            out.append(diag("realization.schema", f"{name} must be a non-empty string"))

    if not (isinstance(tr["capabilityHash"], str) and HEX64.fullmatch(tr["capabilityHash"])):
        out.append(diag("realization.bad_hash",
                        "capabilityHash must be a 64-char lowercase hex sha256"))

    # inputs: int|string; computed/ledgerDeltas: int; eventChain/invariants: [string]
    if not isinstance(tr["inputs"], dict) or not all(
            _is_int(v) or isinstance(v, str) for v in tr["inputs"].values()):
        out.append(diag("realization.schema", "inputs must map names to integer/string"))
    for num in ("computed", "ledgerDeltas"):
        if not isinstance(tr[num], dict) or not all(_is_int(v) for v in tr[num].values()):
            out.append(diag("realization.schema", f"{num} must map names to integers"))
    for arr in ("eventChain", "invariants"):
        if not isinstance(tr[arr], list) or not all(isinstance(x, str) for x in tr[arr]):
            out.append(diag("realization.schema", f"{arr} must be an array of strings"))

    return out


def _cross_check(tr: dict, spec_path: str, out: list) -> None:
    """Beyond-schema: capabilityHash must match the referenced spec's."""
    try:
        spec = json.load(open(spec_path, encoding="utf-8"))
        spec_hash = spec["identity"]["capabilityHash"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        out.append(diag("realization.io", f"cannot read spec for cross-check: {exc}"))
        return
    if tr.get("capabilityHash") != spec_hash:
        out.append(diag("realization.hash_mismatch",
                        "capabilityHash does not match the referenced spec's "
                        f"identity.capabilityHash ({tr.get('capabilityHash')} != {spec_hash})"))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate a neutrino test-realization (--target=test-realization output)")
    ap.add_argument("file", help="path to test-realization.json")
    ap.add_argument("--spec", help="a capability-spec.json to cross-check capabilityHash against")
    ap.add_argument("--out", help="output dir for realization.report.json + diagnostics.json")
    args = ap.parse_args()

    tr = None
    try:
        tr = json.load(open(args.file, encoding="utf-8"))
        diagnostics = validate(tr)
    except OSError as exc:
        diagnostics = [diag("realization.io", f"cannot read test-realization: {exc}")]
    except ValueError as exc:
        diagnostics = [diag("realization.json", f"not well-formed JSON: {exc}")]

    if args.spec and isinstance(tr, dict) and not diagnostics:
        _cross_check(tr, args.spec, diagnostics)

    errors = [d for d in diagnostics if d.get("severity") == "error"]
    ok = not errors
    scenario = tr.get("scenario") if isinstance(tr, dict) else None
    report = {"ok": ok, "file": os.path.basename(args.file), "scenario": scenario,
              "diagnostics": diagnostics}

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        json.dump(report, open(os.path.join(args.out, "realization.report.json"), "w"),
                  indent=2, sort_keys=True)
        json.dump({"ok": ok, "diagnostics": diagnostics},
                  open(os.path.join(args.out, "diagnostics.json"), "w"), indent=2, sort_keys=True)

    json.dump({"ok": ok, "diagnostics": diagnostics}, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
