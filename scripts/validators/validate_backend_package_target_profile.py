#!/usr/bin/env python3
"""Validate the closed target profile embedded in a verified backend package."""

from __future__ import annotations

import argparse
import json
import os
import sys

import validate_target_profile as base

PACKAGE_FIELDS = base.FIELDS | base.OPTIONAL_FIELDS
CAPABILITY_SPEC_VERSION = "v1"
MAX_PROFILE_VERSION = (1 << 32) - 1
MAX_SEMANTIC_LIMIT = (1 << 63) - 1
BEYOND_SCHEMA_INVARIANTS = frozenset(
    {
        "descriptor-identity-binding",
        "feature-array-lexicographic-order",
        "profile-id-version-binding",
        "semantic-feature-closed-vocabulary",
        "supported-unsupported-disjointness",
    }
)


def _ordered(profile, path, diagnostics):
    value = profile
    for field in path.split("."):
        if not isinstance(value, dict):
            return
        value = value.get(field)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        if value != sorted(value):
            diagnostics.append(
                base.diag(
                    "profile.noncanonical_order",
                    f"{path} must be lexicographically sorted",
                )
            )


def validate(profile):
    diagnostics = list(base.validate(profile))
    if not isinstance(profile, dict):
        return diagnostics

    for field in sorted(PACKAGE_FIELDS - set(profile)):
        diagnostics.append(
            base.diag("profile.missing_field", f"missing package field '{field}'")
        )
    for field in sorted(set(profile) - PACKAGE_FIELDS):
        diagnostics.append(
            base.diag("profile.unknown_field", f"unknown package field '{field}'")
        )

    profile_version = profile.get("profileVersion")
    if (
        isinstance(profile_version, int)
        and not isinstance(profile_version, bool)
        and profile_version > MAX_PROFILE_VERSION
    ):
        diagnostics.append(
            base.diag(
                "profile.schema",
                f"profileVersion must be at most {MAX_PROFILE_VERSION}",
            )
        )
    if profile.get("capabilitySpecVersion") != CAPABILITY_SPEC_VERSION:
        diagnostics.append(
            base.diag(
                "profile.schema",
                f"capabilitySpecVersion must be '{CAPABILITY_SPEC_VERSION}'",
            )
        )

    semantic = profile.get("semanticProfile")
    if not isinstance(semantic, dict):
        diagnostics.append(
            base.diag("profile.schema", "semanticProfile must be a JSON object")
        )
    else:
        limits = semantic.get("limits")
        if isinstance(limits, dict):
            for field in sorted(base.LIMIT_FIELDS & set(limits)):
                value = limits[field]
                if (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value > MAX_SEMANTIC_LIMIT
                ):
                    diagnostics.append(
                        base.diag(
                            "profile.schema",
                            f"semanticProfile.limits.{field} must be at most "
                            f"{MAX_SEMANTIC_LIMIT}",
                        )
                    )

    _ordered(profile, "supportedFeatures", diagnostics)
    _ordered(profile, "unsupportedConstructs", diagnostics)
    _ordered(profile, "semanticProfile.features", diagnostics)
    return sorted(diagnostics, key=lambda item: (item["code"], item["message"]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--out")
    args = parser.parse_args()
    profile = None
    try:
        with open(args.file, encoding="utf-8") as stream:
            profile = json.load(stream)
        diagnostics = validate(profile)
    except (OSError, ValueError) as error:
        diagnostics = [
            base.diag("profile.io", f"cannot read package target profile: {error}")
        ]
    ok = not diagnostics
    report = {
        "ok": ok,
        "file": os.path.basename(args.file),
        "profileId": profile.get("profileId") if isinstance(profile, dict) else None,
        "diagnostics": diagnostics,
    }
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(
            os.path.join(args.out, "profile.report.json"), "w", encoding="utf-8"
        ) as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
