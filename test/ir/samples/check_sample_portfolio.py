"""[67] M3 sample portfolio (). Ported verbatim from the retired run_cpp_tests.sh [67] block (
S5l). The coverage map over the strategy  samples validates against the committed fixtures; and it
fails closed on: a current-valid sample pointing at a missing artifact; a current-valid artifact without
a  validation classification; and a validation entry classifying a non-declared/stale path (the
reverse-direction gate). Negatives run against a mutated copy of the examples tree.

Usage: check_sample_portfolio.py <validate_sample_portfolio.py> <examples-dir>
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

VSP, EXAMPLES = sys.argv[1:3]
REPO = os.path.dirname(os.path.abspath(EXAMPLES))
fails = []


def validate(repo_root):
    return subprocess.run([sys.executable, VSP, "--repo-root", repo_root,
                           "--portfolio", "examples/m3-sample-portfolio.json"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


# positive: the committed portfolio validates.
if validate(REPO) != 0:
    fails.append("sample portfolio map is invalid or drifted")


def mutated_repo(mutate):
    root = tempfile.mkdtemp(prefix="port67.")
    shutil.copytree(EXAMPLES, os.path.join(root, "examples"))
    p = os.path.join(root, "examples", "m3-sample-portfolio.json")
    d = json.load(open(p))
    mutate(d)
    json.dump(d, open(p, "w"), indent=2)
    return root


def _missing_artifact(d):
    d["samples"][0]["artifacts"]["l1"] = "examples/domains/does_not_exist/source/x.neu"


def _drop_validation(d):
    s0 = d["samples"][0]
    s0["validation"] = [v for v in s0["validation"] if v.get("path") != s0["artifacts"]["l1"]]


def _stale_classification(d):
    d["samples"][0]["validation"].append({
        "path": "examples/domains/missing/generated.sol",
        "classification": "native-validated",
        "validator": "fabricated",
        "gateIssue": "urn:neutrino:gate:native-build-v1",
    })


for label, mutate in [
    ("a current-valid sample with a missing artifact", _missing_artifact),
    ("a current-valid artifact without a  validation classification", _drop_validation),
    ("a validation classification for a non-fixture/stale path", _stale_classification),
]:
    if validate(mutated_repo(mutate)) == 0:
        fails.append(f"portfolio validator accepted {label}")

if fails:
    print("[67] sample-portfolio contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[67] OK: portfolio map validates against committed fixtures; drifted/missing artifacts, missing "
      " validation classifications, and validation entries for non-declared/stale paths all rejected")
