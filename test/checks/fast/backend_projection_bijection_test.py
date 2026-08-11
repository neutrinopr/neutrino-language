#!/usr/bin/env python3
"""Fast checks for the Tier-2-final backend-projection reconciliation."""
import copy
import json
import os
import subprocess
import sys
import unittest

from _fastcase import REPO

GATE = os.path.join(
    REPO, "scripts", "gates", "check_backend_projection_bijection.py"
)

sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
import check_backend_projection_bijection as gate  # noqa: E402
import check_backend_projection_family_reconciliation as family_gate  # noqa: E402

TERMINAL = gate._load(gate.INVENTORY).get("terminalStructuralZero") is not None


def _run(*args):
    return subprocess.run(
        [sys.executable, GATE, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@unittest.skipIf(
    TERMINAL,
    "the frozen occurrence ledger is immutable historical evidence after ",
)
class BackendProjectionBijection(unittest.TestCase):
    @staticmethod
    def _inventory_with_retired_addition():
        #  G1-S1 landed 20 real additionRetirements (the status-authority
        # atoms migrated to the generated idiom table). This fixture ADDS a
        # synthetic declared-addition-then-retired record ALONGSIDE them (never
        # overwriting them), and returns that synthetic record's live reference in
        # the additionRetirements list so a test can mutate exactly it.
        inv = gate._load(gate.INVENTORY)
        record = copy.deepcopy(inv["migration"]["additions"][0])
        record["occurrence"] = "postgres:legalizePostgres:control:if:0-retired-fixture"
        inv["migration"]["additions"].append(record)
        inv["migration"]["additions"].sort(key=lambda item: item["occurrence"])
        synthetic = copy.deepcopy(record)
        inv["migration"]["additionRetirements"].append(synthetic)
        inv["migration"]["additionRetirements"].sort(
            key=lambda item: item["occurrence"]
        )
        return inv, synthetic

    def test_final_snapshot_is_bijective_and_non_vacuous(self):
        result = _run()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        report = json.loads(result.stdout)
        self.assertIs(report["conformant"], True)
        self.assertEqual(report["diagnostics"], [])
        self.assertGreaterEqual(report["counts"]["rows"], 15)
        self.assertGreaterEqual(report["counts"]["sites"], 30)
        self.assertGreaterEqual(report["counts"]["decisionOccurrences"], 150)
        self.assertEqual(report["counts"]["governedFunctions"], 10)
        self.assertEqual(report["counts"]["traces"], 3)
        self.assertEqual(report["counts"]["unsupported"], 1)

    def test_selftest(self):
        result = _run("--selftest")
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_anchored_identity_survives_earlier_same_kind_deletion(self):
        first = "if (coordinationPlan.effects.empty()) return 1;"
        survivor = "if (coordinationPlan.balanced) return 2;"
        before = gate.Counter(
            gate._decision_surface("{" + first + survivor + "}", [])
        )
        after = gate.Counter(gate._decision_surface("{" + survivor + "}", []))
        self.assertTrue(after)
        self.assertFalse(after - before)

    def test_anchored_identity_survives_independent_reordering(self):
        first = "if (coordinationPlan.effects.empty()) return 1;"
        second = "if (coordinationPlan.balanced) return 2;"
        forward = gate.Counter(
            gate._decision_surface("{" + first + second + "}", [])
        )
        reverse = gate.Counter(
            gate._decision_surface("{" + second + first + "}", [])
        )
        self.assertEqual(forward, reverse)

    def test_anchored_identity_changes_with_governed_expression(self):
        before = set(
            gate._decision_surface(
                "{if (coordinationPlan.balanced) return 2;}", []
            )
        )
        after = set(
            gate._decision_surface(
                "{if (!coordinationPlan.balanced) return 2;}", []
            )
        )
        self.assertTrue(before)
        self.assertTrue(after)
        self.assertTrue(before.isdisjoint(after))

    def test_duplicate_anchored_identities_are_distinct_and_deterministic(self):
        statement = "if (coordinationPlan.balanced) return 2;"
        body = "{" + statement + statement + "}"
        anchors = gate._decision_surface(body, [])
        first = [
            gate._persistent_identity(anchor, f"fixture:duplicate:{index}")
            for index, anchor in enumerate(anchors)
        ]
        second = [
            gate._persistent_identity(anchor, f"fixture:duplicate:{index}")
            for index, anchor in enumerate(gate._decision_surface(body, []))
        ]
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        self.assertEqual(len(first), len(set(first)))
        self.assertEqual(
            len({gate._identity_anchor(identity) for identity in first}), 2
        )

    def test_deleting_first_identical_duplicate_preserves_second_identity(self):
        statement = "if (coordinationPlan.balanced) return 2;"
        single = gate._decision_surface("{" + statement + "}", [])
        doubled = gate._decision_surface(
            "{" + statement + statement + "}", []
        )
        expected = gate.Counter(single)
        expected.update(single)
        self.assertEqual(gate.Counter(doubled), expected)

        first = {
            gate._persistent_identity(anchor, "fixture:first:" + anchor)
            for anchor in single
        }
        second = {
            gate._persistent_identity(anchor, "fixture:second:" + anchor)
            for anchor in single
        }
        owned_before = first | second
        owned_after = owned_before - first

        self.assertEqual(owned_after, second)
        self.assertEqual(
            gate.Counter(map(gate._identity_anchor, owned_after)),
            gate.Counter(single),
        )
        self.assertTrue(first.isdisjoint(owned_after))

    def test_string_literal_substitution_changes_anchored_identity(self):
        alpha = set(
            gate._decision_surface(
                '{if (coordinationPlan.procedure == "alpha") return 1;}', []
            )
        )
        beta = set(
            gate._decision_surface(
                '{if (coordinationPlan.procedure == "beta") return 1;}', []
            )
        )
        self.assertTrue(alpha)
        self.assertTrue(beta)
        self.assertTrue(alpha.isdisjoint(beta))

    def test_real_backend_string_literal_substitution_changes_surface(self):
        rel = "lib/backends/postgres/PostgresModel.cpp"
        with open(os.path.join(REPO, rel), encoding="utf-8") as handle:
            source = handle.read()
        body = gate._function_body(source, "legalizePostgresTemporal")
        self.assertIn('"procedure has no ledger entries"', body)
        mutated = body.replace(
            '"procedure has no ledger entries"',
            '"procedure has no effects"',
            1,
        )
        governed = gate._load(gate.INVENTORY)["governedSymbols"]["postgres"]
        before = gate.Counter(gate._decision_surface(body, governed))
        after = gate.Counter(gate._decision_surface(mutated, governed))
        self.assertNotEqual(before, after)
        self.assertTrue(before - after)
        self.assertTrue(after - before)

    def test_cross_row_source_binding_swap_fails_both_reconciliation_gates(self):
        inv = gate._load(gate.INVENTORY)
        traces = gate._load(gate.TRACES)
        gate._apply_probe("cross-row-source-binding", inv, traces)

        bijection_errors = gate._validate_inventory(inv)
        self.assertTrue(
            any(
                error.startswith("bijection.cross_owner_source_binding:")
                for error in bijection_errors
            ),
            bijection_errors,
        )
        family_errors = family_gate.validate(inv)
        self.assertTrue(
            any(
                error.startswith("reconciliation.cross_row_source_binding:")
                for error in family_errors
            ),
            family_errors,
        )

    def test_identity_migration_exactly_covers_current_live_surface(self):
        inv = gate._load(gate.INVENTORY)
        errors = gate._validate_inventory(inv)
        self.assertFalse(
            [error for error in errors if "identity_migration" in error],
            errors,
        )
        entries = inv["decisionIdentityMigration"]["entries"]
        live = sum(
            len(group["occurrences"])
            for group in inv["decisionOccurrenceOwnership"]
        )
        self.assertEqual(len(entries), gate.IDENTITY_MIGRATION_COUNT)
        self.assertEqual(
            len({entry["old"] for entry in entries}),
            gate.IDENTITY_MIGRATION_COUNT,
        )
        self.assertEqual(
            len({entry["new"] for entry in entries}),
            gate.IDENTITY_MIGRATION_COUNT,
        )
        migrated = {entry["new"] for entry in entries}
        current = {
            identity
            for group in inv["decisionOccurrenceOwnership"]
            for identity in group["occurrences"]
        }
        self.assertEqual(len(current), live)
        self.assertTrue(current.issubset(migrated))

    def test_real_611_preimage_derives_exact_source_bound_retirements(self):
        inv = gate._load(gate.INVENTORY)
        errors = gate._validate_inventory(inv)
        self.assertFalse(
            [
                error
                for error in errors
                if error.startswith("bijection.611_preimage_")
            ],
            errors,
        )
        self.assertEqual(errors, [])
        self.assertEqual(family_gate.validate(inv), [])

    def test_nonempty_addition_retirement_lifecycle_is_valid(self):
        inv, _ = self._inventory_with_retired_addition()
        self.assertEqual(gate._validate_inventory(inv), [])

    def test_addition_retirement_malformed_record_bites(self):
        inv, synthetic = self._inventory_with_retired_addition()
        synthetic["unexpected"] = "field"
        self.assertIn(
            "bijection.migration_addition_retirement_shape:" + repr(synthetic),
            gate._validate_inventory(inv),
        )

    def test_addition_retirement_provenance_mismatch_bites(self):
        inv, synthetic = self._inventory_with_retired_addition()
        synthetic["destination"] = "LifecycleState.terminal"
        self.assertIn(
            "bijection.migration_addition_retirement_provenance:"
            + synthetic["occurrence"],
            gate._validate_inventory(inv),
        )

    def test_undeclared_addition_retirement_bites(self):
        inv, synthetic = self._inventory_with_retired_addition()
        inv["migration"]["additions"] = [
            item
            for item in inv["migration"]["additions"]
            if item["occurrence"] != synthetic["occurrence"]
        ]
        self.assertIn(
            "bijection.migration_addition_retirement_undeclared:"
            + synthetic["occurrence"],
            gate._validate_inventory(inv),
        )

    def test_duplicate_addition_retirement_bites(self):
        inv, synthetic = self._inventory_with_retired_addition()
        inv["migration"]["additionRetirements"].append(copy.deepcopy(synthetic))
        self.assertIn(
            "bijection.migration_addition_retirement_duplicate:"
            + synthetic["occurrence"],
            gate._validate_inventory(inv),
        )

    def test_addition_retirement_resurrection_bites(self):
        # An addition that is still PRESENT + owned (a projection-consumption
        # addition, not one of the status-authority atoms retired by G1-S1) cannot
        # be addition-retired: it must be absent + unowned first.
        inv = gate._load(gate.INVENTORY)
        record = copy.deepcopy(
            next(
                a
                for a in inv["migration"]["additions"]
                if a["owningSlice"] != "d657-status-authority-surface"
            )
        )
        inv["migration"]["additionRetirements"].append(record)
        errors = gate._validate_inventory(inv)
        self.assertIn(
            "bijection.migration_addition_retirement_resurrected:"
            + record["occurrence"],
            errors,
        )
        self.assertIn(
            "bijection.migration_addition_retirement_still_owned:"
            + record["occurrence"],
            errors,
        )

    def test_baseline_and_addition_retirement_overlap_bites(self):
        inv = gate._load(gate.INVENTORY)
        record = copy.deepcopy(inv["migration"]["retirements"][0])
        inv["migration"]["additions"].append(copy.deepcopy(record))
        inv["migration"]["additions"].sort(key=lambda item: item["occurrence"])
        inv["migration"]["additionRetirements"] = [copy.deepcopy(record)]
        self.assertIn(
            "bijection.migration_retire_addition_retirement_overlap:"
            + record["occurrence"],
            gate._validate_inventory(inv),
        )

    def test_status_authority_baseline_refreeze_bites_both_validators(self):
        #  G1-S1 consumed the status-authority atoms into the generated idiom
        # table and additionRetired their 20 identities;  then retired its
        # exact 69 owned occurrences, so the live surface is now 224 while the
        # pre-migration baseline stays frozen at 314. The rejected
        #  mutable-baseline refreeze to 334 (which had tried to absorb those
        # 20 identities) is still rejected by BOTH independent 314 pins — the
        # bijection frozen constant and the family reconciliation gate.
        inv = gate._load(gate.INVENTORY)
        live = sum(
            len(group["occurrences"])
            for group in inv["decisionOccurrenceOwnership"]
        )
        self.assertEqual(live, 224)
        self.assertEqual(gate.MIGRATION_BASELINE, 314)
        self.assertEqual(family_gate.FROZEN_BASELINE, 314)

        inv["migration"]["baseline"] = 334
        inv["familyReconciliation"]["frozenBaseline"] = 334
        self.assertIn(
            "bijection.migration_baseline_frozen:334!=314",
            gate._validate_inventory(inv),
        )
        family_errors = family_gate.validate(inv)
        self.assertIn("reconciliation.frozen_baseline", family_errors)
        self.assertIn("reconciliation.migration_baseline", family_errors)

    def test_status_authority_slice_cannot_launder_identity_row(self):
        inv = gate._load(gate.INVENTORY)
        record = next(
            record
            for record in inv["migration"]["additions"]
            if record["owningSlice"] == "d657-status-authority-surface"
        )
        record["owningSlice"] = "d657-identity-terminal-projection"
        self.assertIn(
            "bijection.migration_addition_slice_row:"
            + record["occurrence"]
            + ":d657-identity-terminal-projection~status-authority",
            gate._validate_inventory(inv),
        )

    def test_every_b1_b4_tamper_bites(self):
        self.assertEqual(
            set(gate.PROBES),
            {
                "duplicate-site",
                "unclassified-site",
                "rail-hole",
                "source-drift",
                "decision-surface-hole",
                "decision-occurrence-unowned",
                "decision-occurrence-multiply",
                "decision-local-field-unowned",
                "decision-ternary-unowned",
                "group-duplicate-posting",
                "balance-extra-group",
                "posting-expansion-removal",
                "posting-expansion-substitution",
                "rollback-discharge-missing",
                "rollback-discharge-wrong",
                "rollback-discharge-ambiguous",
                "fixture-binding-missing",
                "source-binding-garbage",
                "trace-value-fabricated",
                "compensate-accepted",
                "intake-bypass",
                "migration-baseline-tamper",
                "migration-baseline-coordinated-tamper",
                "migration-retirement-dropped",
                "migration-retirement-duplicate",
                "migration-retirement-cross-family-row",
                "migration-preimage-binding-substitution",
                "migration-addition-wrong-site",
                "migration-addition-absent",
                "migration-source-legacy-reintroduced",
                "status-authority-omission",
                "status-authority-substitution",
                "status-authority-duplicate",
                "status-authority-table-selection",
                "identity-migration-omission",
                "identity-migration-duplicate-old",
                "identity-migration-duplicate-new",
                "identity-migration-substitution",
                "cross-row-source-binding",
            },
        )
        for probe in gate.PROBES:
            with self.subTest(probe=probe):
                result = _run("--probe", probe)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"probe-failed-as-expected:{probe}",
                    result.stdout.decode(),
                )


@unittest.skipUnless(TERMINAL, "requires the  structural-zero endpoint")
class BackendProjectionBijectionTerminal(unittest.TestCase):
    def test_final_snapshot_is_bijective_and_non_vacuous(self):
        result = _run()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        report = json.loads(result.stdout)
        self.assertIs(report["conformant"], True)
        self.assertEqual(report["diagnostics"], [])
        self.assertEqual(report["counts"]["decisionOccurrences"], 0)
        self.assertEqual(report["counts"]["governedFunctions"], 0)
        self.assertEqual(
            report["migration"]["reconciled"], "terminal-structural-zero"
        )
        self.assertEqual(
            report["terminalStructuralZero"]["successorGate"],
            "backend_convergence",
        )

    def test_selftest(self):
        result = _run("--selftest")
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_retired_ledger_mutations_cannot_revive_arithmetic_authority(self):
        for probe in gate.PROBES:
            with self.subTest(probe=probe):
                result = _run("--probe", probe)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"probe-failed-as-expected:{probe}",
                    result.stdout.decode(),
                )


if __name__ == "__main__":
    unittest.main()
