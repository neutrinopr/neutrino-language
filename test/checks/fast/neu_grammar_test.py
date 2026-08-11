"""[fast] M5  T1 (): the .neu TextMate grammar is GENERATED from the compiler-owned
LanguageMetadata and cannot fall behind it.

No-build drift gate: the committed docs/neutrino.tmLanguage.json must byte-match a fresh
regeneration from docs/language-metadata.json, every compiler token must have a grammar rule, and
the fixture must exercise every highlightable category. Fail-closed negatives prove the teeth.
"""

import json
import os
import shutil
import unittest

from _fastcase import FastCase, REPO, PY

GEN = "scripts/generators/generate_tmgrammar.py"
META = os.path.join(REPO, "docs/language-metadata.json")
GRAMMAR = os.path.join(REPO, "docs/neutrino.tmLanguage.json")
FIXTURE = os.path.join(REPO, "test/grammar/neutrino_grammar_fixture.neu")


class NeuGrammar(FastCase):
    def test_grammar_generated_and_byte_matches(self):
        self.val_ok("grammar is generated, byte-matches, covers every token, "
                    "fixture exercises all categories", GEN, "--check")

    def test_generator_emits_grammar_non_vacuous(self):
        # Prove the generator actually EMITS a grammar (missing generation must fail, per ).
        r = self.assert_ok("generator emits a grammar", PY, GEN)
        g = json.loads(r.stdout.decode())
        self.require_floor("grammar repository rules", len(g.get("repository", {})), 8)

    def _meta_with(self, mutate):
        m = self.load_json(META)
        mutate(m)
        return self.dump_json(m, os.path.join(self.tmp, "meta.json"))

    def test_unmapped_keyword_category_rejected(self):
        def mut(m):
            m["keywordCategories"]["unmapped_cat"] = ["zzz"]
        self.val_reject("an unmapped keyword category is rejected",
                        GEN, "--metadata", self._meta_with(mut))

    def test_unmapped_operator_kind_rejected(self):
        def mut(m):
            m["operators"].append({"symbol": "^", "kind": "bitwise"})
        self.val_reject("an unmapped operator kind is rejected",
                        GEN, "--metadata", self._meta_with(mut))

    def test_blockcomment_pair_generates_rule(self):
        # blockComment ( review) is compiler-owned (null today). A future [begin,end] pair must
        # GENERATE a block-comment rule (not silently drop).
        meta = self._meta_with(lambda m: m.__setitem__("blockComment", ["/*", "*/"]))
        self.val_ok("a [begin,end] blockComment generates a rule", GEN, "--metadata", meta)
        r = self.assert_ok("blockComment rule emitted", PY, GEN, "--metadata", meta)
        self.assertIn("comment.block.neutrino", r.stdout.decode(),
                      "a non-null blockComment did not emit a comment.block rule")

    def test_malformed_blockcomment_rejected(self):
        meta = self._meta_with(lambda m: m.__setitem__("blockComment", "/*"))
        self.val_reject("a malformed blockComment (not a [begin,end] pair) is rejected",
                        GEN, "--metadata", meta)

    def _temp_repo(self):
        # A temp repo layout so --check (which derives REPO from the script location) runs against
        # mutated assets.
        r = os.path.join(self.tmp, "repo")
        for sub in ("docs", "test/grammar", "scripts"):
            os.makedirs(os.path.join(r, sub))
        shutil.copy(os.path.join(REPO, GEN), os.path.join(r, "scripts"))
        shutil.copy(META, os.path.join(r, "docs/language-metadata.json"))
        shutil.copy(FIXTURE, os.path.join(r, "test/grammar/"))
        return r

    def test_stale_committed_grammar_caught(self):
        r = self._temp_repo()
        with open(GRAMMAR) as f:
            stale = f.read().replace("procedure", "procedureX")
        with open(os.path.join(r, "docs/neutrino.tmLanguage.json"), "w") as f:
            f.write(stale)
        self.val_reject("a stale committed grammar is caught",
                        os.path.join(r, "scripts/generators/generate_tmgrammar.py"), "--check")

    def test_empty_fixture_caught(self):
        r = self._temp_repo()
        # Fresh-regenerated grammar so ONLY the empty fixture is the failure.
        fresh = self.assert_ok("regen grammar", PY, GEN, "--metadata", META).stdout
        with open(os.path.join(r, "docs/neutrino.tmLanguage.json"), "wb") as f:
            f.write(fresh)
        open(os.path.join(r, "test/grammar/neutrino_grammar_fixture.neu"), "w").close()
        self.val_reject("an empty grammar fixture is caught",
                        os.path.join(r, "scripts/generators/generate_tmgrammar.py"), "--check")


if __name__ == "__main__":
    unittest.main()
