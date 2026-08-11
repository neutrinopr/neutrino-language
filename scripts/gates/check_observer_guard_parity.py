#!/usr/bin/env python3
"""M5 oracle S7 () — observer↔guard parity gate.

The off-chain analogue of the cross-backend equivalence (): prove the rendered serverless observers
(S4, ) and the on-chain acceptance guard (the vetted reference ThresholdQuorumAcceptance.sol,
/) are SINGLE-SOURCED — they agree on WHAT is attested and WHAT quorum accepts it. Deterministic,
no live feeds: it reads the rendered artifacts + the spec/binding and compares a consensus descriptor.

Checked (fail-closed on any mismatch):
  - EIP-712 signing scheme: the observer's DOMAIN/CLAIM type strings are byte-identical to the guard's,
    and the observer signs the domain-separated `claimDigest(...)` — NOT the naked `keccak256(encode(c))`.
    (This is the observer↔guard preimage parity, slice 7: a naked observer's signatures never verify.)
  - Domain binding: observer CAPABILITY_HASH == spec.identity.capabilityHash; CHAIN_ID / VERIFYING_CONTRACT
    == the binding's guard domain.
  - Quorum threshold: observer THRESHOLD (M) == spec attestation quorum threshold.
  - Observer-set identity: observer OBSERVER_SET == the spec/binding observer-set reference.
  - Canonical claim shape: observer claim fields (observerSet, input, field) match the spec/binding, and
    the canonicalization mode is one the guard accepts (`exact` for this discrete reference).

Usage:
    check_observer_guard_parity.py --observers DIR --guard REF.sol --spec spec.json --binding binding.json
Exit 0 iff parity holds; non-zero + a coded reason otherwise.
"""
import argparse
import json
import re
import sys


def fail(reasons, code, msg):
    reasons.append(f"[{code}] {msg}")


def _find(pattern, text, group=1):
    m = re.search(pattern, text)
    return m.group(group) if m else None


def guard_scheme(sol: str) -> dict:
    # The guard's EIP-712 type strings — the parity ground truth. Extract the quoted type strings by the
    # struct name so a whitespace/formatting change in the .sol cannot silently drift the comparison.
    dom = _find(r'"(NeutrinoThresholdQuorumAcceptance\([^"]*\))"', sol)
    clm = _find(r'"(QuorumClaim\([^"]*\))"', sol)
    return {"domainType": dom, "claimType": clm}


def observer_descriptor(obs_js: str) -> dict:
    d = {
        "observerSet": _find(r'const OBSERVER_SET = "([^"]*)"', obs_js),
        "claimField": _find(r'const CLAIM_FIELD = "([^"]*)"', obs_js),
        "input": _find(r'input:\s*"([^"]*)"', obs_js),
        "canonicalization": _find(r'mode:\s*(\w+)\)', obs_js),
        "domainType": _find(r'const DOMAIN_TYPE = "([^"]*)"', obs_js),
        "claimType": _find(r'const CLAIM_TYPE = "([^"]*)"', obs_js),
        "capabilityHash": _find(r'const CAPABILITY_HASH = "([^"]*)"', obs_js),
        "chainId": _find(r'const CHAIN_ID = (\d+)', obs_js),
        "verifyingContract": _find(r'const VERIFYING_CONTRACT = "([^"]*)"', obs_js),
        "signsNaked": bool(re.search(r'const digest = keccak256\(encode\(c\)\)', obs_js)),
    }
    return d


# --- The EIP-712 digest RECIPE, derived from BOTH sides and compared (two-sided, not hardcoded) ---
# The recipe is three ORDERED field lists: the domainSeparator preimage, the struct preimage, and the
# final digest preimage. Each side's syntax (Solidity abi.encode / JS _cat) is normalized to the SAME
# canonical field vocabulary, so a change to EITHER the guard's claimDigest() body or the observer's
# (wrong 0x1901 prefix, omitted domainSeparator, swapped claimId/canonicalClaimHash, reordered domain
# fields) makes the two lists diverge and fails the gate. Deriving from ThresholdQuorumAcceptance.sol
# itself closes the guard-side blind spot.

# arg-substring (lowercased) -> canonical field token, in priority order (first match wins).
_FIELD_TOKENS = [
    ("domain_type", "DOMAIN_TYPEHASH"), ("claim_type", "CLAIM_TYPEHASH"),
    ("canonicalclaimhash", "canonicalClaimHash"), ("executionclaim", "executionClaim"),
    ("capability", "capabilityHash"),
    ("chainid", "chainId"), ("chain_id", "chainId"),
    ("cachedthis", "verifyingContract"), ("verifying_contract", "verifyingContract"),
    ("claimid", "claimId"), ("x19", "prefix1901"), ("1901", "prefix1901"),
    ("domainseparator", "domainSeparator"), ("structhash", "structHash"),
]


def _token(arg: str):
    a = arg.lower()
    for needle, tok in _FIELD_TOKENS:
        if needle in a:
            return tok
    return f"?{arg.strip()}?"  # unrecognized -> guaranteed mismatch (fail-closed)


def _split_top(s: str) -> list:
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip()); cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def _call_args(text: str, opener: str):
    # The balanced argument list of the FIRST `opener` (a substring ending in '(') in text.
    i = text.find(opener)
    if i < 0:
        return None
    i += len(opener)
    depth, j = 1, i
    while j < len(text) and depth:
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
        j += 1
    return [_token(a) for a in _split_top(text[i:j - 1])]


def _between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i)
    return text[i:j] if j >= 0 else text[i:]


def guard_recipe(sol: str):
    dom_fn = _between(sol, "function _buildDomainSeparator(", "}")
    claim_fn = _between(sol, "function claimDigest(", "\n    }")
    return {
        "domain": _call_args(dom_fn, "abi.encode("),
        "struct": _call_args(claim_fn, "abi.encode("),
        "digest": _call_args(claim_fn, "abi.encodePacked("),
    }


def observer_recipe(obs_js: str):
    return {
        "domain": _call_args(_between(obs_js, "const domainSeparator =", ";"), "_cat("),
        "struct": _call_args(_between(obs_js, "const structHash =", ";"), "_cat("),
        "digest": _call_args(_between(obs_js, "return keccak256(_cat(", ";"), "_cat("),
    }


def check_digest_recipe(obs_js: str, where: str, guard: dict, reasons: list) -> None:
    if not re.search(r'const digest = claimDigest\(keccak256, claimId, canonicalClaimHash, '
                     r'executionClaim\);', obs_js):
        fail(reasons, "parity.preimage",
             f"{where}: observer does not sign the guard's EIP-712 claimDigest over both the evidence "
             "claim and the  executionClaim (a naked, absent, or unbound digest never verifies on "
             "chain — bind a guard `domain`, S7, and co-sign the executionClaim)")
    if not re.search(r'const canonicalClaimHash = keccak256\(_utf8\(encode\(c\)\)\);', obs_js):
        fail(reasons, "parity.preimage",
             f"{where}: observer does not derive canonicalClaimHash = keccak256(encode(claim))")
    obs = observer_recipe(obs_js)
    for part in ("domain", "struct", "digest"):
        if not guard.get(part):
            fail(reasons, "parity.guard_recipe",
                 f"could not extract the guard's {part} recipe from the reference .sol")
        elif obs.get(part) != guard.get(part):
            fail(reasons, "parity.digest_recipe",
                 f"{where}: {part} preimage field order diverges from the guard\n"
                 f"      observer: {obs.get(part)}\n      guard:    {guard.get(part)}")


def spec_binding_expected(spec: dict, binding: dict) -> dict:
    att = (spec.get("attestations") or [{}])[0]
    os_ = att.get("observerSet") or {}
    ref = os_.get("ref")
    bset = None
    for s in (binding.get("observerSets") or []):
        if isinstance(s, dict) and s.get("ref") == ref:
            bset = s
            break
    dom = (bset or {}).get("domain") or {}
    return {
        "observerSet": ref,
        "input": att.get("input"),
        "threshold": (att.get("quorum") or {}).get("threshold"),
        "claimField": ((bset or {}).get("source") or {}).get("claimField"),
        "capabilityHash": (spec.get("identity") or {}).get("capabilityHash"),
        "chainId": dom.get("chainId"),
        "verifyingContract": dom.get("verifyingContract"),
    }


# Canonicalization modes the (discrete) reference guard accepts.
GUARD_CANONICALIZATION = {"exact"}


def check(observers_dir, guard_sol, spec, binding) -> list:
    reasons: list = []
    ref = spec_binding_expected(spec, binding)["observerSet"]
    if not ref:
        fail(reasons, "parity.spec", "capability-spec declares no attestation observer-set")
        return reasons
    import os
    base = os.path.join(observers_dir, "observers", ref) if os.path.isdir(
        os.path.join(observers_dir, "observers", ref)) else os.path.join(observers_dir, ref)
    try:
        agg = open(os.path.join(base, "aggregate.js"), encoding="utf-8").read()
        obs_files = sorted(f for f in os.listdir(base) if f.startswith("obs") and f != "aggregate.js"
                           and f.endswith(".js"))
        if not obs_files:
            fail(reasons, "parity.io", f"no observer modules under {base}")
            return reasons
    except OSError as ex:
        fail(reasons, "parity.io", str(ex))
        return reasons

    g = guard_scheme(guard_sol)
    g_recipe = guard_recipe(guard_sol)
    exp = spec_binding_expected(spec, binding)
    threshold = _find(r'const THRESHOLD = (\d+)', agg)

    # Quorum threshold is set once in the aggregator; the rest is checked in EVERY observer module — a
    # drift in any single obs*.js (not just the first) produces unverifiable/wrong signatures for that
    # signer, so all must agree with the spec/binding + the guard.
    _cmp(reasons, "parity.threshold", "threshold (M)", threshold,
         str(exp["threshold"]) if exp["threshold"] is not None else None)

    for f in obs_files:
        try:
            obs = open(os.path.join(base, f), encoding="utf-8").read()
        except OSError as ex:
            fail(reasons, "parity.io", str(ex))
            continue
        d = observer_descriptor(obs)

        # (1) EIP-712 preimage parity — the gap-closing check: type strings byte-identical to the
        # guard AND the full claimDigest recipe body matches (prefix + field order), per module.
        if d["signsNaked"]:
            fail(reasons, "parity.preimage",
                 f"{f}: observer signs the NAKED claim digest, not the guard's EIP-712 claimDigest — a "
                 "naked signature never verifies on chain (bind a guard `domain` to the set, S7)")
        else:
            check_digest_recipe(obs, f, g_recipe, reasons)
        if not g["domainType"] or d["domainType"] != g["domainType"]:
            fail(reasons, "parity.domain_typehash",
                 f"{f}: observer DOMAIN type {d['domainType']!r} != guard {g['domainType']!r}")
        if not g["claimType"] or d["claimType"] != g["claimType"]:
            fail(reasons, "parity.claim_typehash",
                 f"{f}: observer CLAIM type {d['claimType']!r} != guard {g['claimType']!r}")

        # (2) domain binding
        _cmp(reasons, "parity.capability_hash", f"{f} capabilityHash", d["capabilityHash"], exp["capabilityHash"])
        _cmp(reasons, "parity.chain_id", f"{f} chainId", d["chainId"], str(exp["chainId"]) if exp["chainId"] is not None else None)
        _cmp(reasons, "parity.verifying_contract", f"{f} verifyingContract", d["verifyingContract"], exp["verifyingContract"])
        # (3) observer-set identity + (4) canonical claim shape
        _cmp(reasons, "parity.observer_set", f"{f} observerSet", d["observerSet"], exp["observerSet"])
        _cmp(reasons, "parity.claim_field", f"{f} claimField", d["claimField"], exp["claimField"])
        _cmp(reasons, "parity.claim_input", f"{f} claim input", d["input"], exp["input"])
        if d["canonicalization"] not in GUARD_CANONICALIZATION:
            fail(reasons, "parity.canonicalization",
                 f"{f}: observer canonicalization {d['canonicalization']!r} is not one the guard "
                 f"accepts ({sorted(GUARD_CANONICALIZATION)})")
    return reasons


def _cmp(reasons, code, what, got, want):
    if got != want:
        fail(reasons, code, f"observer {what} {got!r} != expected {want!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description="observer↔guard parity gate ()")
    ap.add_argument("--observers", required=True, help="dir holding observers/<ref>/ (or the <ref>/ dir)")
    ap.add_argument("--guard", required=True, help="the acceptance-guard reference .sol")
    ap.add_argument("--spec", required=True, help="the capability-spec.json")
    ap.add_argument("--binding", required=True, help="the observation-binding.json")
    args = ap.parse_args()
    try:
        spec = json.load(open(args.spec, encoding="utf-8"))
        binding = json.load(open(args.binding, encoding="utf-8"))
        guard = open(args.guard, encoding="utf-8").read()
    except (OSError, ValueError) as ex:
        print(f"parity: [parity.io] {ex}", file=sys.stderr)
        return 1
    reasons = check(args.observers, guard, spec, binding)
    if reasons:
        print("observer↔guard parity FAILED:", file=sys.stderr)
        for r in reasons:
            print(f"    {r}", file=sys.stderr)
        return 1
    print("observer↔guard parity OK: EIP-712 scheme + domain + threshold + observer-set + claim shape "
          "agree (observers sign exactly the guard's claimDigest)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
