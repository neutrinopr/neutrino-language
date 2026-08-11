"""[fast] M5 S2 (): corpus-to-proposal generator — deterministic vocabulary-proposal
from the S1 observation-set; validates; teeth fail closed."""

import unittest

from _fastcase import FastCase


class CorpusProposal(FastCase):
    def test_proposal_regenerates_validates_reverifies(self):
        # --check regenerates, asserts the committed proposal is byte-identical, validates it with
        # the OWNING validator, and (ENFORCED BY DEFAULT, ) recomputes corpusRef.contentHash
        # over the committed corpus snapshot and FAILS CLOSED on a rebind — proving the REAL binding.
        self.val_ok("proposal regenerates + validates + re-verifies the committed corpus binding",
                    "scripts/corpus/generate_proposal_from_observations.py",
                    "--observations",
                    "examples/domain-proposals/solidity_samples.observation-set.json",
                    "--corpus", "examples/domain-proposals/solidity_samples.corpus.json",
                    "--check")

    def test_generator_selftest_teeth(self):
        # Fail-closed teeth (in-memory): a rebound observation-set, invalid observations, unknown
        # dimension, corpusRef mismatch, non-authority citation source, unreadable corpus, and the
        # tiny-corpus anti-rebind all fail closed.
        self.val_ok("proposal generator self-test (teeth fail closed)",
                    "scripts/corpus/generate_proposal_selftest.py")


if __name__ == "__main__":
    unittest.main()
