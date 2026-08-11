#!/usr/bin/env python3
"""Emit the M7 backend-free core release receipt ().

The receipt carries the identity that cannot live in a tracked file. BuildInfo.h
bakes the source commit and platform triple into the installed binaries, so a
digest committed in commit C would have to be the digest of a binary built at C
-- a strict fixed point. This producer runs after the final commit is built, from
the same staged install that is published, which is what makes the values
meaningful. See docs/process/M7_CORE_RELEASE_RECEIPT.md.

The receipt is only evidence of provenance when it reaches the consumer
independently of the prefix it describes, or when its own identity is pinned
externally. This producer emits it; delivery is the release flow's obligation and
admission is the consumer's ().
"""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


_GATES = Path(__file__).resolve().parents[1] / "gates"
if str(_GATES) not in sys.path:
    sys.path.insert(0, str(_GATES))

# Importing from the source tree must not deposit __pycache__ into it: the core
# export closure treats any undeclared file under the tree as unreviewed, so a
# stray .pyc turns a release-tooling import into a gate failure.
sys.dont_write_bytecode = True

# Reuse the gate's helpers rather than reimplementing them: the manifest loader
# already enforces the shape schema, so producer and gate cannot drift apart in
# what they consider a valid installed export.
from check_core_only_export import (  # noqa: E402
    INSTALLED_EXPORT_CANONICAL_PATH,
    CheckFailure,
    canonical,
    digest_bytes,
    file_identity,
    inside,
    load_installed_export,
    validate_schema_instance,
)


RECEIPT_KIND = "neutrino.m7-core-release-receipt/1"
RECEIPT_SCHEMA = "docs/schemas/m7-core-release-receipt.schema.json"
INSTALLED_EXPORT = "docs/m7-core-installed-export.json"
BUILD_INFO = "include/Neutrino/BuildInfo.h"


def git(source_root, *args):
    result = subprocess.run(
        ["git", "-C", str(source_root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise CheckFailure(
            "core_receipt.command",
            f"git {' '.join(args)}: {(result.stderr or '').strip()}",
        )
    return result.stdout.strip()


def require_clean_tree(source_root):
    if git(source_root, "status", "--porcelain", "--untracked-files=no"):
        raise CheckFailure(
            "core_receipt.dirty_source",
            "tracked source changes are not bound by the source commit",
        )


def read_build_identity(build_dir):
    """The commit and target the configured build actually baked into the binaries."""
    header = Path(build_dir) / BUILD_INFO
    try:
        text = header.read_text(encoding="utf-8")
    except OSError as exc:
        raise CheckFailure("core_receipt.build_identity", str(exc)) from exc
    found = {}
    for name in ("kGitSha", "kBuildTarget"):
        match = re.search(rf'{name}\s*=\s*"([^"]*)"', text)
        if not match:
            raise CheckFailure("core_receipt.build_identity", f"{name} not declared")
        found[name] = match.group(1)
    if found["kGitSha"] == "unknown" or not found["kBuildTarget"]:
        raise CheckFailure(
            "core_receipt.build_identity", "build identity is not resolved"
        )
    return found["kGitSha"], found["kBuildTarget"]


def require_fresh_build(source_root, build_dir, source_commit):
    """Refuse to describe binaries that were not built from this commit.

    BuildInfo.h is configured at cmake time, so a build predating the final
    commit still links the older identity. Emitting a receipt then would attest
    to bytes the named commit never produced -- the exact failure the release-time
    production point exists to prevent.
    """
    built_sha, build_target = read_build_identity(build_dir)
    if not source_commit.startswith(built_sha):
        raise CheckFailure(
            "core_receipt.stale_build",
            f"configured build identity {built_sha} is not commit {source_commit[:12]}"
            " -- reconfigure and rebuild before releasing",
        )
    return build_target


def stage_core_install(build_dir, stage):
    if stage.exists():
        shutil.rmtree(stage)
    result = subprocess.run(
        [
            "cmake",
            "--install",
            str(build_dir),
            "--prefix",
            str(stage),
            "--component",
            "NeutrinoCore",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise CheckFailure(
            "core_receipt.install",
            (result.stderr or result.stdout or "").strip(),
        )
    return stage


def runtime_rows(stage, manifest):
    """One {path, sha256, mode} row per declared runtime artifact, sorted by path.

    Coverage is a bijection against the shape manifest: a record with no installed
    file, an installed runtime file with no record, and a duplicate path are all
    refusals. A receipt that silently omitted an artifact would let that artifact
    escape admission entirely.
    """
    declared = list(manifest["runtimeArtifacts"])
    if len(declared) != len(set(declared)):
        raise CheckFailure("core_receipt.duplicate_artifact", "duplicate declared path")

    installed = sorted(
        path.relative_to(stage).as_posix()
        for path in (stage / "bin").rglob("*")
        if path.is_file()
    )
    missing = sorted(set(declared) - set(installed))
    extra = sorted(set(installed) - set(declared))
    if missing or extra:
        raise CheckFailure(
            "core_receipt.artifact_closure",
            f"missing={missing[:4]} extra={extra[:4]}",
        )

    rows = []
    for relative in sorted(declared):
        identity = file_identity(stage / relative)
        rows.append(
            {
                "path": relative,
                "sha256": identity["sha256"],
                "mode": identity["mode"],
            }
        )
    return rows


def seal(receipt):
    body = {key: value for key, value in receipt.items() if key != "receiptDigest"}
    receipt["receiptDigest"] = "sha256:" + digest_bytes(canonical(body))
    return receipt


def load_receipt_schema(source_root):
    path = Path(source_root) / RECEIPT_SCHEMA
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckFailure("core_receipt.schema", str(exc)) from exc


def build_receipt(source_root, build_dir, stage):
    source_root = Path(source_root)
    build_dir = Path(build_dir)
    require_clean_tree(source_root)
    source_commit = git(source_root, "rev-parse", "HEAD")
    build_target = require_fresh_build(source_root, build_dir, source_commit)

    manifest_path = source_root / INSTALLED_EXPORT
    manifest = load_installed_export(manifest_path)

    stage_core_install(build_dir, stage)
    # installedExportSha256 is taken over the source manifest, but the prefix now
    # ships its own copy. If the two could differ, the receipt would authenticate
    # a shape contract the consumer is not holding, so refuse rather than emit a
    # digest that describes the wrong bytes.
    installed_manifest = stage / INSTALLED_EXPORT_CANONICAL_PATH
    if not installed_manifest.is_file():
        raise CheckFailure(
            "core_receipt.installed_export_absent",
            f"{INSTALLED_EXPORT_CANONICAL_PATH} is not present in the staged prefix",
        )
    if installed_manifest.read_bytes() != manifest_path.read_bytes():
        raise CheckFailure(
            "core_receipt.installed_export_drift",
            f"{INSTALLED_EXPORT_CANONICAL_PATH} differs from the manifest that "
            "installedExportSha256 is computed over",
        )
    receipt = {
        "kind": RECEIPT_KIND,
        "schemaVersion": 1,
        "sourceCommit": source_commit,
        "buildTarget": build_target,
        "installedExportSha256": file_identity(manifest_path)["sha256"],
        "runtimeArtifacts": runtime_rows(stage, manifest),
    }
    seal(receipt)
    validate_schema_instance(receipt, load_receipt_schema(source_root))
    return receipt


def require_out_of_band(output, stage):
    """Mode A: the receipt must not be written into the prefix it describes.

    A record that travels inside its own prefix proves only self-consistency --
    whoever can replace the artifacts can replace the record beside them. Writing
    the receipt there would recreate exactly the circularity the contract exists
    to remove, so the producer refuses rather than emitting something that reads
    like provenance but is not. Paths are resolved first, so a symlink pointing
    into the prefix is refused too.

    Mode B (a receipt carried in-prefix whose identity is pinned externally) is a
    consumer-side arrangement and is not something this producer can assert.
    """
    output = Path(output)
    if inside(output, Path(stage)):
        raise CheckFailure(
            "core_receipt.prefix_local_output",
            f"{output} resolves inside the installed prefix {stage} -- deliver the"
            " receipt out of band (see M7_CORE_RELEASE_RECEIPT.md section 3)",
        )
    return output


def emit(source_root, build_dir, output, stage=None):
    with tempfile.TemporaryDirectory(prefix="neutrino-core-receipt-") as raw:
        target = Path(stage) if stage else Path(raw) / "install"
        target.parent.mkdir(parents=True, exist_ok=True)
        destination = require_out_of_band(output, target)
        receipt = build_receipt(source_root, build_dir, target)
        # Written while the staged prefix still exists, so the refusal above is
        # what keeps the two apart rather than an accident of cleanup order.
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(canonical(receipt) + b"\n")
    return receipt


def expect_failure(identity, thunk):
    try:
        thunk()
    except CheckFailure as exc:
        if exc.identity != identity:
            raise CheckFailure(
                "core_receipt.selftest", f"expected {identity} got {exc.identity}"
            ) from exc
        return
    raise CheckFailure("core_receipt.selftest", f"{identity} mutation survived")


def selftest():
    """Probe the refusals the contract depends on, against a synthetic prefix."""
    source_root = Path(__file__).resolve().parents[2]
    schema = load_receipt_schema(source_root)
    manifest = load_installed_export(source_root / INSTALLED_EXPORT)

    with tempfile.TemporaryDirectory(prefix="neutrino-core-receipt-selftest-") as raw:
        stage = Path(raw) / "install"
        (stage / "bin").mkdir(parents=True)
        for relative in manifest["runtimeArtifacts"]:
            target = stage / relative
            target.write_bytes(b"artifact:" + relative.encode("utf-8"))
            target.chmod(0o755)

        def build(stage=stage):
            return seal(
                {
                    "kind": RECEIPT_KIND,
                    "schemaVersion": 1,
                    "sourceCommit": "0" * 40,
                    "buildTarget": "Darwin-x86_64",
                    "installedExportSha256": "1" * 64,
                    "runtimeArtifacts": runtime_rows(stage, manifest),
                }
            )

        rows = runtime_rows(stage, manifest)
        receipt = build()
        validate_schema_instance(receipt, schema)

        # Determinism: the same installed bytes must yield a byte-identical
        # receipt. A receipt that varied run to run could not be pinned
        # externally, which is what Mode B of the delivery contract requires.
        if canonical(build()) != canonical(receipt):
            raise CheckFailure(
                "core_receipt.selftest", "emission is not deterministic"
            )

        # Ordering is by path regardless of filesystem enumeration order, so the
        # canonical form is stable across machines.
        if [row["path"] for row in rows] != sorted(row["path"] for row in rows):
            raise CheckFailure(
                "core_receipt.selftest", "runtimeArtifacts are not path-ordered"
            )

        # The seal must actually bind the body: a tampered digest is detectable.
        tampered = json.loads(json.dumps(receipt))
        tampered["runtimeArtifacts"][0]["sha256"] = "2" * 64
        body = {k: v for k, v in tampered.items() if k != "receiptDigest"}
        if tampered["receiptDigest"] == "sha256:" + digest_bytes(canonical(body)):
            raise CheckFailure(
                "core_receipt.selftest", "receiptDigest does not bind runtimeArtifacts"
            )

        # An artifact present on disk but absent from the receipt would escape
        # admission entirely, so closure is enforced in both directions.
        rogue = stage / "bin" / "neutrino-rogue"
        rogue.write_bytes(b"rogue")
        rogue.chmod(0o755)
        expect_failure(
            "core_receipt.artifact_closure", lambda: runtime_rows(stage, manifest)
        )
        rogue.unlink()

        absent = stage / manifest["runtimeArtifacts"][0]
        absent.unlink()
        expect_failure(
            "core_receipt.artifact_closure", lambda: runtime_rows(stage, manifest)
        )
        absent.write_bytes(b"restored")
        absent.chmod(0o755)

        # Identity must move with the bytes and with the mode, or a swapped
        # artifact would still satisfy the receipt.
        before = runtime_rows(stage, manifest)[0]
        absent.write_bytes(b"different bytes")
        after = runtime_rows(stage, manifest)[0]
        if before["sha256"] == after["sha256"]:
            raise CheckFailure(
                "core_receipt.selftest", "sha256 does not track artifact bytes"
            )
        absent.chmod(0o700)
        if runtime_rows(stage, manifest)[0]["mode"] == after["mode"]:
            raise CheckFailure(
                "core_receipt.selftest", "mode does not track artifact mode"
            )
        absent.chmod(0o755)

        # A symlinked artifact is not a regular installed file.
        absent.unlink()
        absent.symlink_to(stage / "bin" / manifest["runtimeArtifacts"][1].split("/")[1])
        expect_failure("core_export.non_regular", lambda: runtime_rows(stage, manifest))
        absent.unlink()
        absent.write_bytes(b"restored")
        absent.chmod(0o755)

        # Schema refusals: identity fields are mandatory and shape-checked.
        for mutate, where in (
            (lambda r: r.update({"sourceCommit": "abc"}), "short sourceCommit"),
            (lambda r: r.update({"buildTarget": ""}), "empty buildTarget"),
            (lambda r: r["runtimeArtifacts"][0].pop("mode"), "missing mode"),
            (
                lambda r: r["runtimeArtifacts"][0].update({"sha256": "sha256:" + "0" * 64}),
                "prefixed sha256",
            ),
            (
                lambda r: r["runtimeArtifacts"].append(r["runtimeArtifacts"][0]),
                "duplicate row",
            ),
        ):
            broken = json.loads(json.dumps(receipt))
            mutate(broken)
            expect_failure(
                "core_export.json_schema",
                lambda broken=broken: validate_schema_instance(broken, schema),
            )

        # Mode A: the receipt must not be written into the prefix it describes,
        # and a symlink is not a way around that.
        expect_failure(
            "core_receipt.prefix_local_output",
            lambda: require_out_of_band(stage / "receipt.json", stage),
        )
        expect_failure(
            "core_receipt.prefix_local_output",
            lambda: require_out_of_band(stage / "bin" / "receipt.json", stage),
        )
        outside = Path(raw) / "delivery"
        outside.mkdir()
        bridge = outside / "sneaky.json"
        bridge.symlink_to(stage / "receipt.json")
        expect_failure(
            "core_receipt.prefix_local_output",
            lambda: require_out_of_band(bridge, stage),
        )
        bridge.unlink()
        # ... and a genuine out-of-band destination is accepted, so the probe is
        # not simply refusing everything.
        if require_out_of_band(outside / "receipt.json", stage) != (
            outside / "receipt.json"
        ):
            raise CheckFailure(
                "core_receipt.selftest", "out-of-band destination was not accepted"
            )

        # A build that predates the commit must be refused rather than described.
        build_dir = Path(raw) / "build"
        (build_dir / "include" / "Neutrino").mkdir(parents=True)
        header = build_dir / BUILD_INFO
        header.write_text(
            'inline constexpr const char *kGitSha = "0123456789ab";\n'
            'inline constexpr const char *kBuildTarget = "Darwin-x86_64";\n',
            encoding="utf-8",
        )
        expect_failure(
            "core_receipt.stale_build",
            lambda: require_fresh_build(source_root, build_dir, "f" * 40),
        )
        # ... and the matching case is accepted, so the probe is not vacuous.
        if require_fresh_build(
            source_root, build_dir, "0123456789ab" + "0" * 28
        ) != "Darwin-x86_64":
            raise CheckFailure("core_receipt.selftest", "fresh build was not accepted")

        header.write_text(
            'inline constexpr const char *kGitSha = "unknown";\n'
            'inline constexpr const char *kBuildTarget = "Darwin-x86_64";\n',
            encoding="utf-8",
        )
        expect_failure(
            "core_receipt.build_identity",
            lambda: read_build_identity(build_dir),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--stage",
        type=Path,
        help="keep the staged install here instead of a temporary directory",
    )
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    try:
        if args.selftest:
            selftest()
            print("emit_core_release_receipt: PASS")
            return 0
        if not (args.source_root and args.build_dir and args.output):
            parser.error("--source-root, --build-dir and --output are required")
        receipt = emit(args.source_root, args.build_dir, args.output, args.stage)
    except CheckFailure as exc:
        print(f"emit_core_release_receipt: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        "emit_core_release_receipt: PASS "
        f"({len(receipt['runtimeArtifacts'])} artifacts, {receipt['receiptDigest']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
