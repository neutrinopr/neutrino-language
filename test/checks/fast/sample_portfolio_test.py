"""[fast] M3 sample portfolio (): coverage map matches the committed fixtures."""

import unittest

from _fastcase import FastCase


class SamplePortfolio(FastCase):
    def test_portfolio_map_validates(self):
        self.val_ok("sample portfolio", "scripts/samples/validate_sample_portfolio.py")


if __name__ == "__main__":
    unittest.main()
