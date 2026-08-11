"""[fast] Complete domain-pack v2 production and verification stay fail-closed."""

import unittest

from _fastcase import FastCase, PY


class DomainPackV2(FastCase):
    def test_complete_inventory_and_mutations(self):
        self.assert_ok(
            "domain-pack v2 deterministic generator and fail-closed mutations",
            PY,
            "test/ir/bundle/check_domain_pack_v2.py",
            ".",
            "test/ir/bundle/Inputs/pack-v2",
            "test/ir/bundle/Inputs/pack-v2-spec.json",
            "scripts/validators/verify_domain_pack.py",
            "scripts/generators/make_domain_pack.py",
        )


if __name__ == "__main__":
    unittest.main()
