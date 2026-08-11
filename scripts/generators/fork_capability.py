#!/usr/bin/env python3
"""Phase 17 follow-up — capability fork (migration assist).

Scaffolds a NEW versioned capability from an existing `.neu`, per the
capability-forking policy (docs/process/VERSIONING.md): a breaking change is a new
version, not a mutation of the deployed one. This tool carries the whole source
forward and sets/bumps its `version`, so the fork diffs cleanly against its
predecessor; the human then edits the semantics that motivated the fork.

It does not change behaviour by itself — it only produces the next version's
starting point and records provenance (from/to + source hash) in a deterministic
fork-manifest.json.

  fork_capability.py --source OLD.neu (--version X.Y.Z | --bump major|minor|patch) \
                     --out NEW.neu [--manifest fork-manifest.json]

Exit 0 ok / 2 usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

VERSION_RE = re.compile(r'^([ \t]*)version[ \t]+"([^"]*)"[ \t]*$', re.MULTILINE)
TRIGGER_RE = re.compile(r'\n([ \t]*)trigger[ \t]+[^\n]*\n')
PROC_OPEN_RE = re.compile(r'\n([ \t]*)procedure[ \t]+\w+[ \t]*\{[ \t]*\n')


def current_version(src: str) -> str:
    m = VERSION_RE.search(src)
    return m.group(2) if m else "0.1.0"


def bump(version: str, part: str) -> str:
    try:
        major, minor, patch = (int(x) for x in version.split("."))
    except ValueError:
        raise SystemExit(f"error: current version {version!r} is not MAJOR.MINOR.PATCH")
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def set_version(src: str, new: str) -> str:
    """Replace the version value if present, else insert after trigger / proc open."""
    if VERSION_RE.search(src):
        return VERSION_RE.sub(lambda m: f'{m.group(1)}version "{new}"', src, count=1)
    m = TRIGGER_RE.search(src) or PROC_OPEN_RE.search(src)
    if not m:
        raise SystemExit("error: could not find an insertion point (no trigger / procedure)")
    indent = m.group(1) if m.re is TRIGGER_RE else m.group(1) + "    "
    return src[:m.end()] + f'{indent}version "{new}"\n' + src[m.end():]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--version", help="explicit new version MAJOR.MINOR.PATCH")
    ap.add_argument("--bump", choices=["major", "minor", "patch"],
                    help="bump the current version")
    ap.add_argument("--manifest", help="write a fork-manifest.json here")
    args = ap.parse_args()

    if bool(args.version) == bool(args.bump):
        print("error: pass exactly one of --version or --bump", file=sys.stderr)
        return 2
    try:
        src = open(args.source).read()
    except OSError as e:
        print(f"error: cannot read source: {e}", file=sys.stderr)
        return 2

    cur = current_version(src)
    # Validate the current version BEFORE writing anything: both --bump and the
    # --version breaking calculation need cur as MAJOR.MINOR.PATCH, so a non-semver
    # current version (e.g. "dev") is a usage error — fail cleanly with exit 2
    # rather than writing out.neu and then crashing on the int() below.
    if not re.fullmatch(r"\d+\.\d+\.\d+", cur):
        print(f"error: current version {cur!r} is not MAJOR.MINOR.PATCH; "
              "cannot fork from a non-semver version", file=sys.stderr)
        return 2
    new = args.version if args.version else bump(cur, args.bump)
    if not re.fullmatch(r"\d+\.\d+\.\d+", new):
        print(f"error: target version {new!r} is not MAJOR.MINOR.PATCH", file=sys.stderr)
        return 2

    out_src = set_version(src, new)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(out_src)

    breaking = (args.bump == "major") or (
        args.version and int(new.split(".")[0]) > int(cur.split(".")[0]))
    manifest = {
        "kind": "neutrino.capability-fork",
        "from": {"path": os.path.basename(args.source), "version": cur,
                 "sha256": hashlib.sha256(src.encode()).hexdigest()},
        "to": {"path": os.path.basename(args.out), "version": new},
        "breaking": bool(breaking),
        "note": "scaffold only: source carried forward with version set; edit semantics next. "
                "Deployed capabilities are immutable — this forks, it does not mutate.",
    }
    if args.manifest:
        os.makedirs(os.path.dirname(os.path.abspath(args.manifest)), exist_ok=True)
        with open(args.manifest, "w") as f:
            json.dump(manifest, f, indent=2, sort_keys=True)
            f.write("\n")

    print(f"forked {cur} -> {new}"
          + (" (BREAKING / MAJOR)" if breaking else "")
          + f": wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
