"""[fast] Forge toolchain provisioning receipts + closure-preflight wiring ().

Build-free and toolchain-free: this tier runs on a bare box (and on Linux CI), so it asserts the
STRUCTURE of every committed machine receipt against its schema and the WIRING that makes one
declared Forge tool identity reach every launch route. The live closure check (`--preflight`) and
the negative probe (`--selftest`) are the `forge-toolchain-probe` CTest row, which needs a real
forge and is labelled `requires-forge`.
"""

import glob
import json
import os
import re
import sys
import unittest

from _fastcase import FastCase, REPO

sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
import check_forge_toolchain as toolchain  # noqa: E402

RECEIPT_DIR = os.path.join(REPO, "docs", "testing", "forge-toolchain-receipts")
SCHEMA = os.path.join(REPO, "docs", "schemas", "forge-toolchain-receipt.schema.json")
MIN_RECEIPTS = 1  # the self-hosted macOS terminal box; a collapse to zero = fail closed.


def receipts():
    return sorted(glob.glob(os.path.join(RECEIPT_DIR, "*.receipt.json")))


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def code(path):
    """`read` with `#` comment tails removed — cmake/make/sh/py all comment with `#`, and a
    filename or command NAMED in a comment must not count as an invocation."""
    return "\n".join(line.split("#", 1)[0] for line in read(path).splitlines())


class ForgeToolchainReceipt(FastCase):
    def test_receipts_exist(self):
        self.assertGreaterEqual(len(receipts()), MIN_RECEIPTS,
                                f"no provisioning receipts under {RECEIPT_DIR}")

    def test_receipts_match_schema(self):
        schema = json.loads(read(SCHEMA))
        props = schema["properties"]
        checked = 0
        for path in receipts():
            receipt = json.loads(read(path))
            self.assertEqual(receipt["kind"], toolchain.RECEIPT_KIND, path)
            self.assertEqual(receipt["schemaVersion"], toolchain.SCHEMA_VERSION, path)
            self.assertEqual(set(receipt) - set(props), set(),
                             f"{path}: fields outside the closed schema")
            self.assertEqual(set(schema["required"]) - set(receipt), set(),
                             f"{path}: missing required fields")
            self.assertRegex(receipt["forge"]["digest"], r"^sha256:[0-9a-f]{64}$", path)
            self.assertTrue(receipt["forge"]["version"], path)
            # A receipt whose closure did not resolve is not evidence of provisioning.
            for dep in receipt["nativeDependencies"]:
                self.assertIsNotNone(dep["resolvedPath"],
                                     f"{path}: {dep['recordedInstallName']} unresolved")
                self.assertRegex(dep["digest"], r"^sha256:[0-9a-f]{64}$", path)
                self.assertIn(dep["resolvedVia"], ("declaredLibraryPath", "recordedInstallName"))
            checked += 1
        self.require_floor("forge toolchain receipts", checked, MIN_RECEIPTS)

    def test_darwin_receipt_declares_a_derived_prefix(self):
        """A Darwin receipt must name the FORMULA its prefix is derived from, so the recorded
        absolute path is documentation of a machine and never the mechanism."""
        for path in receipts():
            receipt = json.loads(read(path))
            if receipt["machine"]["os"] != "Darwin":
                continue
            self.assertTrue(receipt["declaredNativeLibraryPath"], path)
            self.assertEqual(receipt["declaredNativeFormula"],
                             toolchain.DARWIN_NATIVE_FORMULA, path)

    def test_no_workstation_path_is_baked_into_the_mechanism(self):
        """The derivation must stay parameterized: no tracked mechanism file may contain a
        receipt's recorded absolute prefix."""
        mechanism = [
            os.path.join(REPO, "scripts", "gates", "check_forge_toolchain.py"),
            os.path.join(REPO, "cmake", "NeutrinoForgeToolchain.cmake"),
            os.path.join(REPO, "cmake", "NeutrinoAcceptanceTests.cmake"),
            os.path.join(REPO, "test", "acceptance", "run.sh"),
            os.path.join(REPO, "Makefile"),
        ]
        recorded = {json.loads(read(p))["declaredNativeLibraryPath"] for p in receipts()}
        recorded.discard("")
        for path in mechanism:
            text = read(path)
            for prefix in recorded:
                self.assertNotIn(prefix, text,
                                 f"{path} bakes in the recorded machine prefix {prefix}")

    def test_single_derivation_authority(self):
        """Only check_forge_toolchain.py may derive the declared prefix — a second
        `brew --prefix libusb` anywhere would let the launch routes drift apart."""
        offenders = []
        for path in glob.glob(os.path.join(REPO, "cmake", "*.cmake")) + [
                os.path.join(REPO, "Makefile"),
                os.path.join(REPO, "test", "acceptance", "run.sh"),
                os.path.join(REPO, "test", "curated", "check_solidity_goldens.py")]:
            if re.search(r"brew\s+--prefix\s+libusb", code(path)):
                offenders.append(os.path.relpath(path, REPO))
        self.assertEqual(offenders, [], f"re-derive the prefix via the authority, not: {offenders}")

    def test_every_launch_route_consumes_the_declared_identity(self):
        """The routes that directly spawn forge re-materialise DYLD_LIBRARY_PATH from
        the neutral FORGE_DYLD_LIBRARY_PATH (macOS SIP strips DYLD_* before they run)."""
        routes = {
            "test/acceptance/run.sh": r'DYLD_LIBRARY_PATH="\$FORGE_DYLD_LIBRARY_PATH"',
            "test/curated/check_solidity_goldens.py": r'env\["DYLD_LIBRARY_PATH"\] = library_path',
        }
        for rel, pattern in routes.items():
            self.assertRegex(read(os.path.join(REPO, rel)), pattern,
                             f"{rel} lost the declared-identity spawn boundary")

    def test_preflight_runs_before_any_conformance_step(self):
        """Every requires-forge kind in the acceptance dispatcher preflights the toolchain before
        it renders/compiles/executes anything, so a provisioning defect can never be reported as a
        backend result."""
        run_sh = read(os.path.join(REPO, "test", "acceptance", "run.sh"))
        guards = re.findall(r"have_forge \|\| skip forge;([^\n]*)", run_sh)
        self.assertGreaterEqual(len(guards), 7, "forge-requiring kinds disappeared from run.sh")
        for guard in guards:
            self.assertIn("forge_preflight", guard)
        # …and the preflight is a hard failure, never a skip.
        self.assertIn("exit 66", run_sh)

    def test_requires_forge_rows_carry_the_configured_environment(self):
        acc = read(os.path.join(REPO, "cmake", "NeutrinoAcceptanceTests.cmake"))
        self.assertIn('if("requires-forge" IN_LIST A_LABELS)', acc)
        self.assertIn("NEUTRINO_FORGE_TEST_ENVIRONMENT", acc)
        tests = read(os.path.join(REPO, "cmake", "NeutrinoTests.cmake"))
        self.assertIn("include(${CMAKE_CURRENT_LIST_DIR}/NeutrinoForgeToolchain.cmake)", tests)

    def test_every_acceptance_kind_is_dispatchable(self):
        """A registered KIND with no case in run.sh fails with `unknown kind` before any
        conformance runs — that is how acceptance-compliant-transfer silently rotted ()."""
        acc = code(os.path.join(REPO, "cmake", "NeutrinoAcceptanceTests.cmake"))
        run_sh = read(os.path.join(REPO, "test", "acceptance", "run.sh"))
        kinds = re.findall(r"neutrino_acceptance\(NAME\s+\S+\s+KIND\s+([a-z][a-z0-9-]*)", acc)
        self.assertGreaterEqual(len(kinds), 15, "acceptance registrations disappeared")
        dispatched = set()
        for arm in re.findall(r"^  ([a-z0-9|-]+)\)$", run_sh, re.MULTILINE):
            dispatched.update(arm.split("|"))
        self.assertEqual([k for k in kinds if k not in dispatched], [],
                         "registered acceptance KINDs with no run.sh case")

    def test_registered_in_fast_tier(self):
        cmake = read(os.path.join(REPO, "cmake", "NeutrinoTests.cmake"))
        self.assertIn("fast-forge-toolchain-receipt=forge_toolchain_receipt=", cmake)


if __name__ == "__main__":
    unittest.main()
