#!/usr/bin/env python3
"""Capability-model v1 catalog, fact, filename, and byte-binding mutations."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile


GEN, CHECKER, SOURCE, SCENARIO, MODEL_SCHEMA = sys.argv[1:6]


def run(command, expected=0, cwd=None):
    result = subprocess.run(command, text=True, capture_output=True, cwd=cwd)
    if result.returncode != expected:
        raise AssertionError(
            f"return code {result.returncode}, expected {expected}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    if "Traceback" in result.stderr:
        raise AssertionError(f"checker crashed:\n{result.stderr}")
    return result


def read(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def write(path, value):
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


with tempfile.TemporaryDirectory(prefix="capability-claims-") as temporary:
    trusted_catalog = os.path.join(temporary, "trusted-catalog.json")
    catalog_result = run([GEN, "--verified-target-profile-catalog"])
    with open(trusted_catalog, "w", encoding="utf-8") as stream:
        stream.write(catalog_result.stdout)
    output = os.path.join(temporary, "models")
    run(
        [
            GEN,
            "--target=capability",
            "--scenario",
            SCENARIO,
            SOURCE,
            "-o",
            output,
        ]
    )
    model_names = []
    for name in sorted(os.listdir(output)):
        path = os.path.join(output, name)
        if name.endswith(".json") and os.path.isfile(path):
            value = read(path)
            if value.get("kind") == "neutrino.backend-capability-model":
                model_names.append(name)
    if not model_names:
        raise AssertionError("capability generation produced no verified-profile model")

    spec_dir = os.path.join(temporary, "spec")
    run([GEN, "--target=capability-spec", SOURCE, "-o", spec_dir])
    spec = os.path.join(spec_dir, "capability-spec.json")
    def check(directory, label, expected=1, expected_code=None):
        check_dir = os.path.join(temporary, label + "-check")
        result = run(
            [
                sys.executable,
                CHECKER,
                "--capability",
                directory,
                "--scenario",
                SCENARIO,
                "--spec",
                spec,
                "--trusted-catalog",
                trusted_catalog,
                "--model-schema",
                MODEL_SCHEMA,
                "--out",
                check_dir,
            ],
            expected=expected,
        )
        if expected_code is not None:
            diagnostics = read(os.path.join(check_dir, "diagnostics.json"))[
                "diagnostics"
            ]
            if not any(row.get("code") == expected_code for row in diagnostics):
                raise AssertionError(
                    f"{label} did not bite {expected_code}: {diagnostics}"
                )
        return result

    check(output, "positive", expected=0)

    # The hardened publisher must still reject reuse of a populated output
    # root, while a second Make-style fresh run root succeeds unchanged.
    #
    # Run the reuse rejection against a COPY of the populated root. The refusal
    # happens in publication, but manifest.json/diagnostics.json are written by
    # the sidecar path BEFORE publication, so a refused re-run still overwrites
    # them -- leaving manifest.artifacts empty. Pointing it at `output` therefore
    # destroyed the fixture every later mutation probe copies, and silently made
    # the manifest-digest tamper vacuous (nothing left to tamper).
    reuse_output = os.path.join(temporary, "reuse-models")
    shutil.copytree(output, reuse_output)
    run(
        [
            GEN,
            "--target=capability",
            "--scenario",
            SCENARIO,
            SOURCE,
            "-o",
            reuse_output,
        ],
        expected=2,
    )
    repeat_output = os.path.join(temporary, "repeat-models")
    run(
        [
            GEN,
            "--target=capability",
            "--scenario",
            SCENARIO,
            SOURCE,
            "-o",
            repeat_output,
        ]
    )
    check(repeat_output, "repeat-positive", expected=0)

    # Exercise the real Make-owned lifecycle twice against one retained
    # artifact parent. Each invocation must select a fresh bounded run root.
    repository = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(CHECKER)))
    )
    make_artifacts = os.path.join(temporary, "make-artifacts")
    make_command = [
        "make",
        "-f",
        "Makefile",
        "-o",
        "build",
        "capability-check",
        f"GEN={os.path.abspath(GEN)}",
        f"ARTIFACT_DIR={make_artifacts}",
        f"EXAMPLE={os.path.abspath(SOURCE)}",
        f"SCENARIO={os.path.abspath(SCENARIO)}",
    ]
    run(make_command, cwd=repository)
    run(make_command, cwd=repository)
    run_roots = sorted(
        name
        for name in os.listdir(make_artifacts)
        if name.startswith("capability-check-run.")
    )
    if len(run_roots) != 2 or run_roots[0] == run_roots[1]:
        raise AssertionError(
            f"repeated capability-check did not create two fresh roots: {run_roots}"
        )

    def mutated(label, operation, expected_code=None):
        directory = os.path.join(temporary, label)
        shutil.copytree(output, directory)
        # Published artifacts are deliberately immutable -- ArtifactPublication
        # chmods them 0444 so a published byte cannot be rewritten in place --
        # and copytree preserves that mode. This probe mutates its OWN PRIVATE
        # COPY, so restore write permission here, at the one point where those
        # artifacts enter the probe's workspace. Production immutability is a
        # property asserted elsewhere and is not weakened by this.
        for root, _dirs, names in os.walk(directory):
            for name in names:
                target = os.path.join(root, name)
                os.chmod(target, os.stat(target).st_mode | 0o200)
        operation(directory)
        check(directory, label, expected_code=expected_code)

    def change_model(mutator, all_models=False):
        def operation(directory):
            names = model_names if all_models else model_names[:1]
            for name in names:
                path = os.path.join(directory, name)
                value = read(path)
                mutator(value)
                write(path, value)
        return operation

    def change_runtime(value):
        current = value["package"]["runtimeFamily"]
        value["package"]["runtimeFamily"] = (
            "off_chain" if current != "off_chain" else "on_chain"
        )

    def change_limit(value):
        limits = value["semanticProfile"]["limits"]
        limits["maxEffects"] += 1

    mutated(
        "nested-package-fact",
        change_model(change_runtime),
    )
    mutated(
        "nested-semantic-fact",
        change_model(change_limit),
    )
    mutated(
        "profile-digest",
        change_model(lambda value: value["targetProfile"].__setitem__("digest", "sha256:" + "0" * 64)),
    )
    mutated(
        "catalog-substitution",
        change_model(lambda value: value.__setitem__("catalogIdentity", "sha256:" + "0" * 64), all_models=True),
    )

    def coordinated_catalog_substitution(directory):
        catalog_path = os.path.join(directory, "catalog.json")
        catalog = read(catalog_path)
        catalog["catalogIdentity"] = "sha256:" + "0" * 64
        catalog["profiles"][0]["runtimeFamily"] = (
            "off_chain"
            if catalog["profiles"][0]["runtimeFamily"] != "off_chain"
            else "on_chain"
        )
        write(catalog_path, catalog)
        profiles = {profile["target"]: profile for profile in catalog["profiles"]}
        for name in model_names:
            path = os.path.join(directory, name)
            model = read(path)
            profile = profiles[model["target"]]
            model["catalogIdentity"] = catalog["catalogIdentity"]
            model["package"]["runtimeFamily"] = profile["runtimeFamily"]
            canonical = json.dumps(
                profile, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode()
            model["targetProfile"]["digest"] = (
                "sha256:" + hashlib.sha256(canonical).hexdigest()
            )
            write(path, model)
        manifest_path = os.path.join(directory, "manifest.json")
        manifest = read(manifest_path)
        for row in manifest["artifacts"]:
            path = os.path.join(directory, os.path.basename(row["path"]))
            with open(path, "rb") as stream:
                row["sha256"] = hashlib.sha256(stream.read()).hexdigest()
        write(manifest_path, manifest)

    mutated("coordinated-catalog-substitution", coordinated_catalog_substitution)
    mutated(
        "missing-model",
        lambda directory: os.unlink(os.path.join(directory, model_names[0])),
    )

    def add_extra(directory):
        extra = read(os.path.join(directory, model_names[0]))
        extra["target"] = "invented"
        write(os.path.join(directory, "target-696e76656e746564.json"), extra)

    mutated("extra-model", add_extra)

    def rename_model(directory):
        os.rename(
            os.path.join(directory, model_names[0]),
            os.path.join(directory, "wrong-name.json"),
        )

    mutated("filename-target-mismatch", rename_model)
    mutated(
        "malformed-type",
        change_model(lambda value: value.__setitem__("package", "not-a-package-contract")),
        expected_code="capability.schema",
    )

    def malformed_json(directory):
        with open(os.path.join(directory, model_names[0]), "w", encoding="utf-8") as stream:
            stream.write("{not json\n")

    mutated("malformed-json", malformed_json)
    mutated(
        "stale-version",
        change_model(lambda value: value.__setitem__("modelVersion", "0.1.0")),
    )

    def digest_tamper(directory):
        path = os.path.join(directory, "manifest.json")
        value = read(path)
        value["artifacts"][0]["sha256"] = "0" * 64
        write(path, value)

    mutated("manifest-digest", digest_tamper)

print("capability claims OK: independent catalog, schema, and bytes authenticated; 12 mutations refused")
