#!/usr/bin/env python3
import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path


def load_module(name, path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parent_and_field(profile, pointer):
    parts = pointer.lstrip("/").split("/")
    parent = profile
    for part in parts[:-1]:
        parent = parent[part]
    return parent, parts[-1]


def mutate(profile, mutation):
    if mutation["operation"] == "erase":
        parent, field = parent_and_field(profile, mutation["pointer"])
        del parent[field]
    elif mutation["operation"] == "reverse":
        parent, field = parent_and_field(profile, mutation["pointer"])
        parent[field].reverse()
    elif mutation["operation"] == "assign":
        for assignment in mutation["assignments"]:
            parent, field = parent_and_field(profile, assignment["pointer"])
            parent[field] = assignment["value"]
    else:
        raise AssertionError(f"unknown mutation operation {mutation['operation']}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True, type=Path)
    parser.add_argument("--schema", required=True, type=Path)
    parser.add_argument("--validator", required=True, type=Path)
    parser.add_argument("--schema-validator", required=True, type=Path)
    parser.add_argument("--public-schema", required=True, type=Path)
    parser.add_argument("--public-validator", required=True, type=Path)
    args = parser.parse_args()

    fixture = json.loads(args.fixture.read_text())
    schema = json.loads(args.schema.read_text())
    public_schema = json.loads(args.public_schema.read_text())
    validator = load_module("package_target_profile_validator", args.validator)
    public_validator = load_module("public_target_profile_validator", args.public_validator)
    schema_validator = load_module("domain_pack_schema_validator", args.schema_validator)
    if fixture["kind"] != "neutrino.target-profile-validator-agreement/1":
        raise AssertionError("agreement fixture kind drifted")
    if set(schema["required"]) != validator.PACKAGE_FIELDS:
        raise AssertionError("schema and validator required fields differ")
    if schema["properties"]["capabilitySpecVersion"]["const"] != (
        validator.CAPABILITY_SPEC_VERSION
    ):
        raise AssertionError("capability version contract differs")
    if schema["properties"]["semanticProfile"]["properties"]["version"]["const"] != (
        validator.base.SEMANTIC_PROFILE_VERSION
    ):
        raise AssertionError("semantic profile version contract differs")
    if schema["properties"]["profileVersion"]["maximum"] != (
        validator.MAX_PROFILE_VERSION
    ):
        raise AssertionError("profileVersion numeric domain differs")
    if schema["$defs"]["limit"]["maximum"] != validator.MAX_SEMANTIC_LIMIT:
        raise AssertionError("semantic limit numeric domain differs")
    if set(fixture["beyondSchemaInvariants"]) != validator.BEYOND_SCHEMA_INVARIANTS:
        raise AssertionError("beyond-schema invariant classification differs")

    positive = fixture["positive"]
    legacy = copy.deepcopy(positive)
    del legacy["capabilitySpecVersion"]
    del legacy["semanticProfile"]
    forward_capability = copy.deepcopy(legacy)
    forward_capability["capabilitySpecVersion"] = "v99"
    for name, candidate in (
        ("optional version blocks", legacy),
        ("forward capability version", forward_capability),
    ):
        if public_validator.validate(candidate):
            raise AssertionError(f"public v1 rejected {name}")
        public_diagnostics = []
        schema_validator._validate(
            candidate, public_schema, "profile", public_diagnostics, public_schema
        )
        if public_diagnostics:
            raise AssertionError(
                f"public v1 schema rejected {name}: {public_diagnostics}"
            )

    diagnostics = validator.validate(positive)
    if diagnostics:
        raise AssertionError(f"positive fixture rejected: {diagnostics}")
    schema_diagnostics = []
    schema_validator._validate(
        positive, schema, "profile", schema_diagnostics, schema
    )
    if schema_diagnostics:
        raise AssertionError(f"schema rejected positive fixture: {schema_diagnostics}")
    mutations = fixture["mutations"]
    if len({item["name"] for item in mutations}) != len(mutations):
        raise AssertionError("duplicate mutation name")
    for mutation in mutations:
        candidate = copy.deepcopy(positive)
        mutate(candidate, mutation)
        diagnostics = validator.validate(candidate)
        package_accepted = not diagnostics
        if package_accepted != mutation["packageAccepted"]:
            raise AssertionError(
                f"{mutation['name']} package outcome {package_accepted} != "
                f"{mutation['packageAccepted']}: {diagnostics}"
            )
        schema_diagnostics = []
        schema_validator._validate(
            candidate, schema, "profile", schema_diagnostics, schema
        )
        schema_accepted = not schema_diagnostics
        if schema_accepted != mutation["schemaAccepted"]:
            raise AssertionError(
                f"{mutation['name']} schema outcome {schema_accepted} != "
                f"{mutation['schemaAccepted']}: {schema_diagnostics}"
            )

    print(
        "target-profile-validator-agreement OK: "
        f"2 public-v1 compatibility cases, 1 package positive, "
        f"{len(mutations)} shared cases"
    )


if __name__ == "__main__":
    main()
