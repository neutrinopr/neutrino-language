#!/usr/bin/env python3
"""Integration proof for descriptor-driven neutrino-equiv backends."""

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
        command, text=True, capture_output=True, env=environment
    )
    if completed.returncode != expected:
        raise AssertionError(
            f"command returned {completed.returncode}, expected {expected}:\n"
            f"{' '.join(map(str, command))}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def make_package(
    root, backend, profile_path, schema_path, target, remove_feature=None
):
    entry_name = f"backend-{target}"
    entry = root / "bin" / entry_name
    entry.parent.mkdir(parents=True)
    shutil.copy2(backend, entry)
    entry.chmod(0o500)
    entry_bytes = entry.read_bytes()

    profile = json.loads(profile_path.read_text())
    profile["target"] = target
    profile_identity = f"target.{target.replace('-', '_')}.v1"
    profile["profileId"] = profile_identity
    if remove_feature is not None:
        profile["semanticProfile"]["features"].remove(remove_feature)
    projection_schema = json.loads(schema_path.read_text())["properties"][
        "schemaVersion"
    ]["const"]
    descriptor = {
        "apiVersion": 1,
        "capabilities": ["emit", "stream"],
        "closure": [
            {
                "byteLen": len(entry_bytes),
                "path": f"bin/{entry_name}",
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
        "entry": f"bin/{entry_name}",
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
    return descriptor, entry


def configuration(descriptor, artifact_bytes, mode="success"):
    return {
        "NEUTRINO_SYNTHETIC_ARTIFACT_BYTES": artifact_bytes,
        "NEUTRINO_SYNTHETIC_MODE": mode,
        "NEUTRINO_SYNTHETIC_TARGET_IDENTITY": descriptor["targetIdentity"],
    }


def invoke(equiv, source, scenario, report, packages, targets=()):
    command = [str(equiv)]
    for package in packages:
        command.extend(["--backend-package-dir", str(package)])
    for target in targets:
        command.extend(["--target", target])
    command.extend(
        [
            "--scenario",
            str(scenario),
            str(source),
            "--report",
            str(report),
        ]
    )
    return command


def expect_catalog_failure(command, code):
    failed = run(command, expected=2)
    if code not in failed.stderr:
        raise AssertionError(
            f"missing stable catalog diagnostic {code}:\n{failed.stderr}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--neutrino-equiv", required=True, type=Path)
    parser.add_argument("--backend", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--projection-schema", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--registry", required=True, type=Path)
    args = parser.parse_args()

    third_target = "synthetic-third"
    if third_target in args.registry.read_text():
        raise AssertionError("synthetic third target entered the core registry")
    artifact_bytes = args.source.read_text()

    with tempfile.TemporaryDirectory(prefix="neutrino-equiv-catalog-") as tmp:
        root = Path(tmp).resolve()
        alpha = root / "alpha"
        zeta = root / "zeta"
        alpha_descriptor, alpha_entry = make_package(
            alpha,
            args.backend,
            args.profile,
            args.projection_schema,
            third_target,
        )
        zeta_descriptor, zeta_entry = make_package(
            zeta,
            args.backend,
            args.profile,
            args.projection_schema,
            "zeta-backend",
            remove_feature="effect:credit",
        )
        alpha_environment = configuration(alpha_descriptor, artifact_bytes)
        alpha_environment["SOURCE_DATE_EPOCH"] = "1700000000"

        empty_report = root / "empty-report"
        empty = run(
            invoke(
                args.neutrino_equiv,
                args.source,
                args.scenario,
                empty_report,
                [],
            ),
            expected=2,
            extra_env={"NEUTRINO_BACKEND_PACKAGE_PATH": ""},
        )
        if (
            "no verified external backend package" not in empty.stderr
            or json.loads((empty_report / "equivalence.json").read_text())[
                "ok"
            ]
        ):
            raise AssertionError("empty backend catalog did not fail closed")

        one_report = root / "one-report"
        run(
            invoke(
                args.neutrino_equiv,
                args.source,
                args.scenario,
                one_report,
                [alpha],
                [third_target],
            ),
            extra_env=alpha_environment,
        )
        one = json.loads((one_report / "equivalence.json").read_text())
        names = [entry["name"] for entry in one["backends"]]
        if names != ["reference", third_target]:
            raise AssertionError(f"third backend was not catalog-driven: {names}")
        external = one["backends"][1]
        if (
            external["status"] != "pass"
            or not external["dispatchReceiptDigest"].startswith("sha256:")
            or len(external["artifacts"]) != 1
            or one["specStructural"] != [
                {"missing": [], "name": third_target, "status": "pass"}
            ]
        ):
            raise AssertionError("verified result/receipt was not structurally used")
        repeat_report = root / "repeat-report"
        run(
            invoke(
                args.neutrino_equiv,
                args.source,
                args.scenario,
                repeat_report,
                [alpha],
                [third_target],
            ),
            extra_env=alpha_environment,
        )
        if (one_report / "equivalence.json").read_bytes() != (
            repeat_report / "equivalence.json"
        ).read_bytes():
            raise AssertionError("single-package equivalence report is not deterministic")

        two_report = root / "two-report"
        run(
            invoke(
                args.neutrino_equiv,
                args.source,
                args.scenario,
                two_report,
                [zeta, alpha],
            )
            + ["--allow-skips"],
            extra_env=alpha_environment,
        )
        two = json.loads((two_report / "equivalence.json").read_text())
        if [entry["name"] for entry in two["backends"]] != [
            "reference",
            third_target,
            "zeta-backend",
        ]:
            raise AssertionError("multi-package execution order is not deterministic")
        if two["backends"][2]["status"] != "skip":
            raise AssertionError("incompatible package was invoked instead of refused")

        refused_report = root / "refused-report"
        refused_environment = configuration(zeta_descriptor, artifact_bytes)
        refused_environment["SOURCE_DATE_EPOCH"] = "1700000000"
        run(
            invoke(
                args.neutrino_equiv,
                args.source,
                args.scenario,
                refused_report,
                [zeta],
            )
            + ["--allow-skips"],
            expected=1,
            extra_env=refused_environment,
        )
        refused = json.loads((refused_report / "equivalence.json").read_text())
        refused_diagnostics = json.loads(
            (refused_report / "diagnostics.json").read_text()
        )
        if (
            refused["ok"]
            or refused["backends"][1]["status"] != "skip"
            or not any(
                diagnostic["code"] == "equivalence.backend_failed"
                and "no compatible verified package backend" in diagnostic["message"]
                for diagnostic in refused_diagnostics["diagnostics"]
            )
        ):
            raise AssertionError(
                "--allow-skips accepted an all-refused backend catalog"
            )

        disappeared_report = root / "disappeared-report"
        disappeared_environment = dict(alpha_environment)
        disappeared_environment["NEUTRINO_SYNTHETIC_REMOVE_PATH_ON_START"] = str(
            alpha_entry
        )
        run(
            invoke(
                args.neutrino_equiv,
                args.source,
                args.scenario,
                disappeared_report,
                [alpha],
            ),
            extra_env=disappeared_environment,
        )
        disappeared = json.loads(
            (disappeared_report / "equivalence.json").read_text()
        )
        if not disappeared["ok"]:
            raise AssertionError(
                "verified package handle did not survive entry disappearance"
            )

        missing = root / "missing"
        expect_catalog_failure(
            invoke(
                args.neutrino_equiv,
                args.source,
                args.scenario,
                root / "missing-report",
                [missing],
            ),
            "E_PACKAGE",
        )

        duplicate_a = root / "duplicate-a"
        duplicate_b = root / "duplicate-b"
        make_package(
            duplicate_a,
            args.backend,
            args.profile,
            args.projection_schema,
            "duplicate",
        )
        make_package(
            duplicate_b,
            args.backend,
            args.profile,
            args.projection_schema,
            "duplicate",
            remove_feature="effect:credit",
        )
        expect_catalog_failure(
            invoke(
                args.neutrino_equiv,
                args.source,
                args.scenario,
                root / "duplicate-report",
                [duplicate_a, duplicate_b],
            ),
            "E_TARGET_DUPLICATE",
        )

        tampered = root / "tampered"
        make_package(
            tampered,
            args.backend,
            args.profile,
            args.projection_schema,
            "tampered",
        )
        tampered_entry = tampered / "bin" / "backend-tampered"
        tampered_entry.chmod(0o700)
        with tampered_entry.open("ab") as stream:
            stream.write(b"tamper")
        expect_catalog_failure(
            invoke(
                args.neutrino_equiv,
                args.source,
                args.scenario,
                root / "tampered-report",
                [tampered],
            ),
            "E_PACKAGE",
        )

        incompatible = root / "incompatible"
        incompatible_descriptor, _ = make_package(
            incompatible,
            args.backend,
            args.profile,
            args.projection_schema,
            "incompatible",
        )
        incompatible_descriptor["compatibilityBounds"]["coreProtocol"] = {
            "max": {"major": 2, "minor": 0},
            "min": {"major": 2, "minor": 0},
        }
        incompatible_descriptor.pop("manifestDigest")
        incompatible_descriptor["manifestDigest"] = digest(
            canonical(incompatible_descriptor)
        )
        (incompatible / "backend-package.json").write_bytes(
            canonical(incompatible_descriptor)
        )
        expect_catalog_failure(
            invoke(
                args.neutrino_equiv,
                args.source,
                args.scenario,
                root / "incompatible-report",
                [incompatible],
            ),
            "E_VERSION",
        )

        missing_entry = root / "missing-entry"
        _, missing_entry_path = make_package(
            missing_entry,
            args.backend,
            args.profile,
            args.projection_schema,
            "missing-entry",
        )
        missing_entry_path.unlink()
        expect_catalog_failure(
            invoke(
                args.neutrino_equiv,
                args.source,
                args.scenario,
                root / "missing-entry-report",
                [missing_entry],
            ),
            "E_PACKAGE",
        )

        mismatch = root / "mismatch"
        mismatch_descriptor, _ = make_package(
            mismatch,
            args.backend,
            args.profile,
            args.projection_schema,
            "receipt-mismatch",
        )
        mismatch_report = root / "mismatch-report"
        mismatch_result = run(
            invoke(
                args.neutrino_equiv,
                args.source,
                args.scenario,
                mismatch_report,
                [mismatch],
            ),
            extra_env=configuration(
                mismatch_descriptor, artifact_bytes, mode="request-mismatch"
            ),
            expected=1,
        )
        mismatch_json = json.loads(
            (mismatch_report / "equivalence.json").read_text()
        )
        backend = mismatch_json["backends"][1]
        if (
            backend["status"] != "fail"
            or backend["stage"] != "invoke"
            or "request" not in (backend["detail"] + mismatch_result.stderr)
        ):
            raise AssertionError("request/receipt mismatch did not fail closed")


if __name__ == "__main__":
    main()
