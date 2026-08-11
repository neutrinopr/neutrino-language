#!/usr/bin/env python3
import json
import os

from _fastcase import FastCase, REPO


SCRIPT = "scripts/gates/check_canonical_reduction_domain_blindness.py"
FIXTURE = os.path.join(REPO, "examples/pressure-loop-reduction/s4-domain-blindness.json")


class CanonicalReductionDomainBlindness(FastCase):
    def load_fixture(self):
        return self.load_json(FIXTURE)

    def write_fixture(self, obj):
        path = os.path.join(self.tmp, "canonical-reduction.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
        return path

    def test_committed_fixture_passes_and_hashes_match(self):
        result = self.val_ok("canonical reduction proof", SCRIPT, FIXTURE, "--json")
        payload = json.loads(result.stdout.decode("utf-8"))
        self.assertTrue(payload["ok"])
        group = payload["report"]["groups"][0]
        hashes = {g["canonicalReducedSha256"] for g in group["graphs"]}
        self.assertEqual(len(hashes), 1)
        reduced_bytes = {
            json.dumps(g["reduced"], sort_keys=True, separators=(",", ":"))
            for g in group["graphs"]
        }
        self.assertEqual(len(reduced_bytes), 1)

    def test_selftest_is_non_vacuous(self):
        self.val_ok("canonical reduction selftest", SCRIPT, "--selftest")

    def test_name_collision_without_semantic_equivalence_rejected(self):
        obj = self.load_fixture()
        reqs = obj["groups"][0]["sourceGraphs"][0]["requirements"]
        reqs[0]["name"] = "shared_collision"
        reqs[1]["name"] = "shared_collision"
        rejected = self.val_reject("name collision rejected", SCRIPT, self.write_fixture(obj), "--json")
        self.assertIn("canonical_reduction.name_collision", rejected.stdout.decode("utf-8", "replace"))

    def test_removed_shared_obligation_breaks_proof(self):
        obj = self.load_fixture()
        obj["groups"][0]["sourceGraphs"][1]["selectedRequirementIds"].pop()
        rejected = self.val_reject("removed obligation rejected", SCRIPT, self.write_fixture(obj), "--json")
        self.assertIn("canonical_reduction.not_equivalent", rejected.stdout.decode("utf-8", "replace"))

    def test_changed_shared_obligation_breaks_proof(self):
        obj = self.load_fixture()
        obj["groups"][0]["sourceGraphs"][1]["requirements"][1]["verifierSemantics"]["terminalBound"] = "runtime-host"
        rejected = self.val_reject("changed obligation rejected", SCRIPT, self.write_fixture(obj), "--json")
        self.assertIn("canonical_reduction.not_equivalent", rejected.stdout.decode("utf-8", "replace"))

    def test_domain_or_backend_below_waist_rejected(self):
        for key, value in [
            ("domainReducer", "github-handoff-only"),
            ("backendBranch", "solidity"),
            ("domainLabel", "single_producer_assessment"),
        ]:
            with self.subTest(key=key):
                obj = self.load_fixture()
                obj["groups"][0]["sourceGraphs"][0]["requirements"][0]["verifierSemantics"][key] = value
                rejected = self.val_reject("below-waist label rejected", SCRIPT, self.write_fixture(obj), "--json")
                self.assertIn("canonical_reduction.below_waist_label", rejected.stdout.decode("utf-8", "replace"))

    def test_spec_verification_hash_must_agree(self):
        obj = self.load_fixture()
        obj["groups"][0]["specVerifications"][0]["canonicalReducedSha256"] = "0" * 64
        rejected = self.val_reject("spec verification mismatch rejected", SCRIPT, self.write_fixture(obj), "--json")
        self.assertIn("canonical_reduction.spec_verification", rejected.stdout.decode("utf-8", "replace"))

    def test_gate_integrity_probes_bite(self):
        for probe in [
            "backend-branch",
            "change-shared-obligation",
            "domain-label-below-waist",
            "domain-reducer",
            "name-collision",
            "remove-shared-obligation",
        ]:
            with self.subTest(probe=probe):
                self.val_reject("canonical reduction probe", SCRIPT, "--probe", probe)


if __name__ == "__main__":
    import unittest
    unittest.main()
