"""[fast] Public M6 curated example corpus structural contract."""

import json
import os
import sys
import unittest

from _fastcase import FastCase, REPO

sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
import check_m6_curated_example_corpus as corpus  # noqa: E402


class M6CuratedExampleCorpus(FastCase):
    def test_committed_manifest_validates(self):
        self.val_ok(
            "m6 curated corpus structural check",
            "scripts/gates/check_m6_curated_example_corpus.py",
        )

    def test_selftest_non_vacuous(self):
        self.val_ok(
            "m6 curated corpus selftest",
            "scripts/gates/check_m6_curated_example_corpus.py",
            "--selftest",
        )

    def test_schema_is_closed(self):
        path = os.path.join(REPO, "docs", "schemas", "m6-curated-example-corpus.schema.json")
        with open(path, encoding="utf-8") as handle:
            schema = json.load(handle)
        self.assertIs(schema.get("additionalProperties"), False)
        self.assertEqual(
            set(schema.get("required", [])), set(schema.get("properties", {}))
        )

    def test_unknown_root_field_is_rejected_by_live_validator(self):
        path = os.path.join(REPO, "docs", "m6-curated-example-corpus.json")
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        manifest["unexpected"] = "must fail closed"
        errors = corpus.validate_manifest(corpus.canonical_pretty(manifest))
        self.assertTrue(any("unknown root fields" in error for error in errors), errors)

    def test_freeze_cross_link_and_membership(self):
        path = os.path.join(REPO, "docs", "m6-curated-example-corpus.json")
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["kind"], "neutrino.m6-curated-example-corpus")
        self.assertEqual(manifest["freeze"]["commentId"], 5114443802)
        self.assertEqual(
            manifest["freeze"]["url"],
            "urn:neutrino:document:m6-curated-corpus-freeze-v2",
        )
        self.assertEqual(len(manifest["examples"]), 7)
        self.assertEqual(len(manifest["variancePairs"]), 3)
        for pair in manifest["variancePairs"]:
            self.assertIn(pair["a"], manifest["examples"])
            self.assertIn(pair["b"], manifest["examples"])
            self.assertNotEqual(pair["a"], pair["b"])

    def test_registered_in_fast_tier(self):
        with open(
            os.path.join(REPO, "cmake", "NeutrinoTests.cmake"), encoding="utf-8"
        ) as handle:
            cmake = handle.read()
        # Registered as a discovered fast module (ctest name → test/checks/fast/*.py).
        self.assertIn(
            "fast-m6-curated-example-corpus=m6_curated_example_corpus=",
            cmake,
        )


if __name__ == "__main__":
    unittest.main()
