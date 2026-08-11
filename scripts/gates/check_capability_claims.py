#!/usr/bin/env python3
"""Authenticate catalog-derived backend capability models and their manifest."""

import argparse
import hashlib
import json
import os
import sys

VALIDATORS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "validators")
sys.path.insert(0, VALIDATORS)
import verify_domain_pack as schema_validator  # noqa: E402


PROFILE_KEYS = {
    "schemaVersion", "kind", "profileId", "profileVersion", "target",
    "runtimeFamily", "executionMode", "supportedFeatures",
    "unsupportedConstructs", "fallbackPolicy", "capabilitySpecVersion",
    "semanticProfile",
}
LIMIT_KEYS = {
    "maxAttestations", "maxComputes", "maxEffectGroups", "maxEffects",
    "maxExpressionDepth", "maxOperationSteps",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return "sha256:" + hashlib.sha256(value).hexdigest()


def artifact_name(target):
    if target in ("solidity", "postgres"):
        return target + ".json"
    return "target-" + target.encode("utf-8").hex() + ".json"


def diagnostic(code, message):
    return {"severity": "error", "code": code, "message": message}


def load_json(path, code, diagnostics):
    try:
        with open(path, encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        diagnostics.append(diagnostic(code, f"{path}: {error}"))
        return None
    if not isinstance(value, dict):
        diagnostics.append(diagnostic(code, f"{path}: expected a JSON object"))
        return None
    return value


def is_digest(value):
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(char in "0123456789abcdef" for char in value[7:])
    )


def valid_strings(value):
    return (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and value == sorted(set(value))
    )


def validate_profile(profile):
    if not isinstance(profile, dict) or set(profile) != PROFILE_KEYS:
        return False
    semantic = profile.get("semanticProfile")
    limits = semantic.get("limits") if isinstance(semantic, dict) else None
    return (
        profile.get("schemaVersion") == 1
        and profile.get("kind") == "neutrino.target-profile"
        and isinstance(profile.get("profileId"), str)
        and isinstance(profile.get("profileVersion"), int)
        and not isinstance(profile.get("profileVersion"), bool)
        and profile["profileVersion"] >= 1
        and isinstance(profile.get("target"), str)
        and bool(profile["target"])
        and profile.get("runtimeFamily") in {"on_chain", "relational", "off_chain"}
        and profile.get("executionMode") in {"deterministic", "simulated", "real"}
        and profile.get("fallbackPolicy") in {"fail_closed", "advisory"}
        and isinstance(profile.get("capabilitySpecVersion"), str)
        and valid_strings(profile.get("supportedFeatures"))
        and valid_strings(profile.get("unsupportedConstructs"))
        and set(profile["supportedFeatures"]).isdisjoint(profile["unsupportedConstructs"])
        and isinstance(semantic, dict)
        and set(semantic) == {"features", "limits", "version"}
        and valid_strings(semantic.get("features"))
        and isinstance(semantic.get("version"), int)
        and not isinstance(semantic.get("version"), bool)
        and semantic["version"] >= 1
        and isinstance(limits, dict)
        and set(limits) == LIMIT_KEYS
        and all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in limits.values()
        )
    )


def expected_model(profile, catalog_identity, witness):
    semantic = profile["semanticProfile"]
    return {
        "catalogIdentity": catalog_identity,
        "kind": "neutrino.backend-capability-model",
        "modelVersion": "1.0.0",
        "package": {
            "executionMode": profile["executionMode"],
            "fallbackPolicy": profile["fallbackPolicy"],
            "runtimeFamily": profile["runtimeFamily"],
        },
        "semanticProfile": semantic,
        "sourceCapabilityWitness": witness,
        "supportedFeatures": profile["supportedFeatures"],
        "target": profile["target"],
        "targetProfile": {
            "digest": digest(canonical(profile)),
            "identity": profile["profileId"],
            "version": profile["profileVersion"],
        },
        "unsupportedConstructs": profile["unsupportedConstructs"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--trusted-catalog", required=True)
    parser.add_argument("--model-schema", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    diagnostics = []

    spec = load_json(args.spec, "capability.spec", diagnostics)
    catalog = load_json(args.trusted_catalog, "capability.catalog", diagnostics)
    model_schema = load_json(args.model_schema, "capability.schema", diagnostics)
    manifest = load_json(
        os.path.join(args.capability, "manifest.json"),
        "capability.manifest",
        diagnostics,
    )
    expected = {}
    if spec and catalog:
        if set(catalog) != {"catalogIdentity", "kind", "profiles"} or catalog.get(
            "kind"
        ) != "neutrino.verified-target-profile-catalog/1":
            diagnostics.append(diagnostic("capability.catalog", "invalid trusted catalog shape"))
        if not is_digest(catalog.get("catalogIdentity")):
            diagnostics.append(diagnostic("capability.catalog", "invalid catalog identity"))
        profiles = catalog.get("profiles")
        if not isinstance(profiles, list) or not profiles:
            diagnostics.append(diagnostic("capability.catalog", "trusted catalog has no profiles"))
            profiles = []
        targets = [p.get("target") for p in profiles if isinstance(p, dict)]
        targets_are_strings = all(isinstance(target, str) for target in targets)
        if (
            len(targets) != len(profiles)
            or not targets_are_strings
            or targets != sorted(targets)
            or len(set(targets)) != len(targets)
        ):
            diagnostics.append(diagnostic("capability.catalog", "profiles are not unique and target-sorted"))
        witness = {
            "capabilityHash": spec.get("identity", {}).get("capabilityHash")
            if isinstance(spec.get("identity"), dict)
            else None,
            "procedure": spec.get("procedure"),
            "specVersion": spec.get("specVersion"),
        }
        if not all(isinstance(value, str) and value for value in witness.values()):
            diagnostics.append(diagnostic("capability.spec", "invalid source capability witness"))
        for profile in profiles:
            if not validate_profile(profile):
                diagnostics.append(diagnostic("capability.profile", "malformed trusted profile"))
                continue
            model = expected_model(profile, catalog.get("catalogIdentity"), witness)
            expected[artifact_name(profile["target"])] = model

    emitted_catalog_path = os.path.join(args.capability, "catalog.json")
    emitted_catalog = load_json(emitted_catalog_path, "capability.catalog", diagnostics)
    if catalog and emitted_catalog != catalog:
        diagnostics.append(diagnostic("capability.catalog", "emitted catalog does not match trusted catalog"))

    actual_names = set()
    try:
        capability_entries = sorted(os.listdir(args.capability))
    except OSError as error:
        diagnostics.append(diagnostic("capability.directory", str(error)))
        capability_entries = []
    for name in capability_entries:
        path = os.path.join(args.capability, name)
        if not os.path.isfile(path) or not name.endswith(".json"):
            continue
        if name in {"catalog.json", "manifest.json", "diagnostics.json"}:
            continue
        value = load_json(path, "capability.model", diagnostics)
        actual_names.add(name)
        if value is not None and model_schema is not None:
            schema_diagnostics = []
            schema_validator._validate(
                value, model_schema, "capabilityModel", schema_diagnostics,
                model_schema,
            )
            for message in schema_diagnostics:
                diagnostics.append(diagnostic("capability.schema", message))
        if name not in expected:
            diagnostics.append(diagnostic("capability.extra", f"unexpected model {name}"))
        elif value != expected[name]:
            diagnostics.append(diagnostic("capability.binding", f"{name} does not match its trusted profile"))
    missing = sorted(set(expected) - actual_names)
    for name in missing:
        diagnostics.append(diagnostic("capability.missing", f"missing model {name}"))

    if manifest:
        manifest_artifacts = manifest.get("artifacts")
        if not isinstance(manifest_artifacts, list):
            diagnostics.append(diagnostic("capability.manifest", "artifacts is not a list"))
        else:
            recorded = {}
            for row in manifest_artifacts:
                if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                    diagnostics.append(diagnostic("capability.manifest", "malformed artifact row"))
                    continue
                name = os.path.basename(row["path"])
                if name in recorded:
                    diagnostics.append(diagnostic("capability.manifest", f"duplicate artifact row {name}"))
                    continue
                recorded[name] = row.get("sha256")
            required_files = set(expected) | {"catalog.json"}
            if set(recorded) != required_files:
                diagnostics.append(diagnostic("capability.manifest", "artifact/model bijection mismatch"))
            for name in sorted(required_files & set(recorded)):
                path = os.path.join(args.capability, name)
                try:
                    with open(path, "rb") as stream:
                        actual_digest = hashlib.sha256(stream.read()).hexdigest()
                except OSError as error:
                    diagnostics.append(diagnostic("capability.manifest", f"{name}: {error}"))
                    continue
                if recorded[name] != actual_digest:
                    diagnostics.append(diagnostic("capability.manifest", f"{name}: byte digest mismatch"))

    ok = not diagnostics
    targets = sorted(model["target"] for model in expected.values())
    report = {
        "kind": "neutrino.capability-claims",
        "modelVersion": "1.0.0",
        "ok": ok,
        "targets": targets,
    }
    with open(os.path.join(args.out, "capability-claims.json"), "w") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    with open(os.path.join(args.out, "diagnostics.json"), "w") as stream:
        json.dump({"diagnostics": diagnostics, "ok": ok}, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
