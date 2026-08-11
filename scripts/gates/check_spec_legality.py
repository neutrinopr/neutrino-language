#!/usr/bin/env python3
"""M5 WP4 () — spec-vs-target-profile legality gate (fail-closed, before rendering).

The deterministic gate that decides whether a canonical spec may be rendered to a target: it
matches the spec's `targetRequirements.requirements[].feature` against the target profile's
`supportedFeatures`, and FAILS CLOSED on any unsupported required feature — before renderer
entry. Matching is over semantic FEATURES (value_category:*, effect:*, invariant:*, binding:*,
topology:*), never domain/contract labels. Each legality diagnostic carries the unsupported
`feature`, its originating `primitive`, and its `source` location (straight from the spec
requirement), under the stable `legality.*` code family ( taxonomy), ordered by root cause
(source line, then feature). This is a translator-owned deterministic gate (addendum AD4).

Profile versioning (AD3) is the profile validator's + the  compatibility surface's concern;
this gate matches features. Run scripts/validators/validate_target_profile.py and
scripts/validators/validate_capability_spec.py for the shapes — this gate assumes valid inputs and fails
closed (legality.bad_input) if the pieces it needs are missing.

  check_spec_legality.py SPEC.json --profile PROFILE.json [--out DIR]

Exit 0 legal / 1 illegal (or bad input) / 2 usage.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def diag(code: str, message: str, severity: str = "error", **extra) -> dict:
    d = {"code": code, "severity": severity, "message": message}
    d.update(extra)
    return d


def _src_line(source) -> int:
    return source.get("line", 0) if isinstance(source, dict) else 0


def _str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def _is_span(s) -> bool:
    return (isinstance(s, dict) and set(s) == {"line", "column"}
            and all(isinstance(s.get(k), int) and not isinstance(s.get(k), bool) for k in ("line", "column")))


def check(spec, profile) -> list:
    out: list = []
    tr = spec.get("targetRequirements") if isinstance(spec, dict) else None
    reqs = tr.get("requirements") if isinstance(tr, dict) else None
    supported = profile.get("supportedFeatures") if isinstance(profile, dict) else None
    unsupported = profile.get("unsupportedConstructs") if isinstance(profile, dict) else None
    fallback = profile.get("fallbackPolicy") if isinstance(profile, dict) else None
    # FAIL CLOSED on malformed input — the pre-render gate must never crash and never silently
    # coerce a schema-invalid piece (e.g. unsupportedConstructs:{} -> empty). Shape validation
    # is the validators' job; the gate checks just enough to match safely.
    if not isinstance(reqs, list):
        return [diag("legality.bad_input", "spec.targetRequirements.requirements is missing or not an array")]
    if not _str_list(supported):
        return [diag("legality.bad_input", "profile.supportedFeatures must be an array of strings")]
    if not _str_list(unsupported):
        return [diag("legality.bad_input", "profile.unsupportedConstructs must be an array of strings")]
    supported = set(supported)
    unsupported = set(unsupported)

    for r in reqs:
        if not (isinstance(r, dict) and isinstance(r.get("feature"), str)
                and isinstance(r.get("primitive"), str)
                and r.get("requirement") in ("required", "optional")
                and (r.get("source") is None or _is_span(r.get("source")))):
            out.append(diag("legality.bad_input", "a spec requirement record is malformed"))
            continue
        feature, primitive = r["feature"], r["primitive"]
        source, level = r.get("source"), r["requirement"]
        if feature in supported:
            continue
        explicit = feature in unsupported
        # An OPTIONAL requirement may be waived when the profile's fallback is advisory.
        if level == "optional" and fallback == "advisory" and not explicit:
            out.append(diag("legality.advisory",
                            f"optional feature '{feature}' ({primitive}) is unmet; allowed by advisory fallback",
                            severity="warning", feature=feature, primitive=primitive, source=source))
            continue
        reason = "explicitly unsupported by" if explicit else "not supported by"
        out.append(diag("legality.unsupported_feature",
                        f"{level} feature '{feature}' ({primitive}) is {reason} target profile "
                        f"'{profile.get('profileId')}'",
                        feature=feature, primitive=primitive, source=source))

    # Root-cause ordering (): earliest source line first, then feature.
    return sorted(out, key=lambda d: (_src_line(d.get("source")), d.get("feature") or "", d["code"]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Match a capability-spec against a target profile (legality gate)")
    ap.add_argument("spec", help="path to capability-spec.json")
    ap.add_argument("--profile", required=True, help="path to a target-profile.json")
    ap.add_argument("--target", help="expected target name; if given, the profile must govern it")
    ap.add_argument("--out", help="output dir for legality.report.json + diagnostics.json")
    args = ap.parse_args()

    try:
        spec = json.load(open(args.spec, encoding="utf-8"))
        profile = json.load(open(args.profile, encoding="utf-8"))
        diagnostics = check(spec, profile)
    except (OSError, ValueError) as exc:
        diagnostics = [diag("legality.io", f"cannot read capability-spec/profile: {exc}")]
        spec, profile = None, None

    # Optional target sanity: a solidity profile must not be used to gate a postgres render.
    if args.target and isinstance(profile, dict) and profile.get("target") != args.target:
        diagnostics.append(diag("legality.target_mismatch",
                                f"profile governs target '{profile.get('target')}', not '{args.target}'"))
        diagnostics.sort(key=lambda d: (_src_line(d.get("source")), d.get("feature") or "", d["code"]))

    ok = not [d for d in diagnostics if d.get("severity") == "error"]
    report = {"ok": ok,
              "spec": os.path.basename(args.spec),
              "profileId": profile.get("profileId") if isinstance(profile, dict) else None,
              "procedure": spec.get("procedure") if isinstance(spec, dict) else None,
              "diagnostics": diagnostics}
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        json.dump(report, open(os.path.join(args.out, "legality.report.json"), "w"), indent=2, sort_keys=True)
        json.dump({"ok": ok, "diagnostics": diagnostics},
                  open(os.path.join(args.out, "diagnostics.json"), "w"), indent=2, sort_keys=True)

    json.dump({"ok": ok, "diagnostics": diagnostics}, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
