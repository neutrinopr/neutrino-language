#!/usr/bin/env python3
"""Check that lit's repository test-root substitution is exact."""

import os
import sys


def main() -> int:
    if len(sys.argv) != 3:
        sys.stderr.write("usage: check_test_substitution.py TEST_ROOT TEST_IR_ROOT\n")
        return 2
    test_root = os.path.realpath(sys.argv[1])
    test_ir_root = os.path.realpath(sys.argv[2])
    expected = os.path.dirname(test_ir_root)
    if test_root != expected:
        sys.stderr.write(
            f"%test substitution mismatch: got {test_root}, expected {expected}\n"
        )
        return 1
    sentinel = os.path.join(test_root, "ir", "lit.cfg.py")
    if not os.path.isfile(sentinel):
        sys.stderr.write(
            f"%test substitution does not reach the source test tree: {sentinel}\n"
        )
        return 1
    print(f"%test substitution OK: {test_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
