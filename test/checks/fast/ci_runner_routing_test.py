"""[fast] CI never routes macOS work away from the dedicated translator Mac."""

import os
import re
import unittest

from _fastcase import FastCase, REPO


DEDICATED_LABEL = "translator-macbook"
RUNS_ON = re.compile(r"^(?P<indent>\s*)runs-on\s*:\s*(?P<value>.*)$")
HOSTED_HEAVY_WORKFLOWS = (
    "image.yml",
    "oracle-postgres.yml",
    "oracle-reference.yml",
    "publish-wrapper.yml",
    "release-gate.yml",
    "release.yml",
    "static-analysis.yml",
    "token-compliance.yml",
)


def _indented_value(lines, index, indent, value):
    """Return one scalar/flow value or the following indented YAML block."""
    if value.strip():
        return value.strip()
    block = []
    for line in lines[index + 1:]:
        if not line.strip():
            continue
        child_indent = len(line) - len(line.lstrip())
        if child_indent <= indent:
            break
        block.append(line.strip())
    return " ".join(block)


def _selector_error(selector, origin):
    lower = selector.lower()
    if re.search(r"\bmacos-[a-z0-9_-]+", lower):
        return f"{origin}: GitHub-hosted macOS selector is forbidden: {selector}"
    if re.search(r"\bmacos\b", lower) and DEDICATED_LABEL not in lower:
        return f"{origin}: macOS selector is missing {DEDICATED_LABEL}: {selector}"
    return None


def routing_errors(text):
    """Check every direct selector and every field feeding `matrix.<field>`."""
    lines = text.splitlines()
    selectors = []
    matrix_fields = []

    for index, line in enumerate(lines):
        match = RUNS_ON.match(line)
        if not match:
            continue
        indent = len(match.group("indent"))
        selector = _indented_value(lines, index, indent, match.group("value"))
        selectors.append((index + 1, selector))
        matrix_fields.extend(re.findall(r"matrix\.([A-Za-z_][\w-]*)", selector))

    errors = []
    for line_no, selector in selectors:
        error = _selector_error(selector, f"runs-on line {line_no}")
        if error:
            errors.append(error)

    # `runs-on: ${{ matrix.os }}` is only safe if every candidate assigned to
    # `os` is safe. Inspect both flow lists and include-map scalar/list values.
    for field in sorted(set(matrix_fields)):
        field_pattern = re.compile(
            rf"^(?P<indent>\s*)(?:-\s*)?{re.escape(field)}\s*:\s*(?P<value>.*)$"
        )
        found = 0
        for index, line in enumerate(lines):
            match = field_pattern.match(line)
            if not match or "matrix." in match.group("value"):
                continue
            found += 1
            indent = len(match.group("indent"))
            candidate = _indented_value(lines, index, indent, match.group("value"))
            error = _selector_error(
                candidate, f"matrix.{field} candidate line {index + 1}"
            )
            if error:
                errors.append(error)
        if not found:
            errors.append(f"runs-on matrix.{field} has no statically auditable candidates")
    return errors


# ZERO-SUBJECTS, KEPT DELIBERATELY ( review): the self-hosted macOS lane
# was deleted in the release/m6 CI retarget, so no current workflow contains a
# macOS selector. This policy is FORBIDDEN-class, not retired-class — its value
# is the future case: a macOS job added on a public GitHub-hosted runner would
# be the exact mistake that becomes attractive once nobody remembers why the
# lane went. Do not retire it for having no subjects; that is its success mode.
class CiRunnerRouting(FastCase):
    def test_workflows_pin_every_macos_selector_to_the_dedicated_machine(self):
        workflow_dir = os.path.join(REPO, ".github", "workflows")
        paths = sorted(
            os.path.join(workflow_dir, name)
            for name in os.listdir(workflow_dir)
            if name.endswith((".yml", ".yaml"))
        )
        self.require_floor("GitHub workflow files", len(paths), 10)
        failures = []
        for path in paths:
            with open(path, encoding="utf-8") as f:
                failures.extend(
                    f"{os.path.relpath(path, REPO)}: {error}"
                    for error in routing_errors(f.read())
                )
        self.assertEqual([], failures, "\n".join(failures))

    def test_second_unpinned_job_fails_even_beside_a_pinned_job(self):
        workflow = """jobs:
  pinned:
    runs-on: [self-hosted, macOS, X64, translator-macbook]
  escaped:
    runs-on: [self-hosted, macOS, X64]
"""
        self.assertEqual(1, len(routing_errors(workflow)))

    def test_github_hosted_macos_fails_closed(self):
        self.assertTrue(routing_errors("jobs:\n  test:\n    runs-on: macos-15\n"))

    def test_matrix_supplied_github_macos_fails_closed(self):
        workflow = """jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-22.04, macos-15]
"""
        self.assertTrue(routing_errors(workflow))

    def test_safe_matrix_is_accepted(self):
        workflow = """jobs:
  test:
    runs-on: ${{ matrix.runner }}
    strategy:
      matrix:
        include:
          - runner: ubuntu-22.04
          - runner: [self-hosted, macOS, X64, translator-macbook]
"""
        self.assertFalse(routing_errors(workflow))

    def test_dedicated_machine_is_accepted(self):
        self.assertFalse(
            routing_errors(
                "runs-on: [self-hosted, macOS, X64, translator-macbook]\n"
            )
        )


if __name__ == "__main__":
    unittest.main()
