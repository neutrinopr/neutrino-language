#!/usr/bin/env python3
"""[fast]  S3 — the M7 reduction-conformance report + governance gate.

The conformance seam (admission ->  reduction -> capability registry -> parity)
emits a DETERMINISTIC, versioned, machine-readable report suitable for the S2
governance gate and the  final witness. This tier exercises the seam
build-free by consuming the committed reduction, so it needs no toolchain:

  - the report is byte-reproducible and byte-matches the committed golden;
  - its shape/version axes hold;
  - the committed golden reduction's executable bindings correspond exactly to the
    external fixture's executable edges (the reduction fixture cannot silently
    drift from the artifact it claims to reduce);
  - every fail-closed conformance code is covered by a non-vacuous tamper probe;
  - the driver --selftest passes.

The binary-backed end-to-end (real neutrino-emit) + the byte-identity of the
committed reduction vs the reducer live in test/ir/l2/external_reduction_conformance.test.
"""
import json
import os
import subprocess
import sys
import unittest

from _fastcase import REPO

GATE = os.path.join(REPO, "scripts/gates/check_m7_reduction_conformance.py")
FIXTURE = os.path.join(REPO, "examples", "m7-intake", "core_document_escrow_external.l2v3.json")
REDUCTION = os.path.join(REPO, "examples", "m7-intake", "core_document_escrow_external.reduction.json")
REPORT = os.path.join(REPO, "examples", "m7-intake", "core_document_escrow_external.conformance-report.json")
EXECUTABLE_RELATIONS = ("expands", "discharges")

sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
import check_m7_reduction_conformance as gate  # noqa: E402


def _run(*args):
    return subprocess.run([sys.executable, GATE, *args],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class M7ReductionConformance(unittest.TestCase):
    def test_report_byte_matches_committed_golden(self):
        r = _run("--artifact", FIXTURE, "--reduction", REDUCTION)
        self.assertEqual(r.returncode, 0, r.stderr.decode())
        self.assertEqual(r.stdout.decode(), open(REPORT, encoding="utf-8").read(),
                         "regenerating the conformance report drifted from the committed golden")

    def test_report_is_deterministic(self):
        a = _run("--artifact", FIXTURE, "--reduction", REDUCTION).stdout
        b = _run("--artifact", FIXTURE, "--reduction", REDUCTION).stdout
        self.assertEqual(a, b)

    def test_report_shape_and_version_axes(self):
        rep = json.loads(open(REPORT, encoding="utf-8").read())
        self.assertEqual(rep["kind"], "neutrino.m7-reduction-conformance-report")
        self.assertEqual(rep["schemaVersion"], 1)
        self.assertIs(rep["conformant"], True)
        self.assertEqual(rep["domain"], "coordinate.core_document_escrow")
        # the report binds the verdict to the artifact identity + the three version
        # axes the  witness pins.
        art = json.loads(open(FIXTURE, encoding="utf-8").read())
        self.assertEqual(rep["artifactHash"], art["domainSemanticsHash"])
        # the THREE intake axes are distinct from the report's own schemaVersion:
        # the  envelope axis + the vocabulary + reduction-semantics versions.
        self.assertEqual(rep["schemaVersion"], 1)
        self.assertEqual(rep["artifactSchemaVersion"], art["schemaVersion"])
        self.assertEqual(rep["semanticProfileVersion"], art["intakeVersioning"]["semanticProfileVersion"])
        self.assertEqual(rep["reductionSemanticsVersion"], art["intakeVersioning"]["reductionSemanticsVersion"])
        self.assertEqual(rep["reducedExecutableCapabilities"], ["effect:debit"])
        self.assertEqual(rep["diagnostics"], [])

    def test_malformed_input_emits_the_full_report_envelope(self):
        # A missing/unreadable artifact fails closed through the SAME versioned
        # report envelope (null identity/version fields), so a consumer can
        # schema-negotiate on the fail-closed path exactly as on the happy path.
        r = _run("--artifact", os.path.join(REPO, "does-not-exist.l2v3.json"),
                 "--reduction", REDUCTION)
        self.assertEqual(r.returncode, 1)
        rep = json.loads(r.stdout.decode())
        golden = json.loads(open(REPORT, encoding="utf-8").read())
        self.assertEqual(set(rep), set(golden), "the failure report is not the full report envelope")
        self.assertEqual(rep["kind"], "neutrino.m7-reduction-conformance-report")
        self.assertEqual(rep["schemaVersion"], 1)
        self.assertIs(rep["conformant"], False)
        self.assertIsNone(rep["artifactHash"])
        self.assertIsNone(rep["artifactSchemaVersion"])
        self.assertEqual({d["code"] for d in rep["diagnostics"]}, {"conformance.malformed"})

    def test_committed_reduction_matches_fixture_executable_edges(self):
        art = json.loads(open(FIXTURE, encoding="utf-8").read())
        red = json.loads(open(REDUCTION, encoding="utf-8").read())
        self.assertEqual(red["domain"], art["domain"])
        art_exec = {(r["id"], r["from"], r["to"], r["relation"])
                    for r in art["reductions"] if r["relation"] in EXECUTABLE_RELATIONS}
        red_exec = {(b["edge"], b["concept"], b["feature"], b["relation"])
                    for b in red["bindings"] if b["relation"] in EXECUTABLE_RELATIONS}
        self.assertEqual(art_exec, red_exec,
                         "the committed reduction's executable bindings drifted from the fixture's edges")

    def test_every_conformance_code_has_a_biting_probe(self):
        # each closed conformance.* code (except the never-emitted structural
        # reduction_failed, which requires the live reducer) is covered by a probe.
        probe_codes = {gate.PROBES[name][0] for name in gate.PROBES}
        uncovered = set(gate.CODES) - probe_codes - {"conformance.reduction_failed"}
        self.assertEqual(uncovered, set(), f"conformance codes with no tamper probe: {uncovered}")

    def test_all_probes_fail_closed(self):
        for name in sorted(gate.PROBES):
            with self.subTest(probe=name):
                r = _run("--probe", name)
                self.assertNotEqual(r.returncode, 0, f"probe {name} did not fail closed")
                self.assertIn(f"probe-failed-as-expected:{name}", r.stdout.decode())

    def test_selftest_passes(self):
        r = _run("--selftest")
        self.assertEqual(r.returncode, 0, r.stderr.decode())


if __name__ == "__main__":
    unittest.main()
