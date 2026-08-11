"""[fast] M5 R3 (): side-artifact capability-spec version pins — committed profiles +
dialect pin the emitted contract; mismatch/missing/drift fail closed."""

import os
import unittest

from _fastcase import FastCase


class ArtifactPins(FastCase):
    def test_versioninfo_schema_lockstep(self):
        # Each side artifact declares capabilitySpecVersion pinning VersionInfo.h's emitted
        # kCapabilitySpecVersion, kept in lockstep with the capability-spec schema $id.
        self.val_ok("VersionInfo.h <-> capability-spec schema $id lockstep",
                    "scripts/gates/check_artifact_pins.py", "--self-check")

    def test_committed_side_artifacts_pin(self):
        # Discover ALL committed production profiles + dialects by glob (negatives live in subdirs,
        # not matched) so a NEW side artifact added without a pin fails closed rather than silently
        # escaping a hand-maintained list.
        profiles = self.globr("examples/target-profiles/*.target-profile.json")
        dialects = self.globr("examples/domain-dialects/*.dialect.json")
        self.assertTrue(profiles and dialects, "no committed profiles/dialects discovered")
        self.val_ok("every committed target profile + dialect pins the emitted contract version",
                    "scripts/gates/check_artifact_pins.py", *profiles, *dialects)

    def test_negatives_fail_closed(self):
        negs = self.globr("examples/artifact-pins/negatives/*.json")
        for f in negs:
            self.val_reject(f"artifact-pin negative {os.path.basename(f)}",
                            "scripts/gates/check_artifact_pins.py", f)
        # Ratchet floor pinned to the committed negative count (): the negatives (wrong pin,
        # missing pin, unpinnable kind) are the fail-closed proof; partial erosion must fail.
        self.require_floor("artifact-pin negatives", len(negs), 4)


if __name__ == "__main__":
    unittest.main()
