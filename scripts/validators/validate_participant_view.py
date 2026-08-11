#!/usr/bin/env python3
"""M5 () — participant-view validation.

Validates `neutrino-gen --target=views` output (<participant>.json): a narrowed,
per-participant PROJECTION of the canonical capability spec.

Mirrors docs/schemas/participant-view.schema.json AND enforces the beyond-schema
invariants a JSON-Schema cannot express — the whole reason views exist for
consumption: given the referenced capability-spec (--spec), the view's `capabilityHash`
MATCHES the spec's, its `specContract` matches the spec's kind/schemaVersion, its
`visibleOperations` are the spec's lifecycle op vocabulary, and every `specPath`
in requiredInputs/evidenceObligations RESOLVES in the spec's sourceMap with a
matching source. So a stale/hand-edited view (pointing at no real capability, or
inventing a field the spec doesn't carry) fails closed. Codes come from the
shared failure taxonomy (docs/diagnostic-taxonomy.json, ): view.*.

Stdlib only (no jsonschema); the fast tier runs this script, and self-test [78]
cross-checks its diag() codes against the taxonomy.
"""
import argparse
import json
import os
import re
import sys

SCHEMA_VERSION = "0.2.0"
KIND = "neutrino.participant-view"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
TOP_FIELDS = {"kind", "schemaVersion", "procedure", "dslVersion", "capability",
              "participant", "visibleOperations", "requiredInputs",
              "permittedCounterparties", "evidenceObligations", "provenance"}


def diag(code: str, message: str, severity: str = "error") -> dict:
    return {"severity": severity, "code": code, "message": message}


def _int_ge1(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def _span_ok(s) -> bool:
    return (isinstance(s, dict) and set(s) == {"line", "column"}
            and _int_ge1(s.get("line")) and _int_ge1(s.get("column")))


def _obj(out, val, name, required, optional=frozenset()):
    """Check `val` is an object with exactly required(+optional) keys. Returns
    True if it is at least an object with all required keys (so callers can
    inspect fields), and records shape diagnostics for anything off."""
    if not isinstance(val, dict):
        out.append(diag("view.schema", f"{name} must be an object"))
        return False
    keys = set(val)
    if not required <= keys:
        out.append(diag("view.schema", f"{name} is missing {sorted(required - keys)}"))
    extra = keys - required - optional
    if extra:
        out.append(diag("view.schema", f"{name} has unexpected keys {sorted(extra)}"))
    return required <= keys


def validate(view) -> list:
    out: list = []
    if not isinstance(view, dict):
        return [diag("view.schema", "top-level must be a JSON object")]

    keys = set(view)
    optional = {"binding"}
    for missing in sorted(TOP_FIELDS - keys):
        out.append(diag("view.missing_field", f"missing required field '{missing}'"))
    for unknown in sorted(keys - TOP_FIELDS - optional):
        out.append(diag("view.unknown_field", f"unknown field '{unknown}'"))
    if out:
        return out

    if view["schemaVersion"] != SCHEMA_VERSION:
        out.append(diag("view.schema_version",
                        f"unsupported schemaVersion {view['schemaVersion']!r}"))
    if view["kind"] != KIND:
        out.append(diag("view.schema", f"kind must be '{KIND}'"))
    for s in ("procedure", "dslVersion"):
        if not isinstance(view[s], str) or not view[s]:
            out.append(diag("view.schema", f"{s} must be a non-empty string"))

    # capability { capabilityHash (hex64), specVersion }
    if _obj(out, view["capability"], "capability", {"capabilityHash", "specVersion"}):
        cap = view["capability"]
        if not (isinstance(cap["capabilityHash"], str) and HEX64.fullmatch(cap["capabilityHash"])):
            out.append(diag("view.bad_hash",
                            "capability.capabilityHash must be a 64-char lowercase hex sha256"))
        if not isinstance(cap["specVersion"], str):
            out.append(diag("view.schema", "capability.specVersion must be a string"))

    # participant { name, role, slotId, org? }
    if _obj(out, view["participant"], "participant", {"name", "role", "slotId"}, {"org"}):
        for k in ("name", "role", "slotId"):
            if not isinstance(view["participant"][k], str) or not view["participant"][k]:
                out.append(diag("view.schema", f"participant.{k} must be a non-empty string"))
        if "org" in view["participant"] and not isinstance(view["participant"]["org"], str):
            out.append(diag("view.schema", "participant.org must be a string"))

    if not isinstance(view["visibleOperations"], list) or not all(
            isinstance(x, str) for x in view["visibleOperations"]):
        out.append(diag("view.schema", "visibleOperations must be an array of strings"))

    # requiredInputs [ { name, type, specPath, source? } ]
    if isinstance(view["requiredInputs"], list):
        for item in view["requiredInputs"]:
            if _obj(out, item, "requiredInputs item", {"name", "type", "specPath"}, {"source"}):
                if not all(isinstance(item[k], str) for k in ("name", "type", "specPath")):
                    out.append(diag("view.schema", "requiredInputs name/type/specPath must be strings"))
                if "source" in item and not _span_ok(item["source"]):
                    out.append(diag("view.schema", "requiredInputs.source must be { line, column }"))
    else:
        out.append(diag("view.schema", "requiredInputs must be an array"))

    # permittedCounterparties [ { org, role? } ]
    if isinstance(view["permittedCounterparties"], list):
        for item in view["permittedCounterparties"]:
            if _obj(out, item, "permittedCounterparties item", {"org"}, {"role"}):
                if not isinstance(item["org"], str) or not item["org"]:
                    out.append(diag("view.schema", "permittedCounterparties.org must be a non-empty string"))
                if "role" in item and not isinstance(item["role"], str):
                    out.append(diag("view.schema", "permittedCounterparties.role must be a string"))
    else:
        out.append(diag("view.schema", "permittedCounterparties must be an array"))

    # binding (optional) { mode=to_be_bound, runtimes, minAssurance?, authorizedBinder? }
    if "binding" in view and _obj(out, view["binding"], "binding", {"mode", "runtimes"},
                                  {"minAssurance", "authorizedBinder"}):
        if view["binding"]["mode"] != "to_be_bound":
            out.append(diag("view.schema", "binding.mode must be 'to_be_bound'"))
        if not isinstance(view["binding"]["runtimes"], list) or not all(
                isinstance(x, str) for x in view["binding"]["runtimes"]):
            out.append(diag("view.schema", "binding.runtimes must be an array of strings"))
        for k in ("minAssurance", "authorizedBinder"):
            if k in view["binding"] and not isinstance(view["binding"][k], str):
                out.append(diag("view.schema", f"binding.{k} must be a string"))

    # evidenceObligations [ { leg, kind, ledger, specPath, source? } ]
    if isinstance(view["evidenceObligations"], list):
        for item in view["evidenceObligations"]:
            if _obj(out, item, "evidenceObligations item",
                    {"leg", "kind", "ledger", "specPath"}, {"source"}):
                if not all(isinstance(item[k], str) for k in ("leg", "kind", "ledger", "specPath")):
                    out.append(diag("view.schema", "evidenceObligations leg/kind/ledger/specPath must be strings"))
                if "source" in item and not _span_ok(item["source"]):
                    out.append(diag("view.schema", "evidenceObligations.source must be { line, column }"))
    else:
        out.append(diag("view.schema", "evidenceObligations must be an array"))

    # provenance { derivedFrom, specContract { kind, schemaVersion } }
    if _obj(out, view["provenance"], "provenance", {"derivedFrom", "specContract"}):
        if not isinstance(view["provenance"]["derivedFrom"], str):
            out.append(diag("view.schema", "provenance.derivedFrom must be a string"))
        if _obj(out, view["provenance"]["specContract"], "provenance.specContract",
                {"kind", "schemaVersion"}):
            pc = view["provenance"]["specContract"]
            if pc["kind"] != "neutrino.capability-spec" or not isinstance(pc["schemaVersion"], int):
                out.append(diag("view.schema",
                                "provenance.specContract must be the capability-spec kind + integer schemaVersion"))
    return out


def _idx(pp: str, prefix: str):
    m = re.fullmatch(re.escape(prefix) + r"\[(\d+)\]", pp)
    return int(m.group(1)) if m else None


def _cross_check(view: dict, spec_path: str, out: list) -> None:
    """Beyond-schema: the view must be a faithful projection of THIS spec — not
    just that each specPath resolves, but that the item's VALUES match the spec
    element at that path (so a view can't claim a field the spec doesn't carry)."""
    try:
        spec = json.load(open(spec_path, encoding="utf-8"))
        spec_hash = spec["identity"]["capabilityHash"]
        spec_ver = spec["schemaVersion"]
        spec_inputs = spec["inputs"]
        spec_effects = spec["effects"]
        smap = {e["specPath"]: e for e in spec["sourceMap"]}
        ops, seen = [], set()
        for t in spec["lifecycle"]["transitions"]:
            if t["name"] not in seen:
                ops.append(t["name"]); seen.add(t["name"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        out.append(diag("view.io", f"cannot read spec for cross-check: {exc}"))
        return

    if view["capability"]["capabilityHash"] != spec_hash:
        out.append(diag("view.hash_mismatch",
                        "capability.capabilityHash does not match the referenced spec "
                        f"({view['capability']['capabilityHash']} != {spec_hash})"))
    if view["provenance"]["specContract"]["schemaVersion"] != spec_ver:
        out.append(diag("view.contract_mismatch",
                        "provenance.specContract.schemaVersion "
                        f"{view['provenance']['specContract']['schemaVersion']} != spec {spec_ver}"))
    if view["visibleOperations"] != ops:
        out.append(diag("view.contract_mismatch",
                        f"visibleOperations {view['visibleOperations']} != spec lifecycle ops {ops}"))

    for item in view["requiredInputs"] + view["evidenceObligations"]:
        pp = item["specPath"]
        if pp not in smap:
            out.append(diag("view.unresolved_path",
                            f"specPath '{pp}' does not resolve in the spec sourceMap"))
            continue
        if "source" in item and item["source"] != smap[pp].get("source"):
            out.append(diag("view.unresolved_path",
                            f"source for '{pp}' does not match the spec ({item['source']} != {smap[pp].get('source')})"))

    # value correspondence: requiredInputs name/type == spec.inputs[i];
    # evidenceObligations leg/kind/ledger == spec.effects[i].
    for item in view["requiredInputs"]:
        i = _idx(item["specPath"], "inputs")
        if i is None or i >= len(spec_inputs):
            out.append(diag("view.unresolved_path", f"requiredInputs specPath {item['specPath']} out of range"))
        elif item.get("name") != spec_inputs[i].get("name") or item.get("type") != spec_inputs[i].get("type"):
            out.append(diag("view.contract_mismatch",
                            f"requiredInputs {item.get('name')}/{item.get('type')} != "
                            f"spec.inputs[{i}] {spec_inputs[i].get('name')}/{spec_inputs[i].get('type')}"))
    for item in view["evidenceObligations"]:
        i = _idx(item["specPath"], "effects")
        if i is None or i >= len(spec_effects):
            out.append(diag("view.unresolved_path", f"evidenceObligations specPath {item['specPath']} out of range"))
        else:
            eff = spec_effects[i]
            if (item.get("leg") != eff.get("name") or item.get("kind") != eff.get("kind")
                    or item.get("ledger") != eff.get("ledger")):
                out.append(diag("view.contract_mismatch",
                                f"evidenceObligation {item.get('leg')}/{item.get('kind')}/{item.get('ledger')} != "
                                f"spec.effects[{i}] {eff.get('name')}/{eff.get('kind')}/{eff.get('ledger')}"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a neutrino participant view (--target=views output)")
    ap.add_argument("file", help="path to <participant>.json")
    ap.add_argument("--spec", help="a capability-spec.json to cross-check the view against")
    ap.add_argument("--out", help="output dir for view.report.json + diagnostics.json")
    args = ap.parse_args()

    view = None
    try:
        view = json.load(open(args.file, encoding="utf-8"))
        diagnostics = validate(view)
    except OSError as exc:
        diagnostics = [diag("view.io", f"cannot read view: {exc}")]
    except ValueError as exc:
        diagnostics = [diag("view.json", f"not well-formed JSON: {exc}")]

    if args.spec and isinstance(view, dict) and not diagnostics:
        _cross_check(view, args.spec, diagnostics)

    errors = [d for d in diagnostics if d.get("severity") == "error"]
    ok = not errors
    participant = (view.get("participant", {}).get("name")
                   if isinstance(view, dict) else None)
    report = {"ok": ok, "file": os.path.basename(args.file), "participant": participant,
              "diagnostics": diagnostics}

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        json.dump(report, open(os.path.join(args.out, "view.report.json"), "w"),
                  indent=2, sort_keys=True)
        json.dump({"ok": ok, "diagnostics": diagnostics},
                  open(os.path.join(args.out, "diagnostics.json"), "w"), indent=2, sort_keys=True)

    json.dump({"ok": ok, "diagnostics": diagnostics}, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
