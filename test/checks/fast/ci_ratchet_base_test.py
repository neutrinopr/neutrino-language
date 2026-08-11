import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
RESOLVER_PATH = REPO / "scripts/gates/resolve_ci_ratchet_base.py"
WORKFLOW_PATH = REPO / ".github/workflows/build-and-test.yml"

def load_resolver(path):
    spec = importlib.util.spec_from_file_location("resolve_ci_ratchet_base", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


resolver = load_resolver(RESOLVER_PATH)


def governed_count(repo, revision):
    contents = subprocess.check_output(
        ["git", "show", f"{revision}:governed-sites"],
        cwd=repo,
        text=True,
    )
    return len([line for line in contents.splitlines() if line])


def monotonic_ratchet_passes(repo, current_revision, base_revision):
    return governed_count(repo, current_revision) <= governed_count(
        repo, base_revision
    )


def workflow_errors(workflow):
    errors = []
    if "ratchet_base_sha:" not in workflow or "required: true" not in workflow:
        errors.append("manual dispatch base is not required")
    if workflow.count("python3 scripts/gates/resolve_ci_ratchet_base.py") != 1:
        errors.append("resolver is not invoked exactly once in the fast job")
    if (
        workflow.count('git fetch --no-tags --depth=1 origin "$PR_BASE_SHA"')
        != 1
    ):
        errors.append("immutable base is not fetched exactly once in the fast job")
    if (
        'check_gate_integrity.py --no-exec --base-ref '
        '"${GATE_INTEGRITY_BASE_REF:-origin/main}"'
        not in workflow
    ):
        errors.append("gate-integrity does not consume the exported base")
    return errors


class CiRatchetBaseTest(unittest.TestCase):
    SHA_A = "1" * 40
    SHA_B = "2" * 40
    SHA_C = "3" * 40

    def test_event_kinds_select_only_their_immutable_base(self):
        self.assertEqual(
            resolver.resolve_base("push", {"before": self.SHA_A, "after": self.SHA_B}),
            self.SHA_A,
        )
        self.assertEqual(
            resolver.resolve_base(
                "pull_request",
                {"pull_request": {"base": {"sha": self.SHA_B}}},
            ),
            self.SHA_B,
        )
        self.assertEqual(
            resolver.resolve_base(
                "workflow_dispatch",
                {"inputs": {"ratchet_base_sha": self.SHA_C}},
            ),
            self.SHA_C,
        )

    def test_missing_invalid_and_zero_bases_fail_closed(self):
        bad = (
            ("push", {}),
            ("push", {"before": "0" * 40}),
            ("pull_request", {"pull_request": {}}),
            ("workflow_dispatch", {"inputs": {}}),
            ("schedule", {}),
        )
        for event_name, event in bad:
            with self.subTest(event_name=event_name, event=event):
                with self.assertRaises(resolver.BaseResolutionError):
                    resolver.resolve_base(event_name, event)

    def test_old_push_rerun_is_stable_after_main_advances(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "ci@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "CI Test"], cwd=repo, check=True
            )

            (repo / "governed-sites").write_text("kept\nretired\n", encoding="utf-8")
            subprocess.run(["git", "add", "governed-sites"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
            base = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()

            subprocess.run(
                ["git", "checkout", "-q", "-b", "old-push"],
                cwd=repo,
                check=True,
            )
            (repo / "governed-sites").write_text("kept\n", encoding="utf-8")
            subprocess.run(
                ["git", "commit", "-qam", "old push deletes one site"],
                cwd=repo,
                check=True,
            )
            old_push = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()

            subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
            (repo / "governed-sites").write_text("", encoding="utf-8")
            subprocess.run(
                ["git", "commit", "-qam", "main advances and deletes both sites"],
                cwd=repo,
                check=True,
            )
            advanced_main = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()

            old_event = {"before": base, "after": old_push}
            event_base = resolver.resolve_base("push", old_event)
            self.assertTrue(monotonic_ratchet_passes(repo, old_push, event_base))
            self.assertFalse(monotonic_ratchet_passes(repo, old_push, advanced_main))

    def test_cli_exports_one_base_to_all_ratchet_consumers(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / "event.json"
            github_env = Path(tmp) / "github-env"
            event.write_text(json.dumps({"before": self.SHA_A}), encoding="utf-8")
            result = subprocess.run(
                [
                    "python3",
                    os.fspath(RESOLVER_PATH),
                    "--event-name",
                    "push",
                    "--event-path",
                    os.fspath(event),
                    "--github-env",
                    os.fspath(github_env),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            self.assertEqual(result.stdout.strip(), self.SHA_A)
            self.assertEqual(
                github_env.read_text(encoding="utf-8").splitlines(),
                [
                    f"PR_BASE_SHA={self.SHA_A}",
                    f"GATE_INTEGRITY_BASE_REF={self.SHA_A}",
                    f"GENERALISM_BASE_REF={self.SHA_A}",
                    f"NEUTRINO_BUNDLE_BASE={self.SHA_A}",
                ],
            )

    def test_workflow_requires_manual_base_and_uses_the_resolver_in_the_fast_job(self):
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertEqual(workflow_errors(workflow), [])


def run_probe(probe_id):
    if probe_id == "push-selector-after":
        source = RESOLVER_PATH.read_text(encoding="utf-8")
        mutated = source.replace('event.get("before")', 'event.get("after")', 1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / RESOLVER_PATH.name
            path.write_text(mutated, encoding="utf-8")
            mutated_resolver = load_resolver(path)
            selected = mutated_resolver.resolve_base(
                "push",
                {"before": CiRatchetBaseTest.SHA_A, "after": CiRatchetBaseTest.SHA_B},
            )
        if selected != CiRatchetBaseTest.SHA_A:
            print("probe-failed-as-expected:push-selector-after")
            return 1
    elif probe_id == "exported-base-redirect":
        source = RESOLVER_PATH.read_text(encoding="utf-8")
        original = 'stream.write(f"GENERALISM_BASE_REF={base}\\n")'
        replacement = 'stream.write("GENERALISM_BASE_REF=" + "f" * 40 + "\\n")'
        mutated = source.replace(original, replacement, 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / RESOLVER_PATH.name
            event = root / "event.json"
            github_env = root / "github-env"
            script.write_text(mutated, encoding="utf-8")
            event.write_text(
                json.dumps({"before": CiRatchetBaseTest.SHA_A}),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "python3",
                    os.fspath(script),
                    "--event-name",
                    "push",
                    "--event-path",
                    os.fspath(event),
                    "--github-env",
                    os.fspath(github_env),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            exported = github_env.read_text(encoding="utf-8").splitlines()
        if f"GENERALISM_BASE_REF={CiRatchetBaseTest.SHA_A}" not in exported:
            print("probe-failed-as-expected:exported-base-redirect")
            return 1
    elif probe_id == "second-job-wiring-removal":
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        marker = "python3 scripts/gates/resolve_ci_ratchet_base.py"
        before, separator, after = workflow.rpartition(marker)
        if separator and workflow_errors(before + after):
            print("probe-failed-as-expected:second-job-wiring-removal")
            return 1
    elif probe_id == "second-job-fetch-removal":
        workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        marker = 'git fetch --no-tags --depth=1 origin "$PR_BASE_SHA"'
        before, separator, after = workflow.rpartition(marker)
        if separator and workflow_errors(before + after):
            print("probe-failed-as-expected:second-job-fetch-removal")
            return 1
    else:
        print(f"unknown probe: {probe_id}", file=sys.stderr)
        return 2
    print(f"probe unexpectedly passed: {probe_id}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--probe":
        raise SystemExit(run_probe(sys.argv[2]))
    elif len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        unittest.main(argv=[sys.argv[0]])
    else:
        unittest.main()
