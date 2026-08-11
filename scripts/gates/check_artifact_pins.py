#!/usr/bin/env python3
"""M5 R3 () — side-artifact contract-version pin gate.

Extends the d164 compatibility-pins discipline () to the SIDE ARTIFACTS that consume the
translator's capability-spec contract: **target profiles** and **domain dialects**. Each such
artifact must declare a `capabilitySpecVersion` that pins the capability-spec (canonical
capability-spec) contract version it was authored against; this gate FAILS CLOSED when a declared
pin is missing or mismatches the core's emitted contract version, so a side artifact cannot silently
drift from the translator-owned contract.

The core's emitted contract version is the single source of truth `kCapabilitySpecVersion` in
include/Neutrino/VersionInfo.h (also emitted by every tool's `--version-json`). This checker reads it
from VersionInfo.h (no build needed, matching the repo's other stdlib checkers) and additionally
asserts it stays in lockstep with the `vN` of docs/schemas/capability-spec.schema.json's `$id` — so
the emitted version can never drift from the actual shipped contract.

Fail-closed diagnostics (machine-readable `{code, severity, message}`, `compat.*` family):
  - `compat.pin_missing`            — an in-scope artifact declares no `capabilitySpecVersion`;
  - `compat.capability_spec_mismatch` — a declared pin != the emitted contract version;
  - `compat.contract_drift`         — VersionInfo.h's kCapabilitySpecVersion != the schema `$id` `vN`;
  - `compat.unpinnable_kind`        — the artifact is not a pin-scoped kind;
  - `compat.io` / `compat.schema`   — unreadable / malformed input.

  check_artifact_pins.py ARTIFACT [ARTIFACT ...]
  check_artifact_pins.py --self-check      # only assert VersionInfo.h <-> schema $id lockstep

Exit 0 ok / 1 violations (fail closed) / 2 usage.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VERSIONINFO = os.path.join(REPO, "include", "Neutrino", "VersionInfo.h")
CAPABILITY_SPEC_SCHEMA = os.path.join(REPO, "docs", "schemas", "capability-spec.schema.json")

# Artifact kinds that consume the capability-spec contract and therefore MUST pin it.
PINNED_KINDS = {"neutrino.target-profile", "neutrino.domain-dialect"}
PIN_FIELD = "capabilitySpecVersion"


def diag(code: str, message: str, severity: str = "error") -> dict:
    return {"code": code, "severity": severity, "message": message}


def emitted_capability_spec_version() -> tuple[str | None, list]:
    """Read kCapabilitySpecVersion from VersionInfo.h (the  single source of truth) and assert
    it matches the capability-spec schema `$id` `vN`. Returns (version, diagnostics)."""
    out: list = []
    try:
        vi = open(VERSIONINFO, encoding="utf-8").read()
    except OSError as exc:
        return None, [diag("compat.io", f"cannot read VersionInfo.h: {exc}")]
    m = re.search(r'kCapabilitySpecVersion\s*=\s*"([^"]*)"', vi)
    if not m:
        return None, [diag("compat.io", "kCapabilitySpecVersion not found in VersionInfo.h")]
    emitted = m.group(1)
    # Lockstep with the actual contract: the schema $id ends in /<vN>.
    try:
        sid = json.load(open(CAPABILITY_SPEC_SCHEMA, encoding="utf-8")).get("$id", "")
    except (OSError, ValueError) as exc:
        return emitted, [diag("compat.io", f"cannot read capability-spec schema: {exc}")]
    sm = re.search(r"/([^/]+)$", sid)
    schema_ver = sm.group(1) if sm else None
    if schema_ver != emitted:
        out.append(diag("compat.contract_drift",
                        f"VersionInfo.h kCapabilitySpecVersion '{emitted}' != capability-spec schema "
                        f"$id version '{schema_ver}' — the emitted contract version drifted from the schema"))
    return emitted, out


def check_artifact(path: str, emitted: str) -> list:
    """Fail-closed pin check for one side artifact."""
    try:
        art = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [diag("compat.io", f"{path}: cannot read artifact: {exc}")]
    if not isinstance(art, dict):
        return [diag("compat.schema", f"{path}: artifact must be a JSON object")]
    rel = os.path.relpath(path, REPO)
    kind = art.get("kind")
    if kind not in PINNED_KINDS:
        return [diag("compat.unpinnable_kind",
                     f"{rel}: kind {kind!r} is not a capability-spec-pinned artifact "
                     f"(expected one of {sorted(PINNED_KINDS)})")]
    pin = art.get(PIN_FIELD)
    if pin is None:
        return [diag("compat.pin_missing",
                     f"{rel}: a {kind} must declare '{PIN_FIELD}' pinning the capability-spec "
                     f"contract version (expected '{emitted}')")]
    if not isinstance(pin, str) or pin != emitted:
        return [diag("compat.capability_spec_mismatch",
                     f"{rel}: {PIN_FIELD} {pin!r} != emitted capability-spec contract version "
                     f"'{emitted}' (fail closed — regenerate/repin against the current contract)")]
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description="Enforce side-artifact capability-spec version pins ()")
    ap.add_argument("artifacts", nargs="*", help="target-profile / domain-dialect artifacts to check")
    ap.add_argument("--self-check", action="store_true",
                    help="only assert VersionInfo.h kCapabilitySpecVersion matches the schema $id")
    args = ap.parse_args()

    emitted, diagnostics = emitted_capability_spec_version()
    if emitted is not None and not args.self_check:
        for path in args.artifacts:
            diagnostics += check_artifact(path, emitted)

    errors = [d for d in diagnostics if d.get("severity") == "error"]
    ok = not errors
    json.dump({"ok": ok, "capabilitySpecVersion": emitted,
               "diagnostics": sorted(diagnostics, key=lambda d: (d["code"], d["message"]))},
              sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
