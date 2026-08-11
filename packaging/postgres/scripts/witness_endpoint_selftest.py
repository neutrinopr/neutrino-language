#!/usr/bin/env python3
"""Refusal-path validation for witness_endpoint.py. DO NOT MERGE until .

HARNESS VALIDATION ONLY -- this is NOT  clean-clone acceptance. It proves the
witness harness REFUSES what it claims to refuse, using tiny synthetic fixtures.
It says nothing about whether the real extracted candidate is correct; that is
what running the same unchanged harness against the post- candidate will
establish.

Every refusal the harness advertises is exercised here, because a harness whose
negative paths have never fired is indistinguishable from one that always passes.
"""
import json
import os
import shutil
import stat
import tempfile

from witness_endpoint import (
    DESCRIPTOR_KIND, PROTOCOL_KIND, WitnessFailure, find_descriptor,
    witness_protocol, witness_reach_back, witness_substitution,
)

ENTRY_STUB = "#!/bin/sh\nexit 0\n"


def write_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2, sort_keys=True)


def make_package(root, *, entry_name="bin/pg-backend", descriptors=1,
                 entry_present=True, executable=True, poison=None):
    """A minimal package shaped only by the CONTRACT, not by any real layout."""
    prefix = os.path.join(root, "pkg")
    for index in range(descriptors):
        # Deliberately varied nesting: the harness must find these by KIND, not
        # by an expected relative path.
        sub = "share/neutrino" if index == 0 else f"share/other{index}"
        write_json(os.path.join(prefix, sub, "package-descriptor.json"), {
            "kind": DESCRIPTOR_KIND, "protocol": PROTOCOL_KIND,
            "entry": os.path.relpath(entry_name, sub) if False else entry_name,
        })
    if entry_present:
        entry = os.path.join(prefix, entry_name)
        os.makedirs(os.path.dirname(entry), exist_ok=True)
        with open(entry, "w", encoding="utf-8") as handle:
            handle.write(ENTRY_STUB)
        if executable:
            os.chmod(entry, 0o755)
        else:
            os.chmod(entry, 0o644)
    if poison:
        os.makedirs(os.path.join(prefix, "share"), exist_ok=True)
        with open(os.path.join(prefix, "share", "build-info.txt"), "w",
                  encoding="utf-8") as handle:
            handle.write(f"built from {poison}\n")
    return prefix


def expect(name, code, fails, thunk):
    try:
        thunk()
    except WitnessFailure as failure:
        if failure.witness != code:
            fails.append(f"{name}: refused as {failure.witness!r}, expected {code!r}")
        return
    fails.append(f"{name}: ACCEPTED -- the refusal did not fire")


def run_selftest():
    fails = []
    root = tempfile.mkdtemp(prefix="nbp-witness-selftest-")
    try:
        # POSITIVE control: without it every refusal could pass vacuously on a
        # fixture the harness rejects for unrelated reasons.
        good = make_package(root)
        try:
            path, doc = find_descriptor(good)
            if doc["kind"] != DESCRIPTOR_KIND:
                fails.append("positive: wrong descriptor returned")
        except WitnessFailure as failure:
            fails.append(f"positive: well-formed package REFUSED -- {failure}")

        # --- descriptor discovery ----------------------------------------
        ambiguous = make_package(os.path.join(root, "ambig"), descriptors=2)
        expect("descriptor_ambiguous", "protocol", fails,
               lambda: find_descriptor(ambiguous))

        empty = os.path.join(root, "empty", "pkg")
        os.makedirs(empty)
        expect("descriptor_absent", "protocol", fails,
               lambda: find_descriptor(empty))

        # --- entry resolution ---------------------------------------------
        no_entry = make_package(os.path.join(root, "noentry"), entry_present=False)
        expect("entry_missing", "protocol", fails,
               lambda: witness_protocol(no_entry, root))

        not_exec = make_package(os.path.join(root, "noexec"), executable=False)
        expect("entry_not_executable", "protocol", fails,
               lambda: witness_protocol(not_exec, root))

        # --- reach-back ----------------------------------------------------
        # An empty forbidden-root list must REFUSE, not silently pass: a scan
        # with nothing to look for is the definition of a vacuous witness.
        expect("reachback_no_forbidden_root", "reach-back", fails,
               lambda: witness_reach_back(good, []))

        poisoned = make_package(os.path.join(root, "poison"),
                                poison="/some/translator/checkout")
        expect("reachback_detects_reference", "reach-back", fails,
               lambda: witness_reach_back(poisoned, ["/some/translator/checkout"]))

        # A clean prefix must PASS, or the check would be trivially red.
        try:
            witness_reach_back(good, ["/some/translator/checkout"])
        except WitnessFailure as failure:
            fails.append(f"reachback_clean_prefix: clean prefix REFUSED -- {failure}")

        # --- receipt substitution -----------------------------------------
        # A verifier that ignores bytes must be caught: the harness asserts the
        # substitution is REJECTED, so an always-succeeding verifier fails here.
        blind = os.path.join(root, "blind_verifier.py")
        with open(blind, "w", encoding="utf-8") as handle:
            handle.write("import sys\nsys.exit(0)\n")
        receipt = os.path.join(root, "receipt.json")
        write_json(receipt, {"artifacts": [{"path": "bin/pg-backend"}]})
        expect("substitution_blind_verifier", "substitution", fails,
               lambda: witness_substitution(good, receipt, blind, root))

        # And a byte-checking verifier must let the harness pass.
        checker = os.path.join(root, "checking_verifier.py")
        with open(checker, "w", encoding="utf-8") as handle:
            handle.write(
                "import sys\n"
                "i=sys.argv.index('--prefix'); p=sys.argv[i+1]\n"
                "d=open(p+'/bin/pg-backend','rb').read()\n"
                "sys.exit(1 if b'SUBSTITUTED' in d else 0)\n")
        try:
            witness_substitution(good, receipt, checker, root)
        except WitnessFailure as failure:
            fails.append(
                f"substitution_checking_verifier: a byte-checking verifier was "
                f"reported as failing -- {failure}")

        empty_receipt = os.path.join(root, "empty-receipt.json")
        write_json(empty_receipt, {"artifacts": []})
        expect("substitution_receipt_declares_nothing", "substitution", fails,
               lambda: witness_substitution(good, empty_receipt, checker, root))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    if fails:
        print("witness harness refusal validation FAILED:")
        for failure in fails:
            print(f"    {failure}")
        return 1
    print("witness harness refusal validation PASS (descriptor ambiguity and "
          "absence, missing and non-executable entry, empty forbidden-root, "
          "reach-back detection with a clean-prefix control, blind-verifier "
          "substitution with a byte-checking control, and an empty receipt all "
          "refuse; positive controls admit)")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(run_selftest())
