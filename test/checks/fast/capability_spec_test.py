"""[fast] capability spec validator (): committed sample specs validate, tampered spec
fails closed."""

import os
import unittest

from _fastcase import FastCase, REPO


class CapabilitySpec(FastCase):
    def test_committed_specs_validate(self):
        specs = [member.spec_path for member in self.curated_members().values()]
        for p in specs:
            dom = os.path.basename(os.path.dirname(os.path.dirname(p)))
            self.val_ok(f"spec {dom}", "scripts/validators/validate_capability_spec.py", p)
        self.require_floor("committed capability specs", len(specs), 1)

    def test_tampered_spec_fails_closed(self):
        # A tampered spec (mutated identity-bearing field without re-hashing) must fail closed.
        anchor = list(self.curated_members().values())[3].spec_path
        self.assertTrue(os.path.isfile(anchor), f"tamper anchor spec missing: {anchor}")
        spec = self.load_json(anchor)
        spec["procedure"] = "tampered"
        out = self.dump_json(spec, os.path.join(self.tmp, "tampered_spec.json"))
        self.val_reject("tampered spec (hash mismatch)",
                        "scripts/validators/validate_capability_spec.py", out)


if __name__ == "__main__":
    unittest.main()
