#!/usr/bin/env python3
"""M5 S3 () — backend-genericity scorecard gate.

Validates the M5 scorecard (examples/m5-scorecard/scorecard.json) against the committed
classification snapshot and the two committed evidence-anchor samples, fail-closed:

  - the scorecard's `expressible` set equals EXACTLY the M5-expressible reference shapes in the
    classification snapshot (evidenceStyle single_hash / merkle_root) — no more, no less;
  - each expressible sample has a committed `.neu` + `capability-spec.json`; the spec validates
    (validate_capability_spec.py) and is legality-GREEN against both committed target profiles
    (check_spec_legality.py) — a spec/classification-alignment check at the capability-spec level;
  - the honest M5 boundary: NO M6-frontier reference shape (evidenceStyle other than
    single_hash/merkle_root) is translated here — examples/m5-scorecard/ holds only the expressible
    samples, so a coordination-machine shape can't sneak in as "expressible".

The render gap (a value-less evidence anchor is legal but does not render to Solidity/PostgreSQL —
the backends require a ledger leg) is a documented finding, proven fail-closed in the full tier.

  check_m5_scorecard.py            # print {ok, expressible, frontier, diagnostics}

Exit 0 ok / 1 violations (fail closed) / 2 usage.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # samples/ -> scripts -> repo ()
SCORECARD = os.path.join(REPO, "examples", "m5-scorecard", "scorecard.json")
SCORECARD_DIR = os.path.join(REPO, "examples", "m5-scorecard")
PROFILES = [os.path.join(REPO, "examples", "target-profiles", f"{t}.target-profile.json")
            for t in ("solidity", "postgres")]

# The evidence styles M5 expresses as a value-less evidence-anchor capability. Everything else is
# the M6 frontier (coordination machines / attestation / netting / cross-domain ordering).
M5_EVIDENCE_STYLES = {"single_hash", "merkle_root"}
# evidenceStyle -> the deferred M6 primitive it needs (scorecard narrative).
FRONTIER_NEEDS = {
    "state_machine": "author-defined lifecycle state machine",
    "attestation_set": "M-of-N attestation guard",
    "netting_state": "multilateral netting primitive",
    "cross_domain_message": "cross-domain ordering model / per-source nonce",
}


def diag(code: str, message: str, severity: str = "error") -> dict:
    return {"code": code, "severity": severity, "message": message}


def _run_ok(argv: list) -> bool:
    return subprocess.run(argv, capture_output=True, text=True).returncode == 0


def main() -> int:
    out: list = []
    try:
        scorecard = json.load(open(SCORECARD, encoding="utf-8"))
        classification = json.load(open(os.path.join(REPO, scorecard["classificationSnapshot"]), encoding="utf-8"))
    except (OSError, ValueError, KeyError) as exc:
        json.dump({"ok": False, "diagnostics": [diag("scorecard.io", f"cannot load scorecard/classification: {exc}")]},
                  sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 1

    # Derive the M5 / M6 split from the classification snapshot (the single source of truth).
    m5_by_contract = {s["contract"]: s for s in classification["samples"] if s["evidenceStyle"] in M5_EVIDENCE_STYLES}
    m6 = sorted(s["contract"] for s in classification["samples"] if s["evidenceStyle"] not in M5_EVIDENCE_STYLES)

    expressible = scorecard.get("expressible", [])
    declared_contracts = {e.get("referenceContract") for e in expressible}

    # 1. expressible set == the classification M5 set, exactly (both ways).
    for c in sorted(declared_contracts - set(m5_by_contract)):
        out.append(diag("scorecard.not_expressible",
                        f"scorecard lists '{c}' as expressible but it is not M5 in the classification snapshot"))
    for c in sorted(set(m5_by_contract) - declared_contracts):
        out.append(diag("scorecard.missing_expressible",
                        f"classification M5 shape '{c}' is not covered by the scorecard"))

    # 2. every M6 frontier shape is NOT translated here (honest boundary) — no sample dir for it.
    sample_dirs = {d for d in os.listdir(SCORECARD_DIR)
                   if os.path.isdir(os.path.join(SCORECARD_DIR, d))}
    expected_dirs = {e.get("sample") for e in expressible}
    for d in sorted(sample_dirs - expected_dirs):
        out.append(diag("scorecard.unexpected_sample",
                        f"examples/m5-scorecard/{d} is not a declared expressible sample "
                        f"(M6 frontier shapes must not be translated here)"))

    # 3. each expressible sample: committed .neu + spec; spec validates; legality green both profiles.
    for e in expressible:
        contract, prof, sample = e.get("referenceContract"), e.get("profileId"), e.get("sample")
        where = f"expressible '{contract}'"
        ref = m5_by_contract.get(contract)
        if ref and prof != ref.get("profileId"):
            out.append(diag("scorecard.profile_mismatch",
                            f"{where}: profileId '{prof}' != classification '{ref.get('profileId')}'"))
        if ref and e.get("evidenceStyle") != ref.get("evidenceStyle"):
            out.append(diag("scorecard.profile_mismatch",
                            f"{where}: evidenceStyle '{e.get('evidenceStyle')}' != classification '{ref.get('evidenceStyle')}'"))
        base = os.path.join(SCORECARD_DIR, sample or "")
        neu = os.path.join(base, "source", f"{sample}.neu")
        spec = os.path.join(base, "generated", "capability-spec", "capability-spec.json")
        if not os.path.isfile(neu):
            out.append(diag("scorecard.missing_source", f"{where}: no source at {os.path.relpath(neu, REPO)}"))
        if not os.path.isfile(spec):
            out.append(diag("scorecard.missing_spec", f"{where}: no capability-spec at {os.path.relpath(spec, REPO)}"))
            continue
        if not _run_ok([sys.executable, os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"), spec]):
            out.append(diag("scorecard.invalid_spec", f"{where}: capability-spec fails validate_capability_spec.py"))
        for profile in PROFILES:
            if not _run_ok([sys.executable, os.path.join(REPO, "scripts", "gates", "check_spec_legality.py"),
                            spec, "--profile", profile]):
                out.append(diag("scorecard.illegal",
                                f"{where}: capability-spec is NOT legality-green against {os.path.basename(profile)}"))

    frontier = [{"referenceContract": c,
                 "evidenceStyle": next(s["evidenceStyle"] for s in classification["samples"] if s["contract"] == c),
                 "needs": FRONTIER_NEEDS.get(
                     next(s["evidenceStyle"] for s in classification["samples"] if s["contract"] == c),
                     "coordination primitive beyond the M5 kernel")}
                for c in m6]

    errors = [d for d in out if d.get("severity") == "error"]
    ok = not errors
    json.dump({"ok": ok,
               "expressible": sorted(declared_contracts),
               "frontier": frontier,
               "diagnostics": sorted(out, key=lambda d: (d["code"], d["message"]))},
              sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
