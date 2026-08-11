#!/usr/bin/env python3
"""[fast]  G1-S1 P1-2: the standalone (mode, role) -> atom idiom generator
path (`LifecycleAtom`) is validated on the PRODUCER side, mirroring the totality
/ identifier / non-empty checks the attached `EnumField` enums get. A row keyed
on an unknown mode/role symbol, carrying an empty atom, or duplicating a
(mode, role) key must fail closed with a specific diagnostic before it can
regenerate a vacuous or shadowed status accessor. Also pins that `render_enums`
emits the `NEU_<Abbrev>_STATUS_ATOM` X-macro the `<backend>StatusAtom(mode, role)`
accessor reads.
"""

import os
import sys
import unittest

from _fastcase import REPO

sys.path.insert(0, os.path.join(REPO, "scripts", "generators"))
import gen_target_node_registry as generator  # noqa: E402


def _row(mode, role, atom):
    return {"mode": mode, "role": role, "atom": atom}


# A valid, minimal Solidity-shaped table (evidence + coordination rails).
VALID_ROWS = [
    _row("Evidence", "Initial", "None"),
    _row("Evidence", "Success", "Accepted"),
    _row("Effectful", "Initial", "None"),
    _row("Effectful", "Success", "Reconciled"),
]


class LifecycleAtomValidation(unittest.TestCase):
    def test_valid_rows_pass(self):
        generator.validate_status_atoms(VALID_ROWS)  # no SystemExit

    def test_closed_symbol_domains_match_projection_enums(self):
        # The generator's key domain is the closed projection ExecutionMode /
        # LifecycleRole symbol sets; drift from BackendProjection.h is caught by
        # the freshness gate + the C++ compile, but pin the intended closed sets.
        self.assertEqual(generator.STATUS_ATOM_MODES,
                         ("Evidence", "Effectful", "Temporal"))
        self.assertEqual(generator.STATUS_ATOM_ROLES,
                         ("Initial", "AcceptedOrAttested", "Success"))

    def test_unknown_mode_fails_closed(self):
        with self.assertRaises(SystemExit) as cm:
            generator.validate_status_atoms(VALID_ROWS + [_row("Bogus", "Success", "X")])
        self.assertIn("unknown mode", str(cm.exception))

    def test_unknown_role_fails_closed(self):
        with self.assertRaises(SystemExit) as cm:
            generator.validate_status_atoms(VALID_ROWS + [_row("Evidence", "Bogus", "X")])
        self.assertIn("unknown role", str(cm.exception))

    def test_empty_atom_fails_closed(self):
        with self.assertRaises(SystemExit) as cm:
            generator.validate_status_atoms([_row("Evidence", "Success", "")])
        self.assertIn("empty atom", str(cm.exception))

    def test_duplicate_mapping_fails_closed(self):
        # The same (mode, role) key mapped twice would silently shadow a real
        # mapping — the accessor must be an unambiguous function of the key.
        with self.assertRaises(SystemExit) as cm:
            generator.validate_status_atoms([
                _row("Evidence", "Success", "Accepted"),
                _row("Evidence", "Success", "Reconciled"),
            ])
        self.assertIn("duplicate", str(cm.exception))
        self.assertIn("('Evidence', 'Success')", str(cm.exception))


class StatusAtomRendering(unittest.TestCase):
    BACKEND = {"abbrev": "SOL", "target": "solidity", "model": "SolStmt"}

    def test_render_emits_status_atom_macro_block(self):
        text = generator.render_enums(
            "SolidityTargetNodes.td", [], self.BACKEND, VALID_ROWS)
        self.assertIn("#ifdef NEU_SOL_STATUS_ATOM", text)
        self.assertIn('NEU_SOL_STATUS_ATOM(Evidence, Success, "Accepted")', text)
        self.assertIn('NEU_SOL_STATUS_ATOM(Effectful, Success, "Reconciled")', text)
        self.assertIn("#endif // NEU_SOL_STATUS_ATOM", text)

    def test_render_preserves_row_order(self):
        # `records()` sorts by (mode, role) before rendering; `render_enums`
        # itself must preserve the order it is given, so the committed .inc is a
        # deterministic function of that sorted input.
        rows = [_row("Effectful", "Success", "Reconciled"),
                _row("Evidence", "Success", "Accepted")]
        text = generator.render_enums(
            "SolidityTargetNodes.td", [], self.BACKEND, rows)
        block = text.split("#ifdef NEU_SOL_STATUS_ATOM", 1)[1]
        self.assertLess(block.index("(Effectful"), block.index("(Evidence"))

    def test_no_rows_and_no_enums_emits_nothing(self):
        self.assertIsNone(generator.render_enums(
            "SolidityTargetNodes.td", [], self.BACKEND, ()))


if __name__ == "__main__":
    unittest.main()
