#!/usr/bin/env python3
"""[fast]  Stage A/B whole-suite lit accounting and dead-harness probes."""

import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import xml.etree.ElementTree as ET

from _fastcase import REPO

sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
import run_lit_suite_accounting as gate  # noqa: E402


BASELINE = {
    "kind": gate.BASELINE_KIND,
    "schemaVersion": 1,
    "stage": "A",
    "state": "UNARMED",
}

COMMIT = "0" * 39 + "b"
OTHER_COMMIT = "0" * 39 + "c"


class LitSuiteAccounting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.json_path = self.root / "lit.json"
        self.xml_path = self.root / "lit.xml"

    def write_json(self, rows, path=None):
        (path or self.json_path).write_text(json.dumps({
            "__version__": [18, 1, 8],
            "elapsed": 0.1,
            "tests": [
                {"name": name, "code": code, "output": "", "elapsed": 0.01}
                for name, code in rows
            ],
        }), encoding="utf-8")

    def write_xunit(self, rows, declared=None, out=None):
        root = ET.Element("testsuites", {"time": "0.10"})
        suite = ET.SubElement(root, "testsuite", {
            "name": "neutrino-ir",
            "tests": str(len(rows) if declared is None else declared),
            "failures": str(sum(code in {
                "FAIL", "XPASS", "TIMEOUT", "UNRESOLVED"
            } for _path, code in rows)),
            "skipped": str(sum(code in {
                "UNSUPPORTED", "SKIPPED", "EXCLUDED"
            } for _path, code in rows)),
        })
        for path, code in rows:
            parts = path.split("/")
            # lit spells a root-level testcase class as "<suite>.<suite>".
            class_name = "neutrino-ir.neutrino-ir"
            if len(parts) > 1:
                class_name = "neutrino-ir." + ".".join(parts[:-1])
            case = ET.SubElement(suite, "testcase", {
                "classname": class_name,
                "name": parts[-1],
                "time": "0.01",
            })
            if code in {"FAIL", "XPASS", "TIMEOUT", "UNRESOLVED"}:
                ET.SubElement(case, "failure")
            elif code in {"UNSUPPORTED", "SKIPPED", "EXCLUDED"}:
                ET.SubElement(case, "skipped")
        ET.ElementTree(root).write(out or self.xml_path, encoding="unicode")

    @staticmethod
    def full(path):
        return f"neutrino-ir :: {path}"

    def assert_diag(self, code, callback):
        with self.assertRaises(gate.AccountingError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_happy_report_is_deterministic_total_disjoint_partition(self):
        rows = [
            ("root.test", "PASS"),
            ("a/pass.test", "PASS"),
            ("b/fail.test", "FAIL"),
            ("b/xfail.test", "XFAIL"),
            ("c/unsupported.test", "UNSUPPORTED"),
        ]
        self.write_json([(self.full(path), code) for path, code in rows])
        self.write_xunit(rows)
        first = gate.build_report(self.json_path, self.xml_path, 1, BASELINE)
        second = gate.build_report(self.json_path, self.xml_path, 1, BASELINE)
        self.assertEqual(first, second)
        self.assertEqual(first["counts"]["discovered"], 5)
        self.assertEqual(first["counts"]["attempted"], 4)
        self.assertEqual(first["counts"]["executed"], 4)
        flattened = [
            identity
            for category in gate.CATEGORIES
            for identity in first["categories"][category]
        ]
        self.assertEqual(sorted(flattened), first["discoveredIdentities"])
        self.assertEqual(len(flattened), len(set(flattened)))

    def test_empty_execution_bites(self):
        rows = [("only/unsupported.test", "UNSUPPORTED")]
        self.write_json([(self.full(path), code) for path, code in rows])
        self.write_xunit(rows)
        self.assert_diag(
            "zero-attempted",
            lambda: gate.build_report(
                self.json_path, self.xml_path, 0, BASELINE))

    def test_duplicate_accounting_bites(self):
        name = self.full("dup.test")
        self.write_json([(name, "PASS"), (name, "PASS")])
        self.write_xunit([("dup.test", "PASS")])
        self.assert_diag(
            "identity-duplicate",
            lambda: gate.build_report(
                self.json_path, self.xml_path, 0, BASELINE))

    def test_incomplete_accounting_bites(self):
        self.write_json([(self.full("present.test"), "PASS")])
        self.write_xunit([
            ("present.test", "PASS"),
            ("missing.test", "PASS"),
        ])
        self.assert_diag(
            "report-incomplete",
            lambda: gate.build_report(
                self.json_path, self.xml_path, 0, BASELINE))

    def test_malformed_report_bites(self):
        self.json_path.write_text("{", encoding="utf-8")
        self.write_xunit([("probe.test", "PASS")])
        self.assert_diag(
            "report-malformed",
            lambda: gate.build_report(
                self.json_path, self.xml_path, 0, BASELINE))

    def test_exit_status_suppression_bites(self):
        rows = [("failure.test", "FAIL")]
        self.write_json([(self.full(path), code) for path, code in rows])
        self.write_xunit(rows)
        self.assert_diag(
            "status-suppressed",
            lambda: gate.build_report(
                self.json_path, self.xml_path, 0, BASELINE))

    def test_unarmed_terminal_refuses_before_lit_invocation(self):
        baseline = self.root / "baseline.json"
        baseline.write_text(json.dumps(BASELINE), encoding="utf-8")
        with unittest.mock.patch.object(gate.subprocess, "run") as invoke:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = gate.run(
                    "lit", "suite", self.root / "report.json", baseline, True)
        self.assertEqual(result, 2)
        invoke.assert_not_called()
        self.assertIn("[lit-accounting.unarmed-terminal]", stderr.getvalue())

    def test_forged_armed_baselines_refuse_before_lit_invocation(self):
        for stage in ("A", "B"):
            with self.subTest(stage=stage):
                forged = dict(BASELINE, state="ARMED", stage=stage)
                baseline = self.root / f"armed-{stage}.json"
                baseline.write_text(json.dumps(forged), encoding="utf-8")
                with unittest.mock.patch.object(
                        gate.subprocess, "run") as invoke:
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(stderr):
                        result = gate.run(
                            "lit", "suite", self.root / "report.json",
                            baseline, True)
                self.assertEqual(result, 2)
                invoke.assert_not_called()
                self.assertIn(
                    "[lit-accounting.baseline-malformed]",
                    stderr.getvalue())

    def test_xunit_skip_with_json_pass_bites(self):
        rows = [("contradiction.test", "PASS")]
        self.write_json([(self.full(path), code) for path, code in rows])
        self.write_xunit([("contradiction.test", "UNSUPPORTED")])
        self.assert_diag(
            "skip-mismatch",
            lambda: gate.build_report(
                self.json_path, self.xml_path, 0, BASELINE))

    def test_json_skip_without_xunit_skip_bites(self):
        rows = [("contradiction.test", "UNSUPPORTED")]
        self.write_json([(self.full(path), code) for path, code in rows])
        self.write_xunit([("contradiction.test", "PASS")])
        self.assert_diag(
            "skip-mismatch",
            lambda: gate.build_report(
                self.json_path, self.xml_path, 0, BASELINE))

    def test_json_omitted_xunit_skip_is_accounted(self):
        self.write_json([(self.full("executed.test"), "PASS")])
        self.write_xunit([
            ("executed.test", "PASS"),
            ("omitted.test", "UNSUPPORTED"),
        ])
        report = gate.build_report(
            self.json_path, self.xml_path, 0, BASELINE)
        self.assertEqual(
            report["categories"]["unsupported/skipped"],
            [self.full("omitted.test")])
        self.assertEqual(report["counts"]["discovered"], 2)
        self.assertEqual(report["counts"]["attempted"], 1)
        self.assertEqual(report["counts"]["executed"], 1)

    def test_absent_reports_bite_and_preserve_nonzero_lit_status(self):
        baseline = self.root / "baseline.json"
        baseline.write_text(json.dumps(BASELINE), encoding="utf-8")
        fake = self.root / "fake-lit"
        fake.write_text("#!/bin/sh\nexit \"${FAKE_LIT_STATUS:-0}\"\n",
                        encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with unittest.mock.patch.dict(
                    os.environ, {"FAKE_LIT_STATUS": "0"}):
                self.assertEqual(
                    gate.run(str(fake), "suite", self.root / "report.json",
                             baseline, False),
                    2)
        self.assertIn("[lit-accounting.report-absent]", stderr.getvalue())

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with unittest.mock.patch.dict(
                    os.environ, {"FAKE_LIT_STATUS": "7"}):
                self.assertEqual(
                    gate.run(str(fake), "suite", self.root / "report.json",
                             baseline, False),
                    7)
        self.assertIn("[lit-accounting.report-absent]", stderr.getvalue())

    # ---------------------------------------------------------------- Stage B

    def armed(self, identities, skips=None, unresolved=None, commit=COMMIT,
              **overrides):
        """A complete, internally consistent ARMED/B baseline."""
        identities = sorted(identities)
        baseline = {
            "kind": gate.BASELINE_KIND,
            "schemaVersion": 1,
            "stage": "B",
            "state": "ARMED",
            "sourceCommit": commit,
            "discoveredCount": len(identities),
            "discoveredIdentities": identities,
            "identitySetSha256": gate.identity_digest(identities),
            "allowedUnsupportedSkipped": dict(skips or {}),
            "allowedUnresolved": dict(unresolved or {}),
        }
        baseline.update(overrides)
        return baseline

    def load(self, data, name="armed.json"):
        path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return gate.load_baseline(path)

    def assert_baseline_diag(self, code, data, fragment=None):
        with self.assertRaises(gate.AccountingError) as caught:
            self.load(data)
        self.assertEqual(caught.exception.code, code)
        if fragment is not None:
            self.assertIn(fragment, caught.exception.message)

    def report_for(self, rows, status, baseline=BASELINE):
        self.write_json([(self.full(path), code) for path, code in rows])
        self.write_xunit(rows)
        return gate.build_report(self.json_path, self.xml_path, status,
                                 baseline)

    def test_valid_armed_baseline_loads(self):
        """Control: the Stage-B schema is satisfiable, not merely strict."""
        identities = [self.full("a.test"), self.full("b.test")]
        data = self.armed(identities,
                          skips={identities[1]: "no postgres backend here"})
        self.assertEqual(self.load(data), data)

    def test_armed_baseline_missing_each_required_field_bites(self):
        identities = [self.full("a.test")]
        complete = self.armed(identities)
        for field in sorted(complete):
            with self.subTest(missing=field):
                forged = {k: v for k, v in complete.items() if k != field}
                with self.assertRaises(gate.AccountingError) as caught:
                    self.load(forged, name=f"missing-{field}.json")
                # Dropping `state` is caught EARLIER and more precisely, by the
                # state whitelist itself (absent state is not a declared state),
                # rather than by the key-set check. Every other field still
                # fails the shape check.
                expected = ("baseline-state-unknown" if field == "state"
                            else "baseline-malformed")
                self.assertEqual(caught.exception.code, expected)

    def test_armed_baseline_unknown_field_bites(self):
        forged = self.armed([self.full("a.test")], note="hand edited")
        self.assert_baseline_diag("baseline-malformed", forged, "unknown:")

    def test_armed_baseline_wrong_typed_fields_bite(self):
        identities = [self.full("a.test")]
        wrong = {
            "sourceCommit": 12345,
            "discoveredIdentities": "neutrino-ir :: a.test",
            "discoveredCount": "1",
            "identitySetSha256": ["sha256:" + "0" * 64],
            "allowedUnsupportedSkipped": [],
            "allowedUnresolved": None,
        }
        for field, value in sorted(wrong.items()):
            with self.subTest(field=field):
                self.assert_baseline_diag(
                    "baseline-malformed",
                    self.armed(identities, **{field: value}),
                    field)

    def test_armed_baseline_short_or_uppercase_commit_bites(self):
        for commit in ("abc123", "A" * 40, "g" * 40, ""):
            with self.subTest(commit=commit):
                self.assert_baseline_diag(
                    "baseline-malformed",
                    self.armed([self.full("a.test")], commit=commit),
                    "sourceCommit")

    def test_armed_baseline_empty_or_duplicate_identity_set_bites(self):
        self.assert_baseline_diag(
            "baseline-malformed",
            self.armed([], discoveredCount=0,
                       identitySetSha256=gate.identity_digest([])),
            "non-empty")
        duplicated = [self.full("a.test"), self.full("a.test")]
        self.assert_baseline_diag(
            "baseline-malformed",
            self.armed([self.full("a.test")], discoveredIdentities=duplicated,
                       discoveredCount=2),
            "duplicates")
        self.assert_baseline_diag(
            "baseline-malformed",
            self.armed([self.full("a.test")], discoveredIdentities=["  "],
                       discoveredCount=1),
            "empty entry")

    def test_armed_baseline_count_not_equal_to_set_length_bites(self):
        identities = [self.full("a.test"), self.full("b.test")]
        self.assert_baseline_diag(
            "baseline-inconsistent",
            self.armed(identities, discoveredCount=3),
            "discoveredCount 3")
        self.assert_baseline_diag(
            "baseline-inconsistent",
            self.armed(identities, discoveredCount=1),
            "discoveredCount 1")

    def test_armed_baseline_identity_digest_mismatch_bites(self):
        identities = [self.full("a.test"), self.full("b.test")]
        self.assert_baseline_diag(
            "baseline-inconsistent",
            self.armed(identities, identitySetSha256="sha256:" + "0" * 64),
            "identitySetSha256")
        self.assert_baseline_diag(
            "baseline-malformed",
            self.armed(identities, identitySetSha256="deadbeef"),
            "identitySetSha256")

    def test_armed_baseline_allowed_entry_outside_discovered_set_bites(self):
        identities = [self.full("a.test")]
        self.assert_baseline_diag(
            "baseline-inconsistent",
            self.armed(identities,
                       skips={self.full("ghost.test"): "never discovered"}),
            "allowedUnsupportedSkipped")
        self.assert_baseline_diag(
            "baseline-inconsistent",
            self.armed(identities,
                       unresolved={self.full("ghost.test"): "never discovered"}),
            "allowedUnresolved")

    def test_armed_baseline_allowed_entry_without_reason_bites(self):
        identities = [self.full("a.test")]
        for empty in ("", "   "):
            with self.subTest(reason=repr(empty)):
                self.assert_baseline_diag(
                    "baseline-malformed",
                    self.armed(identities, skips={identities[0]: empty}),
                    "no non-empty reason")
                self.assert_baseline_diag(
                    "baseline-malformed",
                    self.armed(identities, unresolved={identities[0]: empty}),
                    "no non-empty reason")
        self.assert_baseline_diag(
            "baseline-malformed",
            self.armed(identities, skips={identities[0]: None}),
            "no non-empty reason")

    def test_armed_baseline_requires_stage_b(self):
        identities = [self.full("a.test")]
        self.assert_baseline_diag(
            "baseline-malformed", self.armed(identities, stage="A"), "stage")
        self.assert_baseline_diag(
            "baseline-malformed", self.armed(identities, stage="C"), "stage")

    def test_unknown_baseline_state_still_fails_closed(self):
        """The STATE WHITELIST must do the rejecting — not an incidental check.

        The earlier form asserted (`baseline-malformed`, substring "PARTIAL"),
        which a widened whitelist still satisfied *for the wrong reason*: the
        key-set check raised `baseline-malformed` with a message beginning
        "PARTIAL baseline keys must be exactly…". So the probe passed while the
        defect it names — an undeclared state inheriting another state's shape —
        was live. It now binds to the whitelist's own distinct code, and to the
        undeclared state carrying a full Stage-B body (which would otherwise sail
        past the key-set check and reach the ratchet unvalidated).
        """
        self.assert_baseline_diag(
            "baseline-state-unknown", dict(BASELINE, state="PARTIAL"), "PARTIAL")
        armed_body = self.armed([self.full("a.test")])
        forged = dict(armed_body, state="PARTIAL")
        self.assert_baseline_diag("baseline-state-unknown", forged, "PARTIAL")

    def test_undeclared_state_cannot_inherit_shape_validation_or_ratchet(self):
        """A state absent from STATES participates in nothing.

        This is the §4 finding: shape, stage, validation and ratchet used to be
        selected by three independent comparisons, so a new token inherited the
        Stage-B key set while inheriting neither its validator nor the ratchet.
        The single table makes that combination unexpressible.
        """
        for state, (stage, keys, validator, ratcheted) in gate.STATES.items():
            with self.subTest(state=state):
                self.assertIsInstance(stage, str)
                self.assertTrue(keys)
                # Any state carrying the Stage-B key set MUST carry a validator
                # and MUST participate in the ratchet.
                if keys == gate.STAGE_B_KEYS:
                    self.assertIsNotNone(
                        validator,
                        f"{state} declares the Stage-B shape with no validator")
                    self.assertTrue(
                        ratcheted,
                        f"{state} declares the Stage-B shape but skips the ratchet")
                if validator is not None:
                    self.assertTrue(callable(gate.globals()[validator])
                                    if hasattr(gate, "globals")
                                    else callable(getattr(gate, validator)))
        # An undeclared state never reaches the ratchet.
        self.assertFalse(gate.is_ratcheted({"state": "PARTIAL"}))
        self.assertFalse(gate.is_ratcheted({"state": "UNARMED"}))
        self.assertTrue(gate.is_ratcheted({"state": "ARMED"}))

    def test_unarmed_baseline_still_requires_exact_stage_a_shape(self):
        self.assert_baseline_diag(
            "baseline-malformed", dict(BASELINE, stage="B"), "stage")
        self.assert_baseline_diag(
            "baseline-malformed", dict(BASELINE, sourceCommit=COMMIT),
            "unknown:")

    # Rule 1 -- discovered-set shrinkage.

    def test_baseline_shrinkage_bites(self):
        banked = [self.full("a.test"), self.full("b.test")]
        baseline = self.armed(banked)
        report = self.report_for([("a.test", "PASS")], 0, baseline)
        with self.assertRaises(gate.AccountingError) as caught:
            gate.compare_to_baseline(report, baseline)
        self.assertEqual(caught.exception.code, "baseline-shrinkage")
        self.assertIn("b.test", caught.exception.message)

    def test_delete_one_add_one_swap_bites_and_does_not_net_out(self):
        """Growth must never offset shrinkage: compare per identity, not by count."""
        banked = [self.full("a.test"), self.full("b.test")]
        baseline = self.armed(banked)
        report = self.report_for(
            [("a.test", "PASS"), ("new.test", "PASS")], 0, baseline)
        # The counts are identical -- a count comparison would call this clean.
        self.assertEqual(report["counts"]["discovered"],
                         baseline["discoveredCount"])
        with self.assertRaises(gate.AccountingError) as caught:
            gate.compare_to_baseline(report, baseline)
        self.assertEqual(caught.exception.code, "baseline-shrinkage")
        self.assertIn("b.test", caught.exception.message)

    def test_pure_addition_passes(self):
        """Guard against over-tightening: a newly discovered test is not a failure."""
        banked = [self.full("a.test"), self.full("b.test")]
        baseline = self.armed(banked)
        report = self.report_for(
            [("a.test", "PASS"), ("b.test", "PASS"), ("new.test", "PASS")],
            0, baseline)
        gate.compare_to_baseline(report, baseline)
        self.assertEqual(report["counts"]["discovered"], 3)

    # Rule 2 -- unexplained skip growth.

    def test_unexplained_skip_growth_bites(self):
        banked = [self.full("a.test"), self.full("b.test")]
        baseline = self.armed(banked)
        report = self.report_for(
            [("a.test", "PASS"), ("b.test", "UNSUPPORTED")], 0, baseline)
        with self.assertRaises(gate.AccountingError) as caught:
            gate.compare_to_baseline(report, baseline)
        self.assertEqual(caught.exception.code, "baseline-skip-growth")
        self.assertIn("b.test", caught.exception.message)

    def test_a_newly_added_test_that_arrives_skipped_bites(self):
        banked = [self.full("a.test")]
        baseline = self.armed(banked)
        report = self.report_for(
            [("a.test", "PASS"), ("new.test", "UNSUPPORTED")], 0, baseline)
        with self.assertRaises(gate.AccountingError) as caught:
            gate.compare_to_baseline(report, baseline)
        self.assertEqual(caught.exception.code, "baseline-skip-growth")

    def test_explicitly_allowed_skip_passes(self):
        banked = [self.full("a.test"), self.full("b.test")]
        baseline = self.armed(
            banked, skips={self.full("b.test"): "requires the postgres backend"})
        report = self.report_for(
            [("a.test", "PASS"), ("b.test", "UNSUPPORTED")], 0, baseline)
        gate.compare_to_baseline(report, baseline)

    # Rule 3 -- new unresolved tests.

    def test_new_unresolved_bites(self):
        banked = [self.full("a.test"), self.full("b.test")]
        baseline = self.armed(banked)
        report = self.report_for(
            [("a.test", "PASS"), ("b.test", "UNRESOLVED")], 1, baseline)
        with self.assertRaises(gate.AccountingError) as caught:
            gate.compare_to_baseline(report, baseline)
        self.assertEqual(caught.exception.code, "baseline-unresolved-growth")
        self.assertIn("b.test", caught.exception.message)

    def test_explicitly_allowed_unresolved_passes(self):
        banked = [self.full("a.test"), self.full("b.test")]
        baseline = self.armed(
            banked,
            unresolved={self.full("b.test"): "known unresolved, tracked by "})
        report = self.report_for(
            [("a.test", "PASS"), ("b.test", "UNRESOLVED")], 1, baseline)
        gate.compare_to_baseline(report, baseline)

    # Rule 4 -- total partition against the banked set.

    def test_result_identity_absent_from_partition_bites(self):
        banked = [self.full("a.test"), self.full("b.test")]
        baseline = self.armed(banked)
        report = self.report_for(
            [("a.test", "PASS"), ("b.test", "PASS")], 0, baseline)
        gate.compare_to_baseline(report, baseline)
        forged = json.loads(json.dumps(report))
        forged["categories"]["passed"].remove(self.full("b.test"))
        with self.assertRaises(gate.AccountingError) as caught:
            gate.compare_to_baseline(forged, baseline)
        self.assertEqual(caught.exception.code, "baseline-partition")
        self.assertIn("b.test", caught.exception.message)

    def test_identity_counted_twice_in_the_partition_bites(self):
        banked = [self.full("a.test")]
        baseline = self.armed(banked)
        report = self.report_for([("a.test", "PASS")], 0, baseline)
        forged = json.loads(json.dumps(report))
        forged["categories"]["xfail"].append(self.full("a.test"))
        with self.assertRaises(gate.AccountingError) as caught:
            gate.compare_to_baseline(forged, baseline)
        self.assertEqual(caught.exception.code, "baseline-partition")

    def test_partition_carrying_an_undiscovered_identity_bites(self):
        banked = [self.full("a.test")]
        baseline = self.armed(banked)
        report = self.report_for([("a.test", "PASS")], 0, baseline)
        forged = json.loads(json.dumps(report))
        forged["categories"]["passed"].append(self.full("phantom.test"))
        with self.assertRaises(gate.AccountingError) as caught:
            gate.compare_to_baseline(forged, baseline)
        self.assertEqual(caught.exception.code, "baseline-partition")

    def test_unarmed_baseline_runs_no_ratchet(self):
        report = self.report_for([("a.test", "PASS")], 0, BASELINE)
        gate.compare_to_baseline(report, BASELINE)

    # Terminal mode.

    def test_terminal_accepts_a_valid_armed_baseline(self):
        """Every baseline check passes and lit is reached (parent-bound model)."""
        result, err, calls = self._terminal_with_git(
            head="1" * 40, parent=COMMIT, changed=[self.BASELINE_PATH])
        self.assertNotIn("baseline-provenance", err)
        self.assertNotIn("baseline-arming-delta", err)
        self.assertNotIn("baseline-dirty-tree", err)
        self.assertTrue([c for c in calls if c and c[0] == "lit"],
                        "lit was never reached on a valid arming commit")

    def test_non_terminal_provenance_still_compares_the_run_commit(self):
        """The non-terminal path keeps the direct HEAD/--source-commit comparison.

        Terminal mode moved to the parent binding (see the HEAD^ probes below);
        this retains the diagnostic form for non-terminal callers, so dropping
        the terminal comparison did not silently delete the check itself.
        """
        baseline = self.armed([self.full("a.test")])
        with self.assertRaises(gate.AccountingError) as caught:
            gate.verify_provenance(baseline, OTHER_COMMIT, terminal=False)
        self.assertEqual(caught.exception.code, "baseline-provenance")
        # The matching commit is accepted.
        self.assertEqual(
            gate.verify_provenance(baseline, COMMIT, terminal=False), COMMIT)

    def test_terminal_refuses_a_dirty_tree_before_lit_invocation(self):
        """Commit match alone does not establish reproducibility (§6a).

        The tree can sit at the armed SHA with uncommitted edits, and 's
        single authorised run feeds a milestone verdict whose entire claim is
        "this evidence is reproducible from this SHA". Refused BEFORE lit, so a
        dirty terminal run cannot produce evidence at all.
        """
        baseline = self.root / "armed-dirty.json"
        baseline.write_text(json.dumps(self.armed([self.full("a.test")])),
                            encoding="utf-8")
        real_run = gate.subprocess.run

        def fake(cmd, *args, **kwargs):
            if list(cmd)[-1:] == ["HEAD"]:            # rev-parse HEAD
                return subprocess.CompletedProcess(cmd, 0, COMMIT + "\n", "")
            if "--porcelain" in list(cmd):            # status --porcelain
                return subprocess.CompletedProcess(
                    cmd, 0, " M scripts/gates/run_lit_suite_accounting.py\n", "")
            return real_run(cmd, *args, **kwargs)     # would be lit

        with unittest.mock.patch.object(gate.subprocess, "run", side_effect=fake) as invoke:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = gate.run("lit", "suite", self.root / "report.json",
                                  baseline, True, COMMIT)
        self.assertEqual(result, 2)
        self.assertIn("[lit-accounting.baseline-dirty-tree]", stderr.getvalue())
        # lit was never launched — only the two git probes ran.
        for call in invoke.call_args_list:
            self.assertIn("git", list(call.args[0])[0])

    def test_terminal_accepts_a_clean_tree_at_the_armed_commit(self):
        """Over-tightening guard for the dirty-tree check itself."""
        result, err, calls = self._terminal_with_git(
            head="1" * 40, parent=COMMIT, changed=[self.BASELINE_PATH], dirty="")
        self.assertNotIn("baseline-dirty-tree", err)
        self.assertTrue([c for c in calls if c and c[0] == "lit"],
                        "lit was never invoked on a clean armed tree")

    def _terminal_with_git(self, head, parent, changed, dirty="", commit=COMMIT):
        """Drive terminal mode with a scripted git, returning (exit, stderr, calls)."""
        baseline = self.root / f"armed-{parent[:6]}.json"
        baseline.write_text(json.dumps(self.armed([self.full("a.test")],
                                                  commit=commit)),
                            encoding="utf-8")
        calls = []

        def fake(cmd, *args, **kwargs):
            argv = list(cmd)
            calls.append(argv)
            if argv[0] != "git":
                return subprocess.CompletedProcess(argv, 0, "", "")
            if "--porcelain" in argv:
                return subprocess.CompletedProcess(argv, 0, dirty, "")
            if argv[-1] == "HEAD":
                return subprocess.CompletedProcess(argv, 0, head + "\n", "")
            if argv[-1] == "HEAD^":
                return subprocess.CompletedProcess(argv, 0, parent + "\n", "")
            if "--name-only" in argv:
                return subprocess.CompletedProcess(
                    argv, 0, "\n".join(changed) + "\n", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with unittest.mock.patch.object(gate.subprocess, "run", side_effect=fake):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = gate.run("lit", "suite", self.root / "report.json",
                                  baseline, True, None)
        return result, stderr.getvalue(), calls

    BASELINE_PATH = "docs/m6-lit-suite-accounting-baseline.json"

    def test_terminal_refuses_when_parent_is_not_the_source_commit(self):
        """The arming commit must sit DIRECTLY atop the commit it was measured at.

        `sourceCommit` names the clean parent because a baseline cannot contain
        the hash of the commit that ships it. If main advanced underneath, HEAD^
        is no longer that commit and the evidence no longer describes this tree.
        """
        result, err, calls = self._terminal_with_git(
            head="1" * 40, parent=OTHER_COMMIT, changed=[self.BASELINE_PATH])
        self.assertEqual(result, 2)
        self.assertIn("[lit-accounting.baseline-provenance]", err)
        self.assertIn("HEAD^", err)
        self.assertFalse([c for c in calls if c and c[0] == "lit"],
                         "lit ran despite a wrong arming parent")

    def test_terminal_refuses_an_arming_delta_carrying_production_files(self):
        """Without this, the parent-anchor would be decorative.

        A commit can sit correctly atop the source commit and still smuggle
        arbitrary production changes into the arming delta.
        """
        result, err, calls = self._terminal_with_git(
            head="1" * 40, parent=COMMIT,
            changed=[self.BASELINE_PATH, "lib/backends/solidity/SolidityEmit.cpp"])
        self.assertEqual(result, 2)
        self.assertIn("[lit-accounting.baseline-arming-delta]", err)
        self.assertIn("SolidityEmit.cpp", err)
        self.assertFalse([c for c in calls if c and c[0] == "lit"],
                         "lit ran despite a stray production file in the arming delta")

    def test_terminal_refuses_an_arming_delta_that_does_not_touch_the_baseline(self):
        result, err, _ = self._terminal_with_git(
            head="1" * 40, parent=COMMIT, changed=["Makefile"])
        self.assertEqual(result, 2)
        self.assertIn("[lit-accounting.baseline-arming-delta]", err)

    def test_terminal_source_commit_flag_cannot_override_the_parent_binding(self):
        """`--source-commit` must NOT be authoritative in terminal mode.

        Honouring it would reduce provenance to a caller-supplied assertion —
        exactly the bypass the parent-binding exists to close.
        """
        baseline = self.root / "armed-bypass.json"
        baseline.write_text(json.dumps(self.armed([self.full("a.test")])),
                            encoding="utf-8")

        def fake(cmd, *args, **kwargs):
            argv = list(cmd)
            if argv[0] != "git":
                return subprocess.CompletedProcess(argv, 0, "", "")
            if "--porcelain" in argv:
                return subprocess.CompletedProcess(argv, 0, "", "")
            if argv[-1] == "HEAD":
                return subprocess.CompletedProcess(argv, 0, "1" * 40 + "\n", "")
            if argv[-1] == "HEAD^":
                # The real parent is NOT the banked sourceCommit.
                return subprocess.CompletedProcess(argv, 0, OTHER_COMMIT + "\n", "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with unittest.mock.patch.object(gate.subprocess, "run", side_effect=fake):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                # A caller asserting the "right" commit must not escape the check.
                result = gate.run("lit", "suite", self.root / "report.json",
                                  baseline, True, COMMIT)
        self.assertEqual(result, 2)
        self.assertIn("[lit-accounting.baseline-provenance]", stderr.getvalue())

    def test_terminal_accepts_a_correct_arming_commit(self):
        """Over-tightening guard: clean tree + right parent + allowlisted delta."""
        result, err, calls = self._terminal_with_git(
            head="1" * 40, parent=COMMIT,
            changed=[self.BASELINE_PATH, "Makefile",
                     "scripts/gates/run_lit_suite_accounting.py",
                     "test/checks/fast/lit_suite_accounting_test.py"])
        self.assertNotIn("baseline-provenance", err)
        self.assertNotIn("baseline-arming-delta", err)
        self.assertTrue([c for c in calls if c and c[0] == "lit"],
                        "lit was never reached on a correct arming commit")

    def test_registered_lit_ctest_stays_non_terminal(self):
        """The ordinary row must never carry --terminal.

        Terminal mode refuses a dirty tree and binds provenance to HEAD^; if the
        registered row carried it, every later head and every developer tree
        would fail. The ratchet still applies there because compare_to_baseline
        is deliberately NOT terminal-gated.
        """
        cmake = (Path(REPO) / "cmake" / "NeutrinoTests.cmake").read_text(
            encoding="utf-8")
        self.assertIn("run_lit_suite_accounting.py", cmake)
        self.assertNotIn("--terminal", cmake)

    def test_armed_ratchet_bites_end_to_end_through_run(self):
        banked = [self.full("a.test"), self.full("b.test")]
        baseline = self.root / "armed-e2e.json"
        baseline.write_text(json.dumps(self.armed(banked)), encoding="utf-8")
        report_path = self.root / "report.json"

        def fake_lit(command, *args, **kwargs):
            # Terminal mode probes git first: clean tree, then HEAD/HEAD^ and the
            # arming delta. Answer them so the run reaches lit and the RATCHET is
            # what bites, not provenance.
            argv = list(command)
            if argv and argv[0] == "git":
                if "--porcelain" in argv:
                    return subprocess.CompletedProcess(argv, 0, "", "")
                if argv[-1] == "HEAD":
                    return subprocess.CompletedProcess(argv, 0, "1" * 40 + "\n", "")
                if argv[-1] == "HEAD^":
                    return subprocess.CompletedProcess(argv, 0, COMMIT + "\n", "")
                if "--name-only" in argv:
                    return subprocess.CompletedProcess(
                        argv, 0,
                        "docs/m6-lit-suite-accounting-baseline.json\n", "")
                return subprocess.CompletedProcess(argv, 0, "", "")
            rows = [("a.test", "PASS"), ("new.test", "PASS")]
            self.write_json([(self.full(p), c) for p, c in rows],
                            path=Path(command[command.index("-o") + 1]))
            self.write_xunit(
                rows,
                out=Path(command[command.index("--xunit-xml-output") + 1]))
            return subprocess.CompletedProcess(command, 0)

        with unittest.mock.patch.object(gate.subprocess, "run", fake_lit):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = gate.run("lit", "suite", report_path, baseline, True,
                                  COMMIT)
        self.assertEqual(result, 2)
        self.assertIn("[lit-accounting.baseline-shrinkage]", stderr.getvalue())
        # The evidence a reviewed baseline update would rest on is still written.
        written = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(written["baselineState"], "ARMED")

    def test_committed_baseline_is_armed_at_repaired_parent(self):
        committed = json.loads(
            (Path(REPO) / "docs" / "m6-lit-suite-accounting-baseline.json")
            .read_text(encoding="utf-8"))
        loaded = gate.load_baseline(gate.DEFAULT_BASELINE)
        self.assertEqual(loaded, committed)
        self.assertEqual(committed["stage"], "B")
        self.assertEqual(committed["state"], "ARMED")
        self.assertEqual(
            committed["sourceCommit"],
            "fd055d1ad4b94301008685c494c8874be4928581")
        self.assertEqual(committed["discoveredCount"], 196)
        self.assertEqual(
            committed["discoveredCount"],
            len(committed["discoveredIdentities"]))
        self.assertEqual(
            committed["identitySetSha256"],
            gate.identity_digest(committed["discoveredIdentities"]))
        self.assertEqual(committed["allowedUnsupportedSkipped"], {})
        self.assertEqual(committed["allowedUnresolved"], {})


if __name__ == "__main__":
    unittest.main()
