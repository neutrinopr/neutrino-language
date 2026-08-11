#!/usr/bin/env python3
"""Gate entry point for the compiler-derived core feature/example matrix."""

import sys
from pathlib import Path

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
sys.path.insert(0, str(SAMPLES))

from make_core_feature_example_matrix import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
