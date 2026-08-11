#!/usr/bin/env python3
"""Resolve the immutable comparison base recorded by a GitHub Actions event."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


_SHA1 = re.compile(r"[0-9a-fA-F]{40}")
_ZERO_SHA = "0" * 40


class BaseResolutionError(ValueError):
    pass


def _require_sha(value: object, source: str) -> str:
    if not isinstance(value, str) or not _SHA1.fullmatch(value):
        raise BaseResolutionError(f"{source} must be an explicit 40-hex commit SHA")
    sha = value.lower()
    if sha == _ZERO_SHA:
        raise BaseResolutionError(f"{source} is the zero SHA, not an immutable commit base")
    return sha


def resolve_base(event_name: str, event: dict[str, object]) -> str:
    if event_name == "push":
        return _require_sha(event.get("before"), "github.event.before")
    if event_name == "pull_request":
        pull_request = event.get("pull_request")
        if not isinstance(pull_request, dict):
            raise BaseResolutionError("pull_request event has no pull_request object")
        base = pull_request.get("base")
        if not isinstance(base, dict):
            raise BaseResolutionError("pull_request event has no base object")
        return _require_sha(base.get("sha"), "github.event.pull_request.base.sha")
    if event_name == "workflow_dispatch":
        inputs = event.get("inputs")
        if not isinstance(inputs, dict):
            raise BaseResolutionError(
                "workflow_dispatch requires the ratchet_base_sha input"
            )
        return _require_sha(
            inputs.get("ratchet_base_sha"),
            "github.event.inputs.ratchet_base_sha",
        )
    raise BaseResolutionError(f"unsupported GitHub event {event_name!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--event-path", type=Path, required=True)
    parser.add_argument("--github-env", type=Path)
    args = parser.parse_args()

    try:
        event = json.loads(args.event_path.read_text(encoding="utf-8"))
        if not isinstance(event, dict):
            raise BaseResolutionError("GitHub event payload must be a JSON object")
        base = resolve_base(args.event_name, event)
    except (OSError, json.JSONDecodeError, BaseResolutionError) as error:
        parser.error(str(error))

    print(base)
    if args.github_env:
        with args.github_env.open("a", encoding="utf-8") as stream:
            stream.write(f"PR_BASE_SHA={base}\n")
            stream.write(f"GATE_INTEGRITY_BASE_REF={base}\n")
            stream.write(f"GENERALISM_BASE_REF={base}\n")
            stream.write(f"NEUTRINO_BUNDLE_BASE={base}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
