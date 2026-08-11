"""[fast] The M6 pack resolver hydrates the pack-v2 fixture and fails closed ()."""

import unittest

from _fastcase import FastCase, PY


class PackResolver(FastCase):
    def test_receipt_verified_hydration_and_fail_closed(self):
        self.assert_ok(
            "M6 pack resolver: positive hydration + tampered rejection + schema + fallback",
            PY,
            "test/ir/bundle/check_pack_resolver.py",
            ".",
            "test/ir/bundle/Inputs/pack-v2",
            "test/ir/bundle/Inputs/pack-v2-receipt/receipt.json",
            "scripts/gates/m6_pack_resolver.py",
        )


if __name__ == "__main__":
    unittest.main()
