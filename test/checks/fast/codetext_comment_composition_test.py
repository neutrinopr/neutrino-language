"""[fast]  /  review P1: the codetext trailing-composition surface is
GOVERNED to be comment-only, so a later production caller cannot append raw
target grammar after a generated/typed node.

The storage migration hangs an aligned trailing comment off a typed StorageDecl
node. That composition must NOT be an arbitrary-string append (which would let a
backend emit a second live construct outside the `.td`-owned declaration and
still keep the raw-seam ratchet green). This gate pins the structural shape:
codetext exposes ONE trailing primitive, `commentedLine`, which takes a padding
COUNT + a comment BODY and OWNS the `// ` framing itself — so the body is always
rendered behind `//` on one physical line (structurally inert). The behavioural
proof (a code-bearing body renders as an inert comment, a newline is rejected)
lives in the CodeText gtest tier; this gate keeps the SURFACE from regressing.
"""

import os
import re
import unittest

from _fastcase import REPO


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        text = f.read()
    assert text, "empty/renamed source — the governance gate would pass vacuously"
    return text


class CodetextCommentCompositionGovernance(unittest.TestCase):
    def setUp(self):
        self.hdr = _read("include/Neutrino/CodeText.h")
        self.cpp = _read("lib/codetext/CodeText.cpp")
        self.sol = _read("lib/backends/solidity/provider/SolidityRenderer.cpp")

    def test_trailing_primitive_takes_a_padding_count_not_a_raw_suffix(self):
        # The ONLY trailing composition is `commentedLine(Node, unsigned pad,
        # std::string body)`: a padding COUNT and a comment BODY — never a
        # free-form suffix string appended verbatim after the node.
        self.assertRegex(
            self.hdr,
            r"Node\s+commentedLine\s*\(\s*Node\s+\w+\s*,\s*unsigned\s+\w+\s*,"
            r"\s*std::string\s+\w+\s*\)")

    def test_no_arbitrary_raw_suffix_append_primitive_exists(self):
        # A `suffixLine(Node, std::string)`-style raw append after a node would
        # reopen the ungoverned raw-syntax surface (a backend could append
        # `; uint256 public injected;`). It must not exist in the public header
        # OR the implementation.
        self.assertNotIn("suffixLine", self.hdr)
        self.assertNotIn("suffixLine", self.cpp)

    def test_codetext_owns_the_comment_framing(self):
        # codetext emits the `// ` prefix itself in the CommentLine printer, so
        # the body is ALWAYS behind it — a code-bearing body is inert, never
        # live source. The framing is not caller-supplied.
        self.assertIn('"// "', self.cpp)

    def test_solidity_storage_hangs_comments_via_the_governed_primitive(self):
        # The Solidity printer uses `commentedLine` (not a raw suffix), and the
        # storage comment operands it passes are BODIES ONLY — no literal carries
        # `//` framing, so the framing can never be smuggled in through a body.
        self.assertIn("commentedLine(", self.sol)
        self.assertNotIn("suffixLine(", self.sol)
        # No storage comment literal reintroduces `//` framing. The storage
        # slots store unframed bodies like `"key -> ledger -> net"`.
        self.assertFalse(
            re.search(r'"//[^"]*->', self.sol),
            "a storage comment literal still carries `//` framing — the body "
            "must be unframed so codetext owns the comment prefix")


if __name__ == "__main__":
    unittest.main()
