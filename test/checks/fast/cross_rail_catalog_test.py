"""[fast] cross-rail fixture catalog validates against committed artifacts."""

import unittest

from _fastcase import FastCase


class CrossRailCatalog(FastCase):
    def test_committed_catalog_validates(self):
        self.val_ok("cross-rail catalog", "scripts/validators/validate_cross_rail_catalog.py")


if __name__ == "__main__":
    unittest.main()
