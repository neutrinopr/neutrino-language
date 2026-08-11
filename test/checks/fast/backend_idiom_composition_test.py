#!/usr/bin/env python3
"""[fast]  read-only backend idiom composition inventory checks."""

import os

from _fastcase import FastCase, REPO


SCRIPT = "scripts/gates/check_backend_idiom_composition.py"


class BackendIdiomComposition(FastCase):
    def test_ast_classifier_and_fail_closed_mutations(self):
        out = self.val_ok("backend idiom composition selftest", SCRIPT, "--selftest")
        self.assertIn(
            "denominator/forbidden/provider/candidate/exclusion-growth",
            out.stdout.decode("utf-8", "replace"),
        )

    def test_committed_inventory_is_reconciled_and_owned(self):
        report = self.load_json(os.path.join(
            REPO, "docs/backend-idiom-composition-inventory.json"))
        rows = report["occurrences"]
        self.require_floor("AST composition occurrences", len(rows), 1)
        self.assertEqual(report["totals"]["occurrences"], len(rows))
        self.assertEqual(
            sum(report["totals"]["byClassification"].values()), len(rows))
        self.assertEqual(report["securityRegistry"]["resolverRows"], 5)
        self.assertEqual(len(report["securityRegistry"]["entryIds"]), 7)
        self.assertEqual(report["completion"], {
            "backendSpecificGenericOccurrences": 0,
            "forbiddenResidueOccurrences": 0,
            "umbrellaCandidateOccurrences": 0,
            "unassignedOwnerOccurrences": 0,
            "verdict": "complete",
        })
        self.assertTrue(all(row["symbolUsr"].startswith("c:") for row in rows))
        self.assertTrue(all(row["ownerIssue"] is not None for row in rows))
        candidates = [
            row for row in rows
            if row["classification"] == "declarative-recipe-candidate"
        ]
        # Terminal invariant (): declarative-recipe-candidate is fully
        # retired — exactly zero occurrences, so the candidate-owner set is empty.
        self.assertEqual(
            len(candidates), 0,
            "terminal: declarative-recipe-candidate must be exactly 0")
        self.assertEqual(
            {row["ownerIssue"] for row in candidates},
            set(),
        )
        # A genuinely-new candidate (e.g. reintroduced under ) must never
        # reappear in the terminal set — kept as a standing protection.
        self.assertNotIn(661, {row["ownerIssue"] for row in candidates})
        security = [
            row for row in rows
            if row["classification"] == "security-carveout-656"
        ]
        self.assertTrue(all(row["ownerIssue"] == 656 for row in security))
        generic = [
            row for row in rows
            if row["classification"] == "generic-driver-validation"
        ]
        self.assertTrue(all(row["ownerIssue"] == 898 for row in generic))
        self.assertEqual(
            sum(row["occurrences"] for row in report["ownershipSlices"]),
            len(candidates),
        )
        self.assertEqual(
            sum(row["occurrences"] for row in report["symbolSummary"]),
            len(rows),
        )
        postgres_sources = set(
            report["discovery"]["sources"]["postgres"]["files"])
        solidity_sources = set(
            report["discovery"]["sources"]["solidity"]["files"])
        # SqlEmitter.cpp retired with the sql:: emitter () — must be absent.
        self.assertNotIn(
            "lib/backends/postgres/SqlEmitter.cpp", postgres_sources)
        # PgSqlSyntax.cpp relocated to leaf/ by the  package-role reorg.
        self.assertIn(
            "lib/backends/postgres/leaf/PgSqlSyntax.cpp", postgres_sources)
        self.assertIn(
            "lib/backends/solidity/provider/SolidityEmit.cpp", solidity_sources)
        self.assertEqual(
            len(report["sourceDispositions"]),
            len(postgres_sources) + len(solidity_sources),
        )
        self.assertTrue(all(
            source["translationUnitAuthority"] == "compile_commands.json"
            for source in report["discovery"]["sources"].values()
        ))
        # The sql:: generic-driver symbols lived in the now-deleted
        # SqlEmitter.cpp (); no generic row may originate there.
        self.assertEqual(
            {
                row["symbol"] for row in generic
                if row["file"].endswith("SqlEmitter.cpp")
            },
            set(),
        )
        dispositions = {
            row["file"]: row["disposition"]
            for row in report["sourceDispositions"]
        }
        self.assertEqual(
            dispositions["lib/backends/postgres/leaf/PgSqlSyntax.cpp"],
            "authenticated-leaf-formatting-only",
        )
        self.assertEqual(
            dispositions["lib/backends/solidity/provider/SolidityEmit.cpp"],
            "authenticated-leaf-formatting-only",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
