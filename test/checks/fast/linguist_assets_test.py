"""[fast] M5  T3 (): the packaged GitHub/Linguist assets are GENERATED from the one
grammar and cannot drift.

No-build drift gate: the packaged grammar must byte-equal the generated docs/neutrino.tmLanguage.json,
and linguist/languages.yml must byte-match a fresh regeneration from the compiler metadata + grammar.
Fail-closed negatives prove the teeth.
"""

import os
import re
import shutil
import unittest

from _fastcase import FastCase, REPO

GEN = "scripts/generators/generate_linguist_assets.py"


class LinguistAssets(FastCase):
    def setUp(self):
        super().setUp()
        for rel in (GEN, "linguist/neutrino.tmLanguage.json", "linguist/languages.yml"):
            self.assertTrue(os.path.isfile(os.path.join(REPO, rel)),
                            f"the linguist package or its generator is missing: {rel}")

    def test_package_generated_and_byte_matches(self):
        # positive: packaged grammar == generated; languages.yml fresh + parses + maps
        # .neu -> source.neutrino.
        self.val_ok("linguist package is generated, byte-matches, and its entry maps the .neu scope",
                    GEN, "--check")

    def test_gitattributes_routes_neu(self):
        # Non-vacuous: .gitattributes actually routes .neu to Neutrino (the whole point of the pkg).
        with open(os.path.join(REPO, ".gitattributes")) as f:
            text = f.read()
        self.assertRegex(text, r"(?m)^\*\.neu[ \t]+linguist-language=Neutrino",
                         ".gitattributes does not map *.neu to the Neutrino language")

    def test_make_linguist_runs(self):
        # The advertised `make linguist` must actually RUN (not no-op because linguist/ exists and
        # the target isn't .PHONY,  review) — assert it regenerates. Byte-identical output
        # leaves the tree clean.
        r = self.assert_ok("make linguist runs", "make", "linguist")
        self.assertIn("wrote linguist/ package", r.stdout.decode(),
                      "'make linguist' did not run (add it to .PHONY)")

    def _mk_repo(self):
        d = os.path.join(self.tmp, f"r{len(os.listdir(self.tmp))}")
        for sub in ("scripts", "docs", "linguist"):
            os.makedirs(os.path.join(d, sub))
        shutil.copy(os.path.join(REPO, GEN), os.path.join(d, "scripts"))
        for rel in ("docs/language-metadata.json", "docs/neutrino.tmLanguage.json"):
            shutil.copy(os.path.join(REPO, rel), os.path.join(d, "docs"))
        for rel in ("linguist/neutrino.tmLanguage.json", "linguist/languages.yml"):
            shutil.copy(os.path.join(REPO, rel), os.path.join(d, "linguist"))
        return d

    def _gen_check(self, repo_dir):
        return os.path.join(repo_dir, "scripts/generators/generate_linguist_assets.py")

    def _sub(self, path, old, new):
        with open(path) as f:
            text = f.read().replace(old, new)
        with open(path, "w") as f:
            f.write(text)

    def test_stale_packaged_grammar_caught(self):
        # negative 1: a STALE packaged grammar (differs from the generated one) fails closed.
        d = self._mk_repo()
        self._sub(os.path.join(d, "linguist/neutrino.tmLanguage.json"),
                  "source.neutrino", "source.tampered")
        self.val_reject("a stale packaged grammar is caught", self._gen_check(d), "--check")

    def test_stale_languages_yml_caught(self):
        # negative 2: a STALE languages.yml (hand-edited away from the generated form) fails closed.
        d = self._mk_repo()
        with open(os.path.join(d, "linguist/languages.yml"), "a") as f:
            f.write("\n# hand edit\n")
        self.val_reject("a stale languages.yml is caught", self._gen_check(d), "--check")

    def test_non_regenerated_after_grammar_change_caught(self):
        # negative 3: if the GENERATED grammar's scope changes, a not-regenerated package fails
        # closed (proves the package is pinned to the generated grammar, not a frozen copy).
        d = self._mk_repo()
        self._sub(os.path.join(d, "docs/neutrino.tmLanguage.json"),
                  "source.neutrino", "source.neutrino2")
        self.val_reject("a package not regenerated after a grammar-scope change is caught",
                        self._gen_check(d), "--check")


if __name__ == "__main__":
    unittest.main()
