#!/usr/bin/env python3
"""Synthetic fail-closed suite for the  Mode-A receipt consumer.

Synthetic by necessity and by design. No producer has landed ( section 5),
so there is no real receipt to consume; these fixtures are built here to the
frozen schema and invent no producer field. They are NOT a substitute for the
acceptance witnesses -- when the producer lands,  binds a real receipt and
runs the clean-clone/PostgreSQL witnesses against it.

The decisive case is `paired_substitution`: replace an artifact AND the
prefix-local record together, consistently, leaving the out-of-band receipt
untouched. The transitional sidecar cannot refuse this -- it is derived from the
prefix, so a consistent rewrite satisfies it. Admission must still reject.
"""
import copy
import json
import os
import shutil
import stat
import tempfile

from admit_core_receipt import Refusal, admit, canonical_digest, sha256_bytes

ARTIFACTS = {
    "bin/neutrino-emit": b"ELF-ish core emitter bytes\n",
    "bin/neutrino-equiv": b"ELF-ish equivalence bytes\n",
}
BUILD_TARGET = "arm64-apple-darwin24.6.0"


def seal(receipt):
    """Recompute receiptDigest so a fixture is self-consistent unless a probe
    deliberately breaks it. Uses the consumer's own canonical form, so a probe
    that tampers with the body without resealing is caught by obligation 1."""
    body = {k: v for k, v in receipt.items() if k != "receiptDigest"}
    receipt["receiptDigest"] = "sha256:" + canonical_digest(body)
    return receipt


def build_fixture(root):
    """A well-formed prefix + out-of-band receipt + shape manifest."""
    prefix = os.path.join(root, "prefix")
    outofband = os.path.join(root, "release")
    os.makedirs(os.path.join(prefix, "bin"))
    os.makedirs(outofband)

    for rel, data in ARTIFACTS.items():
        path = os.path.join(prefix, rel)
        with open(path, "wb") as handle:
            handle.write(data)
        os.chmod(path, 0o755)

    export = {
        "kind": "neutrino.m7-core-installed-export/1",
        "cppAbiPolicy": "forbidden",
        "runtimeArtifacts": sorted(ARTIFACTS),
    }
    export_path = os.path.join(root, "m7-core-installed-export.json")
    export_bytes = json.dumps(export, indent=2, sort_keys=True).encode() + b"\n"
    with open(export_path, "wb") as handle:
        handle.write(export_bytes)

    receipt = seal({
        "kind": "neutrino.m7-core-release-receipt/1",
        "schemaVersion": 1,
        "sourceCommit": "0" * 39 + "a",
        "buildTarget": BUILD_TARGET,
        "installedExportSha256": sha256_bytes(export_bytes),
        "runtimeArtifacts": [
            {"path": rel, "sha256": sha256_bytes(data), "mode": "0755"}
            for rel, data in sorted(ARTIFACTS.items())
        ],
        "receiptDigest": "placeholder",
    })
    receipt_path = os.path.join(outofband, "core-release-receipt.json")
    write_receipt(receipt_path, receipt)

    # The transitional sidecar stays exactly where it is: prefix-local, derived,
    # explicitly consistency-only. It is present in the fixture precisely so the
    # decisive probe can rewrite it consistently and still be refused.
    write_sidecar(prefix)
    return prefix, receipt_path, export_path, receipt


def write_receipt(path, receipt):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_sidecar(prefix):
    """The prefix-local consistency-only record (transitional, never authority)."""
    record = {
        "kind": "neutrino.core-artifact-digests/transitional",
        "note": "consistency check only; not authentication, not provenance",
        "artifacts": {
            rel: sha256_bytes(open(os.path.join(prefix, rel), "rb").read())
            for rel in sorted(ARTIFACTS)
        },
    }
    with open(os.path.join(prefix, "core-artifact-digests.json"),
              "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")


def expect_refusal(name, code, fails, prefix, receipt_path, export_path,
                   expect_digest=None, build_target=BUILD_TARGET):
    try:
        admit(prefix, receipt_path, export_path, expect_digest, build_target)
    except Refusal as refusal:
        if refusal.code != code:
            fails.append(
                f"{name}: refused with {refusal.code}, expected {code}")
        return
    fails.append(f"{name}: ADMITTED -- the probe did not bite")


def run_selftest():
    fails = []
    root = tempfile.mkdtemp(prefix="nbp-receipt-selftest-")
    try:
        prefix, receipt_path, export_path, good = build_fixture(root)

        # POSITIVE control. Without this every refusal below could pass
        # vacuously on a fixture that never admits at all.
        try:
            digest = admit(prefix, receipt_path, export_path,
                           build_target=BUILD_TARGET)
            if digest != good["receiptDigest"]:
                fails.append(
                    f"positive: admitted against {digest}, expected "
                    f"{good['receiptDigest']}")
        except Refusal as refusal:
            fails.append(f"positive: well-formed fixture REFUSED -- {refusal}")

        # ---- THE DECISIVE MUTATION (section 6) -------------------------------
        # Replace an artifact and the prefix-local record together, consistently.
        # The sidecar is satisfied; the out-of-band receipt is not.
        forged = os.path.join(root, "forged")
        shutil.copytree(prefix, forged)
        with open(os.path.join(forged, "bin/neutrino-emit"), "wb") as handle:
            handle.write(b"SUBSTITUTED emitter bytes\n")
        os.chmod(os.path.join(forged, "bin/neutrino-emit"), 0o755)
        write_sidecar(forged)  # rewrite the local record to match, consistently
        sidecar = json.load(
            open(os.path.join(forged, "core-artifact-digests.json"),
                 encoding="utf-8"))
        forged_digest = sha256_bytes(
            open(os.path.join(forged, "bin/neutrino-emit"), "rb").read())
        if sidecar["artifacts"]["bin/neutrino-emit"] != forged_digest:
            fails.append(
                "paired_substitution: fixture is not self-consistent -- the "
                "sidecar was not rewritten to match, so the probe would bite "
                "for the wrong reason")
        expect_refusal("paired_substitution", "artifact.digest_mismatch", fails,
                       forged, receipt_path, export_path)

        # ---- Mode A delivery (section 3) -------------------------------------
        inside = os.path.join(prefix, "core-release-receipt.json")
        shutil.copyfile(receipt_path, inside)
        expect_refusal("receipt_inside_prefix", "receipt.inside_prefix", fails,
                       prefix, inside, export_path)
        os.remove(inside)

        # A symlink that merely points out-of-band must not launder an in-prefix
        # path, and a symlink from outside INTO the prefix must not launder one
        # either: realpath resolution is what the rule turns on.
        laundered = os.path.join(root, "laundered-receipt.json")
        os.symlink(os.path.join(prefix, "bin", "neutrino-emit"), laundered)
        expect_refusal("receipt_symlink_into_prefix", "receipt.inside_prefix",
                       fails, prefix, laundered, export_path)

        # P1: the reverse direction. A symlink INSIDE the prefix pointing at a
        # genuine external receipt used to pass, because only the resolved
        # target was tested. The bytes are external, but whoever controls the
        # prefix controls WHICH receipt is consulted -- that selection is the
        # thing Mode-A separation exists to deny.
        inside_link = os.path.join(prefix, "release-receipt.json")
        os.symlink(receipt_path, inside_link)
        expect_refusal("in_prefix_symlink_to_external_receipt",
                       "receipt.inside_prefix", fails, prefix, inside_link,
                       export_path)
        os.remove(inside_link)

        # ---- Obligation 1: identity -----------------------------------------
        tampered = copy.deepcopy(good)
        tampered["sourceCommit"] = "1" * 40  # body changed, digest NOT resealed
        path = os.path.join(root, "tampered.json")
        write_receipt(path, tampered)
        expect_refusal("body_tampered_unresealed", "receipt.digest_mismatch",
                       fails, prefix, path, export_path)

        # ---- Obligation 2: platform -----------------------------------------
        other = seal({**copy.deepcopy(good), "buildTarget": "x86_64-unknown-linux-gnu"})
        other_path = os.path.join(root, "other-target.json")
        write_receipt(other_path, other)
        expect_refusal("build_target_mismatch", "receipt.build_target_mismatch",
                       fails, prefix, other_path, export_path)

        # P1: an undetermined platform must REFUSE, not skip the comparison.
        # Previously a wrong-platform receipt was admitted whenever neither
        # --build-target nor NBP_BUILD_TARGET was supplied, which is the common
        # case rather than an exotic one.
        stashed = os.environ.pop("NBP_BUILD_TARGET", None)
        try:
            expect_refusal("platform_undetermined_rejects_wrong_target",
                           "platform.undetermined", fails, prefix, other_path,
                           export_path, build_target=None)
            # Even a correct receipt is refused: the platform is unproven.
            expect_refusal("platform_undetermined_rejects_right_target",
                           "platform.undetermined", fails, prefix, receipt_path,
                           export_path, build_target=None)
            # The environment fallback still works when it is actually set.
            os.environ["NBP_BUILD_TARGET"] = BUILD_TARGET
            try:
                admit(prefix, receipt_path, export_path, build_target=None)
            except Refusal as refusal:
                fails.append(
                    f"platform_env_fallback: refused -- {refusal}")
            del os.environ["NBP_BUILD_TARGET"]
        finally:
            if stashed is not None:
                os.environ["NBP_BUILD_TARGET"] = stashed

        # ---- Obligation 3: bound to the shape contract ----------------------
        drifted = os.path.join(root, "drifted-export.json")
        with open(drifted, "wb") as handle:
            handle.write(json.dumps({
                "kind": "neutrino.m7-core-installed-export/1",
                "cppAbiPolicy": "forbidden",
                "runtimeArtifacts": sorted(ARTIFACTS),
                "revision": "a later manifest",
            }, indent=2, sort_keys=True).encode() + b"\n")
        expect_refusal("export_revision_mismatch", "receipt.export_mismatch",
                       fails, prefix, receipt_path, drifted)

        # ---- Obligation 5: bijection ----------------------------------------
        dropped = copy.deepcopy(good)
        dropped["runtimeArtifacts"] = [
            a for a in dropped["runtimeArtifacts"]
            if a["path"] != "bin/neutrino-equiv"]
        path = os.path.join(root, "dropped.json")
        write_receipt(path, seal(dropped))
        expect_refusal("missing_record", "receipt.missing_record", fails,
                       prefix, path, export_path)

        added = copy.deepcopy(good)
        added["runtimeArtifacts"].append(
            {"path": "bin/neutrino-extra", "sha256": "b" * 64, "mode": "0755"})
        added["runtimeArtifacts"].sort(key=lambda a: a["path"])
        path = os.path.join(root, "added.json")
        write_receipt(path, seal(added))
        expect_refusal("extra_record", "receipt.extra_record", fails, prefix,
                       path, export_path)

        duplicated = copy.deepcopy(good)
        duplicated["runtimeArtifacts"].append(
            copy.deepcopy(duplicated["runtimeArtifacts"][0]))
        duplicated["runtimeArtifacts"].sort(key=lambda a: a["path"])
        path = os.path.join(root, "duplicated.json")
        write_receipt(path, seal(duplicated))
        expect_refusal("duplicate_path", "receipt.duplicate_path", fails,
                       prefix, path, export_path)

        # An artifact installed under bin/ that no record covers.
        smuggled = os.path.join(root, "smuggled")
        shutil.copytree(prefix, smuggled)
        with open(os.path.join(smuggled, "bin/neutrino-rogue"), "wb") as handle:
            handle.write(b"unrecorded\n")
        expect_refusal("unrecorded_artifact", "prefix.unrecorded_artifact",
                       fails, smuggled, receipt_path, export_path)

        # ---- Obligation 4: mode is declared, not guessed --------------------
        chmodded = os.path.join(root, "chmodded")
        shutil.copytree(prefix, chmodded)
        os.chmod(os.path.join(chmodded, "bin/neutrino-emit"), 0o644)
        expect_refusal("mode_mismatch", "artifact.mode_mismatch", fails,
                       chmodded, receipt_path, export_path)

        # P1: consistency must not launder a non-runnable core. Declare 0644 in
        # the receipt AND chmod the artifact to match, so file and record agree
        # perfectly -- the retained executable check (obligation 4) must still
        # refuse, because executability is a property of the artifact rather
        # than agreement between two descriptions of it.
        nonexec = os.path.join(root, "nonexec")
        shutil.copytree(prefix, nonexec)
        os.chmod(os.path.join(nonexec, "bin/neutrino-emit"), 0o644)
        consistent = copy.deepcopy(good)
        for record in consistent["runtimeArtifacts"]:
            if record["path"] == "bin/neutrino-emit":
                record["mode"] = "0644"
        path = os.path.join(root, "consistent-nonexec.json")
        write_receipt(path, seal(consistent))
        actual_mode = stat.S_IMODE(
            os.stat(os.path.join(nonexec, "bin/neutrino-emit")).st_mode)
        if actual_mode != 0o644:
            fails.append(
                "consistent_non_executable: fixture is not self-consistent -- "
                f"artifact is {actual_mode:04o}, receipt declares 0644, so the "
                "probe would bite as a mode mismatch instead")
        expect_refusal("consistent_non_executable", "artifact.not_executable",
                       fails, nonexec, path, export_path)

        # ---- Schema mirror bites ---------------------------------------------
        for name, code, mutate in (
            ("undeclared_field", "receipt.additional_properties",
             lambda r: r.update({"signature": "not-a-declared-field"})),
            ("bad_commit", "receipt.sourceCommit",
             lambda r: r.update({"sourceCommit": "abc"})),
            ("bare_receipt_digest", "receipt.receiptDigest",
             lambda r: r.update({"receiptDigest": "c" * 64})),
            ("bad_artifact_path", "receipt.artifact_path",
             lambda r: r["runtimeArtifacts"][0].update({"path": "lib/x.so"})),
            ("bad_mode", "receipt.artifact_mode",
             lambda r: r["runtimeArtifacts"][0].update({"mode": "755"})),
            ("bool_schema_version", "receipt.schema_version",
             lambda r: r.update({"schemaVersion": True})),
        ):
            mutated = copy.deepcopy(good)
            mutate(mutated)
            # NOT resealed for shape probes: the shape mirror must reject before
            # identity is ever consulted, so these bite on their own terms.
            path = os.path.join(root, f"{name}.json")
            write_receipt(path, mutated)
            expect_refusal(name, code, fails, prefix, receipt_path=path,
                           export_path=export_path)

        # ---- Canonical form agrees with the producer, byte-for-byte ----------
        # Sealed with the PRODUCER's formula written out independently here
        # (scripts/release/emit_core_release_receipt.py -> canonical()), not
        # with the consumer's own helper, so a divergence cannot cancel itself
        # out. buildTarget carries a non-ASCII byte, which is the only place
        # today's field values can distinguish ensure_ascii=True from False.
        unicode_target = "arm64-apple-darwin24.6.0-übertest"
        agreed = copy.deepcopy(good)
        agreed["buildTarget"] = unicode_target
        body = {k: v for k, v in agreed.items() if k != "receiptDigest"}
        producer_digest = "sha256:" + sha256_bytes(json.dumps(
            body, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode("utf-8"))
        agreed["receiptDigest"] = producer_digest
        # Guard the probe itself: if this equals the ensure_ascii=True form the
        # fixture proves nothing, because both conventions would agree.
        ascii_digest = "sha256:" + sha256_bytes(json.dumps(
            body, sort_keys=True, separators=(",", ":")).encode())
        if producer_digest == ascii_digest:
            fails.append(
                "canonical_form_matches_producer: fixture is vacuous -- the "
                "two encodings agree on this body, so it cannot detect a "
                "divergence")
        path = os.path.join(root, "unicode-target.json")
        write_receipt(path, agreed)
        try:
            admit(prefix, path, export_path, build_target=unicode_target)
        except Refusal as refusal:
            fails.append(
                "canonical_form_matches_producer: a receipt sealed with the "
                f"producer's canonical form was REFUSED -- {refusal}")

        # ---- External pin is additional, never a substitute ------------------
        expect_refusal("pin_mismatch", "receipt.pin_mismatch", fails, prefix,
                       receipt_path, export_path,
                       expect_digest="sha256:" + "d" * 64)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    if fails:
        print("Mode-A receipt consumer selftest FAILED:")
        for failure in fails:
            print(f"    {failure}")
        return 1
    print("Mode-A receipt consumer selftest PASS (positive control admits; "
          "the paired artifact+local-record substitution is refused with the "
          "sidecar left self-consistent; Mode-A refuses an in-prefix receipt, "
          "an outside link INTO the prefix, and an in-prefix link OUT to a "
          "genuine external receipt; an undetermined platform refuses rather "
          "than skips; a consistently-declared 0644 artifact is refused as "
          "non-executable; identity, shape-contract, bijection, mode, and "
          "every schema-mirror constraint bite)")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(run_selftest())
