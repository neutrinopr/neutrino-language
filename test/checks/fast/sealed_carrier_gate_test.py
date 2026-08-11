#!/usr/bin/env python3
"""[fast]  governance: the GENERIC sealed-body-carrier gate exemption is
STRUCTURAL and mutation-sensitive. A backend may register an emitter `case` in
`/sealedBodyCarriers` to exempt it from the handwritten-printer inventory ONLY
while that case is the sole permitted opaque pass-through
(`<dst>.push_back(*<s>.<member>); return;`); the instant it authors any extra
statement/call/literal the exemption is DENIED and the site is re-counted as
handwritten. Proven here on SYNTHETIC data — no concrete carrier, no migration —
so the reusable gate capability is validated independently of any slice that
later consumes it (per : governance widening is reviewed on its own).
"""

import os
import sys
import unittest

from _fastcase import REPO

sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
import check_target_node_registry as gate  # noqa: E402

_PROVEN = set()
_EXPECTED_PROOFS = {"positive", "extra", "phantom", "absent", "committed"}

# A synthetic emitter TU: a `Probe` case that is the sole opaque pass-through
# (hands the pre-rendered node straight through, authors nothing else), followed
# by an unrelated case so the body extraction has a stop boundary.
_PASSTHROUGH = (
    "  switch (s.kind) {\n"
    "  case Stmt::Kind::Probe:\n"
    "    // an opaque pre-rendered carrier: placed verbatim, no framing authored\n"
    "    dst.push_back(*s.probe);\n"
    "    return;\n"
    "  case Stmt::Kind::Other:\n"
    "    return;\n"
    "  }\n")

# The same case with a raw handwritten emit smuggled in alongside the pass-through.
_TAMPERED = (
    "  switch (s.kind) {\n"
    "  case Stmt::Kind::Probe:\n"
    '    dst.push_back(ct::line("raw handwritten SQL"));\n'
    "    dst.push_back(*s.probe);\n"
    "    return;\n"
    "  case Stmt::Kind::Other:\n"
    "    return;\n"
    "  }\n")

_ENTRY = {
    "target": "synthetic",
    "node": "Probe",
    "path": "synthetic/Emitter.cpp",
    "matcher": "case Stmt::Kind::Probe:",
}


class SealedCarrierGate(unittest.TestCase):
    def _inv(self):
        return {"sealedBodyCarriers": [dict(_ENTRY)]}

    def _scanned(self):
        # The site the raw case-scan would surface for `case Stmt::Kind::Probe:`.
        return [dict(_ENTRY)]

    def test_sole_passthrough_earns_the_exemption(self):
        reasons, ok = gate.sealed_carrier_reasons(
            self._inv(), self._scanned(), lambda _p: _PASSTHROUGH)
        self.assertEqual(reasons, [], reasons)
        self.assertEqual(len(ok), 1)
        _PROVEN.add("positive")

    def test_extra_statement_denies_the_exemption(self):
        # The biting mutation: a raw emit inside the allowlisted case must DENY the
        # exemption, so the site is re-counted as handwritten (fail-closed).
        reasons, ok = gate.sealed_carrier_reasons(
            self._inv(), self._scanned(), lambda _p: _TAMPERED)
        self.assertTrue(
            any("not the sole permitted opaque pass-through" in r
                for r in reasons), reasons)
        self.assertEqual(ok, set())
        _PROVEN.add("extra")

    def test_phantom_entry_cannot_mask_a_missing_site(self):
        # An allowlist entry with no matching scanned site is rejected, so the
        # allowlist can never remove a site that was never really the sealed case.
        reasons, ok = gate.sealed_carrier_reasons(
            self._inv(), [], lambda _p: _PASSTHROUGH)
        self.assertTrue(any("phantom seal" in r for r in reasons), reasons)
        self.assertEqual(ok, set())
        _PROVEN.add("phantom")

    def test_absent_case_body_is_denied(self):
        # If the case named by the matcher is not in the source at all, no body can
        # be validated, so the exemption is denied (never silently granted).
        reasons, ok = gate.sealed_carrier_reasons(
            self._inv(), self._scanned(), lambda _p: "  switch (s.kind) {}\n")
        self.assertTrue(reasons)
        self.assertEqual(ok, set())
        _PROVEN.add("absent")

    def test_committed_inventory_entries_are_structurally_valid(self):
        # Every committed beneficiary must earn the generic exemption against its
        # real emitter source. The equality check covers both directions: no
        # registered identity may fail validation, and validation may not produce
        # an identity that was not registered. An empty committed list remains a
        # valid zero-beneficiary state.
        inv = gate.load_inventory(gate.INVENTORY)
        registered = {
            gate._inventory_key(entry)
            for entry in inv.get("sealedBodyCarriers", [])
        }
        reasons, validated = gate.sealed_carrier_reasons(
            inv,
            gate.scan_handwritten_inventory(),
            lambda path: gate._read(os.path.join(REPO, path)),
        )
        self.assertEqual(reasons, [], reasons)
        self.assertEqual(validated, registered)
        _PROVEN.add("committed")


if __name__ == "__main__":
    result = unittest.TextTestRunner().run(
        unittest.defaultTestLoader.loadTestsFromTestCase(SealedCarrierGate)
    )
    if result.wasSuccessful() and _PROVEN == _EXPECTED_PROOFS:
        print("sealed-carrier-proof:positive,extra,phantom,absent,committed")
        sys.exit(0)
    print(
        "sealed-carrier proof is incomplete: "
        f"missing={sorted(_EXPECTED_PROOFS - _PROVEN)}",
        file=sys.stderr,
    )
    sys.exit(1)
