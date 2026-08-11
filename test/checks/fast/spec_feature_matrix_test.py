"""[fast] M5 WP7 (): spec-feature coverage matrix — every supported primitive is
exercised, explicit denials are accounted for, and unknown terms fail closed."""

import copy
import glob
import json
import sys
import textwrap
import unittest

from _fastcase import FastCase, PY, REPO

sys.path.insert(0, f"{REPO}/scripts/samples")
import spec_feature_matrix as matrix


class SpecFeatureMatrix(FastCase):
    def test_matrix_gate(self):
        # Every kernel-primitive feature carried in a sample spec is a known primitive, every
        # primitive is exercised by >=1 fixture, the four WP7 gate samples emit schema-valid specs,
        # and the committed matrix doc is not stale.
        self.val_ok("spec-feature matrix gate", "scripts/samples/spec_feature_matrix.py", "--check")

    def test_unglued_feature_flagged(self):
        # Exercise the glue rule directly (the gate scans the whole committed tree, so inject a
        # synthetic spec set): an unglued spec feature (not a known primitive) must be flagged.
        code = textwrap.dedent("""
            import sys
            sys.path.insert(0, "scripts/samples")
            import spec_feature_matrix as m
            vocab = m.primitive_vocabulary()
            specs = {"synthetic": {"features": ["value_category:UNGLUED_TERM"],
                                   "lowerings": [], "spec_path": "/dev/null"}}
            errs = m.check(vocab, specs, m.build_matrix(vocab, specs))
            sys.exit(0 if any("UNGLUED_TERM" in e for e in errs) else 1)
        """)
        self.assert_ok("unglued spec feature is flagged", PY, "-c", code)

    def test_unsupported_accounting_is_non_vacuous(self):
        profiles = [self.load_json(path) for path in sorted(glob.glob(
            f"{REPO}/examples/target-profiles/*.target-profile.json"))]
        known, _supported = matrix.profile_vocabularies(profiles)
        unsupported = set().union(*(set(profile["unsupportedConstructs"])
                                    for profile in profiles))
        used = {feature for info in matrix.sample_specs().values()
                for feature in info["features"]}
        self.assertTrue(unsupported, "non-vacuous explicit unsupported vocabulary")
        self.assertLessEqual(unsupported, known)
        self.assertIn("value_category:extension", unsupported)
        self.assertNotIn("value_category:extension", used)

    def test_supported_unsupported_asymmetry_is_allowed(self):
        profiles = [self.load_json(path) for path in sorted(glob.glob(
            f"{REPO}/examples/target-profiles/*.target-profile.json"))]
        asymmetric = copy.deepcopy(profiles)
        feature = "value_category:extension"
        asymmetric[0]["unsupportedConstructs"].remove(feature)
        asymmetric[0]["supportedFeatures"].append(feature)
        known, supported = matrix.profile_vocabularies(asymmetric)
        specs = matrix.sample_specs()
        specs["synthetic_unknown_extension"] = {
            "features": [feature], "lowerings": [], "spec_path": "/dev/null"}
        errors = matrix.check(known, specs, matrix.build_matrix(known, specs), supported)
        self.assertNotIn(feature, "\n".join(errors), errors)

    def test_removing_unsupported_accounting_makes_extension_unglued(self):
        profiles = [self.load_json(path) for path in sorted(glob.glob(
            f"{REPO}/examples/target-profiles/*.target-profile.json"))]
        tampered = copy.deepcopy(profiles)
        feature = "value_category:extension"
        for profile in tampered:
            profile["unsupportedConstructs"] = [
                item for item in profile["unsupportedConstructs"] if item != feature]
        known, supported = matrix.profile_vocabularies(tampered)
        specs = matrix.sample_specs()
        specs["synthetic_unknown_extension"] = {
            "features": [feature], "lowerings": [], "spec_path": "/dev/null"}
        errors = matrix.check(known, specs, matrix.build_matrix(known, specs), supported)
        self.assertTrue(any("unglued term" in error and feature in error for error in errors),
                        errors)


if __name__ == "__main__":
    unittest.main()
