#!/usr/bin/env python3
"""Spec-feature coverage matrix (M5 WP7, ).

The sample coverage matrix that "forces generalization": it enumerates every spec
FEATURE (a kernel primitive requirement carried in a spec's `targetRequirements`)
across all committed sample specs, and records which fixtures exercise each feature
and which target lowerings each fixture provides. It is the spec-level gate for
domain scaling — fail-closed and deterministic, standard library only.

The closed glue vocabulary is the union of `supportedFeatures` and
`unsupportedConstructs` across the committed target profiles
(examples/target-profiles/*.target-profile.json). Target profiles match PRIMITIVES,
not domain labels (), so a spec feature that is not explicitly supported or
unsupported is an unglued term — it must fail here, before any renderer. Coverage is
measured only over supported primitives: an explicit denial is accounted for but is
not a backend capability claim.

Checks (fail-closed):
  1. glue: every feature appearing in a sample spec is explicitly supported or
     explicitly unsupported — an unknown/unglued term fails before renderers;
  2. coverage: every supported primitive is exercised by at least one fixture
     (no supported-but-unexercised "decoration" primitive — e.g. evidence);
  3. gate samples: each of the four WP7 gate samples emits a schema-valid spec
     through the same kernel/spec path;
  4. drift: the committed matrix doc (docs/spec/SPEC_FEATURE_MATRIX.md) is up to date.

Usage:
  spec_feature_matrix.py --write   # regenerate docs/spec/SPEC_FEATURE_MATRIX.md
  spec_feature_matrix.py --check   # fail-closed gate (default)

Exit 0 ok / 1 violations / 2 usage.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # samples/ -> scripts -> repo ()
LOWERINGS = ("solidity", "postgres", "slot")
# The WP7 gate samples (): installment, co-branded/earmarked redemption,
# conditional escrow, and one non-payment evidence-heavy sample.
GATE_SAMPLES = ("curated-0", "curated-1", "curated-6", "curated-5")
MATRIX_DOC = os.path.join(REPO, "docs", "spec", "SPEC_FEATURE_MATRIX.md")


def profile_vocabularies(profiles=None) -> tuple[set[str], set[str]]:
    """Return (known glue vocabulary, supported coverage vocabulary)."""
    known: set[str] = set()
    supported: set[str] = set()
    if profiles is None:
        profiles = []
        for path in sorted(glob.glob(
                os.path.join(REPO, "examples", "target-profiles", "*.target-profile.json"))):
            with open(path, encoding="utf-8") as handle:
                profiles.append(json.load(handle))
    for profile in profiles:
        profile_supported = set(profile.get("supportedFeatures", []))
        supported |= profile_supported
        known |= profile_supported | set(profile.get("unsupportedConstructs", []))
    return known, supported


def primitive_vocabulary() -> set[str]:
    """Closed glue vocabulary: explicitly supported or explicitly unsupported."""
    return profile_vocabularies()[0]


def sample_specs() -> dict[str, dict]:
    """domain -> {features: sorted[str], lowerings: sorted[str], spec_path: str}."""
    sys.path.insert(0, os.path.join(REPO, "scripts", "gates"))
    import m6_pack_resolver

    with open(os.path.join(REPO, "docs", "m6-curated-example-corpus.json"),
              encoding="utf-8") as handle:
        manifest = json.load(handle)
    members = m6_pack_resolver.resolve_members(
        manifest, repo=Path(REPO)
    )
    out: dict[str, dict] = {}
    for index, member_id in enumerate(manifest["examples"]):
        member = members[member_id]
        d = str(member.root)
        spec_path = str(member.spec_path)
        name = f"curated-{index}"
        with open(spec_path, encoding="utf-8") as handle:
            spec = json.load(handle)
        feats = sorted({r["feature"]
                        for r in spec.get("targetRequirements", {}).get("requirements", [])})
        low = sorted(t for t in LOWERINGS
                     if os.path.isdir(os.path.join(d, "generated", t)))
        out[name] = {"features": feats, "lowerings": low, "spec_path": spec_path}
    return out


def build_matrix(vocab: set[str], specs: dict[str, dict]) -> dict:
    """feature -> {fixtures: [names], lowerings: [targets union across fixtures]}."""
    matrix: dict[str, dict] = {f: {"fixtures": [], "lowerings": set()} for f in vocab}
    for name, info in specs.items():
        for f in info["features"]:
            entry = matrix.setdefault(f, {"fixtures": [], "lowerings": set()})
            entry["fixtures"].append(name)
            entry["lowerings"] |= set(info["lowerings"])
    for f in matrix:
        matrix[f]["fixtures"].sort()
        matrix[f]["lowerings"] = sorted(matrix[f]["lowerings"])
    return matrix


def render_doc(vocab: set[str], supported: set[str], specs: dict[str, dict],
               matrix: dict) -> str:
    lines = []
    lines.append("# Spec-feature coverage matrix (M5 WP7, )")
    lines.append("")
    lines.append("<!-- GENERATED by scripts/samples/spec_feature_matrix.py --write. DO NOT EDIT. -->")
    lines.append("")
    lines.append("Every spec **feature** is a kernel-primitive requirement carried in a spec's")
    lines.append("`targetRequirements`. Target profiles match primitives, not domain labels (),")
    lines.append("so this matrix is keyed by the closed primitive glue vocabulary (the union of")
    lines.append("`supportedFeatures` and `unsupportedConstructs` across the committed target")
    lines.append("profiles). A feature outside that vocabulary is an unglued term and fails the gate")
    lines.append("before any renderer.")
    lines.append("")
    lines.append("**Coverage denominator.** The denominator is the profile-*supported* primitive")
    lines.append("vocabulary — not explicitly unsupported constructs and not every primitive the")
    lines.append("kernel could theoretically emit. So this matrix proves a two-sided closure: every")
    lines.append("profile-supported primitive is exercised by a fixture (coverage), and every feature")
    lines.append("a spec emits is explicitly supported or unsupported (glue). It does **not** claim")
    lines.append("\"every kernel primitive is exercised\": a primitive")
    lines.append("the kernel could emit that no spec emits *and* no profile declares is dormant and")
    lines.append("invisible to both sides by design.")
    lines.append("")
    lines.append("## Feature -> fixtures / lowerings")
    lines.append("")
    lines.append("The `lowerings on covering fixtures` column is **fixture-granularity**: the union")
    lines.append("of committed backend lowerings across the fixtures that carry this feature — NOT a")
    lines.append("claim that this specific feature is exercised through that lowering. Per-feature")
    lines.append("lowering coverage is the lowering-level gate, tracked in .")
    lines.append("")
    lines.append("| Spec feature (primitive) | # fixtures | fixtures | lowerings on covering fixtures |")
    lines.append("| --- | --- | --- | --- |")
    for f in sorted(matrix):
        e = matrix[f]
        fixtures = ", ".join(e["fixtures"]) or "—"
        low = ", ".join(e["lowerings"]) or "— (spec only)"
        status = "supported" if f in supported else "explicitly unsupported"
        lines.append(f"| `{f}` ({status}) | {len(e['fixtures'])} | {fixtures} | {low} |")
    lines.append("")
    lines.append("## Fixture -> features / lowerings")
    lines.append("")
    lines.append("| Fixture | # features | lowerings committed |")
    lines.append("| --- | --- | --- |")
    for name in sorted(specs):
        info = specs[name]
        low = ", ".join(info["lowerings"]) or "— (spec only)"
        star = " ⭐" if name in GATE_SAMPLES else ""
        lines.append(f"| {name}{star} | {len(info['features'])} | {low} |")
    lines.append("")
    lines.append("⭐ = WP7 gate sample. `lowerings` at the fixture level are the committed")
    lines.append("backend artifacts (solidity/postgres/slot); a `spec only` fixture emits a")
    lines.append("schema-valid spec but no committed lowering yet (lowering-level coverage is the")
    lines.append("WP7 lowering gate, tracked separately).")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def check(vocab: set[str], specs: dict[str, dict], matrix: dict,
          supported: set[str] | None = None) -> list[str]:
    errors: list[str] = []
    if supported is None:
        supported = profile_vocabularies()[1]
    # 1. glue: every feature in a sample spec is a known primitive.
    used = {f for info in specs.values() for f in info["features"]}
    for f in sorted(used - vocab):
        errors.append(f"glue: spec feature '{f}' is not a known primitive (not in any "
                      f"target profile's supportedFeatures or unsupportedConstructs) — "
                      f"an unglued term")
    # 2. coverage: every supported primitive is exercised by >= 1 fixture.
    for f in sorted(supported):
        if not matrix.get(f, {}).get("fixtures"):
            errors.append(f"coverage: primitive '{f}' is declared in a target profile but "
                          f"exercised by NO sample spec (declared-but-unexercised decoration)")
    # 3. gate samples emit schema-valid specs through the same path.
    for name in GATE_SAMPLES:
        if name not in specs:
            errors.append(f"gate-sample: '{name}' has no committed capability-spec.json")
            continue
        rc = subprocess.run(
            [sys.executable, os.path.join(REPO, "scripts", "validators", "validate_capability_spec.py"),
             specs[name]["spec_path"]],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        if rc != 0:
            errors.append(f"gate-sample: '{name}' capability-spec.json is not schema-valid (rc={rc})")
    # 4. drift: committed doc up to date.
    want = render_doc(vocab, supported, specs, matrix)
    if os.path.isfile(MATRIX_DOC):
        with open(MATRIX_DOC, encoding="utf-8") as handle:
            have = handle.read()
    else:
        have = ""
    if want != have:
        errors.append("drift: docs/spec/SPEC_FEATURE_MATRIX.md is stale — regenerate with "
                      "scripts/samples/spec_feature_matrix.py --write")
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--write", action="store_true", help="regenerate the matrix doc")
    g.add_argument("--check", action="store_true", help="fail-closed gate (default)")
    args = ap.parse_args()

    vocab, supported = profile_vocabularies()
    specs = sample_specs()
    if not vocab or not specs:
        print("error: no target profiles or sample specs found", file=sys.stderr)
        return 2
    matrix = build_matrix(vocab, specs)

    if args.write:
        with open(MATRIX_DOC, "w", encoding="utf-8") as handle:
            handle.write(render_doc(vocab, supported, specs, matrix))
        print(f"wrote {os.path.relpath(MATRIX_DOC, REPO)} "
              f"({len(vocab)} primitives x {len(specs)} fixtures)")
        return 0

    errors = check(vocab, specs, matrix, supported)
    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1
    covered_low = sorted({t for info in specs.values() for t in info["lowerings"]})
    print(f"ok: {len(vocab)} known primitives, {len(supported)} supported and all exercised "
          f"by >=1 of {len(specs)} fixtures; "
          f"{len(GATE_SAMPLES)} gate samples schema-valid; "
          f"lowerings present: {', '.join(covered_low)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
