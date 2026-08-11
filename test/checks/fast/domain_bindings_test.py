"""[fast] M5 signature binding (, PR  review P2): every committed
translator-owned observation binding is validated against its capability-spec.

The sample-artifact drift DAG (`neutrino_sample_artifacts`) checks a domain's source / scenario /
capability-spec / test-realization, but NOT its `binding.json` — so a malformed binding, an unbound
observer-set `ref`, or an infeasible M>N could merge while every other gate stayed green. The oracle
observer + guard slices consume these bindings as first-class inputs, so this closes the hole: every
The production domains are external packs after , so this gate deliberately exercises the
translator-owned validator fixture rather than reaching back into a domain payload.
fail-closed, with a non-vacuous floor so the scan can't silently erode to zero.
"""

import os
import unittest

from _fastcase import FastCase, REPO

SCRIPT = "scripts/validators/validate_observation_binding.py"


class DomainBindings(FastCase):
    def test_committed_domain_bindings_validate(self):
        binding = os.path.join(REPO, "test", "generalism", "Inputs",
                               "export_clearance_fixture", "binding.json")
        spec = os.path.join(REPO, "test", "generalism", "Inputs",
                            "export_clearance_fixture", "capability-spec.json")
        self.assertTrue(os.path.isfile(binding), f"binding fixture missing: {binding}")
        self.assertTrue(os.path.isfile(spec), f"capability-spec fixture missing: {spec}")
        self.val_ok("translator-owned observation binding", SCRIPT,
                    "--binding", binding, "--spec", spec)


if __name__ == "__main__":
    unittest.main()
