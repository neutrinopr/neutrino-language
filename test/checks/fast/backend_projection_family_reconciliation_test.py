#!/usr/bin/env python3
"""Fast checks for the frozen - occurrence reconciliation."""

import json
import os
import subprocess
import sys
import unittest

from _fastcase import REPO


GATE = os.path.join(
    REPO, "scripts", "gates", "check_backend_projection_family_reconciliation.py"
)
sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
import check_backend_projection_family_reconciliation as gate  # noqa: E402


def _run(*args):
    return subprocess.run(
        [sys.executable, GATE, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class BackendProjectionFamilyReconciliation(unittest.TestCase):
    def test_frozen_equation_and_partition_reconcile(self):
        result = _run()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        report = json.loads(result.stdout)
        self.assertIs(report["conformant"], True)
        self.assertEqual(report["diagnostics"], [])
        self.assertEqual(
            report["initialPartition"],
            {"": 53, "": 70, "": 96, "": 72, "": 7},
        )
        self.assertEqual(
            report["correctedInitialPartition"],
            {"": 39, "": 72, "": 98, "": 82, "": 7},
        )
        self.assertEqual(
            report["historicalLivePartition"],
            {"": 53, "": 0, "": 93, "": 71, "": 7},
        )
        self.assertEqual(
            report["livePartition"],
            {"": 0, "": 0, "": 0, "": 0, "": 0},
        )
        self.assertEqual(
            report["ownershipCorrections"],
            {
                "count": 14,
                "identitySetSha256": (
                    "481602f6431043af64d2e265389d113ec"
                    "3b7452d607d9126911cc4b268ab5a8c"
                ),
                "sourceCommit": (
                    "25278e6b2847df821ed0651f00c4b4bad7206a9a"
                ),
            },
        )
        equation = report["equation"]
        self.assertEqual(equation["live"], 0)
        self.assertEqual(
            report["terminalStructuralZero"]["successorGate"],
            "backend_convergence",
        )

    def test_selftest(self):
        result = _run("--selftest")
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_every_reconciliation_failure_class_bites(self):
        self.assertEqual(
            set(gate.PROBES),
            {
                "equation",
                "live-overlap",
                "live-omission",
                "bucket-overlap",
                "bucket-omission",
                "duplicate-retirement",
                "undeclared-addition",
                "retired-still-live",
                "unauthorized-survivor",
                "cross-row-source-binding",
                "ownership-correction-omission",
                "ownership-correction-duplicate",
                "ownership-correction-identity",
                "ownership-correction-source",
                "ownership-correction-target",
                "ownership-correction-retirement-source",
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

    def test_corrections_are_exact_and_preserve_original_rows(self):
        inv = gate._load()
        policy = inv["familyReconciliation"]
        records = policy["ownershipCorrections"]["records"]
        self.assertEqual(len(records), 14)
        self.assertEqual(
            gate._identity_digest(record["occurrence"] for record in records),
            gate.CORRECTION_IDENTITY_DIGEST,
        )
        self.assertEqual(
            {record["fromBucket"] for record in records},
            {""},
        )
        self.assertEqual(
            {
                target: sum(
                    record["toBucket"] == target for record in records
                )
                for target in ("", "", "")
            },
            {"": 2, "": 2, "": 10},
        )
        site_row = {
            site: row["id"]
            for row in inv["rows"]
            for rail in ("solidity", "postgres")
            for site in row[rail]
        }
        for record in records:
            with self.subTest(identity=record["occurrence"]):
                self.assertEqual(
                    site_row[record["sourceSite"]],
                    record["sourceRow"],
                )

    def test_correction_maps_v2_and_retirement_identity_to_same_family(self):
        inv = gate._load()
        policy = inv["familyReconciliation"]
        row_bucket = {
            row: bucket["id"]
            for bucket in policy["buckets"]
            for row in bucket["rows"]
        }
        site_row = {
            site: row["id"]
            for row in inv["rows"]
            for rail in ("solidity", "postgres")
            for site in row[rail]
        }
        new_to_old = {
            entry["new"]: entry["old"]
            for entry in inv["decisionIdentityMigration"]["entries"]
        }
        errors = []
        by_v2, by_canonical, corrected = gate._ownership_corrections(
            policy, row_bucket, site_row, new_to_old, errors
        )
        self.assertEqual(errors, [])
        self.assertEqual(corrected, gate.CORRECTED_INITIAL_PARTITION)
        for identity, record in by_v2.items():
            with self.subTest(identity=identity):
                self.assertIs(
                    by_canonical[new_to_old[identity]],
                    record,
                )
                self.assertEqual(
                    by_canonical[new_to_old[identity]]["toBucket"],
                    record["toBucket"],
                )


if __name__ == "__main__":
    unittest.main()
