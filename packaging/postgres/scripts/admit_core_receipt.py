#!/usr/bin/env python3
"""/ Mode-A consumer for the M7 core release receipt ().

Authenticates an admitted core prefix against a producer-emitted release receipt
(`neutrino.m7-core-release-receipt/1`). Implements the six consumer obligations
in docs/process/M7_CORE_RELEASE_RECEIPT.md section 4 and the Mode-A delivery rule
in section 3.

Mode A only: the receipt must reach us out-of-band. A receipt that resolves
INSIDE the prefix it describes is refused, symlinks included -- a record that
travels with the artifacts proves only self-consistency, which is the whole
reason this replaces the transitional sidecar. Mode B (externally pinned
receiptDigest / signature) depends on the  authority decision and is NOT
implemented here; --expect-digest is accepted as an additional constraint, never
as a substitute for out-of-band delivery.

No producer is landed yet, so nothing here writes or derives a receipt: the
producer owns emission from the staged install (section 5). This consumes only
the seven frozen schema fields and invents none.
"""
import argparse
import hashlib
import json
import os
import re
import stat
import sys

KIND = "neutrino.m7-core-release-receipt/1"
SCHEMA_VERSION = 1

RE_COMMIT = re.compile(r"^[0-9a-f]{40}$")
RE_BARE_SHA = re.compile(r"^[0-9a-f]{64}$")
RE_PREFIXED_SHA = re.compile(r"^sha256:[0-9a-f]{64}$")
RE_ARTIFACT_PATH = re.compile(r"^bin/[^/]+$")
RE_MODE = re.compile(r"^0[0-7]{3}$")

# Mirrors the frozen schema's additionalProperties:false exactly.
RECEIPT_FIELDS = {
    "kind", "schemaVersion", "sourceCommit", "buildTarget",
    "installedExportSha256", "runtimeArtifacts", "receiptDigest",
}
ARTIFACT_FIELDS = {"path", "sha256", "mode"}


class Refusal(Exception):
    """A fail-closed refusal. Every path that cannot prove provenance raises."""

    def __init__(self, code, detail):
        super().__init__(f"{code}: {detail}")
        self.code = code


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def canonical_digest(body):
    """Canonical-JSON digest, byte-for-byte the producer's `canonical()`.

    `ensure_ascii=False` with an explicit UTF-8 encode is load-bearing, not
    incidental. The producer () emits that form; Python's default would
    escape non-ASCII as \\uXXXX and hash different bytes. Every value in the
    receipt today is ASCII so both agree, but `buildTarget` is a free-form
    string, and a single non-ASCII byte would otherwise make a valid receipt
    fail as `receipt.digest_mismatch` -- indistinguishable from tampering.
    The producer defines the bytes; this follows it.
    """
    return sha256_bytes(json.dumps(
        body, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8"))


def validate_receipt_shape(receipt):
    """Full structural mirror of m7-core-release-receipt.schema.json.

    Hand-written because the extracted package cannot reach back into the
    translator tree for a validator, and a partial mirror would let a
    schema-invalid receipt through the one check that is supposed to be
    exhaustive. Every constraint the schema states is enforced here: types,
    consts, patterns, minItems/minLength, uniqueness, and BOTH
    additionalProperties:false objects.
    """
    if not isinstance(receipt, dict):
        raise Refusal("receipt.type", "receipt is not a JSON object")

    missing = sorted(RECEIPT_FIELDS - set(receipt))
    if missing:
        raise Refusal("receipt.required", f"missing field(s): {missing}")
    extra = sorted(set(receipt) - RECEIPT_FIELDS)
    if extra:
        raise Refusal("receipt.additional_properties",
                      f"undeclared field(s): {extra} (schema forbids)")

    if receipt["kind"] != KIND:
        raise Refusal("receipt.kind", f"expected {KIND}, got {receipt['kind']!r}")
    # Guard bool explicitly: in Python True == 1, so a bool would satisfy a
    # naive equality against the const and slip through.
    if isinstance(receipt["schemaVersion"], bool) or \
            receipt["schemaVersion"] != SCHEMA_VERSION:
        raise Refusal("receipt.schema_version",
                      f"expected {SCHEMA_VERSION}, got {receipt['schemaVersion']!r}")

    for field, pattern, label in (
        ("sourceCommit", RE_COMMIT, "40-hex commit"),
        ("installedExportSha256", RE_BARE_SHA, "bare 64-hex sha256"),
        ("receiptDigest", RE_PREFIXED_SHA, "sha256:<64-hex>"),
    ):
        value = receipt[field]
        if not isinstance(value, str) or not pattern.match(value):
            raise Refusal(f"receipt.{field}", f"not a {label}: {value!r}")

    target = receipt["buildTarget"]
    if not isinstance(target, str) or not target:
        raise Refusal("receipt.build_target", "must be a non-empty string")

    artifacts = receipt["runtimeArtifacts"]
    if not isinstance(artifacts, list):
        raise Refusal("receipt.runtime_artifacts", "must be an array")
    if not artifacts:
        raise Refusal("receipt.runtime_artifacts",
                      "must declare at least one artifact (minItems 1)")

    seen = set()
    for index, item in enumerate(artifacts):
        where = f"runtimeArtifacts[{index}]"
        if not isinstance(item, dict):
            raise Refusal("receipt.artifact_type", f"{where} is not an object")
        item_missing = sorted(ARTIFACT_FIELDS - set(item))
        if item_missing:
            raise Refusal("receipt.artifact_required",
                          f"{where} missing {item_missing}")
        item_extra = sorted(set(item) - ARTIFACT_FIELDS)
        if item_extra:
            raise Refusal("receipt.artifact_additional_properties",
                          f"{where} has undeclared field(s) {item_extra}")
        if not isinstance(item["path"], str) or \
                not RE_ARTIFACT_PATH.match(item["path"]):
            raise Refusal("receipt.artifact_path",
                          f"{where} path {item['path']!r} is not bin/<name>")
        if not isinstance(item["sha256"], str) or \
                not RE_BARE_SHA.match(item["sha256"]):
            raise Refusal("receipt.artifact_sha256",
                          f"{where} sha256 {item['sha256']!r} is not bare 64-hex")
        if not isinstance(item["mode"], str) or not RE_MODE.match(item["mode"]):
            raise Refusal("receipt.artifact_mode",
                          f"{where} mode {item['mode']!r} is not 0NNN octal")
        # uniqueItems is declared over whole objects; duplicate paths are a
        # named refusal in section 2 regardless of whether the records differ.
        if item["path"] in seen:
            raise Refusal("receipt.duplicate_path",
                          f"{item['path']} declared more than once")
        seen.add(item["path"])

    ordered = [a["path"] for a in artifacts]
    if ordered != sorted(ordered):
        raise Refusal("receipt.ordering",
                      "runtimeArtifacts must be ordered by path so the "
                      "canonical form is stable")


def verify_receipt_digest(receipt):
    """Obligation 1: recompute receiptDigest over the canonical form with that
    field removed."""
    body = {k: v for k, v in receipt.items() if k != "receiptDigest"}
    computed = "sha256:" + canonical_digest(body)
    if computed != receipt["receiptDigest"]:
        raise Refusal(
            "receipt.digest_mismatch",
            f"declared {receipt['receiptDigest']}, recomputed {computed} -- the "
            "receipt body does not hash to its own identity")
    return computed


def _under(path, root):
    return path == root or path.startswith(root + os.sep)


def refuse_in_prefix_receipt(receipt_path, prefix):
    """Section 3 Mode A: a receipt resolving inside the admitted prefix is
    refused, symlinks included. This is the check that makes out-of-band
    delivery mean anything, so it is required rather than advisory.

    BOTH the literal access path and its symlink resolution must lie outside
    the prefix. Resolving only the target lets an in-prefix symlink point at an
    external file: the bytes then come from outside, but *which* receipt is
    consulted is chosen from inside the prefix, so whoever can rewrite the
    prefix still selects the receipt. Refusing only the resolved target would
    leave that selection under the attacker's control.
    """
    real_prefix = os.path.realpath(prefix)
    # Resolve the CONTAINING directory but not the final component, so the
    # access path is compared in the same namespace as the prefix (a symlinked
    # parent -- /var -> /private/var on macOS, or the prefix reached through a
    # link -- must not make an in-prefix receipt look external), while the
    # receipt's own symlink target is still judged separately below.
    literal = os.path.join(
        os.path.realpath(os.path.dirname(os.path.abspath(receipt_path))),
        os.path.basename(receipt_path))
    resolved = os.path.realpath(receipt_path)
    for label, candidate in (("resolves to", resolved), ("is reached via", literal)):
        if _under(candidate, real_prefix):
            raise Refusal(
                "receipt.inside_prefix",
                f"receipt {receipt_path} {label} {candidate}, inside the "
                f"admitted prefix {real_prefix} -- a record that travels with, "
                "or is selected from within, the artifacts proves only "
                "self-consistency (Mode A requires out-of-band delivery)")


def consuming_platform(explicit=None):
    """Obligation 2 needs a platform to compare against. If we cannot establish
    one we must refuse: skipping the comparison would admit a receipt built for
    a different target, and artifact digests are platform-specific."""
    target = explicit or os.environ.get("NBP_BUILD_TARGET")
    if not target:
        raise Refusal(
            "platform.undetermined",
            "consuming platform is unknown -- pass --build-target or set "
            "NBP_BUILD_TARGET. Obligation 2 is a refusal, so an undetermined "
            "platform cannot be treated as a match")
    return target


def declared_runtime_paths(installed_export):
    """The shape manifest's runtime artifacts. Read-only: this consumer never
    edits the producer's manifest, and reads only the field it already
    publishes."""
    paths = installed_export.get("runtimeArtifacts")
    if not isinstance(paths, list) or not paths:
        raise Refusal("export.runtime_artifacts",
                      "shape manifest declares no runtimeArtifacts")
    out = []
    for entry in paths:
        # The manifest's retained shape is a list of path strings (
        # deliberately keeps identity out of it). Anything else means we are
        # reading a manifest revision this consumer was not written against.
        if not isinstance(entry, str):
            raise Refusal(
                "export.runtime_artifacts",
                f"expected a path string, got {entry!r} -- identity belongs in "
                "the receipt, not the shape manifest")
        out.append(entry)
    return out


def admit(prefix, receipt_path, installed_export_path, expect_digest=None,
          build_target=None):
    """Full Mode-A admission. Returns the receiptDigest admitted against."""
    if not os.path.isdir(prefix):
        raise Refusal("prefix.missing", f"{prefix} is not a directory")

    # Obligation ordering note: the Mode-A delivery check runs FIRST. A receipt
    # sourced from inside the prefix must be refused before any of its contents
    # are trusted enough to act on.
    refuse_in_prefix_receipt(receipt_path, prefix)

    try:
        raw = open(receipt_path, "rb").read()
    except OSError as exc:
        raise Refusal("receipt.unreadable", str(exc)) from exc
    try:
        receipt = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Refusal("receipt.malformed", str(exc)) from exc

    validate_receipt_shape(receipt)
    digest = verify_receipt_digest(receipt)

    # Mode B is not implemented (it awaits the  authority decision), but an
    # externally supplied pin is honoured as an ADDITIONAL constraint when the
    # caller has one. It never substitutes for out-of-band delivery.
    if expect_digest is not None and expect_digest != digest:
        raise Refusal("receipt.pin_mismatch",
                      f"externally pinned {expect_digest}, receipt is {digest}")

    # Obligation 2: platform. Fails closed when the platform is undetermined.
    host_target = consuming_platform(build_target)
    if host_target != receipt["buildTarget"]:
        raise Refusal(
            "receipt.build_target_mismatch",
            f"receipt is for {receipt['buildTarget']}, consuming platform is "
            f"{host_target} -- artifact digests are platform-specific")

    # Obligation 3: bind to the shape contract in force.
    try:
        export_bytes = open(installed_export_path, "rb").read()
    except OSError as exc:
        raise Refusal("export.unreadable", str(exc)) from exc
    export_digest = sha256_bytes(export_bytes)
    if export_digest != receipt["installedExportSha256"]:
        raise Refusal(
            "receipt.export_mismatch",
            f"receipt realizes manifest {receipt['installedExportSha256']}, "
            f"manifest in force is {export_digest} -- receipt paired with a "
            "different manifest revision")
    try:
        installed_export = json.loads(export_bytes)
    except json.JSONDecodeError as exc:
        raise Refusal("export.malformed", str(exc)) from exc

    # Obligation 5: bijection against the shape manifest.
    declared = set(declared_runtime_paths(installed_export))
    recorded = {a["path"] for a in receipt["runtimeArtifacts"]}
    missing = sorted(declared - recorded)
    if missing:
        raise Refusal("receipt.missing_record",
                      f"shape manifest declares {missing} with no receipt record")
    extra = sorted(recorded - declared)
    if extra:
        raise Refusal("receipt.extra_record",
                      f"receipt records {extra}, not declared by the manifest")

    # Obligation 4: byte-bind every artifact, and check the declared mode.
    for artifact in receipt["runtimeArtifacts"]:
        target = os.path.join(prefix, artifact["path"])
        # Retained pre-digest diagnostics: they produce a clear failure before
        # the digest comparison rather than an opaque mismatch.
        if os.path.islink(target) or not os.path.isfile(target):
            raise Refusal("artifact.not_regular_file",
                          f"{artifact['path']} is not a regular file")
        info = os.stat(target)
        if info.st_size == 0:
            raise Refusal("artifact.empty", f"{artifact['path']} is empty")
        declared_mode = int(artifact["mode"], 8)
        actual_mode = stat.S_IMODE(info.st_mode)
        if actual_mode != declared_mode:
            raise Refusal(
                "artifact.mode_mismatch",
                f"{artifact['path']} mode {actual_mode:04o}, receipt declares "
                f"{artifact['mode']}")
        # The retained executable check (obligation 4) is a property of the
        # artifact, not merely agreement between file and record. A runtime
        # artifact under bin/ that is consistently declared non-executable is
        # still not a runnable core, so consistency must not launder it.
        if not declared_mode & 0o111:
            raise Refusal(
                "artifact.not_executable",
                f"{artifact['path']} is declared {artifact['mode']}, which is "
                "not executable -- a bin/ runtime artifact must be runnable "
                "however consistently the mode is recorded")
        actual = sha256_bytes(open(target, "rb").read())
        if actual != artifact["sha256"]:
            raise Refusal(
                "artifact.digest_mismatch",
                f"{artifact['path']} digest {actual} does not match the "
                f"receipt's {artifact['sha256']}")

    # Obligation 5 (second half): nothing installed under bin/ may go unrecorded.
    bindir = os.path.join(prefix, "bin")
    if os.path.isdir(bindir):
        for name in sorted(os.listdir(bindir)):
            rel = f"bin/{name}"
            if rel not in recorded:
                raise Refusal(
                    "prefix.unrecorded_artifact",
                    f"{rel} is installed but carries no receipt record")

    return digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True,
                        help="the installed core prefix being admitted")
    parser.add_argument("--receipt", required=True,
                        help="out-of-band release receipt (must NOT resolve "
                             "inside --prefix)")
    parser.add_argument("--installed-export", required=True,
                        help="the shape manifest in force")
    parser.add_argument("--build-target",
                        help="consuming platform triple; falls back to "
                             "NBP_BUILD_TARGET. Admission refuses if neither "
                             "is supplied -- obligation 2 cannot be skipped")
    parser.add_argument("--expect-digest",
                        help="optional external pin; an additional constraint, "
                             "never a substitute for out-of-band delivery")
    parser.add_argument("--selftest", action="store_true",
                        help="run the synthetic fail-closed suite")
    args, _ = parser.parse_known_args(argv)

    if args.selftest:
        from admit_core_receipt_selftest import run_selftest
        return run_selftest()

    try:
        digest = admit(args.prefix, args.receipt, args.installed_export,
                       args.expect_digest, args.build_target)
    except Refusal as refusal:
        print(f"core receipt admission REFUSED -- {refusal}", file=sys.stderr)
        return 1
    # Obligation 6: report which receipt this admission trusted.
    print(f"core prefix AUTHENTICATED against receipt {digest} "
          f"(Mode A, out-of-band)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
