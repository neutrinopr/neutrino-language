#!/usr/bin/env python3
"""Verify neutrino-bundle consumes and preserves the verified target catalog."""

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


def make_package(root, backend, profile_path, schema_path, target):
    entry = root / "bin" / "backend"
    entry.parent.mkdir(parents=True)
    shutil.copy2(backend, entry)
    entry.chmod(0o500)
    entry_bytes = entry.read_bytes()
    profile = json.loads(profile_path.read_text())
    profile["target"] = target
    profile_identity = f"target.{target.replace('-', '_')}.v1"
    profile["profileId"] = profile_identity
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
    return descriptor


def run(command, expected=0, extra_env=None):
    environment = os.environ.copy()
    environment.pop("NEUTRINO_BACKEND_PACKAGE_PATH", None)
    if extra_env:
        environment.update(extra_env)
    completed = subprocess.run(
        [str(item) for item in command],
        text=True,
        capture_output=True,
        env=environment,
    )
    if completed.returncode != expected:
        raise AssertionError(
            f"command returned {completed.returncode}, expected {expected}:\n"
            f"{' '.join(map(str, command))}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def input_bundle(root, source, scenario, targets):
    root.mkdir()
    shutil.copy2(source, root / "source.neu")
    shutil.copy2(scenario, root / "scenario.json")
    (root / "target.json").write_text(json.dumps({"targets": targets}))


def package_arguments(packages):
    result = []
    for package in packages:
        result.extend(["--backend-package-dir", str(package)])
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--neutrino-bundle", required=True, type=Path)
    parser.add_argument("--neutrino-gen", required=True, type=Path)
    parser.add_argument("--backend", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--projection-schema", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--scenario", required=True, type=Path)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="neutrino-bundle-catalog-") as tmp:
        root = Path(tmp).resolve()

        # With no configured package, capabilities are exactly the core catalog.
        listed = run([args.neutrino_gen, "--list-targets"]).stdout.splitlines()
        capabilities = json.loads(
            run([args.neutrino_bundle, "--capabilities"]).stdout
        )
        generated = [
            row["name"].removeprefix("generate.")
            for row in capabilities["capabilities"]
            if row["name"].startswith("generate.")
        ]
        if generated != listed:
            raise AssertionError("bundle capabilities did not match the core catalog")
        if any(row["name"].startswith("test.") for row in capabilities["capabilities"]):
            raise AssertionError("core descriptor retained package-specific tests")

        synthetic = root / "synthetic"
        make_package(
            synthetic,
            args.backend,
            args.profile,
            args.projection_schema,
            "third-backend",
        )

        # Reversing two configured package directories must not affect catalog
        # identity or target order.
        alpha = root / "alpha"
        zeta = root / "zeta"
        make_package(
            alpha, args.backend, args.profile, args.projection_schema, "alpha"
        )
        make_package(
            zeta, args.backend, args.profile, args.projection_schema, "zeta"
        )
        forward = json.loads(
            run(
                [args.neutrino_bundle]
                + package_arguments([alpha, zeta])
                + ["--capabilities"]
            ).stdout
        )
        reverse = json.loads(
            run(
                [args.neutrino_bundle]
                + package_arguments([zeta, alpha])
                + ["--capabilities"]
            ).stdout
        )
        if forward != reverse:
            raise AssertionError("package order changed the merged catalog")
        external_names = [
            row["name"]
            for row in forward["capabilities"]
            if row["name"] in ("generate.alpha", "generate.zeta")
        ]
        if external_names != ["generate.alpha", "generate.zeta"]:
            raise AssertionError("external package targets are not deterministic")
        environment_catalog = json.loads(
            run(
                [args.neutrino_bundle, "--capabilities"],
                extra_env={
                    "NEUTRINO_BACKEND_PACKAGE_PATH": os.pathsep.join(
                        [str(zeta), str(alpha)]
                    )
                },
            ).stdout
        )
        if environment_catalog != forward:
            raise AssertionError(
                "environment and command-line package resolution diverged"
            )
        environment_targets = run(
            [args.neutrino_gen, "--list-targets"],
            extra_env={
                "NEUTRINO_BACKEND_PACKAGE_PATH": os.pathsep.join(
                    [str(zeta), str(alpha)]
                )
            },
        ).stdout.splitlines()
        if environment_targets[-2:] != ["alpha", "zeta"]:
            raise AssertionError(
                "neutrino-gen did not share environment package resolution"
            )

        installed = root / "installed"
        installed_bundle = installed / "bin" / "neutrino-bundle"
        installed_gen = installed / "bin" / "neutrino-gen"
        installed_bundle.parent.mkdir(parents=True)
        shutil.copy2(args.neutrino_bundle, installed_bundle)
        shutil.copy2(args.neutrino_gen, installed_gen)
        installed_bundle.chmod(0o700)
        installed_gen.chmod(0o700)
        default_root = installed / "lib" / "neutrino" / "backend-packages"
        shutil.copytree(alpha, default_root / "alpha")
        shutil.copytree(zeta, default_root / "zeta")
        default_catalog = json.loads(
            run([installed_bundle, "--capabilities"]).stdout
        )
        if default_catalog != forward:
            raise AssertionError(
                "install-relative default package resolution diverged"
            )
        if run([installed_gen, "--list-targets"]).stdout.splitlines()[-2:] != [
            "alpha",
            "zeta",
        ]:
            raise AssertionError(
                "neutrino-gen did not share default package resolution"
            )

        bundle_input = root / "input"
        input_bundle(
            bundle_input, args.source, args.scenario, ["third-backend"]
        )
        output = root / "output"
        marker = root / "child-arguments.txt"
        wrapper = root / "neutrino-gen-wrapper"
        wrapper.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$@\" > '{marker}'\n"
            f"exec '{args.neutrino_gen}' \"$@\"\n"
        )
        wrapper.chmod(0o700)
        child_environment = {
            "NEUTRINO_GEN": str(wrapper),
            "NEUTRINO_SYNTHETIC_PROFILE_IDENTITY": "target.third_backend.v1",
            "NEUTRINO_SYNTHETIC_TARGET_IDENTITY": "third-backend",
        }
        run(
            [args.neutrino_bundle]
            + package_arguments([synthetic])
            + [bundle_input, "-o", output],
            extra_env=child_environment,
        )
        forwarded = marker.read_text().splitlines()
        expected_pair = ["--backend-package-dir", str(synthetic)]
        if not any(
            forwarded[index : index + 2] == expected_pair
            for index in range(len(forwarded) - 1)
        ):
            raise AssertionError("bundle did not forward the resolved package set")

        bundle_receipt = json.loads(
            (output / "third-backend" / "backend-dispatch-receipt.json").read_text()
        )
        bundle_json = json.loads((output / "bundle.json").read_text())
        result = bundle_json["results"][0]
        binding = result["catalogEntry"]
        if (
            binding["targetIdentity"] != bundle_receipt["targetIdentity"]
            or binding["targetProfileIdentity"]
            != bundle_receipt["targetProfileIdentity"]
            or binding["packageManifestDigest"]
            != bundle_receipt["packageManifestDigest"]
            or bundle_json["identities"]["core"] != bundle_receipt["coreIdentity"]
            or bundle_json["identities"]["catalog"]
            != binding["catalogIdentity"]
        ):
            raise AssertionError("bundle identity does not bind the dispatch receipt")

        direct = root / "direct"
        run(
            [args.neutrino_gen]
            + package_arguments([synthetic])
            + [
                args.source,
                "--target=third-backend",
                "--scenario",
                args.scenario,
                "-o",
                direct,
            ],
            extra_env={
                "NEUTRINO_SYNTHETIC_PROFILE_IDENTITY": "target.third_backend.v1",
                "NEUTRINO_SYNTHETIC_TARGET_IDENTITY": "third-backend",
            },
        )
        direct_receipt = json.loads(
            (direct / "backend-dispatch-receipt.json").read_text()
        )
        for field in (
            "coreIdentity",
            "targetIdentity",
            "targetProfileIdentity",
            "packageManifestDigest",
        ):
            if direct_receipt[field] != bundle_receipt[field]:
                raise AssertionError(
                    f"direct and bundle-driven receipt disagree on {field}"
                )

        duplicate = root / "duplicate"
        make_package(
            duplicate,
            args.backend,
            args.profile,
            args.projection_schema,
            "third-backend",
        )
        duplicate_descriptor = json.loads(
            (duplicate / "backend-package.json").read_text()
        )
        duplicate_descriptor["profileSummary"]["semanticProfile"]["limits"][
            "maxComputes"
        ] += 1
        duplicate_descriptor.pop("manifestDigest")
        duplicate_descriptor["manifestDigest"] = digest(
            canonical(duplicate_descriptor)
        )
        (duplicate / "backend-package.json").write_bytes(
            canonical(duplicate_descriptor)
        )
        duplicate_output = root / "duplicate-output"
        duplicate_result = run(
            [args.neutrino_bundle]
            + package_arguments([synthetic, duplicate])
            + [bundle_input, "-o", duplicate_output],
            expected=2,
        )
        if "E_TARGET_DUPLICATE" not in duplicate_result.stderr:
            raise AssertionError("duplicate target did not fail closed")
        if duplicate_output.exists():
            raise AssertionError("duplicate target wrote an output tree")

        tampered = root / "tampered"
        make_package(
            tampered,
            args.backend,
            args.profile,
            args.projection_schema,
            "tampered",
        )
        tampered_descriptor = json.loads(
            (tampered / "backend-package.json").read_text()
        )
        tampered_descriptor["licenseIdentity"] = "Apache-2.0"
        (tampered / "backend-package.json").write_bytes(
            canonical(tampered_descriptor)
        )
        tampered_result = run(
            [args.neutrino_bundle]
            + package_arguments([tampered])
            + ["--capabilities"],
            expected=2,
        )
        if "E_PACKAGE_MANIFEST_DIGEST" not in tampered_result.stderr:
            raise AssertionError("tampered descriptor did not fail closed")

        missing_output = root / "missing-output"
        missing_result = run(
            [args.neutrino_bundle]
            + package_arguments([root / "vanished"])
            + [bundle_input, "-o", missing_output],
            expected=2,
        )
        if "cannot load target catalog" not in missing_result.stderr:
            raise AssertionError("vanished package did not fail discovery")
        if missing_output.exists():
            raise AssertionError("vanished package wrote an output tree")

        unknown_input = root / "unknown-input"
        input_bundle(unknown_input, args.source, args.scenario, ["unknown"])
        unknown_output = root / "unknown-output"
        unknown = run(
            [args.neutrino_bundle, unknown_input, "-o", unknown_output],
            expected=2,
        )
        if "absent from verified catalog" not in unknown.stderr:
            raise AssertionError("unknown target did not fail catalog admission")
        if unknown_output.exists():
            raise AssertionError("unknown target wrote an output tree")

        # Replace a package after the parent catalog is verified but before the
        # child starts. The child's expected-catalog handshake must refuse
        # before executing the replacement entry or emitting an artifact.
        race_current = root / "race-current"
        make_package(
            race_current,
            args.backend,
            args.profile,
            args.projection_schema,
            "race-target",
        )
        executed = root / "replacement-entry-executed"
        replacement_entry = root / "replacement-entry"
        replacement_entry.write_text(
            "#!/bin/sh\n"
            f"touch '{executed}'\n"
            "exit 91\n"
        )
        replacement_entry.chmod(0o700)
        race_replacement = root / "race-replacement"
        make_package(
            race_replacement,
            replacement_entry,
            args.profile,
            args.projection_schema,
            "race-target",
        )
        race_input = root / "race-input"
        input_bundle(race_input, args.source, args.scenario, ["race-target"])
        race_output = root / "race-output"
        race_wrapper = root / "race-neutrino-gen"
        race_wrapper.write_text(
            "#!/usr/bin/env python3\n"
            "import os\n"
            "from pathlib import Path\n"
            "import shutil\n"
            "import sys\n"
            f"current = Path({str(race_current)!r})\n"
            f"replacement = Path({str(race_replacement)!r})\n"
            "shutil.rmtree(current)\n"
            "replacement.rename(current)\n"
            f"os.execv({str(args.neutrino_gen)!r}, "
            f"[{str(args.neutrino_gen)!r}] + sys.argv[1:])\n"
        )
        race_wrapper.chmod(0o700)
        race_result = run(
            [args.neutrino_bundle]
            + package_arguments([race_current])
            + [race_input, "-o", race_output],
            expected=1,
            extra_env={"NEUTRINO_GEN": str(race_wrapper)},
        )
        if "E_CHILD_CATALOG_IDENTITY" not in race_result.stderr:
            raise AssertionError("replacement race did not fail the child handshake")
        if executed.exists():
            raise AssertionError("replacement package entry executed")
        race_target_output = race_output / "race-target"
        if any(
            path.name not in ("manifest.json", "diagnostics.json")
            for path in race_target_output.iterdir()
        ):
            raise AssertionError("replacement race emitted a backend artifact")

        # A built-in result also needs child evidence. Mutate the frozen
        # expected core identity at the process boundary and prove the child
        # refuses before producing a built-in artifact.
        builtin_input = root / "builtin-input"
        input_bundle(
            builtin_input, args.source, args.scenario, ["capability-spec"]
        )
        builtin_output = root / "builtin-output"
        mismatch_wrapper = root / "mismatched-neutrino-gen"
        mismatch_wrapper.write_text(
            "#!/usr/bin/env python3\n"
            "import os\n"
            "import sys\n"
            "arguments = [\n"
            "    '--expected-core-identity=core:mismatched'\n"
            "    if argument.startswith('--expected-core-identity=')\n"
            "    else argument\n"
            "    for argument in sys.argv[1:]\n"
            "]\n"
            f"os.execv({str(args.neutrino_gen)!r}, "
            f"[{str(args.neutrino_gen)!r}] + arguments)\n"
        )
        mismatch_wrapper.chmod(0o700)
        mismatch_result = run(
            [args.neutrino_bundle, builtin_input, "-o", builtin_output],
            expected=1,
            extra_env={"NEUTRINO_GEN": str(mismatch_wrapper)},
        )
        if "E_CHILD_CORE_IDENTITY" not in mismatch_result.stderr:
            raise AssertionError("built-in child core mismatch did not fail closed")
        builtin_target_output = builtin_output / "capability-spec"
        if any(
            path.name not in ("manifest.json", "diagnostics.json")
            for path in builtin_target_output.iterdir()
        ):
            raise AssertionError("mismatched built-in child emitted an artifact")

    print(
        "bundle catalog: core, arbitrary target, ordering, identity handshake, "
        "failure modes, forwarding, and receipt binding pass"
    )


if __name__ == "__main__":
    main()
