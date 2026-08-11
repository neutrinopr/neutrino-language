"""[fast] M5 WP4 (): target profiles validate + spec-legality gate (fail closed on
unsupported)."""

import json
import os
import shutil
import unittest
from pathlib import Path

from _fastcase import FastCase, PY, REPO

SOLIDITY_PROFILE = "examples/target-profiles/solidity.target-profile.json"


class TargetProfileLegality(FastCase):
    def _curated_spec(self, index):
        return list(self.curated_members().values())[index].spec_path

    def test_profiles_validate(self):
        profiles = self.globr("examples/target-profiles/*.target-profile.json")
        for p in profiles:
            self.val_ok(f"profile {os.path.basename(p)}",
                        "scripts/validators/validate_target_profile.py", p)
        self.require_floor("target profiles", len(profiles), 1)

    def test_profile_negatives_fail_closed(self):
        negs = self.globr("examples/target-profiles/negatives/*.json")
        for f in negs:
            self.val_reject(f"profile negative {os.path.basename(f)}",
                            "scripts/validators/validate_target_profile.py", f)
        # Ratchet floor pinned to the committed negative count (): the profile negatives are
        # the fail-closed proof; partial erosion must fail, not just an empty glob.
        self.require_floor("profile negatives", len(negs), 6)

    @staticmethod
    def _domain_dir(spec):
        return Path(spec).parents[2]

    @classmethod
    def _has_committed_scenario(cls, spec):
        scenario_dir = cls._domain_dir(spec) / "scenario"
        return scenario_dir.is_dir() and any(path.is_file() for path in scenario_dir.iterdir())

    def _scenario_bearing_legality_failures(self, specs, profiles):
        failures = []
        checks = 0
        for spec in specs:
            if not self._has_committed_scenario(spec):
                continue
            for profile in profiles:
                result = self.run_cmd(
                    PY, "scripts/gates/check_spec_legality.py", spec, "--profile", profile)
                checks += 1
                if result.returncode != 0:
                    failures.append((str(spec), profile,
                                     result.stdout.decode("utf-8", "replace")))
        return failures, checks

    def test_scenario_bearing_specs_legal_vs_both_profiles(self):
        specs = [member.spec_path for member in self.curated_members().values()]
        profiles = self.globr("examples/target-profiles/*.target-profile.json")
        failures, checks = self._scenario_bearing_legality_failures(specs, profiles)
        self.assertEqual(failures, [], failures)
        self.require_floor("scenario-bearing legality (spec x profile) checks", checks, 2)

    def test_temporal_source_only_spec_is_narrowly_supported_by_each_profile(self):
        temporal_spec = self._curated_spec(6)
        spec = self.load_json(temporal_spec)
        features = {
            requirement["feature"]
            for requirement in spec["targetRequirements"]["requirements"]
        }
        self.assertIn("value_extension:temporal", features)
        self.assertNotIn("value_category:extension", features)
        profiles = self.globr("examples/target-profiles/*.target-profile.json")
        self.require_floor("temporal narrow-support profiles", len(profiles), 2)
        for profile in profiles:
            result = self.run_cmd(PY, "scripts/gates/check_spec_legality.py", temporal_spec,
                                  "--profile", profile)
            self.assertEqual(result.returncode, 0,
                             (os.path.basename(profile), result.stdout.decode()))

    def test_adding_scenario_keeps_temporal_fixture_legal_in_strict_portfolio(self):
        source_spec = self._curated_spec(6)
        domain = Path(self.tmp) / "core_deadline_transfer"
        copied_spec = domain / "generated/capability-spec/capability-spec.json"
        copied_spec.parent.mkdir(parents=True)
        shutil.copyfile(source_spec, copied_spec)
        scenario = domain / "scenario/core_deadline_transfer_happy_path.json"
        scenario.parent.mkdir()
        self.dump_json({
            "scenario": "core_deadline_transfer_happy_path",
            "procedure": "core_deadline_transfer",
            "inputs": {
                "transfer_id": "transfer-1", "payer": "payer-1", "payee": "payee-1",
                "amount": 100, "currency": "EUR", "now": 10, "deadline": 5,
            },
            "expect": {},
        }, scenario)
        self.assertTrue(self._has_committed_scenario(copied_spec))
        profiles = self.globr("examples/target-profiles/*.target-profile.json")
        failures, checks = self._scenario_bearing_legality_failures([copied_spec], profiles)
        self.assertEqual(checks, len(profiles))
        self.assertEqual(failures, [])

    def test_temporal_support_removal_and_unknown_extension_fail_closed(self):
        temporal_spec = self._curated_spec(6)
        spec = self.load_json(temporal_spec)
        profile = self.load_json(Path(REPO) / SOLIDITY_PROFILE)
        profile["supportedFeatures"].remove("value_extension:temporal")
        refusal = self.dump_json(profile, Path(self.tmp) / "no-temporal.target-profile.json")
        result = self.run_cmd(PY, "scripts/gates/check_spec_legality.py", temporal_spec,
                              "--profile", refusal)
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        diagnostic = next((item for item in report["diagnostics"]
                           if item.get("feature") == "value_extension:temporal"), None)
        self.assertIsNotNone(diagnostic, report)
        self.assertEqual(diagnostic["primitive"], "input now")

        unknown = json.loads(json.dumps(spec))
        temporal = next(item for item in unknown["targetRequirements"]["requirements"]
                        if item["feature"] == "value_extension:temporal")
        temporal["feature"] = "value_category:extension"
        unknown_path = self.dump_json(unknown, Path(self.tmp) / "unknown-extension.json")
        result = self.run_cmd(PY, "scripts/gates/check_spec_legality.py", unknown_path,
                              "--profile", SOLIDITY_PROFILE)
        self.assertNotEqual(result.returncode, 0)
        unknown_report = json.loads(result.stdout)
        self.assertTrue(any(item.get("feature") == "value_category:extension" and
                            item.get("code") == "legality.unsupported_feature"
                            for item in unknown_report["diagnostics"]), unknown_report)

    def test_source_only_classification_and_unsupported_accounting_bite(self):
        specs = [member.spec_path for member in self.curated_members().values()]
        profiles = self.globr("examples/target-profiles/*.target-profile.json")
        scenario_bearing = [spec for spec in specs if self._has_committed_scenario(spec)]
        source_only = [spec for spec in specs if not self._has_committed_scenario(spec)]
        self.require_floor("scenario-bearing fixture classification", len(scenario_bearing), 1)
        self.require_floor("source-only fixture classification", len(source_only), 1)

        for spec in source_only:
            spec_features = {
                requirement["feature"]
                for requirement in self.load_json(spec)["targetRequirements"]["requirements"]
            }
            for prof_path in profiles:
                profile = self.load_json(prof_path)
                accounted = (set(profile["supportedFeatures"]) |
                             set(profile["unsupportedConstructs"]))
                self.assertTrue(
                    spec_features <= accounted,
                    f"{self._domain_dir(spec).name}: source-only primitive escaped "
                    f"{profile['profileId']} supported/unsupported accounting")

        explicit_denials = 0
        for prof_path in profiles:
            profile = self.load_json(prof_path)
            self.assertIn("value_category:extension", profile["unsupportedConstructs"])
            explicit_denials += 1
        self.require_floor("unknown extension explicit denials", explicit_denials, 2)

    def test_crippled_profile_fails_closed(self):
        # A profile that drops a needed feature must fail the legality gate closed.
        prof = self.load_json(os.path.join(REPO, SOLIDITY_PROFILE))
        prof["supportedFeatures"] = [f for f in prof["supportedFeatures"] if f != "effect:debit"]
        crippled = self.dump_json(prof, os.path.join(self.tmp, "crippled.target-profile.json"))
        self.val_reject("legality gate fails closed on unsupported feature",
                        "scripts/gates/check_spec_legality.py", self._curated_spec(3),
                        "--profile", crippled)

    def test_malformed_profile_fails_closed(self):
        # A malformed profile fails the gate closed (legality.bad_input), never a crash.
        prof = self.load_json(os.path.join(REPO, SOLIDITY_PROFILE))
        prof["unsupportedConstructs"] = {}
        malformed = self.dump_json(prof, os.path.join(self.tmp, "malformed.target-profile.json"))
        self.val_reject("legality gate fails closed on a malformed profile",
                        "scripts/gates/check_spec_legality.py", self._curated_spec(3),
                        "--profile", malformed)


if __name__ == "__main__":
    unittest.main()
