#!/usr/bin/env python3
"""Run the configured IR lit suite and account for every discovered identity.

Stage A of  is intentionally UNARMED: it establishes immediate
dead-harness protection without banking a discovered/skip/outcome floor from
the damaged terminal integration head.  The wrapper preserves lit's stdout,
stderr, and exact exit status.  Its own failures are reserved for an otherwise
successful lit process whose reports prove the harness/accounting contract was
violated.

Stage B () adds the machinery that accepts an ARMED baseline banked at a
clean post-repair integration head.  The committed baseline stays UNARMED until
someone arms it deliberately; this module only defines and enforces the
contract an ARMED baseline must satisfy.

Stage-B baseline schema (``state == "ARMED"`` requires ``stage == "B"`` and
exactly these keys -- unknown or absent keys fail closed):

  kind                       "neutrino.lit-suite-accounting-baseline.v1"
  schemaVersion              1
  stage                      "B"
  state                      "ARMED"
  sourceCommit               40-character lowercase hex git commit the
                             baseline was banked at; verified against the
                             working tree HEAD in terminal mode.
  discoveredIdentities       non-empty, duplicate-free list of the exact lit
                             identities discovered at that commit.
  discoveredCount            integer that must equal len(discoveredIdentities).
  identitySetSha256          "sha256:" + digest of the sorted identity set, so
                             the banked set is self-checking rather than
                             trusted.
  allowedUnsupportedSkipped  {identity: reason} for every skip the armed head
                             is permitted to produce.  Keys must be a subset of
                             discoveredIdentities; every reason must be a
                             non-empty string.  May be empty (= no skip is
                             permitted at all), but the key itself is required.
  allowedUnresolved          {identity: reason}, same rules, for the unresolved
                             category.

Stage-B ratchet rules, all compared PER IDENTITY against the banked set and
never by count, so growth can never offset shrinkage:

  1. baseline-shrinkage           a banked identity is absent from the run
  2. baseline-skip-growth         a run skip is not in allowedUnsupportedSkipped
  3. baseline-unresolved-growth   a run unresolved is not in allowedUnresolved
  4. baseline-partition           a banked identity is not accounted exactly
                                  once by the run's category partition

Additions are permitted: a newly discovered identity is not a failure.  But
because rule 1 is per-identity, deleting a banked test and adding a new one
fails as a deletion -- consuming that growth requires a reviewed baseline
update.
"""

import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


REPO = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = REPO / "docs" / "m6-lit-suite-accounting-baseline.json"

REPORT_KIND = "neutrino.lit-suite-accounting.v1"
BASELINE_KIND = "neutrino.lit-suite-accounting-baseline.v1"
CATEGORIES = (
    "passed",
    "failed",
    "xfail",
    "xpass",
    "timeout",
    "unresolved",
    "unsupported/skipped",
)
CODE_CATEGORY = {
    "PASS": "passed",
    "FLAKYPASS": "passed",
    "FAIL": "failed",
    "XFAIL": "xfail",
    "XPASS": "xpass",
    "TIMEOUT": "timeout",
    "UNRESOLVED": "unresolved",
    "UNSUPPORTED": "unsupported/skipped",
    "SKIPPED": "unsupported/skipped",
    "EXCLUDED": "unsupported/skipped",
}
FAILURE_CATEGORIES = {"failed", "xpass", "timeout", "unresolved"}
EXECUTED_CATEGORIES = {"passed", "failed", "xfail", "xpass", "timeout"}

STAGE_A_KEYS = frozenset({"kind", "schemaVersion", "state", "stage"})
STAGE_B_REASON_FIELDS = ("allowedUnsupportedSkipped", "allowedUnresolved")
STAGE_B_KEYS = frozenset(STAGE_A_KEYS | {
    "sourceCommit",
    "discoveredCount",
    "discoveredIdentities",
    "identitySetSha256",
} | set(STAGE_B_REASON_FIELDS))

COMMIT_RE = re.compile(r"\A[0-9a-f]{40}\Z")
DIGEST_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")

# The single state table.  Stage B widened the state whitelist by one token and
# Stage C will widen it again, so "add a state, forget its validator" is the easy
# mistake — previously possible because three decisions keyed off the state
# independently (key set and stage by `!= "UNARMED"`, validation by
# `== "ARMED"`, the ratchet by `!= "ARMED"`). A new token inherited the Stage-B
# SHAPE while inheriting neither its VALIDATION nor the ratchet. Declaring all
# four facts in one place makes that combination unexpressible: adding a state
# forces a stage, a key set, a validator and a ratchet decision together.
STATES = {
    # state: (stage, key set, validator or None, participates in the ratchet)
    "UNARMED": ("A", STAGE_A_KEYS, None, False),
    "ARMED": ("B", STAGE_B_KEYS, "_validate_stage_b", True),
}


class AccountingError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

    def diagnostic(self):
        return f"[lit-accounting.{self.code}] {self.message}"


def _load_json(path, diagnostic="report-malformed"):
    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError) as exc:
        raise AccountingError(diagnostic,
                              f"{path}: cannot load JSON: {exc}")


def identity_digest(identities):
    """The self-checking digest of a sorted, newline-terminated identity set."""
    payload = "".join(identity + "\n" for identity in sorted(identities))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reason_map(data, field, discovered):
    value = data.get(field)
    if not isinstance(value, dict):
        raise AccountingError("baseline-malformed",
                              f"baseline {field} must be an object mapping "
                              f"identity to reason")
    for identity, reason in sorted(value.items()):
        if not isinstance(identity, str) or not identity.strip():
            raise AccountingError(
                "baseline-malformed",
                f"baseline {field} has a non-string or empty identity")
        if not isinstance(reason, str) or not reason.strip():
            raise AccountingError(
                "baseline-malformed",
                f"baseline {field} entry {identity!r} has no non-empty reason")
        if identity not in discovered:
            raise AccountingError(
                "baseline-inconsistent",
                f"baseline {field} entry {identity!r} is not a member of "
                f"discoveredIdentities")
    return value


def _validate_stage_b(data):
    """Validate every Stage-B field; nothing is merely accepted."""
    commit = data.get("sourceCommit")
    if not isinstance(commit, str) or not COMMIT_RE.match(commit):
        raise AccountingError(
            "baseline-malformed",
            "baseline sourceCommit must be a 40-character lowercase hex "
            "git commit")

    identities = data.get("discoveredIdentities")
    if not isinstance(identities, list) or not identities:
        raise AccountingError(
            "baseline-malformed",
            "baseline discoveredIdentities must be a non-empty list")
    for entry in identities:
        if not isinstance(entry, str) or not entry.strip():
            raise AccountingError(
                "baseline-malformed",
                "baseline discoveredIdentities has a non-string or empty entry")
    duplicates = sorted(
        identity for identity, count in collections.Counter(identities).items()
        if count != 1)
    if duplicates:
        raise AccountingError(
            "baseline-malformed",
            f"baseline discoveredIdentities has duplicates: {duplicates}")
    discovered = set(identities)

    count = data.get("discoveredCount")
    if not isinstance(count, int) or isinstance(count, bool):
        raise AccountingError("baseline-malformed",
                              "baseline discoveredCount must be an integer")
    if count != len(identities):
        raise AccountingError(
            "baseline-inconsistent",
            f"baseline discoveredCount {count} does not equal the "
            f"{len(identities)} declared discoveredIdentities")

    digest = data.get("identitySetSha256")
    if not isinstance(digest, str) or not DIGEST_RE.match(digest):
        raise AccountingError(
            "baseline-malformed",
            "baseline identitySetSha256 must be 'sha256:' + 64 lowercase hex")
    recomputed = identity_digest(discovered)
    if digest != recomputed:
        raise AccountingError(
            "baseline-inconsistent",
            f"baseline identitySetSha256 {digest} does not match the "
            f"recomputed {recomputed} of discoveredIdentities")

    for field in STAGE_B_REASON_FIELDS:
        _reason_map(data, field, discovered)
    return data


def load_baseline(path):
    data = _load_json(path, "baseline-malformed")
    if not isinstance(data, dict):
        raise AccountingError("baseline-malformed",
                              "baseline root must be an object")
    state = data.get("state")
    # The state whitelist IS the table: an unknown token is rejected here, by
    # this check, before any shape/stage/validation decision is reached — so a
    # widening cannot silently inherit another state's shape.
    if state not in STATES:
        raise AccountingError(
            "baseline-state-unknown",
            f"baseline state {state!r} is not a declared state "
            f"({sorted(STATES)}); declare it in STATES with its stage, key "
            "set, validator and ratchet participation")
    expected_stage, expected, validator_name, _ratcheted = STATES[state]
    if set(data) != expected:
        missing = sorted(expected - set(data))
        unknown = sorted(set(data) - expected)
        raise AccountingError(
            "baseline-malformed",
            f"{state} baseline keys must be exactly {sorted(expected)} "
            f"(missing: {missing}, unknown: {unknown})")
    if data.get("kind") != BASELINE_KIND or data.get("schemaVersion") != 1:
        raise AccountingError("baseline-malformed",
                              "baseline kind/schemaVersion is unsupported")
    if data.get("stage") != expected_stage:
        raise AccountingError(
            "baseline-malformed",
            f"a {state} baseline requires stage {expected_stage!r}, not "
            f"{data.get('stage')!r}")
    # Validation is dispatched from the same table row as the shape, so a state
    # can never carry a key set without the validator that key set implies.
    if validator_name is not None:
        globals()[validator_name](data)
    return data


def is_ratcheted(baseline):
    """Whether this baseline's state participates in the Stage-B ratchet.

    Keyed off the state table rather than a bare `!= "ARMED"` literal, so a new
    state cannot opt out of the ratchet by accident.
    """
    state = baseline.get("state")
    if state not in STATES:
        return False
    return STATES[state][3]


def resolve_source_commit(explicit):
    """The commit the run is actually happening at, for provenance checks."""
    if explicit:
        if not COMMIT_RE.match(explicit):
            raise AccountingError(
                "baseline-provenance",
                f"--source-commit {explicit!r} is not a 40-character "
                f"lowercase hex commit")
        return explicit
    try:
        probe = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
                               capture_output=True, text=True)
    except OSError as exc:
        raise AccountingError("baseline-provenance",
                              f"cannot resolve the source commit: {exc}")
    resolved = probe.stdout.strip() if probe.stdout else ""
    if probe.returncode != 0 or not COMMIT_RE.match(resolved):
        raise AccountingError(
            "baseline-provenance",
            "cannot resolve the working-tree HEAD commit required to verify "
            "the ARMED baseline provenance")
    return resolved


def verify_clean_tree():
    """Terminal mode requires an undirtied tree at the armed commit.

    A commit match alone does not establish reproducibility: the tree can sit at
    the armed SHA with uncommitted edits, and 's single authorised run feeds
    a milestone-closure verdict whose whole claim is "this evidence is
    reproducible from this SHA". Without this, that claim is unfalsifiable.
    Terminal-only by design — the ordinary registered ctest must keep working on
    a developer's dirty tree.
    """
    try:
        probe = subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain"],
            capture_output=True, text=True)
    except OSError as exc:
        raise AccountingError("baseline-provenance",
                              f"cannot determine working-tree cleanliness: {exc}")
    if probe.returncode != 0:
        raise AccountingError(
            "baseline-provenance",
            "cannot determine working-tree cleanliness required by terminal mode")
    dirty = [line for line in (probe.stdout or "").splitlines() if line.strip()]
    if dirty:
        raise AccountingError(
            "baseline-dirty-tree",
            "terminal mode requires a clean working tree so the evidence is "
            f"reproducible from the armed commit; {len(dirty)} path(s) differ, "
            f"first: {dirty[0].strip()!r}")


def _git(*args, code="baseline-provenance", why="resolve git state"):
    try:
        probe = subprocess.run(["git", "-C", str(REPO), *args],
                               capture_output=True, text=True)
    except OSError as exc:
        raise AccountingError(code, f"cannot {why}: {exc}")
    if probe.returncode != 0:
        raise AccountingError(code, f"cannot {why}")
    return (probe.stdout or "").strip()


def verify_provenance(baseline, source_commit, terminal=False):
    """Bind the ARMED baseline to the commit its report was produced at.

    A baseline cannot contain the hash of the commit that ships it — that is a
    fixed point.  So `sourceCommit` names the CLEAN PARENT: the head the real
    accounting run measured.  The arming change is then required to be exactly
    one commit on top of it, carrying nothing but the arming delta.

    In terminal mode `--source-commit` is NOT authoritative.  Honouring it here
    would reduce provenance to a caller-supplied assertion — precisely the
    bypass this contract exists to close — so the expected value is derived from
    `HEAD^` and a passed flag cannot override it.  The flag remains available
    for non-terminal diagnostics.
    """
    if not terminal:
        actual = resolve_source_commit(source_commit)
        if actual != baseline["sourceCommit"]:
            raise AccountingError(
                "baseline-provenance",
                f"ARMED baseline was banked at {baseline['sourceCommit']} but "
                f"this run is at {actual}")
        return actual

    head = _git("rev-parse", "HEAD", why="resolve HEAD")
    parent = _git("rev-parse", "HEAD^", why="resolve HEAD^ (the arming parent)")
    if not COMMIT_RE.match(head) or not COMMIT_RE.match(parent):
        raise AccountingError("baseline-provenance",
                              "cannot resolve HEAD/HEAD^ as 40-hex commits")
    if parent != baseline["sourceCommit"]:
        raise AccountingError(
            "baseline-provenance",
            f"terminal mode requires the arming commit to sit directly atop the "
            f"commit its report was produced at: baseline sourceCommit is "
            f"{baseline['sourceCommit']}, but HEAD^ is {parent}. If main "
            "advanced, rebase, rerun the accounting wrapper and re-bank.")
    verify_arming_delta(parent, head)
    return parent


# The arming commit may carry ONLY these paths.  Without this allowlist the
# parent-anchor would be decorative: arbitrary production changes could ride
# along inside the arming commit and still satisfy "HEAD^ == sourceCommit".
ARMING_DELTA_ALLOWLIST = (
    "docs/m6-lit-suite-accounting-baseline.json",   # the baseline being armed
    "Makefile",                                     # the --terminal entrypoint
    "scripts/gates/run_lit_suite_accounting.py",    # provenance contract itself
    "test/checks/fast/lit_suite_accounting_test.py",  # and their tests
)


def verify_arming_delta(parent, head):
    """The arming commit carries the arming delta and nothing else."""
    changed = [line for line in
               _git("diff", "--name-only", f"{parent}..{head}",
                    why="list the arming delta").splitlines() if line.strip()]
    stray = sorted(set(changed) - set(ARMING_DELTA_ALLOWLIST))
    if stray:
        raise AccountingError(
            "baseline-arming-delta",
            "the arming commit may carry only the baseline, the terminal "
            f"entrypoint and their tests; it also changes: {stray}")
    if "docs/m6-lit-suite-accounting-baseline.json" not in changed:
        raise AccountingError(
            "baseline-arming-delta",
            "the arming commit does not change the baseline it claims to arm")
    return changed


def compare_to_baseline(report, baseline):
    """Enforce the four Stage-B ratchet rules against a run report.

    Every comparison is per identity against the banked set.  Nothing is
    compared by count, so a deletion can never be offset by an addition.
    """
    if not is_ratcheted(baseline):
        return
    declared = set(baseline["discoveredIdentities"])
    categories = report.get("categories")
    if not isinstance(categories, dict) or set(categories) != set(CATEGORIES):
        raise AccountingError(
            "report-malformed",
            "report categories are absent or do not match the accounting "
            "vocabulary")
    discovered = report.get("discoveredIdentities")
    if not isinstance(discovered, list):
        raise AccountingError("report-malformed",
                              "report discoveredIdentities must be a list")
    discovered = set(discovered)
    partition = collections.Counter(
        identity for name in CATEGORIES for identity in categories[name])

    # Rule 1 -- discovered-set shrinkage.  Per identity: a deletion paired with
    # an addition still bites here, because the deleted identity is named.
    shrunk = sorted(declared - discovered)
    if shrunk:
        raise AccountingError(
            "baseline-shrinkage",
            f"identities banked by the ARMED baseline are absent from this "
            f"run: {shrunk}")

    # Rule 4 -- every result identity is accounted by the partition, and the
    # partition still totals the run's discovered set.
    unaccounted = sorted(identity for identity in declared
                         if partition.get(identity, 0) != 1)
    if unaccounted:
        raise AccountingError(
            "baseline-partition",
            f"baseline identities are not accounted exactly once by the run's "
            f"category partition: {unaccounted}")
    if set(partition) != discovered or any(
            count != 1 for count in partition.values()):
        raise AccountingError(
            "baseline-partition",
            "the run's category partition is not a total, disjoint cover of "
            "its discovered identities")

    # Rule 2 -- unexplained skip growth.
    unexplained = sorted(set(categories["unsupported/skipped"])
                         - set(baseline["allowedUnsupportedSkipped"]))
    if unexplained:
        raise AccountingError(
            "baseline-skip-growth",
            f"unsupported/skipped identities are not permitted by the ARMED "
            f"baseline: {unexplained}")

    # Rule 3 -- new unresolved tests.
    unresolved = sorted(set(categories["unresolved"])
                        - set(baseline["allowedUnresolved"]))
    if unresolved:
        raise AccountingError(
            "baseline-unresolved-growth",
            f"unresolved identities are not permitted by the ARMED baseline: "
            f"{unresolved}")


def _xunit_identity(suite_name, testcase):
    name = testcase.get("name")
    class_name = testcase.get("classname")
    if not isinstance(name, str) or not name:
        raise AccountingError("report-malformed",
                              "xUnit testcase has no non-empty name")
    if not isinstance(class_name, str) or not class_name:
        raise AccountingError("report-malformed",
                              f"xUnit testcase {name!r} has no classname")
    prefix = suite_name + "."
    if class_name in {suite_name, suite_name + "." + suite_name}:
        path = name
    elif class_name.startswith(prefix):
        path = class_name[len(prefix):].replace(".", "/") + "/" + name
    else:
        raise AccountingError(
            "report-malformed",
            f"xUnit testcase {name!r} classname {class_name!r} is outside "
            f"suite {suite_name!r}")
    return f"{suite_name} :: {path}"


def _parse_xunit(path):
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise AccountingError("report-malformed",
                              f"{path}: cannot load xUnit XML: {exc}")
    if root.tag != "testsuites":
        raise AccountingError("report-malformed",
                              "xUnit root must be <testsuites>")
    identities = []
    skipped = set()
    failed = set()
    for suite in root.findall("testsuite"):
        suite_name = suite.get("name")
        if not isinstance(suite_name, str) or not suite_name:
            raise AccountingError("report-malformed",
                                  "xUnit testsuite has no name")
        tests = suite.findall("testcase")
        try:
            declared = int(suite.get("tests", ""))
            declared_failed = int(suite.get("failures", ""))
            declared_skipped = int(suite.get("skipped", ""))
        except ValueError:
            raise AccountingError("report-malformed",
                                  f"xUnit suite {suite_name!r} has an invalid count")
        if declared != len(tests):
            raise AccountingError(
                "report-incomplete",
                f"xUnit suite {suite_name!r} declares {declared} tests but "
                f"contains {len(tests)} testcases")
        suite_failed = 0
        suite_skipped = 0
        for testcase in tests:
            identity = _xunit_identity(suite_name, testcase)
            identities.append(identity)
            if testcase.find("skipped") is not None:
                skipped.add(identity)
                suite_skipped += 1
            if testcase.find("failure") is not None:
                failed.add(identity)
                suite_failed += 1
        if declared_failed != suite_failed or declared_skipped != suite_skipped:
            raise AccountingError(
                "report-incomplete",
                f"xUnit suite {suite_name!r} declares failures/skipped "
                f"{declared_failed}/{declared_skipped} but contains "
                f"{suite_failed}/{suite_skipped}")
    duplicates = sorted(
        identity for identity, count in collections.Counter(identities).items()
        if count != 1)
    if duplicates:
        raise AccountingError("identity-duplicate",
                              f"duplicate xUnit identities: {duplicates}")
    return set(identities), skipped, failed


def _parse_lit_json(path):
    data = _load_json(path)
    if (not isinstance(data, dict)
            or not isinstance(data.get("__version__"), list)
            or not isinstance(data.get("tests"), list)):
        raise AccountingError("report-malformed",
                              "lit JSON requires __version__ and tests")
    rows = data["tests"]
    names = []
    codes = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise AccountingError("report-malformed",
                                  f"lit JSON tests[{index}] is not an object")
        name = row.get("name")
        code = row.get("code")
        if not isinstance(name, str) or not name:
            raise AccountingError("report-malformed",
                                  f"lit JSON tests[{index}] has no identity")
        if code not in CODE_CATEGORY:
            raise AccountingError("report-malformed",
                                  f"{name}: unsupported lit result code {code!r}")
        names.append(name)
        codes[name] = code
    duplicates = sorted(
        identity for identity, count in collections.Counter(names).items()
        if count != 1)
    if duplicates:
        raise AccountingError("identity-duplicate",
                              f"duplicate lit JSON identities: {duplicates}")
    return codes


def build_report(json_path, xunit_path, lit_status, baseline):
    discovered, xunit_skipped, xunit_failed = _parse_xunit(xunit_path)
    codes = _parse_lit_json(json_path)

    extra = sorted(set(codes) - discovered)
    if extra:
        raise AccountingError(
            "report-incomplete",
            f"lit JSON identities absent from discovery report: {extra}")
    missing = sorted(discovered - set(codes))
    unaccounted = sorted(set(missing) - xunit_skipped)
    if unaccounted:
        raise AccountingError(
            "report-incomplete",
            f"discovered identities have no lit result or skipped marker: "
            f"{unaccounted}")
    json_skipped = {
        identity for identity, code in codes.items()
        if CODE_CATEGORY[code] == "unsupported/skipped"
    }
    expected_xunit_skipped = json_skipped | set(missing)
    if xunit_skipped != expected_xunit_skipped:
        raise AccountingError(
            "skip-mismatch",
            "xUnit skipped identities do not match lit JSON skip outcomes "
            "plus JSON-omitted skipped identities")

    categories = {name: [] for name in CATEGORIES}
    for identity, code in codes.items():
        categories[CODE_CATEGORY[code]].append(identity)
    categories["unsupported/skipped"].extend(missing)
    for values in categories.values():
        values.sort()

    partition = [identity for name in CATEGORIES
                 for identity in categories[name]]
    duplicates = sorted(
        identity for identity, count in collections.Counter(partition).items()
        if count != 1)
    if duplicates:
        raise AccountingError("identity-duplicate",
                              f"duplicate accounting identities: {duplicates}")
    if set(partition) != discovered:
        raise AccountingError(
            "report-incomplete",
            "result categories do not form a total discovered-identity partition")
    if not discovered:
        raise AccountingError("zero-discovered",
                              "configured lit suite discovered zero tests")

    expected_xunit_failed = {
        identity for identity, code in codes.items()
        if CODE_CATEGORY[code] in FAILURE_CATEGORIES
    }
    if xunit_failed != expected_xunit_failed:
        raise AccountingError(
            "status-mismatch",
            "xUnit failure identities do not match lit JSON failure categories")

    attempted = sum(len(categories[name]) for name in CATEGORIES
                    if name != "unsupported/skipped")
    executed = sum(len(categories[name]) for name in EXECUTED_CATEGORIES)
    if attempted == 0:
        raise AccountingError("zero-attempted",
                              "configured lit suite attempted zero tests")
    if executed == 0:
        raise AccountingError("zero-executed",
                              "configured lit suite executed zero tests")

    has_failure = any(categories[name] for name in FAILURE_CATEGORIES)
    expected_status = 1 if has_failure else 0
    if lit_status != expected_status:
        code = "status-suppressed" if lit_status == 0 and has_failure else "status-mismatch"
        raise AccountingError(
            code,
            f"lit exit status {lit_status} does not match accounted result "
            f"status {expected_status}")

    discovered_sorted = sorted(discovered)
    counts = {name: len(categories[name]) for name in CATEGORIES}
    counts.update({
        "discovered": len(discovered_sorted),
        "attempted": attempted,
        "executed": executed,
    })
    return {
        "kind": REPORT_KIND,
        "schemaVersion": 1,
        "baselineState": baseline["state"],
        "litExitStatus": lit_status,
        "identitySetSha256": identity_digest(discovered_sorted),
        "discoveredIdentities": discovered_sorted,
        "categories": categories,
        "counts": counts,
    }


def _write_report(path, report):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(str(temporary), str(target))


def run(lit, suite, output, baseline_path, terminal, source_commit=None):
    try:
        baseline = load_baseline(baseline_path)
    except AccountingError as exc:
        print(exc.diagnostic(), file=sys.stderr)
        return 2
    if terminal and baseline["state"] != "ARMED":
        print("[lit-accounting.unarmed-terminal] terminal mode refuses the "
              "committed UNARMED Stage-A baseline", file=sys.stderr)
        return 2
    if terminal:
        try:
            verify_clean_tree()
            verify_provenance(baseline, source_commit, terminal=True)
        except AccountingError as exc:
            print(exc.diagnostic(), file=sys.stderr)
            return 2

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.unlink()
    except FileNotFoundError:
        pass
    temp_dir = tempfile.mkdtemp(prefix="lit-suite-accounting.",
                                dir=str(output_path.parent))
    json_path = Path(temp_dir) / "lit-results.json"
    xunit_path = Path(temp_dir) / "lit-results.xml"
    command = [
        lit,
        "-sv",
        "-o", str(json_path),
        "--xunit-xml-output", str(xunit_path),
        suite,
    ]
    try:
        result = subprocess.run(command)
    except OSError as exc:
        print(f"[lit-accounting.invocation] cannot execute lit: {exc}",
              file=sys.stderr)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return 2

    try:
        if not json_path.is_file() or not xunit_path.is_file():
            missing = [
                name for name, path in
                (("JSON", json_path), ("xUnit", xunit_path))
                if not path.is_file()
            ]
            raise AccountingError(
                "report-absent",
                f"lit did not produce required report(s): {', '.join(missing)}")
        report = build_report(json_path, xunit_path, result.returncode, baseline)
        # Write the report before ratcheting so a ratchet failure still leaves
        # the evidence a reviewed baseline update would be based on.
        _write_report(output_path, report)
        compare_to_baseline(report, baseline)
    except AccountingError as exc:
        print(exc.diagnostic(), file=sys.stderr)
        return result.returncode if result.returncode != 0 else 2
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="run and totally account for the configured test/ir lit suite")
    parser.add_argument("--lit", required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--terminal", action="store_true")
    parser.add_argument(
        "--source-commit",
        help="commit this run is happening at; defaults to the working-tree "
             "HEAD.  Terminal mode requires it to equal the ARMED baseline's "
             "sourceCommit.")
    args = parser.parse_args()
    return run(args.lit, args.suite, args.report, args.baseline, args.terminal,
               args.source_commit)


if __name__ == "__main__":
    raise SystemExit(main())
