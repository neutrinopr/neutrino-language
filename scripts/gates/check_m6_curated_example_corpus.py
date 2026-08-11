#!/usr/bin/env python3
"""Structural gate for the public M6 curated example corpus.

Validates docs/m6-curated-example-corpus.json only:
  - closed kind/schemaVersion and freeze cross-link shape
  - exactly seven examples, no duplicates, frozen membership digest
  - exactly three variance pairs; members belong to the corpus; no self-pairs;
    no duplicate unordered pairs
  - exact published-pack coordinates for every member
  - committed file bytes are deterministic canonical pretty JSON

Does NOT compute source meaning, generate goldens, change profiles/backends, or wire
the final release gate.

  python3 scripts/gates/check_m6_curated_example_corpus.py
  python3 scripts/gates/check_m6_curated_example_corpus.py --selftest
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, List, Sequence, Tuple

REPO = Path(__file__).resolve().parents[2]
MANIFEST_REL = "docs/m6-curated-example-corpus.json"
SCHEMA_REL = "docs/schemas/m6-curated-example-corpus.schema.json"
MANIFEST = REPO / MANIFEST_REL
SCHEMA = REPO / SCHEMA_REL
KIND = "neutrino.m6-curated-example-corpus"
SCHEMA_VERSION = 2
PARENT_ISSUE = "urn:neutrino:document:m6-curated-corpus-v2"
FREEZE_ISSUE = 725
FREEZE_COMMENT_ID = 5114443802
FREEZE_URL = "urn:neutrino:document:m6-curated-corpus-freeze-v2"
FREEZE_TITLE = "§4 freeze — externalization stage 3 / core production-domain zero"
ROOT_FIELDS = {
    "kind",
    "schemaVersion",
    "description",
    "parentIssue",
    "freeze",
    "examples",
    "variancePairs",
    "packs",
}

# Exact architect-frozen member and pair ordering, bound without embedding
# externalized production identities in executable core code.
FROZEN_CORPUS_SHA256 = "4b0380be6844058d871ed7570d94d7790f54fc1a3babd270dbc512213430d042"


def canonical_pretty(obj: Any) -> bytes:
    """Deterministic committed form: sorted object keys, indent 2, trailing newline."""
    return (
        json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _err(errors: List[str], msg: str) -> None:
    errors.append(msg)


def validate_manifest(raw: bytes, *, repo: Path = REPO) -> List[str]:
    errors: List[str] = []
    try:
        text = raw.decode("utf-8")
        obj = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        return [f"manifest is not valid UTF-8 JSON: {e}"]

    if not isinstance(obj, dict):
        return ["manifest must be a JSON object"]

    extra = set(obj) - ROOT_FIELDS
    if extra:
        _err(errors, f"manifest has unknown root fields: {sorted(extra)}")

    # Deterministic bytes (exact file encoding).
    try:
        expected = canonical_pretty(obj)
    except (TypeError, ValueError) as e:
        return [f"manifest is not strict-JSON canonicalizable: {e}"]
    if raw != expected:
        _err(
            errors,
            "manifest bytes are not deterministic canonical pretty JSON "
            "(indent=2, sort_keys=True, trailing newline)",
        )

    if obj.get("kind") != KIND:
        _err(errors, f"kind must be {KIND!r}")
    if obj.get("schemaVersion") != SCHEMA_VERSION:
        _err(errors, f"schemaVersion must be {SCHEMA_VERSION}")
    if obj.get("parentIssue") != PARENT_ISSUE:
        _err(errors, f"parentIssue must be {PARENT_ISSUE!r}")
    if not (isinstance(obj.get("description"), str) and obj["description"]):
        _err(errors, "description must be a non-empty string")

    freeze = obj.get("freeze")
    if not isinstance(freeze, dict):
        _err(errors, "freeze must be an object")
    else:
        if freeze.get("issue") != FREEZE_ISSUE:
            _err(errors, f"freeze.issue must be {FREEZE_ISSUE}")
        if freeze.get("commentId") != FREEZE_COMMENT_ID:
            _err(errors, f"freeze.commentId must be {FREEZE_COMMENT_ID}")
        if freeze.get("url") != FREEZE_URL:
            _err(errors, f"freeze.url must be {FREEZE_URL!r}")
        if freeze.get("title") != FREEZE_TITLE:
            _err(errors, f"freeze.title must be {FREEZE_TITLE!r}")
        extra = set(freeze) - {"issue", "commentId", "url", "title"}
        if extra:
            _err(errors, f"freeze has unknown fields: {sorted(extra)}")

    examples = obj.get("examples")
    if not isinstance(examples, list):
        _err(errors, "examples must be an array")
        examples = []
    if len(examples) != 7:
        _err(errors, f"examples must contain exactly 7 members, got {len(examples)}")
    if len(examples) != len(set(examples)):
        _err(errors, "examples must not contain duplicates")

    for ex in examples:
        if not isinstance(ex, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", ex):
            _err(errors, f"example id must be a non-empty string, got {ex!r}")

    pairs = obj.get("variancePairs")
    if not isinstance(pairs, list):
        _err(errors, "variancePairs must be an array")
        pairs = []
    if len(pairs) != 3:
        _err(errors, f"variancePairs must contain exactly 3 pairs, got {len(pairs)}")

    seen_ids = set()
    seen_unordered: set[Tuple[str, str]] = set()
    corpus = set(examples) if isinstance(examples, list) else set()
    for i, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            _err(errors, f"variancePairs[{i}] must be an object")
            continue
        pid, a, b = pair.get("id"), pair.get("a"), pair.get("b")
        if pid not in (None,) and not (isinstance(pid, str) and pid):
            _err(errors, f"variancePairs[{i}].id must be a non-empty string")
        if isinstance(pid, str):
            if pid in seen_ids:
                _err(errors, f"duplicate variance pair id {pid!r}")
            seen_ids.add(pid)
        if not isinstance(a, str) or not a:
            _err(errors, f"variancePairs[{i}].a must be a non-empty string")
        if not isinstance(b, str) or not b:
            _err(errors, f"variancePairs[{i}].b must be a non-empty string")
        if isinstance(a, str) and isinstance(b, str):
            if a == b:
                _err(errors, f"variancePairs[{i}] must not be a self-pair ({a!r})")
            if a not in corpus:
                _err(
                    errors,
                    f"variancePairs[{i}].a {a!r} is not a corpus member",
                )
            if b not in corpus:
                _err(
                    errors,
                    f"variancePairs[{i}].b {b!r} is not a corpus member",
                )
            key = tuple(sorted((a, b)))
            if key in seen_unordered:
                _err(
                    errors,
                    f"duplicate unordered variance pair {key[0]!r} ↔ {key[1]!r}",
                )
            seen_unordered.add(key)
        extra = set(pair) - {"id", "a", "b"}
        if extra:
            _err(errors, f"variancePairs[{i}] has unknown fields: {sorted(extra)}")

    frozen_body = {"examples": examples, "variancePairs": pairs}
    frozen_digest = hashlib.sha256(
        json.dumps(
            frozen_body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    if frozen_digest != FROZEN_CORPUS_SHA256:
        _err(errors, "membership or variance pairs differ from the architect freeze")

    # Published-pack coordinates are mandatory and exact: no member may fall
    # back to an in-core production tree.
    packs = obj.get("packs")
    if not isinstance(packs, dict):
        _err(errors, "packs must be an object")
    else:
        member_set = set(examples) if isinstance(examples, list) else set()
        if set(packs) != member_set:
            _err(errors, "packs must be an exact bijection with examples")
        pack_fields = {"packPath", "receiptPath", "packDigest", "bundleDigest"}
        digest_re = re.compile(r"^sha256:[0-9a-f]{64}$")
        for name, entry in packs.items():
            if not isinstance(entry, dict):
                _err(errors, f"packs[{name!r}] must be an object")
                continue
            if set(entry) != pack_fields:
                _err(
                    errors,
                    f"packs[{name!r}] must have exactly the fields "
                    f"{sorted(pack_fields)}, got {sorted(entry)}",
                )
            for field in ("packPath", "receiptPath"):
                value = entry.get(field)
                if not (isinstance(value, str) and value):
                    _err(
                        errors,
                        f"packs[{name!r}].{field} must be a non-empty string",
                    )
            for field in ("packDigest", "bundleDigest"):
                value = entry.get(field)
                if not (isinstance(value, str) and digest_re.match(value)):
                    _err(
                        errors,
                        f"packs[{name!r}].{field} must match "
                        r"^sha256:[0-9a-f]{64}$",
                    )

    # Schema file must exist (documentary companion).
    schema_path = repo / SCHEMA_REL
    if not schema_path.is_file():
        _err(errors, f"missing schema {SCHEMA_REL}")

    return errors


def check_committed() -> int:
    if not MANIFEST.is_file():
        print(f"FAIL: missing {MANIFEST_REL}", file=sys.stderr)
        return 1
    raw = MANIFEST.read_bytes()
    errors = validate_manifest(raw, repo=REPO)
    if errors:
        print(f"FAIL {MANIFEST_REL}:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"OK {MANIFEST_REL} (7 examples, 3 variance pairs, local freeze identity)")
    return 0


PROBES = {
    "frozen-membership",
    "frozen-pairs",
    "unknown-root-field",
    "missing-pack-coordinate",
    "outside-corpus-pair",
    "self-pair",
    "duplicate-pair",
    "canonical-bytes",
}


def probe_fixture(probe: str) -> Tuple[bytes, str]:
    obj = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if probe == "frozen-membership":
        obj["examples"] = obj["examples"][:-1]
        expected = "examples must contain exactly 7 members"
    elif probe == "frozen-pairs":
        obj["variancePairs"][2]["a"] = obj["examples"][0]
        expected = "membership or variance pairs differ from the architect freeze"
    elif probe == "unknown-root-field":
        obj["unexpected"] = "must fail closed"
        expected = "manifest has unknown root fields"
    elif probe == "missing-pack-coordinate":
        obj["packs"].pop(obj["examples"][0])
        expected = "packs must be an exact bijection with examples"
    elif probe == "outside-corpus-pair":
        obj["variancePairs"][2]["a"] = "not_in_corpus"
        expected = "is not a corpus member"
    elif probe == "self-pair":
        obj["variancePairs"][2]["a"] = obj["variancePairs"][2]["b"]
        expected = "must not be a self-pair"
    elif probe == "duplicate-pair":
        obj["variancePairs"][2]["a"] = obj["examples"][1]
        obj["variancePairs"][2]["b"] = obj["examples"][0]
        expected = "duplicate unordered variance pair"
    elif probe == "canonical-bytes":
        return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8"), "canonical pretty JSON"
    else:
        raise ValueError(f"unknown probe {probe!r}")
    return canonical_pretty(obj), expected


def run_probe(probe: str) -> int:
    if probe not in PROBES:
        print(f"unknown M6 curated-corpus probe {probe!r}", file=sys.stderr)
        return 2
    raw, expected = probe_fixture(probe)
    errors = validate_manifest(raw, repo=REPO)
    if any(expected in error for error in errors):
        print(f"probe-failed-as-expected:{probe}")
        return 1
    print(f"probe unexpectedly passed:{probe}: {errors}")
    return 0


def selftest() -> int:
    """Run every declared structural weakening probe against the live gate."""
    failures: List[str] = []
    if check_committed() != 0:
        failures.append("committed manifest must validate")
    for probe in sorted(PROBES):
        if run_probe(probe) != 1:
            failures.append(f"probe {probe!r} did not fail for its intended reason")
    if failures:
        print("selftest FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"selftest OK ({len(PROBES)} structural probes fail closed)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if args == ["--selftest"]:
        return selftest()
    if len(args) == 2 and args[0] == "--probe":
        return run_probe(args[1])
    if args:
        print(
            "usage: check_m6_curated_example_corpus.py [--selftest | --probe NAME]",
            file=sys.stderr,
        )
        return 2
    return check_committed()


if __name__ == "__main__":
    raise SystemExit(main())
