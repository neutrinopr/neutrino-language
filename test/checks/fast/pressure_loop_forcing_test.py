#!/usr/bin/env python3
import json
import os
import stat
import sys

from _fastcase import FastCase, REPO

sys.path.insert(0, os.path.join(REPO, "scripts", "generators"))
import run_pressure_loop_forcing as forcing  # noqa: E402


SCRIPT = "scripts/generators/run_pressure_loop_forcing.py"
FIXTURES = os.path.join(REPO, "examples/pressure-loop-forcing/fixtures.json")
VALIDATOR = "scripts/validators/validate_pressure_loop_register.py"


class PressureLoopForcing(FastCase):
    def tool_dir(self, *, tamper_trace=False, fail_representable=False, reduction_succeeds=False):
        tool_dir = os.path.join(self.tmp, "tools")
        os.makedirs(tool_dir, exist_ok=True)
        gen = os.path.join(tool_dir, "neutrino-gen")
        trace = {
            "outcome": "terminal",
            "trace": [
                {"kind": "authorization"},
                {"name": "bonus_amount"},
                {"effect": "pay_out", "delta": -1000},
                {"effect": "bonus_in", "delta": 1001},
            ],
            "nextState": {
                "balances": [
                    {"ledger": "a.src", "party": "buyer-1", "currency": "EUR", "balance": -2001},
                    {"ledger": "b.dst", "party": "seller-1", "currency": "EUR", "balance": 2001},
                ],
                "keyStatus": {"F-1": "CLOSED"},
                "keyClaim": {},
                "committedGroups": {},
                "postedKeys": [] if tamper_trace else ["F-1"],
            },
        }
        with open(gen, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env python3\n")
            fh.write("import json, os, sys\n")
            fh.write("args=sys.argv[1:]\n")
            fh.write("target=args[args.index('--target')+1] if '--target' in args else ''\n")
            fh.write("for a in args:\n")
            fh.write("  if a.startswith('--target='): target=a.split('=',1)[1]\n")
            fh.write("if target=='capability-spec':\n")
            fh.write("  out=args[args.index('-o')+1]; os.makedirs(out, exist_ok=True); json.dump({'kind':'capability-spec'}, open(os.path.join(out,'capability-spec.json'),'w')); sys.exit(0)\n")
            fh.write("if target=='coordination-trace':\n")
            if fail_representable:
                fh.write("  print('forced representable failure'); sys.exit(7)\n")
            fh.write("  out=args[args.index('-o')+1]; os.makedirs(out, exist_ok=True); json.dump(" + repr(trace) + ", open(os.path.join(out,'coordination-trace.json'),'w'), indent=2, sort_keys=True); sys.exit(0)\n")
            fh.write("print('--target must be known'); sys.exit(2)\n")
        emit = os.path.join(tool_dir, "neutrino-emit")
        with open(emit, "w", encoding="utf-8") as fh:
            fh.write("#!/usr/bin/env python3\n")
            fh.write("import sys\n")
            if reduction_succeeds:
                fh.write("print('ok')\nsys.exit(0)\n")
            else:
                fh.write("print('error: unregistered feature totally:madeup')\nsys.exit(4)\n")
        os.chmod(gen, stat.S_IRWXU)
        os.chmod(emit, stat.S_IRWXU)
        return tool_dir

    def emit(self, fixture_path=FIXTURES):
        out = os.path.join(self.tmp, "register.json")
        self.val_ok("pressure-loop forcing emit", SCRIPT, fixture_path, "--out", out, "--tool-dir", self.tool_dir())
        return out

    def test_selftest_is_non_vacuous(self):
        self.val_ok("pressure-loop forcing selftest", SCRIPT, "--selftest")

    def test_emits_validator_clean_v2_register(self):
        out = self.emit()
        reg = self.load_json(out)
        self.assertEqual(reg["kind"], "neutrino.pressure-loop-register")
        self.assertEqual(reg["schemaVersion"], 2)
        self.assertEqual([r["rowId"] for r in reg["rows"]], sorted(r["rowId"] for r in reg["rows"]))
        self.val_ok("emitted pressure-loop register validates", VALIDATOR, out)

    def test_three_execution_paths_are_exercised(self):
        reg = self.load_json(self.emit())
        rows = {r["rowId"]: r for r in reg["rows"]}
        self.require_floor("forcing rows", len(rows), 4)
        self.assertEqual(rows["plf-001-representable"]["supportStatus"], "present")
        self.assertEqual(rows["plf-001-representable"]["evidenceRefs"][0]["type"], "executable")
        self.assertIn("plf-001-representable.proof.json",
                      rows["plf-001-representable"]["evidenceRefs"][0]["ref"])
        self.assertEqual(rows["plf-002-failed-reduction"]["outcome"], "unresolved")
        self.assertEqual(rows["plf-002-failed-reduction"]["class"], "3")
        self.assertEqual(rows["plf-002-failed-reduction"]["failedVerifierObligation"],
                         "unregistered feature totally:madeup")
        self.assertEqual(rows["plf-003-runtime-orthogonal"]["disposition"], "L3_RUNTIME")
        self.assertIsNone(rows["plf-003-runtime-orthogonal"]["currentArtifactOperation"])
        self.assertEqual(rows["plf-004-refusal"]["disposition"], "UNSUPPORTED_REFUSED")
        self.assertEqual(rows["plf-004-refusal"]["evidenceRefs"][0]["type"], "refusal")

    def write_fixture(self, mutator):
        obj = self.load_json(FIXTURES)
        mutator(obj)
        path = os.path.join(self.tmp, "fixtures.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(obj, fh)
        return path

    def test_fails_closed_on_zero_fixtures(self):
        rejected = self.val_reject("zero fixtures rejected", SCRIPT, self.write_fixture(lambda o: o.__setitem__("fixtures", [])), "--out", os.path.join(self.tmp, "reject.json"))
        self.assertIn("at least one", rejected.stdout.decode("utf-8", "replace"))

    def test_fails_closed_on_unknown_fixture_version(self):
        rejected = self.val_reject("unknown fixture version rejected", SCRIPT, self.write_fixture(lambda o: o.__setitem__("schemaVersion", 99)), "--out", os.path.join(self.tmp, "reject.json"))
        self.assertIn("schemaVersion", rejected.stdout.decode("utf-8", "replace"))

    def test_fails_closed_on_missing_executable_evidence(self):
        def mut(obj):
            obj["fixtures"][0]["inputs"]["source"] = "missing.neu"
        rejected = self.val_reject("missing executable evidence rejected", SCRIPT, self.write_fixture(mut), "--out", os.path.join(self.tmp, "reject.json"))
        self.assertIn("does not exist", rejected.stdout.decode("utf-8", "replace"))

    def test_fails_closed_on_representable_command_failure(self):
        rejected = self.val_reject(
            "representable command failure rejected",
            SCRIPT,
            FIXTURES,
            "--tool-dir",
            self.tool_dir(fail_representable=True),
            "--out",
            os.path.join(self.tmp, "reject.json"),
        )
        self.assertIn("failed with exit", rejected.stdout.decode("utf-8", "replace"))

    def test_fails_closed_on_tampered_trace(self):
        rejected = self.val_reject(
            "tampered generated trace rejected",
            SCRIPT,
            FIXTURES,
            "--tool-dir",
            self.tool_dir(tamper_trace=True),
            "--out",
            os.path.join(self.tmp, "reject.json"),
        )
        self.assertIn("missing posted key", rejected.stdout.decode("utf-8", "replace"))

    def test_fails_closed_on_unresolved_anchor_loss(self):
        def mut(obj):
            obj["fixtures"][1]["expectedObservation"]["anchor"] = "wrong"
        rejected = self.val_reject("missing unresolved anchor rejected", SCRIPT, self.write_fixture(mut), "--tool-dir", self.tool_dir(), "--out", os.path.join(self.tmp, "reject.json"))
        self.assertIn("observed diagnostic", rejected.stdout.decode("utf-8", "replace"))

    def test_fails_closed_when_reduction_unexpectedly_succeeds(self):
        rejected = self.val_reject(
            "reduction success rejected",
            SCRIPT,
            FIXTURES,
            "--tool-dir",
            self.tool_dir(reduction_succeeds=True),
            "--out",
            os.path.join(self.tmp, "reject.json"),
        )
        self.assertIn("unexpectedly succeeded", rejected.stdout.decode("utf-8", "replace"))

    def test_fails_closed_on_unknown_diagnostic_code(self):
        def mut(obj):
            obj["fixtures"][1]["expectedObservation"]["diagnosticCode"] = "unknown.code"
        rejected = self.val_reject("unknown diagnostic rejected", SCRIPT, self.write_fixture(mut), "--tool-dir", self.tool_dir(), "--out", os.path.join(self.tmp, "reject.json"))
        self.assertIn("observed diagnostic", rejected.stdout.decode("utf-8", "replace"))

    def test_real_reduction_diagnostic_maps_to_unregistered_feature(self):
        self.assertEqual(
            forcing.parse_diagnostic("error: spec.ast: l1_feature 'totally:madeup' is not a registered semantic feature (knownSemanticFeatures)\n"),
            ("l2.unregistered_feature", "totally:madeup"),
        )

    def test_fails_closed_on_orthogonal_artifact_fabrication(self):
        def mut(obj):
            obj["fixtures"][2]["currentArtifactOperation"] = "fakeRuntimeArtifact"
        rejected = self.val_reject("fabricated orthogonal artifact rejected", SCRIPT, self.write_fixture(mut), "--tool-dir", self.tool_dir(), "--out", os.path.join(self.tmp, "reject.json"))
        self.assertIn("unknown field", rejected.stdout.decode("utf-8", "replace"))

    def test_fails_closed_on_missing_refusal_evidence(self):
        def mut(obj):
            obj["fixtures"][3]["inputs"]["backend-dispatch"] = True
        rejected = self.val_reject("missing refusal evidence rejected", SCRIPT, self.write_fixture(mut), "--tool-dir", self.tool_dir(), "--out", os.path.join(self.tmp, "reject.json"))
        self.assertIn("backend dispatch", rejected.stdout.decode("utf-8", "replace"))

    def test_fails_closed_on_refusal_target_anchor_mismatch(self):
        def mut(obj):
            obj["fixtures"][3]["inputs"]["command"][1] = "--target=unsupported-different-target"
        rejected = self.val_reject("refusal target anchor mismatch rejected", SCRIPT, self.write_fixture(mut), "--tool-dir", self.tool_dir(), "--out", os.path.join(self.tmp, "reject.json"))
        self.assertIn("observed refusal", rejected.stdout.decode("utf-8", "replace"))

    def test_stdout_requires_durable_evidence_dir(self):
        rejected = self.val_reject(
            "stdout mode requires durable evidence dir",
            SCRIPT,
            FIXTURES,
            "--tool-dir",
            self.tool_dir(),
        )
        self.assertIn("stdout mode requires --evidence-dir", rejected.stdout.decode("utf-8", "replace"))

    def test_stdout_with_evidence_dir_emits_durable_refs(self):
        evidence_dir = os.path.join(self.tmp, "evidence")
        result = self.val_ok(
            "stdout mode with durable evidence dir",
            SCRIPT,
            FIXTURES,
            "--tool-dir",
            self.tool_dir(),
            "--evidence-dir",
            evidence_dir,
        )
        reg = json.loads(result.stdout.decode("utf-8"))
        refs = [
            ref["ref"]
            for row in reg["rows"]
            for ref in row.get("evidenceRefs", [])
        ]
        self.assertTrue(refs)
        for ref in refs:
            self.assertTrue(os.path.exists(os.path.join(REPO, ref)) or os.path.exists(ref), ref)

    def test_stdout_path_is_v2_validated_before_release(self):
        def mut(obj):
            obj["fixtures"][1]["provenance"]["authorityWeightTier"] = "9"
        evidence_dir = os.path.join(self.tmp, "invalid-evidence")
        rejected = self.val_reject(
            "stdout mode validates emitted register",
            SCRIPT,
            self.write_fixture(mut),
            "--tool-dir",
            self.tool_dir(),
            "--evidence-dir",
            evidence_dir,
        )
        self.assertIn("emitted register failed v2 validation", rejected.stdout.decode("utf-8", "replace"))

    def test_out_validation_failure_leaves_no_final_artifact(self):
        def mut(obj):
            obj["fixtures"][1]["provenance"]["authorityWeightTier"] = "9"
        out = os.path.join(self.tmp, "must-not-exist.json")
        rejected = self.val_reject(
            "out mode validates before final artifact",
            SCRIPT,
            self.write_fixture(mut),
            "--tool-dir",
            self.tool_dir(),
            "--out",
            out,
        )
        self.assertIn("emitted register failed v2 validation", rejected.stdout.decode("utf-8", "replace"))
        self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    import unittest
    unittest.main()
