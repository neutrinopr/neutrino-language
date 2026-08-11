#!/usr/bin/env python3
"""Fail closed when a source-governance CTest entrypoint loses its shared lock."""

import argparse
import copy
import json
import os
import subprocess
import sys


LOCK = "neutrino_source_tree_gate"
REQUIRED = {
    "fast",
    "core-feature-example-matrix-selftest",
    "renderer-include-lock",
    "anti-inference-production",
    "anti-inference-selftest",
    "decision-path-lock",
    "idiom-table-capability",
    "canonical-reduction-domain-blindness",
    "cpp-policy",
    "arch-backend-isolation",
    "arch-domain-isolation",
    "arch-root-scripts",
    "extraction-manifests",
    "extraction-boundaries",
    "arch-link-direction",
    "no-orphan-scripts",
    "parser-metadata-keywords",
    "catalog-registry",
    "target-node-registry",
    "ctest-labels",
}


def lock_values(test):
    for prop in test.get("properties", []):
        if prop.get("name") == "RESOURCE_LOCK":
            value = prop.get("value", [])
            return value if isinstance(value, list) else [value]
    return []


def command_scripts(test):
    return {
        os.path.normpath(token)
        for token in test.get("command", [])
        if isinstance(token, str) and token.endswith((".py", ".sh"))
    }


def is_fast_discovery(test):
    command = test.get("command", [])
    return (
        "unittest" in command
        and "discover" in command
        and any("/test/checks/fast" in token.replace("\\", "/") for token in command)
    )


def is_lit_discovery(test):
    command = test.get("command", [])
    return (
        any(os.path.basename(token) in {"lit", "llvm-lit"} for token in command)
        and any("/test/ir" in token.replace("\\", "/") for token in command)
    )


def check(payload):
    tests = {test.get("name"): test for test in payload.get("tests", [])}
    required = set(REQUIRED)
    if "lit" in tests:
        required.add("lit")
    reasons = []
    for name in sorted(required):
        if name not in tests:
            reasons.append(f"[source_lock.missing_test] required CTest {name!r} is not registered")
        elif LOCK not in lock_values(tests[name]):
            reasons.append(
                f"[source_lock.unlocked] CTest {name!r} does not hold RESOURCE_LOCK {LOCK!r}")
    governed_scripts = set()
    for name in required:
        if name in tests:
            governed_scripts |= command_scripts(tests[name])
    for name, test in sorted(tests.items()):
        duplicates_governed_entrypoint = (
            bool(command_scripts(test) & governed_scripts)
            or is_fast_discovery(test)
            or is_lit_discovery(test)
        )
        if duplicates_governed_entrypoint and LOCK not in lock_values(test):
            reasons.append(
                f"[source_lock.unlocked_entrypoint] CTest {name!r} duplicates a governed "
                f"source-tree entrypoint without RESOURCE_LOCK {LOCK!r}")
    return reasons


def load_ctest(build_dir):
    result = subprocess.run(
        ["ctest", "--test-dir", build_dir, "--show-only=json-v1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "ctest JSON query failed")
    return json.loads(result.stdout)


def report(reasons):
    if not reasons:
        print(f"CTest source-tree lock OK: all governed entrypoints hold {LOCK}")
        return 0
    print("CTest source-tree lock FAILED:", file=sys.stderr)
    for reason in reasons:
        print(f"    {reason}", file=sys.stderr)
    return 1


def selftest(payload):
    if report(check(payload)):
        print("selftest: the configured CTest graph does not pass the gate", file=sys.stderr)
        return 1
    fails = []
    for victim in ("fast", "anti-inference-boundary"):
        mutated = copy.deepcopy(payload)
        test = next((item for item in mutated["tests"] if item.get("name") == victim), None)
        if test is None:
            fails.append(f"cannot find required witness {victim!r}")
            continue
        test["properties"] = [
            prop for prop in test.get("properties", [])
            if prop.get("name") != "RESOURCE_LOCK"
        ]
        if not any("[source_lock.unlocked]" in reason for reason in check(mutated)):
            fails.append(f"removing {victim!r}'s lock should fail closed")
        duplicate = copy.deepcopy(test)
        duplicate["name"] = victim + "-duplicate"
        duplicate["properties"] = [
            prop for prop in duplicate.get("properties", [])
            if prop.get("name") != "RESOURCE_LOCK"
        ]
        duplicated = copy.deepcopy(payload)
        duplicated["tests"].append(duplicate)
        if not any(
                "[source_lock.unlocked_entrypoint]" in reason
                and victim + "-duplicate" in reason
                for reason in check(duplicated)):
            fails.append(f"an unlocked duplicate of {victim!r} should fail closed")
    if fails:
        print("CTest source-tree lock SELFTEST FAILED:", file=sys.stderr)
        for failure in fails:
            print(f"    {failure}", file=sys.stderr)
        return 1
    print("CTest source-tree lock selftest PASS: umbrella and standalone lock deletions bite")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    try:
        payload = load_ctest(args.build_dir)
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"CTest source-tree lock FAILED: {exc}", file=sys.stderr)
        return 2
    return selftest(payload) if args.selftest else report(check(payload))


if __name__ == "__main__":
    sys.exit(main())
