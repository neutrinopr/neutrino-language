"""[fast] M5 WP2 (): test-realization validator — committed companions validate +
cross-check the spec; tampered reference fails closed."""

import os
import unittest

from _fastcase import FastCase, REPO


class TestRealization(FastCase):
    def test_committed_realizations_validate(self):
        members = self.curated_members()
        trs = []
        for name, member in members.items():
            tr = member.root / "generated" / "test-realization" / "test-realization.json"
            if not tr.is_file():
                continue
            trs.append(tr)
            self.val_ok(f"pack realization {name}",
                        "scripts/validators/validate_test_realization.py",
                        tr, "--spec", member.spec_path)
        self.require_floor("committed test realizations", len(trs), 1)

    def test_tampered_realization_fails_closed(self):
        # A realization whose capabilityHash reference does not match the spec fails closed.
        base = os.path.join(REPO, "test/ir/pipeline/Inputs/core_sample_installment/generated")
        tr = os.path.join(base, "test-realization/test-realization.json")
        spec = os.path.join(base, "capability-spec/capability-spec.json")
        self.assertTrue(os.path.isfile(tr), f"tamper anchor realization missing: {tr}")
        obj = self.load_json(tr)
        obj["capabilityHash"] = "0" * 64
        out = self.dump_json(obj, os.path.join(self.tmp, "tampered_realization.json"))
        self.val_reject("tampered realization (hash mismatch)",
                        "scripts/validators/validate_test_realization.py", out, "--spec", spec)


if __name__ == "__main__":
    unittest.main()
