"""[fast]  governance policy: identity-based comment retirement for the
target-node registry  ratchet, BOUND to the added handler's identity.

A new generated handler may be credited by a retired governed COMMENT shape, but
the credit binds BOTH sides: (a) the retirement is keyed to the removed comment
DIGESTS (never `len(comments)`), and (b) the newly-ADDED generated handler must be
a comment-class node (registry feature 'comment'). So neither a count substitution
NOR retiring a comment while adding an UNRELATED (non-comment) handler can
mechanically authorize a handler. (The authoritative PR-base resolver is proven in
test/ir/pipeline/target_node_registry.test.)
"""

import os
import sys
import unittest

from _fastcase import REPO

sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
import check_target_node_registry as gate  # noqa: E402

X, Y = "aaaaaaaaaaaaaaaa", "bbbbbbbbbbbbbbbb"
# A registry feature map: a comment-class node and an unrelated (assignment) node.
FEAT = {"SpdxLicense": "comment", "DocComment": "comment", "Assign": "assignment"}


class CommentRetirementIdentity(unittest.TestCase):
    def test_identity_shrink_only(self):
        # _comment_retirement is a strict identity shrink (retire >=1, add none).
        self.assertTrue(gate._comment_retirement(frozenset(), frozenset({X})))
        self.assertTrue(gate._comment_retirement(frozenset({X}), frozenset({X, Y})))
        self.assertFalse(gate._comment_retirement(frozenset({Y}), frozenset({X})))  # substitution
        self.assertFalse(gate._comment_retirement(frozenset({X}), frozenset({X})))  # unchanged
        self.assertFalse(gate._comment_retirement(frozenset({X}), frozenset()))     # add only
        self.assertFalse(gate._comment_retirement(frozenset({X}), None))            # no base


class CommentRetirementBoundToHandler(unittest.TestCase):
    def _c(self, added, dig_cur, dig_base):
        return gate._comment_retirement_credit(
            frozenset(added), FEAT, frozenset(dig_cur), frozenset(dig_base))

    def test_comment_handler_with_retirement_credits(self):
        self.assertTrue(self._c({"SpdxLicense"}, set(), {X}))

    def test_unrelated_handler_with_retirement_does_not_credit(self):
        # The P1: retire a genuine comment identity but add an UNRELATED
        # (non-comment) handler in the same slice — must NOT credit.
        self.assertFalse(self._c({"Assign"}, set(), {X}))
        # Mixed: one comment + one unrelated added handler is also not all-comment.
        self.assertFalse(self._c({"SpdxLicense", "Assign"}, set(), {X}))

    def test_comment_handler_without_retirement_does_not_credit(self):
        self.assertFalse(self._c({"SpdxLicense"}, {X}, {X}))    # nothing retired
        self.assertFalse(self._c({"SpdxLicense"}, {Y}, {X}))    # substitution

    def test_no_added_handler_does_not_credit(self):
        self.assertFalse(self._c(set(), set(), {X}))


class NodeFeaturesParsesRealRegistry(unittest.TestCase):
    """Exercise the REAL `_node_features()` against the committed `.inc`, not a
    synthetic feature map. The registry `leaf` column is a bool LITERAL
    (true/false); a `\\d+` match silently returned {}, which made
    `_comment_retirement_credit` (all added nodes must be feature=='comment')
    ALWAYS return False — a dead credit path a synthetic-dict test cannot catch."""

    def setUp(self):
        #  P1.1: _node_features is per-backend now (it reads the backend's own
        # generated registry .inc). Build a per-target map and a combined view.
        self.backends = gate.discover_backends()
        self.feat_by_target = {b["target"]: gate._node_features(b) for b in self.backends}
        self.feat = {}
        for f in self.feat_by_target.values():
            self.feat.update(f)

    def test_features_non_empty(self):
        for target, feat in self.feat_by_target.items():
            self.assertTrue(feat, f"_node_features() parsed the {target} .inc to {{}}")

    def test_every_generated_node_is_classified(self):
        # Every generated-handler node (across all backends) has a registry feature
        # in its OWN backend's parsed map.
        gen = gate._generated_nodes(gate._read(gate.INVENTORY))
        self.assertIsNotNone(gen)
        missing = sorted(n for n in gen if n not in self.feat)
        self.assertEqual(missing, [], f"generated nodes with no registry feature: {missing}")

    def test_comment_class_node_credits_through_real_map(self):
        # A real comment-class node (from the committed Solidity registry) + a
        # genuine retirement credits; a real non-comment node does not — proving the
        # credit consults the ACTUAL parsed feature classes.
        feat = self.feat_by_target["solidity"]
        comment_nodes = [n for n, f in feat.items() if f == "comment"]
        other_nodes = [n for n, f in feat.items() if f != "comment"]
        self.assertTrue(comment_nodes and other_nodes, "registry lacks both classes to probe")
        self.assertTrue(gate._comment_retirement_credit(
            frozenset({comment_nodes[0]}), self.feat, frozenset(), frozenset({X})))
        self.assertFalse(gate._comment_retirement_credit(
            frozenset({other_nodes[0]}), self.feat, frozenset(), frozenset({X})))


if __name__ == "__main__":
    unittest.main()
