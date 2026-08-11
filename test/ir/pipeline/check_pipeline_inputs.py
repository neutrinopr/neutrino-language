"""Focused missing-input probe for the  /  lit fixture boundary."""

from pathlib import Path
import json
import sys
import tempfile

from pipeline_inputs import (CORE_FIXTURES, PipelineInputError,
                             REGISTRY_MEMBERS, _fixture,
                             discover_core_fixture_roots, resolve_core_fixture,
                             resolve_core_fixtures, resolve_pipeline_inputs)


if len(sys.argv) != 2:
    print("usage: check_pipeline_inputs.py <repo>", file=sys.stderr)
    raise SystemExit(2)

repo = Path(sys.argv[1]).resolve()

# The live boundary must first resolve all receipt-verified inputs.
try:
    resolved = resolve_pipeline_inputs(repo)
except PipelineInputError as error:
    print(f"[1072] FAIL: {error}", file=sys.stderr)
    raise SystemExit(1)

manifest_members = set(
    json.load(
        (repo / "docs/m6-curated-example-corpus.json").open(encoding="utf-8")
    )["examples"]
)
if set(resolved) != manifest_members | REGISTRY_MEMBERS:
    print("[1072] FAIL: pipeline input registry has the wrong members", file=sys.stderr)
    raise SystemExit(1)

# Biting removal probe: a missing source must be diagnosed at the input
# boundary, naming the exact owner/surface, before any generator can run.
with tempfile.TemporaryDirectory(prefix="pipeline-input-1072.") as temp:
    root = Path(temp) / "missing_source"
    (root / "scenario").mkdir(parents=True)
    (root / "scenario" / "happy.json").write_text("{}\n", encoding="utf-8")
    try:
        _fixture("synthetic_missing", root, scenario_required=True)
    except PipelineInputError as error:
        diagnostic = str(error)
        expected = (
            "required pipeline input missing: synthetic_missing.source "
            f"(directory {root / 'source'})"
        )
        if diagnostic != expected:
            print(
                "[1072] FAIL: missing-input diagnostic drifted: "
                f"{diagnostic!r} != {expected!r}",
                file=sys.stderr,
            )
            raise SystemExit(1)
    else:
        print("[1072] FAIL: removed source did not fail at the input boundary", file=sys.stderr)
        raise SystemExit(1)

# : the core-owned synthetic registry must be a BIJECTION with what is
# committed. A fixture added, moved or deleted without updating CORE_FIXTURES is
# how `examples/domains/` reach-back went unnoticed: a corpus quietly shrank
# instead of failing. Prove both directions, then prove the check bites.
try:
    resolve_core_fixtures(repo)
except PipelineInputError as error:
    print(f"[1080] FAIL: {error}", file=sys.stderr)
    raise SystemExit(1)
committed_core = discover_core_fixture_roots(repo)
if committed_core.keys() != set(CORE_FIXTURES):
    print("[1080] FAIL: core fixture registry drifted from the committed tree",
          file=sys.stderr)
    raise SystemExit(1)
if len(CORE_FIXTURES) < 14:
    print(f"[1080] FAIL: core fixture registry shrank to {len(CORE_FIXTURES)} "
          "(need >=14) — core-owned coverage may not be deleted silently",
          file=sys.stderr)
    raise SystemExit(1)

# Biting probe: an unregistered name is refused by NAME, not silently resolved.
try:
    resolve_core_fixture(repo, "core_not_registered")
except PipelineInputError as error:
    if "is not registered" not in str(error):
        print(f"[1080] FAIL: unregistered core fixture diagnostic drifted: {error}",
              file=sys.stderr)
        raise SystemExit(1)
else:
    print("[1080] FAIL: an unregistered core fixture resolved", file=sys.stderr)
    raise SystemExit(1)

# Biting probe: a registered fixture whose surface is absent names the surface.
_probe = resolve_core_fixture(repo, "core_dual_offer")
try:
    from pipeline_inputs import require_surface
    require_surface(_probe, "generated", "no_such_surface", "gone.json")
except PipelineInputError as error:
    expected = ("required pipeline input missing: core_dual_offer."
                "generated/no_such_surface/gone.json")
    if not str(error).startswith(expected):
        print(f"[1080] FAIL: missing-surface diagnostic drifted: {error}",
              file=sys.stderr)
        raise SystemExit(1)
else:
    print("[1080] FAIL: an absent fixture surface resolved", file=sys.stderr)
    raise SystemExit(1)

print("[1072] OK: verified external-pack input boundary; missing source fails early")
print(f"[1080] OK: core fixture registry is a bijection with the committed tree "
      f"({len(CORE_FIXTURES)} fixtures); unregistered name and absent surface each "
      "fail closed naming the owner")
