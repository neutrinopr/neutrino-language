"""[fast]  M6 S4: backend anti-inference boundary — the contract-legalization
TUs legalize off the normalized CoordinationPlan and never re-read a shared
semantic decision from the raw capability-spec (JSON). This drives
check_anti_inference.py's positive sweep, its non-vacuous selftest (it must bite
on an injected bypass), and a fresh injection — with NO build.

The compiler rule: semantics normalize once (); targets legalize ();
CodeText prints. This is the SOURCE complement of the runtime differential ().
"""

import os
import shutil
import unittest

from _fastcase import FastCase, REPO


class AntiInferenceBoundary(FastCase):
    def test_boundary_holds(self):
        record = os.path.join(self.tmp, "anti-inference-core-report.json")
        self.val_ok(
            "real core is clean and the pinned fixture is exact",
            "scripts/gates/check_anti_inference.py",
            "--check-core",
            "--execution-record",
            record,
        )
        self.assertTrue(os.path.isfile(record))

    def test_selftest_is_non_vacuous(self):
        # The gate proves it DISCOVERS the legalizers (floor) and REJECTS injected
        # first-effect-key / balance / policy / lifecycle bypasses.
        self.val_ok("anti-inference gate bites on injected bypasses",
                    "scripts/gates/check_anti_inference.py", "--selftest")

    def test_injected_inference_fails_closed(self):
        # Copy a real legalization TU and reintroduce a shared semantic inference
        # (renderer-local balance discovery from the raw spec); prove it is rejected.
        dst = os.path.join(self.tmp, "SolidityRecipeProvider.cpp")
        shutil.copy(
            os.path.join(REPO, "lib/backends/solidity/provider/SolidityRecipeProvider.cpp"),
            dst,
        )
        with open(dst, "a") as f:
            f.write('\nstatic bool _leak(const llvm::json::Object &spec) {\n'
                    '  return !spec.getArray("invariants")->empty();\n}\n')
        self.val_reject("reintroduced renderer-local balance discovery",
                        "scripts/gates/check_anti_inference.py", "--file", dst)

    def test_char_literal_obfuscation_still_caught(self):
        # A char literal `'"'` must NOT let a following spec read hide from the
        # scanner (the reused  stripper handles it); and the type/dependency
        # boundary catches spec.find(...) / operator[], not just getX() syntax.
        dst = os.path.join(self.tmp, "PostgresModel.cpp")
        shutil.copy(
            os.path.join(
                REPO, "lib/backends/postgres/model/PostgresModel.cpp"),
            dst,
        )
        with open(dst, "a") as f:
            f.write('\nstatic auto _leak(const llvm::json::Object &spec) {\n'
                    '  char q = \'"\';  (void)q;\n'
                    '  return spec.find("effects");\n}\n')
        self.val_reject("char-literal-obfuscated spec.find access",
                        "scripts/gates/check_anti_inference.py", "--file", dst)

    def test_one_waist_sibling_projection_probes_bite(self):
        for probe in [
            "backend-l2-read",
            "evaluator-spec-read",
            "external-spec-planfromspec-bypass",
            "reducer-domain-branch",
            "below-waist-domain-label",
        ]:
            with self.subTest(probe=probe):
                self.val_reject(f"one-waist probe {probe}",
                                "scripts/gates/check_gate_integrity.py",
                                "--probe", "anti_inference", probe)

    def test_two_leg_fail_closed_taxonomy_bites(self):
        expected = {
            "fixture-missing": "anti_inference.fixture_missing",
            "fixture-empty": "anti_inference.fixture_empty",
            "fixture-undetected": "anti_inference.fixture_undetected",
            "fixture-unexpected": "anti_inference.fixture_unexpected",
            "corpus-empty": "anti_inference.corpus_empty",
            "matcher-vacuous": "anti_inference.matcher_vacuous",
            "unauthenticated-exclusion":
                "anti_inference.unauthenticated_exclusion",
            "suppressed-finding": "anti_inference.suppressed_finding",
            "not-executed": "anti_inference.not_executed",
        }
        for probe, identity in expected.items():
            with self.subTest(probe=probe):
                result = self.val_reject(
                    f"two-leg mutation {probe}",
                    "scripts/gates/check_anti_inference.py",
                    "--probe-core",
                    probe,
                )
                self.assertIn(
                    f"probe-failed-as-expected:{probe} {identity}",
                    result.stdout.decode("utf-8", "replace"),
                )

    def test_fixture_pin_and_production_routing_bite(self):
        for probe in (
                "fixture-digest-pin",
                "production-selftest-substitution"):
            with self.subTest(probe=probe):
                result = self.val_reject(
                    f"gate-integrity mutation {probe}",
                    "scripts/gates/check_gate_integrity.py",
                    "--probe",
                    "anti_inference",
                    probe,
                )
                self.assertIn(
                    f"probe-failed-as-expected:{probe}",
                    result.stdout.decode("utf-8", "replace"),
                )


if __name__ == "__main__":
    unittest.main()
