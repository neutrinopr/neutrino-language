#!/usr/bin/env python3
"""Fast governance tests for the source-neutral M7 intake bijection."""
import copy
import json
import os
import subprocess
import sys
import unittest

from _fastcase import REPO

GATE = os.path.join(REPO, "scripts", "gates", "check_m7_intake_bijection.py")
REPORT = os.path.join(
    REPO,
    "examples",
    "m7-intake",
    "core_document_escrow_external.intake-bijection-report.json",
)

sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
import check_m7_intake_bijection as gate  # noqa: E402


def _run(*args):
    return subprocess.run(
        [sys.executable, GATE, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class M7IntakeBijection(unittest.TestCase):
    def test_report_byte_matches_committed_golden(self):
        result = _run("--base-ref", "origin/main")
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        with open(REPORT, encoding="utf-8") as fh:
            expected = fh.read()
        self.assertEqual(result.stdout.decode(), expected)

    def test_report_is_deterministic_and_non_vacuous(self):
        first = _run("--base-ref", "origin/main")
        second = _run("--base-ref", "origin/main")
        self.assertEqual(first.stdout, second.stdout)
        report = json.loads(first.stdout)
        self.assertEqual(report["kind"], "neutrino.m7-intake-bijection-report")
        self.assertEqual(report["schemaVersion"], 1)
        self.assertIs(report["conformant"], True)
        self.assertEqual(report["diagnostics"], [])
        self.assertGreater(report["counts"]["concepts"], 0)
        self.assertGreater(report["counts"]["capabilities"], 0)
        self.assertGreater(report["counts"]["consumers"], 0)
        self.assertGreater(report["counts"]["governedBackends"], 0)
        consumed = {
            binding["capability"] for binding in report["executableBindings"]
        }
        realized = {
            row["capability"] for row in report["capabilityRealizations"]
        }
        self.assertEqual(consumed, realized)
        self.assertTrue(
            all(
                row["genericRealization"] == "reduceSidecarToCoordinationPlan"
                for row in report["capabilityRealizations"]
            )
        )

    def test_every_required_failure_has_one_biting_probe(self):
        self.assertEqual(
            set(gate.PROBES),
            {
                "unknown-capability-anchor",
                "ignored-behavior-field",
                "deleted-field-consumption",
                "concept-id-dispatch",
                "compiled-domain-registration",
                "direct-domain-read",
                "unseen-domain-identity",
                "non-escrow-schema-read",
                "non-equality-domain-dispatch",
                "below-waist-domain-api",
                "self-authorized-projection-change",
                "bundled-capability-widening",
                "descriptive-coordination-influence",
                "stale-gate-registration",
            },
        )
        for name in sorted(gate.PROBES):
            with self.subTest(probe=name):
                result = _run("--base-ref", "origin/main", "--probe", name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"probe-failed-as-expected:{name}", result.stdout.decode()
                )

    def test_field_accounting_is_exact(self):
        report = json.loads(_run("--base-ref", "origin/main").stdout)
        rows = report["fieldAccounting"]
        fields = [row["field"] for row in rows]
        self.assertEqual(len(fields), len(set(fields)))
        self.assertEqual(
            set(fields),
            set(gate._schema_leaf_surface(gate._load(gate.SCHEMA_PATH))),
        )
        self.assertEqual(set(fields), set(gate.FIELD_BINDINGS))
        self.assertEqual(
            {row["disposition"] for row in rows},
            {"consumed", "rejected"},
        )
        self.assertTrue(all(row["authority"] or row["reason"] for row in rows))
        self.assertTrue(
            all(
                (row["proof"] in gate.CONSUMER_PROOFS)
                if row["disposition"] == "consumed"
                else row["proof"] is None
                for row in rows
            )
        )
        contract = gate._load(gate.PROJECTION_CONTRACT_PATH)
        reducer_fields = {
            field
            for field, (proof, _rejection) in gate.FIELD_BINDINGS.items()
            if proof is not None
            and gate.CONSUMER_PROOFS[proof][0] == "generic-reducer"
        }
        self.assertEqual(set(contract["fieldProjection"]), reducer_fields)
        self.assertIn(
            report["trustedProjection"]["sourceSha256"],
            contract["trustedReducer"]["approvedSourceSha256"],
        )

    def test_review_bypass_shapes_fail_closed(self):
        cases = []

        snapshot = gate._snapshot("origin/main")
        snapshot["consumerTexts"][gate.REDUCER_PATH] = snapshot["consumerTexts"][
            gate.REDUCER_PATH
        ].replace('auto to = o->getString("to");', "auto to = ignoredEndpoint();")
        cases.append(
            ("deleted-concrete-consumption", snapshot, "bijection.unconsumed_field")
        )

        snapshot = gate._snapshot("origin/main")
        snapshot["consumerTexts"][gate.REDUCER_PATH] = snapshot["consumerTexts"][
            gate.REDUCER_PATH
        ].replace(
            "m.edges.push_back({id->str(), from->str(), to->str(), rel->str()});",
            "m.edges.push_back({id->str(), from->str(), ignoredTo(), rel->str()});",
        )
        cases.append(
            ("read-not-projected", snapshot, "bijection.unconsumed_field")
        )

        snapshot = gate._snapshot("origin/main")
        snapshot["fieldBindings"]["reductions[].to"] = (
            "reducer-edge-id",
            None,
        )
        cases.append(
            ("rebound-consumption-proof", snapshot, "bijection.unconsumed_field")
        )

        snapshot = gate._snapshot("origin/main")
        snapshot["schema"]["properties"]["reductions"]["items"]["properties"][
            "optionalLeaf"
        ] = {"type": "string"}
        cases.append(
            ("optional-schema-leaf", snapshot, "bijection.unconsumed_field")
        )

        snapshot = gate._snapshot("origin/main")
        snapshot["changedLines"].extend(
            [
                ("lib/L2Reduction.cpp", "auto selector = conceptId;"),
                ("lib/L2Reduction.cpp", "if ("),
                ("lib/L2Reduction.cpp", 'selector == "escrow_funded"'),
                ("lib/L2Reduction.cpp", ") return special;"),
            ]
        )
        cases.append(
            ("multiline-concept-dispatch", snapshot, "bijection.concept_dispatch")
        )

        snapshot = gate._snapshot("origin/main")
        snapshot["changedLines"].extend(
            [
                ("include/Neutrino/NeutrinoOps.td", "def"),
                ("include/Neutrino/NeutrinoOps.td", "EscrowDomainConceptOp;"),
            ]
        )
        cases.append(
            (
                "multiline-compiled-registration",
                snapshot,
                "bijection.compiled_domain_registration",
            )
        )

        snapshot = gate._snapshot("origin/main")
        snapshot["changedLines"].extend(
            [
                ("lib/backends/postgres/PostgresModel.cpp", "auto identity ="),
                ("lib/backends/postgres/PostgresModel.cpp", "domainId;"),
                ("lib/backends/postgres/PostgresModel.cpp", "auto capabilities ="),
                (
                    "lib/backends/postgres/PostgresModel.cpp",
                    "knownSemanticFeatures();",
                ),
            ]
        )
        cases.append(
            ("helper-alias-backend-selection", snapshot, "bijection.direct_domain_read")
        )

        snapshot = gate._snapshot("origin/main")
        snapshot["changedLines"].append(
            (
                "lib/backends/postgres/PostgresModel.cpp",
                'auto identity = sidecar.getString("domain");',
            )
        )
        cases.append(
            ("structural-domain-accessor", snapshot, "bijection.direct_domain_read")
        )

        snapshot = gate._snapshot("origin/main")
        snapshot["baseRegistry"] = copy.deepcopy(snapshot["registry"])
        snapshot["registry"]["capabilities"][0]["category"] = "obligation"
        snapshot["changedPaths"].add(
            os.path.join(
                gate.DOMAIN_DATA_ROOT,
                "review-probe",
                "domain-semantics.json",
            )
        )
        cases.append(
            (
                "same-id-registry-semantic-delta",
                snapshot,
                "bijection.self_authorized_widening",
            )
        )

        for name, snapshot, expected in cases:
            with self.subTest(case=name):
                report = gate.evaluate(snapshot)
                self.assertFalse(report["conformant"])
                self.assertIn(
                    expected,
                    {item["code"] for item in report["diagnostics"]},
                )

    def test_missing_authoritative_base_fails_closed(self):
        env = os.environ.copy()
        env.pop("PR_BASE_SHA", None)
        env.pop("GITHUB_BASE_SHA", None)
        result = subprocess.run(
            [
                sys.executable,
                GATE,
                "--base-ref",
                "neutrino-definitely-missing-base",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self.assertNotEqual(result.returncode, 0)
        report = json.loads(result.stdout)
        self.assertIn(
            "bijection.stale_registration",
            {item["code"] for item in report["diagnostics"]},
        )

    def test_selftest_passes(self):
        result = _run("--base-ref", "origin/main", "--selftest")
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertIn("14 fail-closed probes", result.stdout.decode())


if __name__ == "__main__":
    unittest.main()
