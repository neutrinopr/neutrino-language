"""[fast] M4 release-artifact manifest (): every release sample + schema artifact is
present and pins."""

import os
import unittest

from _fastcase import FastCase


class ReleaseManifest(FastCase):
    def test_manifest_present_and_pinned(self):
        # No build needed: the generator hashes committed release artifacts and fails closed if a
        # portfolio L1/L2/L3 path or a release schema is missing. Tool-version surface is skipped
        # (no --translate).
        self.val_ok("release manifest", "scripts/generators/make_release_manifest.py",
                    "--out", os.path.join(self.tmp, "release-artifact-manifest.json"))


if __name__ == "__main__":
    unittest.main()
