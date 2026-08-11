#!/usr/bin/env python3
"""Compare a freshly-derived S7 register (arg1) to the committed one (arg2).

Used by the  build-tier lit witness: the derived register's evidence refs point
at an ephemeral evidence dir, so we compare only the earned SEMANTIC cells of the
row — proving the committed artifact matches what the BUILT tool derives right now.
"""
import json
import sys

CELLS = ("rowId", "outcome", "class", "disposition", "supportStatus",
         "failedVerifierObligation", "minimalCounterexample", "linkedDecision")


def row(path):
    rows = json.load(open(path))["rows"]
    if len(rows) != 1:
        sys.exit(f"{path}: expected exactly one row, got {len(rows)}")
    return rows[0]


def main():
    derived, committed = row(sys.argv[1]), row(sys.argv[2])
    diffs = [f"  {c}: derived={derived.get(c)!r} != committed={committed.get(c)!r}"
             for c in CELLS if derived.get(c) != committed.get(c)]
    if diffs:
        sys.exit("derived register drifted from committed on:\n" + "\n".join(diffs))
    if derived["disposition"] != "LAYER_DECISION_REQUIRED" or derived["class"] != "3":
        sys.exit(f"earned row is not Class-3 LAYER_DECISION_REQUIRED: {derived['class']}/{derived['disposition']}")
    print("OK: built-tool derived row matches committed (Class-3 LAYER_DECISION_REQUIRED)")


if __name__ == "__main__":
    main()
