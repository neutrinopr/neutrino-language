"""[fast]  M6→M7 intake seam S0: the source-neutral domain-semantics profile is
frozen. The classifier admits the hand-authored ontology-shaped v3 fixture, every
executable reduction anchors to the CLOSED L1 vocabulary (referenced by identity, not
re-listed), the three version axes are pinned to the current vocabulary + reducer, a
legacy v2 artifact stays byte-valid but is rejected by the M7 profile, and every
unknown/ambiguous/unversioned/provenance-incomplete/stale/cyclic mapping fails closed."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from _fastcase import FastCase, PY, REPO

GATE = "scripts/gates/classify_m7_intake.py"
PROFILE = "docs/m7-intake-profile.json"
FIXTURE = "examples/m7-intake/ontology_shaped_milestone_acceptance.l2v3.json"
VOCABULARY = "docs/semantic-feature-vocabulary.json"
V2_VALIDATOR = "scripts/domain/validate_l2_domain_semantics_v2.py"
V3_VALIDATOR = "scripts/domain/validate_l2_domain_semantics_v3.py"
PROBES = (
    "unregistered-capability", "unversioned-mapping", "provenance-incomplete",
    "ambiguous-mapping", "descriptive-drives-executable", "unsupported-schema-version",
    "legacy-v2-rejected", "stale-vocabulary", "stale-reducer", "mixed-version",
    "tampered-hash", "bad-vocabulary-source",
)


class M7IntakeSeam(FastCase):
    def _report(self, *args):
        result = self.run_cmd(PY, GATE, *args)
        return result, (json.loads(result.stdout) if result.stdout.strip().startswith(b"{") else None)

    def test_classifier_selftest_passes(self):
        # The one entrypoint that proves fixture-admitted + all probes fail closed.
        # Literal path (not the GATE constant) so the no-orphan-script gate's AST
        # traces classify_m7_intake.py as invoked from this reachable fast test.
        result = self.run_cmd(PY, "scripts/gates/classify_m7_intake.py", "--selftest")
        self.assertEqual(result.returncode, 0, result.stdout.decode())

    def test_reference_fixture_is_v3_and_admitted(self):
        artifact = self.load_json(Path(REPO) / FIXTURE)
        self.assertEqual(artifact["schemaVersion"], 3)
        self.assertIn("intakeVersioning", artifact)
        result, report = self._report("--artifact", FIXTURE)
        self.assertEqual(result.returncode, 0, result.stdout.decode())
        self.assertTrue(report["admitted"], report["diagnostics"])
        self.assertTrue(report["executableCapabilities"], "admitted with no executable capabilities")

    def test_current_baseline_fixture_pins_live_versions(self):
        # The committed fixture is pinned to the CURRENT vocabulary + reducer, so a
        # future bump that is not reflected in the fixture fails this test (and the
        # seam would reject the stale artifact). This is the "current-baseline" pin.
        iv = self.load_json(Path(REPO) / FIXTURE)["intakeVersioning"]
        vocab = self.load_json(Path(REPO) / VOCABULARY)
        profile = self.load_json(Path(REPO) / PROFILE)
        self.assertEqual(iv["semanticProfileVersion"], vocab["semanticProfileVersion"])
        self.assertEqual(iv["reductionSemanticsVersion"], profile["reductionSemantics"]["version"])

    def test_executable_capabilities_anchor_to_closed_vocabulary(self):
        report = json.loads(self.run_cmd(PY, GATE, "--artifact", FIXTURE).stdout)
        vocab = set(self.load_json(Path(REPO) / VOCABULARY)["features"])
        for cap in report["executableCapabilities"]:
            self.assertIn(cap, vocab, f"executable capability {cap} not in the closed vocabulary")

    def test_profile_references_vocabulary_by_identity_not_relisted(self):
        profile = self.load_json(Path(REPO) / PROFILE)
        vocab = self.load_json(Path(REPO) / VOCABULARY)
        cn = profile["capabilityNamespace"]
        self.assertEqual(cn["kind"], "neutrino.semantic-feature-vocabulary")
        self.assertEqual(cn["source"], VOCABULARY)
        self.assertEqual(cn["semanticProfileVersion"], vocab["semanticProfileVersion"])
        self.assertEqual(profile["intakeContract"]["artifactSchemaVersion"], 3)
        blob = json.dumps(profile)
        self.assertNotIn("effect:debit", blob, "profile re-lists closed-vocabulary features")
        self.assertNotIn('"features"', blob, "profile must not carry a feature list")

    def test_legacy_v2_byte_valid_but_rejected_by_profile(self):
        # v2 stays byte-valid (the v2 validator accepts a downgraded artifact) but
        # the M7 profile REFUSES it — v2 is the compatibility baseline, not an intake
        # choice. Proves v2 was not reversioned and the seam admits v3 only.
        v3 = self.load_json(Path(REPO) / FIXTURE)
        v2 = json.loads(json.dumps(v3))
        v2["schemaVersion"] = 2
        v2.pop("intakeVersioning")
        v2.pop("domainSemanticsHash", None)
        # re-sign with the v2 canonicalizer so it is genuinely byte-valid v2
        canon = subprocess.run([PY, V2_VALIDATOR, "--canonicalize", "-"],
                               cwd=REPO, input=json.dumps(v2).encode(), stdout=subprocess.PIPE)
        v2_path = self.dump_json(json.loads(canon.stdout), os.path.join(self.tmp, "legacy.l2v2.json"))
        self.val_ok("legacy v2 artifact is byte-valid", V2_VALIDATOR, "--artifact", v2_path)
        result, report = self._report("--artifact", v2_path)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any(d["code"] == "intake.unsupported_schema_version"
                            for d in report["diagnostics"]), report)

    def test_profile_admission_diagnostics_match_classifier(self):
        result = self.run_cmd(PY, "-c",
                              "import sys;sys.path.insert(0,'scripts/gates');"
                              "import classify_m7_intake as c;"
                              "ok,msg=c.assert_codes_match_profile();"
                              "print(msg);sys.exit(0 if ok else 1)")
        self.assertEqual(result.returncode, 0, result.stdout.decode())

    def test_every_probe_fails_closed(self):
        for probe in PROBES:
            result = self.run_cmd(PY, GATE, "--probe", probe)
            self.assertEqual(result.returncode, 1,
                             f"probe {probe} did not fail closed: {result.stdout.decode()}")
            self.assertIn(f"probe-failed-as-expected:{probe}", result.stdout.decode())
        self.require_floor("m7 intake fail-closed probes", len(PROBES), 12)

    def test_malformed_profile_fails_closed(self):
        profile = self.load_json(Path(REPO) / PROFILE)
        del profile["capabilityNamespace"]
        bad = self.dump_json(profile, os.path.join(self.tmp, "bad-profile.json"))
        result, report = self._report("--artifact", FIXTURE, "--profile", bad)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(any(d["code"] == "intake.profile_invalid" for d in report["diagnostics"]), report)


if __name__ == "__main__":
    unittest.main()
