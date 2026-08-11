"""[fast] M5 (): participant-view validator — committed views validate + cross-check
the spec; tampered reference fails closed."""

import os
import unittest

from _fastcase import FastCase, REPO


class ParticipantView(FastCase):
    def test_committed_views_validate(self):
        members = self.curated_members()
        views = []
        for name, member in members.items():
            member_views = sorted((member.root / "generated" / "views").glob("*.json"))
            views.extend(member_views)
            for vf in member_views:
                self.val_ok(f"pack view {name}/{vf.name}",
                            "scripts/validators/validate_participant_view.py",
                            vf, "--spec", member.spec_path)
        self.require_floor("receipted pack participant views", len(views), 1)

    def test_tampered_view_fails_closed(self):
        # A view whose capabilityHash reference does not match the spec fails closed.
        base = os.path.join(REPO, "test/ir/domain/Inputs/core_flexible_binding/generated")
        views = self.globr("test/ir/domain/Inputs/core_flexible_binding/generated/views/*.json")
        self.assertTrue(views, "tamper anchor view missing under core_flexible_binding")
        spec = os.path.join(base, "capability-spec/capability-spec.json")
        obj = self.load_json(views[0])
        obj["capability"]["capabilityHash"] = "0" * 64
        out = self.dump_json(obj, os.path.join(self.tmp, "tampered_view.json"))
        self.val_reject("tampered view (hash mismatch)",
                        "scripts/validators/validate_participant_view.py", out, "--spec", spec)


if __name__ == "__main__":
    unittest.main()
