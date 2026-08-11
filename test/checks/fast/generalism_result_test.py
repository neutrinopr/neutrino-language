"""[fast] M6  generalism-result contract: positives validate, negatives fail closed,
and Markdown reporting is generated from the JSON envelope."""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from _fastcase import FastCase, REPO

BUILD_TOOLS_REPORT_REVISION = "2cf85d5b8baf38e259a574357045f7ded12f9395"


def _verify_build_tools_cli(cli):
    if not cli or not os.path.isfile(cli):
        return None
    root = subprocess.run(
        ["git", "-C", os.path.dirname(cli), "rev-parse", "--show-toplevel"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if root.returncode != 0:
        raise AssertionError(f"build-tools verifier is not inside a git checkout: {cli}")
    checkout = root.stdout.strip()
    head = subprocess.run(
        ["git", "-C", checkout, "rev-parse", "HEAD"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if head.returncode != 0:
        raise AssertionError(head.stderr.strip() or head.stdout.strip())
    if head.stdout.strip() != BUILD_TOOLS_REPORT_REVISION:
        raise AssertionError(
            f"build-tools verifier checkout HEAD {head.stdout.strip()} != pinned {BUILD_TOOLS_REPORT_REVISION}"
        )
    dirty = subprocess.run(
        ["git", "-C", checkout, "status", "--porcelain"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if dirty.returncode != 0:
        raise AssertionError(dirty.stderr.strip() or dirty.stdout.strip())
    if dirty.stdout.strip():
        raise AssertionError(f"build-tools verifier checkout is dirty: {checkout}")
    return cli


def _build_tools_report_cli():
    candidates = [
        os.environ.get("NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_CLI"),
        os.path.join(REPO, ".ci/neutrino-build-tools/m4/generalism_verification_report.py"),
    ]
    for candidate in candidates:
        verified = _verify_build_tools_cli(candidate)
        if verified:
            return verified
    raise AssertionError("missing pinned authoritative build-tools generalism_verification_report.py")


class GeneralismResult(FastCase):
    def setUp(self):
        super().setUp()
        old_cli = os.environ.get("NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_CLI")
        old_rev = os.environ.get("NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_REVISION")
        os.environ["NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_CLI"] = _build_tools_report_cli()
        os.environ["NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_REVISION"] = BUILD_TOOLS_REPORT_REVISION

        def restore():
            if old_cli is None:
                os.environ.pop("NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_CLI", None)
            else:
                os.environ["NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_CLI"] = old_cli
            if old_rev is None:
                os.environ.pop("NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_REVISION", None)
            else:
                os.environ["NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_REVISION"] = old_rev
        self.addCleanup(restore)

    def _rebind(self, obj, tag):
        """Re-sign per-run evidence bound to a MUTATED envelope so it stays -valid (the binding
        check now ties the signed evidence to the exact result, ); the PR-fast gate then rejects
        the planted policy issue. Evidence artifacts land in a repo-relative temp dir."""
        import importlib.util
        import shutil
        spec = importlib.util.spec_from_file_location(
            "gmatrix", os.path.join(REPO, "scripts", "generators", "run_generalism_matrix.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        d = os.path.join(REPO, "test", "generalism", "results", "_resulttest_" + tag)
        os.makedirs(d, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        obj = dict(obj)
        obj.pop("evidence", None)
        obj["evidence"] = mod.build_run_evidence(
            os.path.join(d, "rebind"), obj["capability"]["id"], obj["capability"]["version"],
            obj["cases"], obj["summary"]["profileStatus"], mod.result_identity_digest(obj))
        return obj

    def test_positive_results_validate(self):
        positives = self.globr("examples/generalism-results/*.json")
        for p in positives:
            self.val_ok(f"generalism result positive {os.path.basename(p)}",
                        "scripts/validators/validate_generalism_result.py", p)
        self.require_floor("generalism result positives", len(positives), 4)

    def _make_fake_build_tools_repo(self, *, with_cli=True):
        repo = os.path.join(self.tmp, "fake-build-tools")
        return self._make_fake_build_tools_repo_at(repo, with_cli=with_cli)

    def _make_fake_build_tools_repo_at(self, repo, *, with_cli=True):
        os.makedirs(os.path.join(repo, "m4"), exist_ok=True)
        if with_cli:
            with open(os.path.join(repo, "m4", "generalism_verification_report.py"), "w", encoding="utf-8") as f:
                f.write("#!/usr/bin/env python3\n")
        else:
            with open(os.path.join(repo, "README.md"), "w", encoding="utf-8") as f:
                f.write("fake build-tools checkout without verifier CLI\n")
        self.assert_ok("init fake build-tools repo", "git", "init", repo)
        self.assert_ok("add fake build-tools files", "git", "-C", repo, "add", ".")
        self.assert_ok(
            "commit fake build-tools repo",
            "git", "-C", repo,
            "-c", "user.email=test@example.invalid",
            "-c", "user.name=test",
            "commit", "-m", "seed",
        )
        head = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
        return repo, head

    def test_build_tools_setup_verifies_existing_checkout(self):
        repo, head = self._make_fake_build_tools_repo()
        r = self.val_ok(
            "build-tools setup verifies an existing pinned checkout",
            "scripts/gates/setup_build_tools_verifier.py",
            "--dest", repo,
            "--revision", head,
            "--no-fetch",
            "--print-env",
        )
        body = r.stdout.decode("utf-8", "replace")
        self.assertIn(f"NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_REVISION={head}", body)
        self.assertIn("NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_CLI=", body)

    def test_build_tools_setup_fails_wrong_revision(self):
        repo, _head = self._make_fake_build_tools_repo()
        rejected = self.val_reject(
            "build-tools setup rejects wrong revision",
            "scripts/gates/setup_build_tools_verifier.py",
            "--dest", repo,
            "--revision", "0" * 40,
            "--no-fetch",
        )
        self.assertIn("buildtools.revision_mismatch", rejected.stdout.decode("utf-8", "replace"))

    def test_build_tools_setup_fails_malformed_revision_before_checkout(self):
        repo = os.path.join(self.tmp, "missing-build-tools")
        rejected = self.val_reject(
            "build-tools setup rejects malformed revision",
            "scripts/gates/setup_build_tools_verifier.py",
            "--dest", repo,
            "--revision", "main",
        )
        self.assertIn("buildtools.revision", rejected.stdout.decode("utf-8", "replace"))
        self.assertFalse(os.path.exists(repo))

    def test_build_tools_setup_fails_missing_cli(self):
        repo, head = self._make_fake_build_tools_repo(with_cli=False)
        rejected = self.val_reject(
            "build-tools setup rejects missing verifier CLI",
            "scripts/gates/setup_build_tools_verifier.py",
            "--dest", repo,
            "--revision", head,
            "--no-fetch",
        )
        self.assertIn("buildtools.cli_missing", rejected.stdout.decode("utf-8", "replace"))

    def test_build_tools_setup_fails_dirty_checkout(self):
        repo, head = self._make_fake_build_tools_repo()
        Path(repo, "m4", "generalism_verification_report.py").write_text("dirty\n", encoding="utf-8")
        rejected = self.val_reject(
            "build-tools setup rejects modified verifier checkout",
            "scripts/gates/setup_build_tools_verifier.py",
            "--dest", repo,
            "--revision", head,
            "--no-fetch",
        )
        self.assertIn("buildtools.dirty", rejected.stdout.decode("utf-8", "replace"))

    def test_build_tools_setup_fails_untracked_python_checkout(self):
        repo, head = self._make_fake_build_tools_repo()
        Path(repo, "m4", "rogue_untracked.py").write_text("# untracked executable surface\n", encoding="utf-8")
        rejected = self.val_reject(
            "build-tools setup rejects untracked verifier checkout code",
            "scripts/gates/setup_build_tools_verifier.py",
            "--dest", repo,
            "--revision", head,
            "--no-fetch",
        )
        self.assertIn("buildtools.dirty", rejected.stdout.decode("utf-8", "replace"))

    def test_build_tools_setup_shell_env_quotes_space_paths(self):
        repo, head = self._make_fake_build_tools_repo_at(os.path.join(self.tmp, "repo with spaces"), with_cli=True)
        r = self.val_ok(
            "build-tools setup quotes shell env paths",
            "scripts/gates/setup_build_tools_verifier.py",
            "--dest", repo,
            "--revision", head,
            "--no-fetch",
            "--print-shell-env",
        )
        body = r.stdout.decode("utf-8", "replace")
        self.assertIn("repo with spaces", body)
        self.assert_ok(
            "quoted build-tools env is eval-safe",
            "bash", "-c",
            'eval "$1"; test -f "$NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_CLI"',
            "bash", body,
        )

    def test_negatives_fail_closed(self):
        negatives = self.globr("examples/generalism-results/negatives/*.json")
        for p in negatives:
            self.val_reject(f"generalism result negative {os.path.basename(p)}",
                            "scripts/validators/validate_generalism_result.py", p)
        self.require_floor("generalism result negatives", len(negatives), 8)

    def test_markdown_projection_is_json_derived(self):
        out = os.path.join(self.tmp, "report.md")
        self.val_ok(
            "markdown projection generated from JSON",
            "scripts/validators/validate_generalism_result.py",
            "examples/generalism-results/pr_fast_faithful.json",
            "--markdown",
            out,
        )
        with open(out, encoding="utf-8") as f:
            md = f.read()
        self.assertIn("m6-pr-fast-cross-border-logistics-001", md)
        self.assertIn("| happy-path-equivalence | translator-differential | FAITHFUL | success |", md)
        self.assertIn("- none", md)

    def test_pr_fast_gate_emits_retained_reports(self):
        out = os.path.join(self.tmp, "gate")
        self.val_ok(
            "PR-fast gate consumes  envelope and emits retained reports",
            "scripts/gates/check_generalism_pr_fast.py",
            "examples/generalism-results/pr_fast_faithful.json",
            "--report-dir",
            out,
        )
        report = self.load_json(os.path.join(out, "generalism-pr-fast-report.json"))
        self.assertTrue(report["ok"])
        self.assertEqual(report["kind"], "neutrino.generalism-pr-fast-gate")
        self.assertEqual(report["profile"], "PR_FAST")
        self.assertEqual(report["verdict"], "FAITHFUL")
        self.assertEqual(report["adapterCaseCounts"]["translator-differential"], 2)
        with open(os.path.join(out, "generalism-pr-fast-report.md"), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("Generalism PR-fast Gate", md)
        self.assertIn("| translator-differential | 2 |", md)
        self.assertIn("| happy-path-equivalence | translator-differential | FAITHFUL | success |", md)

    def test_pr_fast_gate_rejects_other_profiles(self):
        rejected = self.val_reject(
            "PR-fast gate rejects non-PR_FAST profiles",
            "scripts/gates/check_generalism_pr_fast.py",
            "examples/generalism-results/pr_full_broken.json",
            "--json",
        )
        body = rejected.stdout.decode("utf-8", "replace")
        self.assertIn("generalism.pr_fast.profile", body)

    def test_pr_fast_gate_rejects_biting_semantic_mutation(self):
        obj = self.load_json(os.path.join(REPO, "examples/generalism-results/pr_fast_faithful.json"))
        obj["cases"][0]["verdict"] = "SILENT"
        obj["cases"][0]["cause"] = "semantic_mismatch"
        obj["summary"]["verdict"] = "SILENT"
        obj["summary"]["profileStatus"] = "FAIL"
        obj["summary"]["counts"]["FAITHFUL"] = 0
        obj["summary"]["counts"]["SILENT"] = 1
        obj = self._rebind(obj, "semantic")
        out = self.dump_json(obj, os.path.join(self.tmp, "semantic-mismatch.json"))
        # The mutated envelope is structurally valid, then the PR-fast consumer rejects it
        # as a planted semantic failure.
        self.val_ok("semantic mutation remains a valid  result",
                    "scripts/validators/validate_generalism_result.py", out)
        rejected = self.val_reject("PR-fast gate rejects planted SILENT semantic failure",
                                   "scripts/gates/check_generalism_pr_fast.py", out, "--json")
        body = rejected.stdout.decode("utf-8", "replace")
        self.assertIn("generalism.pr_fast.silent", body)

    def test_pr_fast_gate_rejects_biting_compile_mutation(self):
        obj = self.load_json(os.path.join(REPO, "examples/generalism-results/pr_fast_faithful.json"))
        obj["cases"][0]["verdict"] = "BROKEN"
        obj["cases"][0]["cause"] = "compile_failure"
        obj["summary"]["verdict"] = "BROKEN"
        obj["summary"]["profileStatus"] = "FAIL"
        obj["summary"]["counts"]["FAITHFUL"] = 0
        obj["summary"]["counts"]["BROKEN"] = 1
        obj = self._rebind(obj, "compile")
        out = self.dump_json(obj, os.path.join(self.tmp, "compile-failure.json"))
        self.val_ok("compile mutation remains a valid  result",
                    "scripts/validators/validate_generalism_result.py", out)
        rejected = self.val_reject("PR-fast gate rejects planted BROKEN compile failure",
                                   "scripts/gates/check_generalism_pr_fast.py", out, "--json")
        body = rejected.stdout.decode("utf-8", "replace")
        self.assertIn("generalism.pr_fast.broken", body)

    def test_pr_fast_gate_rejects_non_vacuity_mutation(self):
        obj = self.load_json(os.path.join(REPO, "examples/generalism-results/pr_fast_faithful.json"))
        obj["cases"] = []
        obj["summary"]["requiredCasesRun"] = 0
        obj["summary"]["counts"]["FAITHFUL"] = 0
        obj["summary"]["counts"]["REFUSED"] = 0
        out = self.dump_json(obj, os.path.join(self.tmp, "empty-cases.json"))
        rejected = self.val_reject("PR-fast gate rejects empty required case set",
                                   "scripts/gates/check_generalism_pr_fast.py", out, "--json")
        body = rejected.stdout.decode("utf-8", "replace")
        self.assertIn("generalism.pr_fast.validation", body)

    def test_pr_fast_gate_rejects_required_adapter_without_cases(self):
        obj = self.load_json(os.path.join(REPO, "examples/generalism-results/pr_fast_faithful.json"))
        obj["executionProfile"]["requiredAdapters"].append("translator-differential-shadow")
        obj["adapters"].append({
            "adapterId": "translator-differential-shadow",
            "rail": "translator",
            "kind": "semantic",
            "required": True,
            "status": "RAN",
            "proofScope": "neu-semantic-correctness",
        })
        obj = self._rebind(obj, "adapter")
        out = self.dump_json(obj, os.path.join(self.tmp, "uncovered-required-adapter.json"))
        self.val_ok("uncovered adapter mutation remains a valid  result",
                    "scripts/validators/validate_generalism_result.py", out)
        rejected = self.val_reject("PR-fast gate rejects required adapter with zero required cases",
                                   "scripts/gates/check_generalism_pr_fast.py", out, "--json")
        body = rejected.stdout.decode("utf-8", "replace")
        self.assertIn("generalism.pr_fast.required_adapter_uncovered", body)

    def test_pr_fast_gate_rejects_duplicate_case_floor_inflation(self):
        obj = self.load_json(os.path.join(REPO, "examples/generalism-results/pr_fast_faithful.json"))
        obj["executionProfile"]["requiredCaseFloor"] = 3
        obj["cases"].append(dict(obj["cases"][0]))
        obj["summary"]["requiredCasesRun"] = 3
        obj["summary"]["counts"]["FAITHFUL"] = 2
        obj = self._rebind(obj, "duplicate")
        out = self.dump_json(obj, os.path.join(self.tmp, "duplicate-case-floor-inflation.json"))
        self.val_ok("duplicate case mutation remains a valid  result",
                    "scripts/validators/validate_generalism_result.py", out)
        rejected = self.val_reject("PR-fast gate rejects duplicate case floor inflation",
                                   "scripts/gates/check_generalism_pr_fast.py", out, "--json")
        body = rejected.stdout.decode("utf-8", "replace")
        self.assertIn("generalism.pr_fast.duplicate_case", body)
        self.assertIn("generalism.pr_fast.required_case_floor", body)

    def test_missing_build_tools_cli_fails_closed(self):
        os.environ.pop("NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_CLI", None)
        rejected = self.val_reject(
            "missing pinned build-tools verifier fails closed",
            "scripts/validators/validate_generalism_result.py",
            "examples/generalism-results/pr_fast_faithful.json",
            "--json",
        )
        body = rejected.stdout.decode("utf-8", "replace")
        self.assertIn("NEUTRINO_BUILD_TOOLS_GENERALISM_REPORT_CLI is required", body)

    def test_tampered_summary_fails_closed(self):
        obj = self.load_json(os.path.join(REPO, "examples/generalism-results/pr_fast_faithful.json"))
        obj["summary"]["counts"]["SILENT"] = 1
        out = self.dump_json(obj, os.path.join(self.tmp, "tampered.json"))
        self.val_reject("summary count drift fails closed",
                        "scripts/validators/validate_generalism_result.py", out)

    def test_evidence_artifact_refs_are_resolved(self):
        obj = self.load_json(os.path.join(REPO, "examples/generalism-results/pr_fast_faithful.json"))
        obj["evidence"]["evidencePackageRef"] = "does/not/exist.evidence.json"
        out = self.dump_json(obj, os.path.join(self.tmp, "missing-evidence-artifact.json"))
        self.val_reject("missing evidence package artifact fails closed",
                        "scripts/validators/validate_generalism_result.py", out)

    def test_forged_ok_report_with_updated_digests_fails_closed(self):
        scratch = tempfile.mkdtemp(prefix=".generalism-forged.", dir=REPO)
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)

        src_dir = os.path.join(REPO, "examples/generalism-results/artifacts")
        names = {
            "receipt": "happy_allow.receipt.json",
            "trace": "happy_allow.trace.json",
            "package": "happy_allow.evidence.json",
            "report": "happy_allow.verification.json",
        }
        refs = {}
        for key, name in names.items():
            dst = os.path.join(scratch, name)
            shutil.copyfile(os.path.join(src_dir, name), dst)
            refs[key] = os.path.relpath(dst, REPO)

        package_path = os.path.join(REPO, refs["package"])
        package = self.load_json(package_path)
        package["records"][0]["signature"] = "0" * 128
        self.dump_json(package, package_path)
        with open(package_path, "rb") as f:
            package_digest = "sha256:" + hashlib.sha256(f.read()).hexdigest()

        report_path = os.path.join(REPO, refs["report"])
        report = self.load_json(report_path)
        report["artifacts"]["bindingReceipt"]["artifactRef"] = refs["receipt"]
        report["artifacts"]["executionTrace"]["artifactRef"] = refs["trace"]
        report["artifacts"]["evidencePackage"]["artifactRef"] = refs["package"]
        report["artifacts"]["evidencePackage"]["digest"] = package_digest
        # Deliberately do not re-sign the report. Without attestation verification, this
        # same-format forged report plus updated digest would be accepted.
        self.dump_json(report, report_path)
        with open(report_path, "rb") as f:
            report_digest = "sha256:" + hashlib.sha256(f.read()).hexdigest()

        obj = self.load_json(os.path.join(REPO, "examples/generalism-results/pr_fast_faithful.json"))
        ev = obj["evidence"]
        ev["bindingReceiptArtifactRef"] = refs["receipt"]
        ev["evidencePackageRef"] = refs["package"]
        ev["evidencePackageDigest"] = package_digest
        ev["verificationReportRef"] = refs["report"]
        ev["verificationReportDigest"] = report_digest
        ev["verificationReportAttestation"] = report["attestation"]
        out = self.dump_json(obj, os.path.join(self.tmp, "forged-ok-report.json"))
        rejected = self.val_reject("forged ok verification report fails closed",
                                   "scripts/validators/validate_generalism_result.py", out, "--json")
        body = rejected.stdout.decode("utf-8", "replace")
        self.assertIn("pinned build-tools verification CLI rejected", body)


if __name__ == "__main__":
    unittest.main()
