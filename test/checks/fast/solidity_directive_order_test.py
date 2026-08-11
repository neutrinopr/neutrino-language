#!/usr/bin/env python3
"""[fast]  slice 5: source-unit directive ORDER is deterministic across every
committed Solidity golden.

Solidity requires a fixed source-unit order: the `// SPDX-License-Identifier:`
comment first, then the `pragma`, then any `import`s — before the contract body.
Slices 1-4 typed each directive record; this pins their ORDER as a checked
contract so a directive-order mutation (e.g. pragma before SPDX, or an import
ahead of the pragma) bites — complementing the per-record syntax-mutation proofs
and the structural invariant in solidity_model_test.cpp. Bytes stay identical;
this validates the ORDER already present in the goldens, and fails closed if a
future change reorders them.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

from _fastcase import REPO


def _directive_order_violation(sol_text):
    """The first source-unit ordering rule broken by `sol_text`, or None. The
    contract requires: SPDX first, then the pragma, then any imports, and ALL of
    these directives before the first contract-body line (contract/interface/
    library/... — the first non-blank, non-comment, non-pragma, non-import line).
    Only the FIRST occurrence of each directive is considered."""
    spdx = pragma = imp = body = None
    for i, line in enumerate(sol_text.splitlines()):
        s = line.strip()
        if not s:
            continue
        is_comment = s.startswith("//") or s.startswith("/*") or s.startswith("*")
        is_pragma = s.startswith("pragma ")
        is_import = s.startswith("import ")
        if spdx is None and s.startswith("// SPDX-License-Identifier:"):
            spdx = i
        if pragma is None and s.startswith("pragma solidity"):
            pragma = i
        if imp is None and is_import:
            imp = i
        # The first body line: not blank, not a comment, and not a directive.
        if body is None and not is_comment and not is_pragma and not is_import:
            body = i
    if spdx is None or pragma is None:
        return "missing SPDX license and/or pragma directive"
    if not spdx < pragma:
        return f"SPDX (line {spdx}) must precede the pragma (line {pragma})"
    if imp is not None and not pragma < imp:
        return f"pragma (line {pragma}) must precede the import (line {imp})"
    if body is not None:
        for name, idx in (("SPDX", spdx), ("pragma", pragma), ("import", imp)):
            if idx is not None and idx > body:
                return (f"{name} (line {idx}) must precede the contract body "
                        f"(line {body})")
    return None


def _solidity_src_goldens():
    out = subprocess.check_output(
        ["git", "-C", REPO, "ls-files", "*/solidity/src/*.sol"], text=True)
    # src contracts only; exclude Foundry .t.sol test scaffolds.
    paths = [Path(REPO, p) for p in out.splitlines()
             if p.endswith(".sol") and not p.endswith(".t.sol")
             and Path(REPO, p).is_file()]
    sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
    import m6_pack_resolver
    import json
    with open(os.path.join(REPO, "docs", "m6-curated-example-corpus.json"),
              encoding="utf-8") as stream:
        manifest = json.load(stream)
    members = m6_pack_resolver.resolve_members(manifest, repo=Path(REPO))
    for member in members.values():
        paths.extend(sorted((member.root / "generated" / "solidity" / "src").glob("*.sol")))
    return paths


class SolidityDirectiveOrder(unittest.TestCase):
    def test_every_committed_golden_has_canonical_directive_order(self):
        goldens = _solidity_src_goldens()
        # Floor so an eroded discovery cannot pass on zero work.
        self.assertGreaterEqual(
            len(goldens), 12,
            f"expected >=12 translator/receipted-pack Solidity src goldens, "
            f"found {len(goldens)}")
        violations = []
        for rel in goldens:
            with open(rel, encoding="utf-8") as fh:
                v = _directive_order_violation(fh.read())
            if v is not None:
                violations.append(f"{rel}: {v}")
        self.assertEqual(violations, [], f"directive-order violations: {violations}")

    def test_check_is_non_vacuous_on_a_reordered_golden(self):
        # Take a real golden and swap the SPDX and pragma lines: the checker must
        # flag it, so the invariant genuinely bites on a directive reorder.
        goldens = _solidity_src_goldens()
        with open(goldens[0], encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        spdx = next(i for i, l in enumerate(lines)
                    if l.strip().startswith("// SPDX-License-Identifier:"))
        pragma = next(i for i, l in enumerate(lines)
                      if l.strip().startswith("pragma solidity"))
        lines[spdx], lines[pragma] = lines[pragma], lines[spdx]
        self.assertIsNotNone(
            _directive_order_violation("\n".join(lines)),
            "the directive-order check did NOT bite on a pragma-before-SPDX reorder")

    def test_import_before_pragma_is_rejected(self):
        # A synthetic source unit that places the import ahead of the pragma.
        bad = ('// SPDX-License-Identifier: MIT\n'
               'import "./CoordinationEnvelope.sol";\n'
               'pragma solidity ^0.8.20;\n')
        self.assertIsNotNone(_directive_order_violation(bad),
                             "an import ahead of the pragma must be flagged")

    def test_directive_after_contract_body_is_rejected(self):
        # The "before the contract body" half: a pragma after the contract, and an
        # import after the contract, must both be flagged (not just SPDX<pragma).
        pragma_after_body = ('// SPDX-License-Identifier: MIT\n'
                             'contract X {}\n'
                             'pragma solidity ^0.8.20;\n')
        self.assertIsNotNone(
            _directive_order_violation(pragma_after_body),
            "a pragma after the contract body must be flagged")
        import_after_body = ('// SPDX-License-Identifier: MIT\n'
                             'pragma solidity ^0.8.20;\n'
                             'contract X {}\n'
                             'import "./Late.sol";\n')
        self.assertIsNotNone(
            _directive_order_violation(import_after_body),
            "an import after the contract body must be flagged")

    def test_canonical_source_unit_with_body_passes(self):
        # A well-formed source unit (directives, then body) has no violation.
        ok = ('// SPDX-License-Identifier: MIT\n'
              'pragma solidity ^0.8.20;\n\n'
              'import "./CoordinationEnvelope.sol";\n\n'
              '/// doc\n'
              'contract X {}\n')
        self.assertIsNone(_directive_order_violation(ok),
                          "a canonical directives-then-body source unit must pass")


if __name__ == "__main__":
    unittest.main()
