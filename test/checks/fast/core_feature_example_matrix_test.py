"""[fast] Compiler-derived core-feature/example matrix contract."""

import json
import os
import unittest

from _fastcase import FastCase, REPO


class CoreFeatureExampleMatrix(FastCase):
    def test_non_vacuous_matrix_selftest(self):
        self.val_ok("core-feature example matrix selftest",
                    "scripts/samples/make_core_feature_example_matrix.py", "--selftest")

    def test_schemas_are_closed(self):
        for name in ("semantic-requirements", "core-feature-example-matrix"):
            path = os.path.join(REPO, "docs", "schemas", f"{name}.schema.json")
            with open(path, encoding="utf-8") as handle:
                schema = json.load(handle)
            self.assertIs(schema.get("additionalProperties"), False)
            self.assertEqual(set(schema.get("required", [])),
                             set(schema.get("properties", {})))

    def test_target_and_matrix_are_registered(self):
        with open(os.path.join(REPO, "include", "Neutrino", "TargetRegistry.def"),
                  encoding="utf-8") as handle:
            registry = handle.read()
        with open(os.path.join(REPO, "cmake", "NeutrinoTests.cmake"),
                  encoding="utf-8") as handle:
            cmake = handle.read()
        self.assertIn('NEUTRINO_TARGET("semantic-requirements", emitSemanticRequirements', registry)
        self.assertIn("check_core_feature_example_matrix.py --selftest", cmake)
        self.assertIn("scripts/samples/make_core_feature_example_matrix.py\n", cmake)


if __name__ == "__main__":
    unittest.main()
