#!/usr/bin/env python3
"""End-to-end proof for catalog-discovered external target dispatch ()."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def run(command, expected=0, extra_env=None):
    environment = os.environ.copy()
    if extra_env:
        environment.update(extra_env)
    completed = subprocess.run(
        command, text=True, capture_output=True, input="", env=environment
    )
    if completed.returncode != expected:
        raise AssertionError(
            f"command returned {completed.returncode}, expected {expected}:\n"
            f"{' '.join(map(str, command))}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def make_package(
    root,
    backend,
    profile_path,
    schema_path,
    target="synthetic",
    remove_semantic_feature=None,
    profile_marker=None,
):
    entry = root / "bin" / "backend"
    entry.parent.mkdir(parents=True)
    shutil.copy2(backend, entry)
    entry.chmod(0o500)
    entry_bytes = entry.read_bytes()

    profile = json.loads(profile_path.read_text())
    profile["target"] = target
    profile_identity = f"target.{target.replace('-', '_')}.v1"
    profile["profileId"] = profile_identity
    if remove_semantic_feature is not None:
        profile["semanticProfile"]["features"].remove(remove_semantic_feature)
    if profile_marker is not None:
        profile["semanticProfile"]["limits"]["maxComputes"] += 1
    projection_schema = json.loads(schema_path.read_text())["properties"][
        "schemaVersion"
    ]["const"]
    descriptor = {
        "apiVersion": 1,
        "capabilities": ["emit", "stream"],
        "closure": [
            {
                "byteLen": len(entry_bytes),
                "path": "bin/backend",
                "sha256": digest(entry_bytes),
            }
        ],
        "compatibilityBounds": {
            "coreProtocol": {
                "max": {"major": 1, "minor": 0},
                "min": {"major": 1, "minor": 0},
            },
            "projectionSchema": {
                "max": projection_schema,
                "min": projection_schema,
            },
        },
        "entry": "bin/backend",
        "kind": "neutrino.backend-package/1",
        "licenseIdentity": "MIT",
        "profileSummary": profile,
        "protocolMajor": 1,
        "protocolMinor": 0,
        "targetIdentity": target,
        "targetProfileIdentity": profile_identity,
    }
    descriptor["manifestDigest"] = digest(canonical(descriptor))
    (root / "backend-package.json").write_bytes(canonical(descriptor))
    return profile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--neutrino-gen", required=True, type=Path)
    parser.add_argument("--backend", required=True, type=Path)
    parser.add_argument(
        "--manifest-collision-backend", required=True, type=Path
    )
    parser.add_argument(
        "--diagnostics-collision-backend", required=True, type=Path
    )
    parser.add_argument("--receipt-collision-backend", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--projection-schema", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--insecure-spec", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--registry-source", required=True, type=Path)
    parser.add_argument("--emit-cmake", required=True, type=Path)
    parser.add_argument("--gen-source", required=True, type=Path)
    parser.add_argument("--capability-model-source", required=True, type=Path)
    parser.add_argument("--emit-library", required=True, type=Path)
    parser.add_argument("--repository-package", required=True, type=Path)
    args = parser.parse_args()

    registry = args.registry.read_text()
    if '"synthetic"' in registry:
        raise AssertionError(
            "synthetic target must not be added to the built-in target registry"
        )
    if 'NEUTRINO_TARGET("solidity"' in registry:
        raise AssertionError(
            "Solidity must not retain a built-in function-symbol row"
        )
    if 'NEUTRINO_TARGET_DRIVER("capability"' not in registry:
        raise AssertionError("capability target is not driver-serialized")
    capability_source = args.capability_model_source.read_text()
    for forbidden in (
        'target == "solidity"',
        'target == "postgres"',
        "executionEnvironment",
        "languageLevels",
        "valueModel",
        "assuranceTier",
    ):
        if forbidden in capability_source:
            raise AssertionError(
                f"capability model regained core-authored backend facts: {forbidden}"
            )
    registry_source = args.registry_source.read_text()
    if "GenSolidity.h" in registry_source:
        raise AssertionError(
            "the core registry still includes the Solidity generator contract"
        )
    emit_cmake = args.emit_cmake.read_text()
    try:
        emit_section = emit_cmake.split(
            "add_mlir_library(NeutrinoEmit", 1
        )[1].split("# ", 1)[0]
    except IndexError as error:
        raise AssertionError("cannot locate the NeutrinoEmit CMake section") from error
    for forbidden in (
        "targets/SolidityTarget.cpp",
        "NeutrinoBackendSolidity",
    ):
        if forbidden in emit_section:
            raise AssertionError(
                f"NeutrinoEmit retains legacy Solidity coupling: {forbidden}"
            )
    gen_source = args.gen_source.read_text()
    for forbidden in (
        "GenSoliditySpec.h",
        "generateSoliditySourcesFromSpec",
    ):
        if forbidden in gen_source:
            raise AssertionError(
                f"neutrino-gen retains legacy Solidity dispatch: {forbidden}"
            )
    undefined_symbols = subprocess.check_output(
        ["nm", "-u", str(args.emit_library)], text=True
    )
    if "Solidity" in undefined_symbols or "emitSolidity" in undefined_symbols:
        raise AssertionError(
            "NeutrinoEmit retains an undefined Solidity symbol dependency"
        )
    repository_descriptor = json.loads(
        (args.repository_package / "backend-package.json").read_text()
    )
    if (
        repository_descriptor["targetIdentity"] != "solidity"
        or repository_descriptor["entry"] != "bin/neutrino-solidity-backend"
    ):
        raise AssertionError(
            "repository Solidity package does not bind the expected entry"
        )

    with tempfile.TemporaryDirectory(prefix="neutrino-external-target-") as tmp:
        # macOS spells its temp root through /var -> /private/var. The
        # production publisher deliberately rejects symlink components.
        root = Path(tmp).resolve()
        package = root / "package"
        profile = make_package(
            package, args.backend, args.profile, args.projection_schema
        )
        descriptor_path = package / "backend-package.json"
        startup_contract = (
            "--neutrino-backend-startup=neutrino.backend-startup/1"
        )
        startup_descriptor = f"--package-descriptor={descriptor_path}"
        missing_startup = run([str(args.backend)], expected=86)
        if missing_startup.stdout or missing_startup.stderr:
            raise AssertionError("missing startup contract emitted unstable output")
        present_startup = run(
            [str(args.backend), startup_contract, startup_descriptor],
            expected=92,
        )
        if present_startup.stdout or present_startup.stderr:
            raise AssertionError("present startup contract emitted unstable output")
        invalid_descriptor = root / "invalid-backend-package.json"
        invalid_value = json.loads(descriptor_path.read_text())
        invalid_value["manifestDigest"] = "sha256:" + "0" * 64
        invalid_descriptor.write_bytes(canonical(invalid_value))
        invalid_startup = run(
            [
                str(args.backend),
                startup_contract,
                f"--package-descriptor={invalid_descriptor}",
            ],
            expected=87,
        )
        if invalid_startup.stdout or invalid_startup.stderr:
            raise AssertionError(
                "mismatched startup descriptor emitted unstable output"
            )
        common = [
            str(args.neutrino_gen),
            "--backend-package-dir",
            str(package),
        ]

        # Ordinary build-tree use supplies no package flag. The separately
        # linked repository package must be discovered through the installed
        # layout relative to neutrino-gen, and its real backend must publish a
        # receipt bound to the verified descriptor.
        ordinary_listed = run(
            [str(args.neutrino_gen), "--list-targets"]
        ).stdout.splitlines()
        if ordinary_listed.count("solidity") != 1:
            raise AssertionError(
                "ordinary build-tree target discovery omitted Solidity: "
                f"{ordinary_listed}"
            )
        ordinary_output = root / "ordinary-solidity"
        run(
            [
                str(args.neutrino_gen),
                str(args.source),
                "--target=solidity",
                "--scenario",
                str(args.scenario),
                "-o",
                str(ordinary_output),
            ]
        )
        ordinary_receipt = json.loads(
            (ordinary_output / "backend-dispatch-receipt.json").read_text()
        )
        if (
            ordinary_receipt["targetIdentity"] != "solidity"
            or ordinary_receipt["packageManifestDigest"]
            != repository_descriptor["manifestDigest"]
        ):
            raise AssertionError(
                "ordinary Solidity dispatch was not bound to the repository package"
            )

        empty_packages = root / "empty-packages"
        empty_packages.mkdir()
        missing = run(
            [
                str(args.neutrino_gen),
                "--backend-package-dir",
                str(empty_packages),
                str(args.source),
                "--target=solidity",
                "--scenario",
                str(args.scenario),
                "-o",
                str(root / "missing-solidity"),
            ],
            expected=2,
        )
        if (
            "E_PACKAGE_DESCRIPTOR: backend-package.json is missing"
            not in missing.stderr
        ):
            raise AssertionError(
                "missing Solidity package did not fail with the stable package "
                f"diagnostic:\n{missing.stderr}"
            )

        listed = run(common + ["--list-targets"]).stdout.splitlines()
        if listed.count("synthetic") != 1 or "solidity" in listed:
            raise AssertionError(f"unified target list is incomplete: {listed}")

        profiles = json.loads(run(common + ["--target-profiles"]).stdout)
        synthetic_profiles = [
            item for item in profiles if item["target"] == "synthetic"
        ]
        if synthetic_profiles != [
            {
                "id": "target.synthetic.v1",
                "target": "synthetic",
                "version": profile["semanticProfile"]["version"],
            }
        ]:
            raise AssertionError(
                f"external target profile was not catalog-derived: {profiles}"
            )

        dumped = json.loads(
            run(common + ["--dump-semantic-profile=synthetic"]).stdout
        )
        if dumped != profile["semanticProfile"]:
            raise AssertionError("external semantic profile lookup drifted")

        capability_output = root / "capability-models"
        run(
            common
            + [
                str(args.source),
                "--target=capability",
                "--scenario",
                str(args.scenario),
                "-o",
                str(capability_output),
            ]
        )
        synthetic_model_path = capability_output / "target-73796e746865746963.json"
        synthetic_model = json.loads(synthetic_model_path.read_text())
        if (
            synthetic_model["modelVersion"] != "1.0.0"
            or synthetic_model["target"] != "synthetic"
            or synthetic_model["targetProfile"]["digest"]
            != digest(canonical(profile))
            or synthetic_model["semanticProfile"] != profile["semanticProfile"]
            or synthetic_model["supportedFeatures"]
            != profile["supportedFeatures"]
            or synthetic_model["unsupportedConstructs"]
            != profile["unsupportedConstructs"]
        ):
            raise AssertionError(
                "capability model was not derived from the verified profile"
            )
        stale_fields = {
            "assurance",
            "assuranceTier",
            "executionEnvironment",
            "features",
            "languageLevels",
            "maturity",
            "valueModel",
        }
        if stale_fields & set(synthetic_model):
            raise AssertionError("capability model retained core-authored backend facts")

        alpha_package = root / "alpha-package"
        alpha_profile = make_package(
            alpha_package,
            args.backend,
            args.profile,
            args.projection_schema,
            target="alpha",
        )
        ordered_a = root / "capability-order-a"
        ordered_b = root / "capability-order-b"
        for directories, output_dir in (
            ((package, alpha_package), ordered_a),
            ((alpha_package, package), ordered_b),
        ):
            command = [str(args.neutrino_gen)]
            for directory in directories:
                command += ["--backend-package-dir", str(directory)]
            run(
                command
                + [
                    str(args.source),
                    "--target=capability",
                    "--scenario",
                    str(args.scenario),
                    "-o",
                    str(output_dir),
                ]
            )
        expected_names = {
            "catalog.json",
            "target-616c706861.json",
            "target-73796e746865746963.json",
        }
        for output_dir in (ordered_a, ordered_b):
            names = {
                path.name
                for path in output_dir.glob("*.json")
                if path.name not in {"manifest.json", "diagnostics.json"}
            }
            if names != expected_names:
                raise AssertionError(f"capability catalog output drifted: {names}")
        for name in expected_names:
            if (ordered_a / name).read_bytes() != (ordered_b / name).read_bytes():
                raise AssertionError("capability output depends on discovery order")
        alpha_model = json.loads(
            (ordered_a / "target-616c706861.json").read_text()
        )
        if alpha_model["targetProfile"]["digest"] != digest(
            canonical(alpha_profile)
        ):
            raise AssertionError("second catalog profile was not digest-bound")

        invalid = run(
            common
            + [
                str(args.source),
                "--target=not-a-target",
                "--scenario",
                str(args.scenario),
                "-o",
                str(root / "invalid"),
            ],
            expected=2,
        )
        if "'synthetic'" not in invalid.stderr:
            raise AssertionError("target diagnostic did not consume the catalog")

        solidity_package = root / "solidity-package"
        make_package(
            solidity_package,
            args.backend,
            args.profile,
            args.projection_schema,
            target="solidity",
        )
        solidity_listed = run(
            [
                str(args.neutrino_gen),
                "--backend-package-dir",
                str(solidity_package),
                "--list-targets",
            ]
        ).stdout.splitlines()
        if solidity_listed.count("solidity") != 1:
            raise AssertionError(
                "Solidity was not discovered exclusively from its package"
            )

        duplicate = root / "duplicate-solidity-package"
        make_package(
            duplicate,
            args.backend,
            args.profile,
            args.projection_schema,
            target="solidity",
            profile_marker="distinct duplicate Solidity package",
        )
        duplicate_result = run(
            [
                str(args.neutrino_gen),
                "--backend-package-dir",
                str(solidity_package),
                "--backend-package-dir",
                str(duplicate),
                "--list-targets",
            ],
            expected=2,
        )
        if "E_TARGET_DUPLICATE" not in duplicate_result.stderr:
            raise AssertionError("duplicate Solidity packages did not fail closed")

        restricted_package = root / "restricted-profile"
        make_package(
            restricted_package,
            args.backend,
            args.profile,
            args.projection_schema,
            remove_semantic_feature="effect:credit",
        )
        restricted_common = [
            str(args.neutrino_gen),
            "--backend-package-dir",
            str(restricted_package),
        ]
        refused = run(
            restricted_common
            + [
                str(args.source),
                "--target=synthetic",
                "--scenario",
                str(args.scenario),
                "-o",
                str(root / "restricted-refusal"),
            ],
            expected=6,
        )
        if (
            "required feature 'effect:credit'" not in refused.stderr
            or "not supported by target 'target.synthetic.v1'"
            not in refused.stderr
        ):
            raise AssertionError(
                "restricted verified package profile did not refuse the plan:\n"
                + refused.stderr
            )
        override = run(
            restricted_common
            + [
                str(args.source),
                "--target=synthetic",
                "--scenario",
                str(args.scenario),
                "--profile",
                str(args.profile),
                "-o",
                str(root / "restricted-override"),
            ],
            expected=6,
        )
        if "verified package profile" not in override.stderr:
            raise AssertionError(
                "caller-controlled --profile overrode an external package profile"
            )

        for collision_name, collision_backend in (
            ("manifest", args.manifest_collision_backend),
            ("diagnostics-ancestor", args.diagnostics_collision_backend),
            ("receipt-ancestor", args.receipt_collision_backend),
        ):
            collision_package = root / f"package-{collision_name}"
            make_package(
                collision_package,
                collision_backend,
                args.profile,
                args.projection_schema,
            )
            collision_output = root / f"output-{collision_name}"
            collision = run(
                [
                    str(args.neutrino_gen),
                    "--backend-package-dir",
                    str(collision_package),
                    str(args.source),
                    "--target=synthetic",
                    "--scenario",
                    str(args.scenario),
                    "-o",
                    str(collision_output),
                ],
                expected=4,
            )
            if "reserved core bundle path" not in collision.stderr:
                raise AssertionError(
                    f"backend metadata collision was not rejected: {collision_name}"
                )
            collision_manifest = json.loads(
                (collision_output / "manifest.json").read_text()
            )
            collision_diagnostics = json.loads(
                (collision_output / "diagnostics.json").read_text()
            )
            if collision_manifest["ok"] or collision_diagnostics["ok"]:
                raise AssertionError(
                    "core metadata did not record the collision failure"
                )
            if any(
                path.is_file()
                and path.read_bytes() == b"synthetic artifact\n"
                for path in collision_output.rglob("*")
            ):
                raise AssertionError(
                    "a reserved backend artifact was partially published"
                )

        output = root / "output"
        run(
            common
            + [
                str(args.source),
                "--target=synthetic",
                "--scenario",
                str(args.scenario),
                "-o",
                str(output),
            ]
        )
        if (output / "result.txt").read_text() != "synthetic artifact\n":
            raise AssertionError("external artifact was not published")
        manifest = json.loads((output / "manifest.json").read_text())
        diagnostics = json.loads((output / "diagnostics.json").read_text())
        if manifest["target"] != "synthetic" or not manifest["ok"]:
            raise AssertionError("external result manifest is invalid")
        if not diagnostics["ok"]:
            raise AssertionError("external result diagnostics are invalid")
        receipt_bytes = (output / "backend-dispatch-receipt.json").read_bytes()
        receipt = json.loads(receipt_bytes)
        receipt_digest = receipt.pop("receiptDigest")
        if receipt_digest != digest(canonical(receipt)):
            raise AssertionError("external dispatch receipt self-digest drifted")
        descriptor = json.loads((package / "backend-package.json").read_text())
        if (
            receipt["kind"] != "neutrino.backend-dispatch-receipt/1"
            or receipt["schemaVersion"] != 1
            or receipt["requestId"] != 1
            or receipt["targetIdentity"] != "synthetic"
            or receipt["targetProfileIdentity"] != "target.synthetic.v1"
            or receipt["packageManifestDigest"] != descriptor["manifestDigest"]
            or receipt["security"]
            != {
                "decision": "approved",
                "projectionDigest": receipt["projection"]["sha256"],
                "requestId": receipt["requestId"],
            }
            or receipt["artifacts"]
            != [
                {
                    "byteLen": len(b"synthetic artifact\n"),
                    "path": "result.txt",
                    "sha256": digest(b"synthetic artifact\n"),
                }
            ]
        ):
            raise AssertionError("external dispatch receipt identity binding drifted")

        mismatched_identity = run(
            common
            + [
                str(args.source),
                "--target=synthetic",
                "--scenario",
                str(args.scenario),
                "-o",
                str(root / "mismatched-startup-identity"),
            ],
            expected=4,
            extra_env={"NEUTRINO_SYNTHETIC_MODE": "manifest-mismatch"},
        )
        if (
            "E_PACKAGE_BINDING" not in mismatched_identity.stderr
            or "manifest digest" not in mismatched_identity.stderr
        ):
            raise AssertionError(
                "package-derived startup identity mismatch did not fail closed:\n"
                + mismatched_identity.stderr
            )

        alternate_package = root / "package-alternate"
        make_package(
            alternate_package,
            args.backend,
            args.profile,
            args.projection_schema,
            profile_marker="independent core identity probe",
        )
        alternate_output = root / "output-alternate"
        run(
            [
                str(args.neutrino_gen),
                "--backend-package-dir",
                str(alternate_package),
                str(args.source),
                "--target=synthetic",
                "--scenario",
                str(args.scenario),
                "-o",
                str(alternate_output),
            ]
        )
        alternate_receipt = json.loads(
            (alternate_output / "backend-dispatch-receipt.json").read_text()
        )
        if (
            alternate_receipt["packageManifestDigest"]
            == receipt["packageManifestDigest"]
            or alternate_receipt["coreIdentity"] != receipt["coreIdentity"]
        ):
            raise AssertionError(
                "core identity is not independent of package identity"
            )

        preexisting_output = root / "preexisting-receipt"
        preexisting_output.mkdir()
        receipt_path = preexisting_output / "backend-dispatch-receipt.json"
        receipt_path.write_text("pre-existing\n")
        publication_marker = root / "publication-invoked.marker"
        publication = run(
            common
            + [
                str(args.source),
                "--target=synthetic",
                "--scenario",
                str(args.scenario),
                "-o",
                str(preexisting_output),
            ],
            expected=2,
            extra_env={
                "NEUTRINO_SYNTHETIC_INVOCATION_MARKER": str(
                    publication_marker
                )
            },
        )
        if (
            not publication_marker.is_file()
            or (preexisting_output / "result.txt").exists()
            or receipt_path.read_text() != "pre-existing\n"
            or "backend-dispatch-receipt.json" not in publication.stderr
        ):
            raise AssertionError(
                "pre-existing receipt did not prevent unaudited publication:\n"
                f"marker={publication_marker.exists()} "
                f"artifact={(preexisting_output / 'result.txt').exists()} "
                f"receipt={receipt_path.read_text()!r}\n"
                f"stderr:\n{publication.stderr}"
            )

        insecure_output = root / "insecure-from-spec"
        insecure_marker = root / "insecure-invoked.marker"
        insecure = run(
            common
            + [
                str(args.insecure_spec),
                "--target=synthetic",
                "--from-spec",
                "-o",
                str(insecure_output),
            ],
            expected=5,
            extra_env={
                "NEUTRINO_SYNTHETIC_INVOCATION_MARKER": str(insecure_marker)
            },
        )
        if (
            insecure_marker.exists()
            or (insecure_output / "backend-dispatch-receipt.json").exists()
            or (insecure_output / "result.txt").exists()
            or "refusing to lower an insecure capability" not in insecure.stderr
        ):
            raise AssertionError(
                "insecure --from-spec input crossed the dispatch boundary:\n"
                f"marker={insecure_marker.exists()} "
                f"receipt={(insecure_output / 'backend-dispatch-receipt.json').exists()} "
                f"artifact={(insecure_output / 'result.txt').exists()}\n"
                f"stderr:\n{insecure.stderr}"
            )

        spec_output = root / "spec"
        run(
            common
            + [
                str(args.source),
                "--target=capability-spec",
                "-o",
                str(spec_output),
            ]
        )
        from_spec_output = root / "from-spec"
        run(
            common
            + [
                str(spec_output / "capability-spec.json"),
                "--target=synthetic",
                "--from-spec",
                "-o",
                str(from_spec_output),
            ]
        )
        if (from_spec_output / "result.txt").read_bytes() != (
            output / "result.txt"
        ).read_bytes():
            raise AssertionError("source and --from-spec external dispatch drifted")
        if (
            from_spec_output / "backend-dispatch-receipt.json"
        ).read_bytes() != receipt_bytes:
            raise AssertionError(
                "source and --from-spec external dispatch receipts drifted"
            )


if __name__ == "__main__":
    main()
