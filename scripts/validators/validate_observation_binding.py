#!/usr/bin/env python3
"""M5 oracle S5 () — observation-binding validator.

Validates a neutrino.observation-binding (docs/schemas/observation-binding.schema.json): the
binding-side contract that maps a portable attestation policy (capability-spec `attestations[]`, )
to concrete observers, public keys, and a mocked external source. FULLY mirrors the schema (required
key sets + additionalProperties:false at every level + the safe-identifier / path-safety patterns) —
CI runs THIS validator, not a JSON-Schema library, so a partial mirror would admit a malformed binding
that the oracle-observer backend () or the on-chain guard () then renders.

Beyond the schema it enforces the cross-references JSON Schema cannot express, fail-closed:
  - observer IDENTITY uniqueness within a set (duplicate ids would collide generated files);
  - observer-set REFERENCE uniqueness across the binding;
  - given the capability-spec (--spec): every attestation observer-set reference is BOUND, and its
    M is achievable by the bound N (quorum feasibility, M <= N) — so a leg can never require a quorum
    the bound observers can never reach.

Exit 0 iff no error diagnostics. With --json, prints {ok, diagnostics[]}. Usage:
    validate_observation_binding.py --binding B.json [--spec capability-spec.json] [--json]
    validate_observation_binding.py --selftest
"""
import argparse
import json
import re
import sys

SAFE_IDENT = re.compile(r"^[A-Za-z0-9._-]+$")
SUPPORTED_SOURCE_TYPES = {"mock"}
ASSURANCE = {"A1", "A2", "A3", "A4"}
INDEPENDENCE = {"independent", "correlated"}


def diag(code: str, message: str, severity: str = "error") -> dict:
    return {"code": code, "severity": severity, "message": message}


def _s(v) -> bool:
    return isinstance(v, str) and v != ""


def _safe_ident(v) -> bool:
    # Mirrors the schema pattern AND the backend's path-safety: a safe identifier that is not the
    # traversal tokens '.'/'..' (the id/ref reaches generated filenames + code).
    return _s(v) and bool(SAFE_IDENT.match(v)) and v not in (".", "..")


def _exact_object(obj, allowed: set, where: str, out: list) -> bool:
    # additionalProperties:false + a required key set: reject a non-object, any unknown field, and any
    # missing field (fail-closed, like the other stdlib validators).
    if not isinstance(obj, dict):
        out.append(diag("binding.schema", f"{where}: must be an object"))
        return False
    ok = True
    for k in sorted(set(obj) - allowed):
        out.append(diag("binding.schema", f"{where}: unknown field '{k}'"))
        ok = False
    for k in sorted(allowed - set(obj)):
        out.append(diag("binding.schema", f"{where}: missing '{k}'"))
        ok = False
    return ok


def _validate_source(src, where: str, out: list) -> None:
    if not _exact_object(src, {"type", "id", "claimField"}, where, out):
        return
    if src.get("type") not in SUPPORTED_SOURCE_TYPES:
        out.append(diag("binding.unsupported_source",
                        f"{where}.type '{src.get('type')}' is not a supported source descriptor "
                        f"(expected one of: {sorted(SUPPORTED_SOURCE_TYPES)})"))
    if not _safe_ident(src.get("id")):
        out.append(diag("binding.schema", f"{where}.id must be a safe identifier"))
    if not _s(src.get("claimField")):
        out.append(diag("binding.schema", f"{where}.claimField must be a non-empty string"))


VERIFYING_CONTRACT = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _validate_domain(d, where: str, out: list) -> None:
    # Optional EIP-712 acceptance-guard domain (oracle S7, ): present iff a bound guard
    # domain-separates the signed digest. chainId is a positive EIP-155 id; verifyingContract is the
    # deployed guard address. (capabilityHash — the third domain field — is the spec's identity, bound
    # at render, not carried here.)
    if not _exact_object(d, {"chainId", "verifyingContract"}, where, out):
        return
    cid = d.get("chainId")
    if not (isinstance(cid, int) and not isinstance(cid, bool) and cid >= 1):
        out.append(diag("binding.schema", f"{where}.chainId must be a positive integer (EIP-155 id)"))
    if not (isinstance(d.get("verifyingContract"), str) and VERIFYING_CONTRACT.match(d["verifyingContract"])):
        out.append(diag("binding.schema", f"{where}.verifyingContract must be a 0x-prefixed 20-byte address"))


def _validate_member(m, where: str, out: list) -> None:
    if not _exact_object(m, {"id", "publicKey"}, where, out):
        return
    if not _safe_ident(m.get("id")):
        out.append(diag("binding.schema", f"{where}.id must be a safe identifier"))
    # A missing/empty public key is a fail-open hole: the aggregator authorizes the quorum by public
    # key, so an empty key would let an unauthenticated attestation count toward M.
    if not _s(m.get("publicKey")):
        out.append(diag("binding.missing_public_key",
                        f"{where}.publicKey must be a non-empty public key"))


def validate_binding(binding, out: list) -> None:
    if not _exact_object(binding, {"kind", "schemaVersion", "observerSets"}, "observation-binding", out):
        return
    if binding.get("kind") != "neutrino.observation-binding":
        out.append(diag("binding.schema", "kind must be 'neutrino.observation-binding'"))
    if binding.get("schemaVersion") != 1:
        out.append(diag("binding.schema", "schemaVersion must be 1"))
    sets = binding.get("observerSets")
    if not isinstance(sets, list) or not sets:
        out.append(diag("binding.schema", "observerSets must be a non-empty array"))
        return
    seen_refs = set()
    for i, s in enumerate(sets):
        w = f"observerSets[{i}]"
        # ref/source/members required; domain (oracle S7, ) optional — the key is present only when
        # a bound acceptance guard domain-separates the signed digest. Enforce additionalProperties:false.
        if not isinstance(s, dict):
            out.append(diag("binding.schema", f"{w}: must be an object"))
            continue
        for k in sorted(set(s) - {"ref", "source", "members", "domain", "assurance", "independence"}):
            out.append(diag("binding.schema", f"{w}: unknown field '{k}'"))
        for k in sorted({"ref", "source", "members"} - set(s)):
            out.append(diag("binding.schema", f"{w}: missing '{k}'"))
        if "domain" in s:
            _validate_domain(s.get("domain"), f"{w}.domain", out)
        ref = s.get("ref")
        if not _safe_ident(ref):
            out.append(diag("binding.schema", f"{w}.ref must be a safe identifier"))
        elif ref in seen_refs:
            out.append(diag("binding.duplicate_observer_set",
                            f"{w}.ref '{ref}' is bound more than once"))
        else:
            seen_refs.add(ref)
        _validate_source(s.get("source"), f"{w}.source", out)
        if "assurance" in s and s.get("assurance") not in ASSURANCE:
            out.append(diag("binding.observer_assurance_invalid",
                            f"{w}.assurance must be one of {sorted(ASSURANCE)}"))
        if "independence" in s and s.get("independence") not in INDEPENDENCE:
            out.append(diag("binding.observer_independence_invalid",
                            f"{w}.independence must be one of {sorted(INDEPENDENCE)}"))
        members = s.get("members")
        if not isinstance(members, list) or not members:
            out.append(diag("binding.schema", f"{w}.members must be a non-empty array"))
            continue
        seen_ids = set()
        for j, m in enumerate(members):
            mw = f"{w}.members[{j}]"
            _validate_member(m, mw, out)
            if isinstance(m, dict) and _s(m.get("id")):
                if m["id"] in seen_ids:
                    out.append(diag("binding.duplicate_observer",
                                    f"{mw}.id '{m['id']}' is not unique within '{s.get('ref')}'"))
                else:
                    seen_ids.add(m["id"])


def cross_validate_spec(binding, spec, out: list) -> None:
    # Feasibility (needs both artifacts): every attestation observer-set reference must be bound, and
    # the spec's M-of-N threshold M must be achievable by the bound observer count N (M <= N).
    if not isinstance(spec, dict):
        out.append(diag("binding.schema", "capability-spec must be an object"))
        return
    bound = {}
    for s in (binding.get("observerSets") or []):
        if isinstance(s, dict) and _s(s.get("ref")) and isinstance(s.get("members"), list):
            bound[s["ref"]] = s
    for i, a in enumerate(spec.get("attestations") or []):
        if not isinstance(a, dict):
            continue
        os_ = a.get("observerSet") or {}
        ref = os_.get("ref") if isinstance(os_, dict) else None
        m = None
        q = a.get("quorum")
        if isinstance(q, dict) and isinstance(q.get("threshold"), int):
            m = q["threshold"]
        if not _s(ref):
            continue
        if ref not in bound:
            out.append(diag("binding.unbound_observer_set",
                            f"attestations[{i}] observer-set '{ref}' has no entry in the binding"))
            continue
        bound_set = bound[ref]
        n = len(bound_set.get("members") or [])
        if isinstance(m, int) and m > n:
            out.append(diag("binding.quorum_infeasible",
                            f"attestations[{i}] observer-set '{ref}' requires a quorum of M={m} but "
                            f"the binding supplies only N={n} observers — M-of-N is infeasible"))
        for field, code in (("assurance", "binding.observer_assurance_mismatch"),
                            ("independence", "binding.observer_independence_mismatch")):
            if field not in os_:
                continue
            if bound_set.get(field) != os_.get(field):
                out.append(diag(code,
                                f"attestations[{i}] observer-set '{ref}' declares {field} "
                                f"{os_.get(field)!r} but the binding supplies "
                                f"{bound_set.get(field)!r}"))


def run(binding, spec=None) -> list:
    out: list = []
    validate_binding(binding, out)
    # Cross-checks only make sense on a structurally sound binding.
    if spec is not None and not any(d["severity"] == "error" for d in out):
        cross_validate_spec(binding, spec, out)
    return out


def _selftest() -> int:
    def good_binding():
        return {"kind": "neutrino.observation-binding", "schemaVersion": 1,
                "observerSets": [{"ref": "delivery_oracles",
                                  "source": {"type": "mock", "id": "delivery_events", "claimField": "delivered"},
                                  "members": [{"id": "obs-a", "publicKey": "0xa1"},
                                              {"id": "obs-b", "publicKey": "0xb2"},
                                              {"id": "obs-c", "publicKey": "0xc3"}]}]}

    def good_spec():
        return {"attestations": [{"input": "delivery_proof", "quorum": {"threshold": 2},
                                  "observerSet": {"ref": "delivery_oracles", "role": None}}]}

    fails = []
    if run(good_binding(), good_spec()):
        fails.append(("a well-formed binding (+spec) was rejected", run(good_binding(), good_spec())))

    # A binding declaring a valid EIP-712 guard domain (oracle S7, ) must also pass.
    with_domain = good_binding()
    with_domain["observerSets"][0]["domain"] = {
        "chainId": 1, "verifyingContract": "0x00000000000000000000000000000000000000ab"}
    if run(with_domain, good_spec()):
        fails.append(("a binding with a valid guard domain was rejected", run(with_domain, good_spec())))

    declared = good_binding()
    declared["observerSets"][0]["assurance"] = "A3"
    declared["observerSets"][0]["independence"] = "independent"
    declared_spec = good_spec()
    declared_spec["attestations"][0]["observerSet"].update(
        {"assurance": "A3", "independence": "independent"})
    if run(declared, declared_spec):
        fails.append(("a binding with matching observer assurance/independence was rejected",
                      run(declared, declared_spec)))

    def good_with_domain(b, s):
        b["observerSets"][0]["domain"] = {"chainId": 1,
                                          "verifyingContract": "0x00000000000000000000000000000000000000ab"}

    # Each invalid shape MUST produce an error diagnostic.
    cases = [
        ("bad kind", lambda b, s: b.__setitem__("kind", "nope")),
        ("bad schemaVersion", lambda b, s: b.__setitem__("schemaVersion", 2)),
        ("unknown top field", lambda b, s: b.__setitem__("extra", 1)),
        ("empty observerSets", lambda b, s: b.__setitem__("observerSets", [])),
        ("unknown set field", lambda b, s: b["observerSets"][0].__setitem__("x", 1)),
        ("missing source", lambda b, s: b["observerSets"][0].pop("source")),
        ("unsupported source type", lambda b, s: b["observerSets"][0]["source"].__setitem__("type", "https")),
        ("unknown source field", lambda b, s: b["observerSets"][0]["source"].__setitem__("url", "x")),
        ("empty claimField", lambda b, s: b["observerSets"][0]["source"].__setitem__("claimField", "")),
        ("unsafe ref (traversal)", lambda b, s: b["observerSets"][0].__setitem__("ref", "..")),
        ("unsafe member id", lambda b, s: b["observerSets"][0]["members"][0].__setitem__("id", "a/b")),
        ("missing public key", lambda b, s: b["observerSets"][0]["members"][0].__setitem__("publicKey", "")),
        ("missing key field", lambda b, s: b["observerSets"][0]["members"][0].pop("publicKey")),
        ("duplicate observer id", lambda b, s: b["observerSets"][0]["members"].__setitem__(1, {"id": "obs-a", "publicKey": "0xd4"})),
        ("duplicate observer-set ref", lambda b, s: b["observerSets"].append(dict(b["observerSets"][0]))),
        ("empty members", lambda b, s: b["observerSets"][0].__setitem__("members", [])),
        ("invalid observer assurance", lambda b, s: b["observerSets"][0].__setitem__("assurance", "A9")),
        ("invalid observer independence", lambda b, s: b["observerSets"][0].__setitem__("independence", "solo")),
        # optional guard domain (S7)
        ("domain missing chainId", lambda b, s: (good_with_domain(b, s), b["observerSets"][0]["domain"].pop("chainId"))),
        ("domain bad chainId", lambda b, s: (good_with_domain(b, s), b["observerSets"][0]["domain"].__setitem__("chainId", 0))),
        ("domain bad verifyingContract", lambda b, s: (good_with_domain(b, s), b["observerSets"][0]["domain"].__setitem__("verifyingContract", "0xnothex"))),
        ("domain unknown field", lambda b, s: (good_with_domain(b, s), b["observerSets"][0]["domain"].__setitem__("salt", "0x00"))),
        # cross-spec feasibility
        ("quorum infeasible M>N", lambda b, s: s["attestations"][0]["quorum"].__setitem__("threshold", 9)),
        ("unbound observer set", lambda b, s: s["attestations"][0]["observerSet"].__setitem__("ref", "other_oracles")),
        ("assurance mismatch", lambda b, s: (
            b["observerSets"][0].__setitem__("assurance", "A2"),
            s["attestations"][0]["observerSet"].__setitem__("assurance", "A3"))),
        ("independence mismatch", lambda b, s: (
            b["observerSets"][0].__setitem__("independence", "correlated"),
            s["attestations"][0]["observerSet"].__setitem__("independence", "independent"))),
    ]
    for name, mutate in cases:
        b, s = good_binding(), good_spec()
        mutate(b, s)
        diags = run(b, s)
        if not any(d["severity"] == "error" for d in diags):
            fails.append((f"invalid shape not rejected: {name}", diags))

    if fails:
        print("validate_observation_binding selftest FAILED:", file=sys.stderr)
        for msg, diags in fails:
            print(f"    FAIL: {msg} -> {diags}", file=sys.stderr)
        return 1
    print(f"    PASS (observation-binding schema mirror + cross-refs: valid passes; {len(cases)} "
          "invalid shapes each rejected)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate a neutrino.observation-binding ().")
    ap.add_argument("--binding", help="path to the observation-binding JSON")
    ap.add_argument("--spec", help="optional capability-spec JSON, to cross-check quorum feasibility")
    ap.add_argument("--json", action="store_true", help="print the structured report")
    ap.add_argument("--selftest", action="store_true", help="run the schema-mirror self-test and exit")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if not args.binding:
        ap.error("--binding is required (or use --selftest)")

    try:
        binding = json.load(open(args.binding, encoding="utf-8"))
    except (OSError, ValueError) as ex:
        print(json.dumps({"ok": False, "diagnostics": [diag("binding.io", str(ex))]}))
        return 1
    spec = None
    if args.spec:
        try:
            spec = json.load(open(args.spec, encoding="utf-8"))
        except (OSError, ValueError) as ex:
            print(json.dumps({"ok": False, "diagnostics": [diag("binding.io", str(ex))]}))
            return 1

    diags = run(binding, spec)
    ok = not any(d["severity"] == "error" for d in diags)
    if args.json:
        print(json.dumps({"ok": ok, "diagnostics": diags}, indent=2))
    elif not ok:
        for d in diags:
            print(f"{d['severity']}: [{d['code']}] {d['message']}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
