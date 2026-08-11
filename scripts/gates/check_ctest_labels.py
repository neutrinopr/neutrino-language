#!/usr/bin/env python3
"""CTest label-taxonomy guard (, residual of ).

The test suite is sliced by CTest LABELS — ownership (which module owns the test),
heaviness (does it need external provisioning), and validator/family kind. Two things
must stay true or the slices silently rot:

  1. LABELS.vocabulary — every label a test carries is in the CLOSED declared vocabulary
     below. A typo (`requires-postgress`, `backend-soldity`) or an ad-hoc new label would
     make `ctest -L <label>` / `-LE <label>` silently select the wrong set, so an
     unknown label FAILS until it is added here deliberately.
  2. LABELS.backend_isolation — a backend-owned test may not depend on a SECOND backend
     (carry two `backend-*` ownership labels) unless it is explicitly an `e2e` test. This
     is  T9: backend-local development must not be coupled to an unrelated backend
     except through the explicit e2e/acceptance boundary.

Source of truth is the cmake label strings (this is a no-build source gate). Parses
`LABELS "..."` assignments across cmake/*.cmake + CMakeLists.txt, plus the
NEUTRINO_FAST_CHECKS `name=module=labels` rows.

Usage: check_ctest_labels.py [--selftest]   (exit 0 ok / 1 violations / 2 fail-closed)
"""
import glob
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MIN_LABEL_SETS = 15  # the suite has far more; a collapse means a mis-parse — fail closed.

# The CLOSED label vocabulary. Add a label here (deliberately) when introducing one.
OWNERSHIP = {"backend-solidity", "backend-postgres", "slot", "policy"}
HEAVINESS = {"acceptance", "e2e"}
PROVISION = {"requires-solc", "requires-forge", "requires-postgres", "requires-docker"}
FAMILY = {
    "umbrella", "fast", "ir", "lit", "frontend", "contract", "completeness",
    "validator", "schema", "domain", "oracle", "artifact", "release", "grammar",
    "s5f", "ctest-native", "golden", "domain-scaling",
}
VOCAB = OWNERSHIP | HEAVINESS | PROVISION | FAMILY

# A label is lowercase-alpha, digits, and hyphens.
_LABEL_RE = re.compile(r"^[a-z][a-z0-9-]*$")
# Single-line `LABELS "…"` (the content may be a literal set, a ${var}, or interpolated).
_LABELS_LITERAL = re.compile(r'LABELS\s+"([^"\n]*)"')
# NEUTRINO_FAST_CHECKS rows: "ctest-name=module=comma,separated,labels".
_FAST_ROW = re.compile(r'"[a-z][a-z0-9-]*=[a-z0-9_]+=([a-z0-9,-]+)"')
_SET_VAR = re.compile(r'set\(\s*([A-Za-z_]\w*)\s+"([^"\n]*)"')
_VAR_REF = re.compile(r"^\$\{([A-Za-z_]\w*)\}$")
# `${var}` LABELS whose CONCRETE values are validated at another parsed site, not here:
#   A_LABELS — the neutrino_acceptance() function param (real labels at each call's LABELS "…");
#   _labels  — the NEUTRINO_FAST_CHECKS foreach var (real labels in the "name=module=labels" rows).
# Any OTHER unresolved ${var} in a LABELS is a hole the gate must not wave through — fail closed.
RESOLVED_ELSEWHERE = {"A_LABELS", "_labels"}


def _setmap(texts):
    m = {}
    for t in texts:
        for var, val in _SET_VAR.findall(t):
            m[var] = val
    return m


def _resolve(expr, setmap):
    """(labels|None, error|None) for one `LABELS "<expr>"` content. Resolves a `${var}` via
    set()/the elsewhere-allowlist so a typo assembled through a variable is still seen; a
    `${var}` that resolves nowhere, or a literal with junk tokens, FAILS CLOSED."""
    ref = _VAR_REF.match(expr.strip())
    if ref:
        var = ref.group(1)
        if var in setmap:
            expr = setmap[var]  # resolved to its literal value; validate below
        elif var in RESOLVED_ELSEWHERE:
            return None, None   # validated at its concrete occurrences
        else:
            return None, f'LABELS "${{{var}}}" resolves to no set()/known variable — cannot verify its labels'
    if "${" in expr:
        return None, f'LABELS "{expr}" is an unrecognized interpolated expression — cannot verify its labels'
    toks = [t for t in expr.split(";") if t]
    bad = [t for t in toks if not _LABEL_RE.match(t)]
    if bad:
        return None, f'LABELS "{expr}" has non-label token(s) {bad}'
    return toks, None


def collect(root):
    """(label_sets, parse_errors). parse_errors are unverifiable LABELS expressions (fail-closed)."""
    files = sorted(glob.glob(os.path.join(root, "cmake", "*.cmake")))
    cml = os.path.join(root, "CMakeLists.txt")
    if os.path.isfile(cml):
        files.append(cml)
    texts = [open(f, encoding="utf-8").read() for f in files]
    setmap = _setmap(texts)
    sets, errors = [], []
    for t in texts:
        for expr in _LABELS_LITERAL.findall(t):
            labels, err = _resolve(expr, setmap)
            if err:
                errors.append(err)
            elif labels:
                sets.append(labels)
        for row in _FAST_ROW.findall(t):
            sets.append([x for x in row.split(",") if x])
    return sets, errors


def check(sets, errors=()):
    reasons = []
    for err in errors:
        reasons.append(f"[labels.unverifiable] {err}")
    if len(sets) < MIN_LABEL_SETS:
        reasons.append(f"[labels.scan] parsed only {len(sets)} label sets (< {MIN_LABEL_SETS}) — the "
                       "cmake LABELS scan drifted; fix it before trusting the taxonomy")
        return reasons
    for labels in sets:
        s = set(labels)
        unknown = s - VOCAB
        if unknown:
            reasons.append(f"[labels.vocabulary] unknown CTest label(s) {sorted(unknown)} on a test "
                           f"labeled {sorted(s)} — add to the declared vocabulary in check_ctest_labels.py "
                           "(ownership/heaviness/provision/family) or fix the typo")
        backends = s & OWNERSHIP & {"backend-solidity", "backend-postgres"}
        if len(backends) >= 2 and "e2e" not in s:
            reasons.append(f"[labels.backend_isolation] test labeled {sorted(s)} carries two backend "
                           f"ownership labels {sorted(backends)} but is not marked `e2e` — a backend-owned "
                           "test must not depend on a second backend except as an explicit e2e test ( T9)")
    return reasons


def _failclosed(reasons):
    return any("[labels.scan]" in r or "[labels.unverifiable]" in r for r in reasons)


def run():
    reasons = check(*collect(REPO))
    if reasons:
        print("ctest-label taxonomy gate FAILED:", file=sys.stderr)
        for r in reasons:
            print(f"    {r}", file=sys.stderr)
        return 2 if _failclosed(reasons) else 1
    print("ctest-label taxonomy gate OK: all labels in the declared vocabulary; no backend-owned test "
          "depends on a second backend without an explicit e2e label")
    return 0


def selftest():
    if run() != 0:
        print("selftest: the real tree does not pass the gate", file=sys.stderr)
        return 1
    fails = []
    pad = [["contract"]] * MIN_LABEL_SETS  # keep above the floor
    # (a) an unknown label fails vocabulary.
    if not any("labels.vocabulary" in r for r in check(pad + [["backend-solidity", "reqires-solc"]])):
        fails.append("an unknown/typo label should fail [labels.vocabulary]")
    # (b) two backend labels without e2e fails isolation.
    if not any("labels.backend_isolation" in r
               for r in check(pad + [["backend-solidity", "backend-postgres", "acceptance"]])):
        fails.append("two backend labels without e2e should fail [labels.backend_isolation]")
    # (c) two backend labels WITH e2e passes.
    if any("labels.backend_isolation" in r
           for r in check(pad + [["backend-solidity", "backend-postgres", "e2e"]])):
        fails.append("two backend labels WITH e2e should pass")
    # (d) a mis-parse (too few sets) fails closed.
    if not any("labels.scan" in r for r in check([["contract"]])):
        fails.append("a sub-floor scan should fail closed [labels.scan]")
    # (e) a typo assembled through a set() variable is RESOLVED and caught, not silently dropped.
    resolved, err = _resolve("${X}", {"X": "backend-solidity;requires-postgress"})
    if err or resolved != ["backend-solidity", "requires-postgress"]:
        fails.append("a set()-backed LABELS should resolve to its literal tokens")
    elif not any("labels.vocabulary" in r for r in check(pad + [resolved])):
        fails.append("a typo assembled through a variable should still fail [labels.vocabulary]")
    # (f) an unresolved ${var} in LABELS fails closed (not silently dropped).
    _, err = _resolve("${MYSTERY}", {})
    if not err:
        fails.append("an unresolved ${var} LABELS should fail closed [labels.unverifiable]")
    # (g) the two known parameterized vars are validated elsewhere (no false failure).
    for known in ("${A_LABELS}", "${_labels}"):
        labels, err = _resolve(known, {})
        if labels is not None or err is not None:
            fails.append(f"{known} should be treated as validated-elsewhere (skipped)")
    if fails:
        print("ctest-label SELFTEST FAILED:", file=sys.stderr)
        for f in fails:
            print(f"    {f}", file=sys.stderr)
        return 1
    print("ctest-label selftest PASS (real tree clean; unknown label, dual-backend-without-e2e, a "
          "sub-floor scan, a variable-assembled typo, and an unresolved ${var} LABELS all fail closed; "
          "dual-backend WITH e2e and the known parameterized vars pass)")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv[1:] else run())
