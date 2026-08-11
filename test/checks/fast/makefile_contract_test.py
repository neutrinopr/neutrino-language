"""[fast] : the root Makefile remains a reliable public command facade."""

import re

from _fastcase import FastCase, REPO


class MakefileContract(FastCase):
    def make_database(self):
        return self.assert_ok("Makefile parses", "make", "-pn").stdout.decode()

    def test_default_goal_is_build(self):
        database = self.make_database()
        self.assertRegex(database, r"(?m)^\.DEFAULT_GOAL := build$")

    def test_every_recipe_target_is_phony(self):
        with open(f"{REPO}/Makefile") as source:
            lines = source.readlines()

        recipe_targets = set()
        current_targets = []
        for line in lines:
            match = re.match(r"^([A-Za-z0-9][A-Za-z0-9_. -]*):(?:\s|$)", line)
            if match:
                current_targets = match.group(1).split()
            elif line.startswith("\t"):
                recipe_targets.update(current_targets)

        database = self.make_database()
        phony_line = re.search(r"(?m)^\.PHONY: (.+)$", database)
        self.assertIsNotNone(phony_line, "expanded .PHONY declaration is missing")
        phony_targets = set(phony_line.group(1).split())

        self.assertGreaterEqual(len(recipe_targets), 40, "recipe-target scan became vacuous")
        self.assertEqual(sorted(recipe_targets - phony_targets), [],
                         "every command-style target must be .PHONY")

    def test_directory_overrides_reach_recipes(self):
        result = self.assert_ok(
            "directory overrides route generated output and tools",
            "make", "-n", "emit",
            "BUILD_DIR=/tmp/neutrino-make-build",
            "ARTIFACT_DIR=/tmp/neutrino-make-artifacts")
        output = result.stdout.decode()
        self.assertIn("/tmp/neutrino-make-build/tools/neutrino-emit/neutrino-emit", output)
        self.assertIn("-o /tmp/neutrino-make-artifacts/events.txt", output)

    def test_acceptance_source_overrides_reach_recipes(self):
        """: the migrated acceptance targets still honor EXAMPLE/SCENARIO overrides
        (they now flow through the CTest wrapper as NEU_SOURCE/NEU_SCENARIO)."""
        for target, src_var, scen_var in (
                ("db-test", "EXAMPLE", "SCENARIO"),
                ("equivalence", "EXAMPLE", "SCENARIO"),
                ("equivalence-scheme", "EXAMPLE2", "SCENARIO2")):
            result = self.assert_ok(
                f"{target} passes source/scenario overrides to the recipe",
                "make", "-n", target,
                f"{src_var}=SENTINEL_SRC.neu", f"{scen_var}=SENTINEL_SCEN.json")
            output = result.stdout.decode()
            self.assertIn("SENTINEL_SRC.neu", output,
                          f"{target} dropped the {src_var} override")
            self.assertIn("SENTINEL_SCEN.json", output,
                          f"{target} dropped the {scen_var} override")

    def test_reference_runner_needs_no_translator_build(self):
        """: `solidity-reference-test` tests a hand-authored Foundry project — its
        dedicated CI runner provisions only solc+Foundry, so the recipe must NOT configure
        or build the translator (no `make build` / cmake / ctest, which would need MLIR)."""
        result = self.assert_ok(
            "solidity-reference-test is build-free",
            "make", "-n", "solidity-reference-test")
        output = result.stdout.decode()
        for forbidden in ("cmake", "ctest", "MLIR_DIR"):
            self.assertNotIn(forbidden, output,
                             f"solidity-reference-test must not invoke '{forbidden}' "
                             "(it must stay build-free for the solc+Foundry-only runner)")
        self.assertIn("run.sh solidity-reference", output,
                      "solidity-reference-test should invoke the reference acceptance recipe")


if __name__ == "__main__":
    import unittest
    unittest.main()
