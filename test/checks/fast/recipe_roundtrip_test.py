"""Focused  R5a checks that do NOT require llvm-tblgen.

Pinned-TableGen production + mutation rejection run under CTest
`recipe-roundtrip` / `recipe-roundtrip-selftest` (cmake/NeutrinoTests.cmake)
with `${LLVM_TOOLS_BINARY_DIR}/llvm-tblgen`. This fast module only asserts
the gate and canonicalizer scripts remain importable and that the closed
membership table stays non-empty — tblgen-free smoke.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load(rel: str):
    path = REPO / rel
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class RecipeRoundtripSmoke(unittest.TestCase):
    def test_scripts_importable(self):
        gate = _load("scripts/gates/check_recipe_roundtrip.py")
        canon = _load("scripts/generators/recipe_canonicalizer.py")
        self.assertTrue(hasattr(gate, "run_backend"))
        self.assertTrue(hasattr(canon, "extract_corpus_ordered"))
        self.assertEqual(len(gate.SOLIDITY_EXPECTED_ORDER), 9)
        self.assertEqual(set(gate.SOLIDITY_EXPECTED_ORDER), gate.SOLIDITY_EXPECTED_IDS)

    def test_grammar_constants(self):
        canon = _load("scripts/generators/recipe_canonicalizer.py")
        self.assertEqual(canon.GRAMMAR_KIND, "neutrino.recipe-record")
        self.assertIn(canon.SOLIDITY_ENTRY_TD, canon.SOLIDITY_CORPUS)


if __name__ == "__main__":
    unittest.main()
