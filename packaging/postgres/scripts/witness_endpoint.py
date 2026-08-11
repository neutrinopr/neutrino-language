#!/usr/bin/env python3
""" end-to-end acceptance witnesses. DO NOT MERGE until  completes.

LAYOUT-NEUTRAL BY CONSTRUCTION. The package under test is an OPAQUE PREFIX: this
harness never names a `.inc`, a payload directory, a source-tree path, or any
build-system variable. It discovers what it needs from the package DESCRIPTOR and
speaks to the core over the versioned subprocess protocol.  is about to
change the materialization layout; nothing here should need editing when it does.

The one thing a witness may assume is the CONTRACT: descriptor fields, protocol
framing, receipt schema. Those are versioned and owned elsewhere. Anything that
would have to change because a file moved is a bug in this harness.

Six witnesses, run in order; each independent, each fails closed:

  1 protocol        -- the package is invoked through the descriptor/protocol
                       seam and answers, with no in-process C++ edge.
  2 sql-bytes       -- emitted SQL is byte-identical to the pinned oracle.
  3 postgresql      -- that SQL executes against a real server and the
                       behavioural slice holds.
  4 receipt         -- the extraction receipt verifies against the built prefix.
  5 substitution    -- replacing an artifact is REJECTED (the mutation that a
                       prefix-derived check cannot catch).
  6 reach-back      -- the built prefix depends on no translator checkout.

Witness 6 is deliberately last: it is an assertion about the finished artifact,
not a build-time scan, so it must observe what the other five actually exercised.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

DESCRIPTOR_KIND = "neutrino.backend-package/1"
PROTOCOL_KIND = "neutrino.backend-protocol/1"  # informational; the descriptor
# carries protocolMajor/protocolMinor rather than this kind string.

# The startup binding, taken from include/Neutrino/BackendStartup.h rather than
# assumed. Verified against the real entry: a wrong identity or a relative
# descriptor path is refused with 96, and a valid binding reaches the frame loop.
STARTUP_ARGUMENT = "--neutrino-backend-startup="
STARTUP_IDENTITY = "neutrino.backend-startup/1"
DESCRIPTOR_ARGUMENT = "--package-descriptor="
# The entry exits here when the startup binding is accepted but stdin carries no
# frame -- i.e. it got past startup and descriptor verification into the loop.
FRAME_LOOP_EMPTY_STDIN = 92


class WitnessFailure(Exception):
    def __init__(self, witness, detail):
        super().__init__(f"{witness}: {detail}")
        self.witness = witness


def sha256_file(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def find_descriptor(package_prefix):
    """The descriptor is the ONLY entry point we are allowed to know about.

    We locate it by KIND, not by a hard-coded relative path, so a layout change
    that moves it does not break the harness. Ambiguity is a refusal: two
    descriptors mean we cannot tell which package is under test.
    """
    found = []
    for root, _dirs, files in os.walk(package_prefix):
        for name in files:
            if not name.endswith(".json"):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, encoding="utf-8") as handle:
                    doc = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(doc, dict) and doc.get("kind") == DESCRIPTOR_KIND:
                found.append((path, doc))
    if not found:
        raise WitnessFailure(
            "protocol",
            f"no {DESCRIPTOR_KIND} descriptor anywhere under {package_prefix} -- "
            "the package exposes no discoverable entry point")
    if len(found) > 1:
        raise WitnessFailure(
            "protocol",
            f"{len(found)} descriptors under {package_prefix}: "
            f"{sorted(p for p, _ in found)}")
    return found[0]


def witness_protocol(package_prefix, core_prefix):
    """1. Invoke through the descriptor/protocol seam."""
    descriptor_path, descriptor = find_descriptor(package_prefix)
    # The descriptor carries the protocol as a MAJOR/MINOR pair, not a kind
    # string -- checked against the real materialized descriptor rather than
    # assumed. Both fields must be present: a package that declares no protocol
    # version cannot be negotiated with.
    major = descriptor.get("protocolMajor")
    minor = descriptor.get("protocolMinor")
    if not isinstance(major, int) or not isinstance(minor, int):
        raise WitnessFailure(
            "protocol",
            f"descriptor declares no protocol version "
            f"(protocolMajor={major!r}, protocolMinor={minor!r})")
    protocol = f"{major}.{minor}"
    entry = descriptor.get("entry")
    if not entry:
        raise WitnessFailure("protocol", "descriptor declares no entry")
    # The entry is resolved RELATIVE TO THE DESCRIPTOR, so the harness never
    # needs to know where inside the prefix either of them lives.
    entry_path = os.path.join(os.path.dirname(descriptor_path), entry)
    if not os.path.isfile(entry_path):
        entry_path = os.path.join(package_prefix, entry)
    if not os.path.isfile(entry_path):
        raise WitnessFailure("protocol", f"declared entry {entry!r} not found")
    if not os.access(entry_path, os.X_OK):
        raise WitnessFailure("protocol", f"entry {entry!r} is not executable")
    # The startup contract, checked against the real binding rather than
    # invented: the entry takes exactly the contract identity and an ABSOLUTE
    # descriptor path, verifies the descriptor's manifestDigest, and only then
    # enters the frame loop. Exit 96/97 mean it refused before that point.
    def invoke(args):
        return subprocess.run([entry_path, *args], capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=60,
                              env={**os.environ,
                                   "NEUTRINO_CORE_PREFIX": core_prefix})

    good = invoke([f"{STARTUP_ARGUMENT}{STARTUP_IDENTITY}",
                   f"{DESCRIPTOR_ARGUMENT}{os.path.abspath(descriptor_path)}"])
    if good.returncode in (96, 97):
        raise WitnessFailure(
            "protocol",
            f"entry refused a VALID startup binding (rc={good.returncode}) -- "
            "the descriptor and the entry disagree")
    if good.returncode != FRAME_LOOP_EMPTY_STDIN:
        raise WitnessFailure(
            "protocol",
            f"entry did not reach the frame loop (rc={good.returncode}); "
            f"expected {FRAME_LOOP_EMPTY_STDIN} on empty stdin")

    # Non-vacuity: the seam must also REFUSE. Without these, a binary that
    # ignored its arguments entirely would satisfy the check above.
    bad_identity = invoke([f"{STARTUP_ARGUMENT}not-the-contract",
                           f"{DESCRIPTOR_ARGUMENT}"
                           f"{os.path.abspath(descriptor_path)}"])
    if bad_identity.returncode != 96:
        raise WitnessFailure(
            "protocol",
            f"a WRONG startup contract identity was not refused "
            f"(rc={bad_identity.returncode})")
    relative = invoke([f"{STARTUP_ARGUMENT}{STARTUP_IDENTITY}",
                       f"{DESCRIPTOR_ARGUMENT}"
                       f"{os.path.basename(descriptor_path)}"])
    if relative.returncode != 96:
        raise WitnessFailure(
            "protocol",
            f"a RELATIVE descriptor path was not refused "
            f"(rc={relative.returncode})")
    return {"descriptor": descriptor_path, "entry": entry_path,
            "protocol": protocol, "startup": "bound; wrong-identity and "
            "relative-path both refused"}


def witness_sql_bytes(package_prefix, generator, spec, scenario, oracle_dir,
                      work_dir):
    """2. Emitted SQL is byte-identical to the pinned oracle.

    The package is driven THROUGH THE CORE over the real protocol: the core
    discovers it via NEUTRINO_BACKEND_PACKAGE_PATH, negotiates, and streams the
    finalized projection to it. The entry has no side-door emission flag, and
    inventing one here would have proved nothing about the seam.

    Compares by RELATIVE NAME within the oracle directory, so which files exist
    is the oracle's business, not a constant in this harness.
    """
    out_dir = os.path.join(work_dir, "sql")
    os.makedirs(out_dir, exist_ok=True)
    command = [generator, "--target=postgres", f"--scenario={scenario}", spec,
               "-o", out_dir]
    proc = subprocess.run(
        command, capture_output=True, text=True, timeout=300,
        env={**os.environ, "NEUTRINO_BACKEND_PACKAGE_PATH": package_prefix})
    if proc.returncode != 0:
        raise WitnessFailure(
            "sql-bytes",
            f"generation through the package failed (rc={proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()[:300]}")
    expected = {}
    for root, _dirs, files in os.walk(oracle_dir):
        for name in files:
            if name.endswith(".sql"):
                full = os.path.join(root, name)
                expected[os.path.relpath(full, oracle_dir)] = sha256_file(full)
    if not expected:
        raise WitnessFailure("sql-bytes", f"oracle {oracle_dir} declares no SQL")
    produced = {}
    for root, _dirs, files in os.walk(out_dir):
        for name in files:
            if name.endswith(".sql"):
                full = os.path.join(root, name)
                produced[os.path.relpath(full, out_dir)] = sha256_file(full)
    missing = sorted(set(expected) - set(produced))
    extra = sorted(set(produced) - set(expected))
    if missing or extra:
        raise WitnessFailure(
            "sql-bytes", f"emission set differs: missing={missing} extra={extra}")
    drift = sorted(k for k in expected if expected[k] != produced[k])
    if drift:
        raise WitnessFailure("sql-bytes", f"byte drift in {drift}")
    return {"files": len(expected)}


PG_IMAGE = "postgres:16-alpine"


def witness_postgresql(sql_dir, behavioural_script):
    """3. The emitted SQL is BEHAVIOURALLY correct on a real server.

    Loading DDL is NOT success: a schema and a procedure that merely parse prove
    nothing about quorum gating, replay refusal, balance movement, reconciliation
    drift, or rollback. This runs the committed run_db_test.sh assertions against
    the artifacts the PACKAGE emitted, so the claim is behaviour rather than
    syntax.

    run_db_test.sh is external test scaffolding: it is copied next to the emitted
    SQL for the run and is NOT part of the package's shipped surface.

    PostgreSQL runs in Docker with psql INSIDE the container, so no host psql is
    required and the server version is pinned. A skip is a FAILURE: a harness
    that reports green on an unrun witness is worse than one that reports red.
    """
    if not os.path.isfile(behavioural_script):
        raise WitnessFailure(
            "postgresql",
            f"behavioural assertions {behavioural_script} not found -- this "
            "witness cannot be satisfied by loading DDL alone")
    staged = os.path.join(sql_dir, os.path.basename(behavioural_script))
    shutil.copy2(behavioural_script, staged)
    os.chmod(staged, 0o755)
    probe = subprocess.run(["docker", "info"], capture_output=True)
    if probe.returncode != 0:
        raise WitnessFailure(
            "postgresql", "docker is unavailable -- the behavioural witness "
            "cannot be satisfied by skipping")
    proc = subprocess.run(["bash", staged], capture_output=True, text=True,
                          timeout=900, cwd=sql_dir)
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise WitnessFailure(
            "postgresql",
            f"behavioural assertions FAILED (rc={proc.returncode}): "
            f"{output.strip()[-400:]}")
    passes = [line.strip() for line in output.splitlines()
              if line.strip().endswith("PASS")]
    if not passes:
        raise WitnessFailure(
            "postgresql",
            "the behavioural script reported no PASS lines -- a silent exit 0 "
            "is not evidence that anything was asserted")
    return {"image": PG_IMAGE, "assertions": len(passes),
            "checks": [p.split(":")[0].strip() for p in passes]}


def witness_receipt(package_prefix, receipt_path, verifier):
    """4. The extraction receipt verifies against the BUILT prefix."""
    proc = subprocess.run(
        [sys.executable, verifier, "--check", "--receipt", receipt_path,
         "--prefix", package_prefix],
        capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise WitnessFailure(
            "receipt", f"verification failed: {proc.stderr.strip()[:300]}")
    return {"receipt": receipt_path}


def witness_substitution(package_prefix, receipt_path, verifier, work_dir):
    """5. Replacing an artifact must be REJECTED.

    The substituted file is chosen from what the RECEIPT declares, not from a
    path this harness knows, so it stays correct across layout changes.
    """
    import shutil
    with open(receipt_path, encoding="utf-8") as handle:
        receipt = json.load(handle)
    declared = [a["path"] for a in receipt.get("artifacts", receipt.get(
        "runtimeArtifacts", []))]
    if not declared:
        raise WitnessFailure(
            "substitution", "receipt declares no artifacts to substitute")
    forged = os.path.join(work_dir, "forged-prefix")
    if os.path.exists(forged):
        shutil.rmtree(forged)
    shutil.copytree(package_prefix, forged, symlinks=True)
    target = os.path.join(forged, declared[0])
    if not os.path.isfile(target):
        raise WitnessFailure(
            "substitution", f"declared artifact {declared[0]} absent from prefix")
    mode = os.stat(target).st_mode
    with open(target, "wb") as handle:
        handle.write(b"SUBSTITUTED\n")
    os.chmod(target, mode)
    proc = subprocess.run(
        [sys.executable, verifier, "--check", "--receipt", receipt_path,
         "--prefix", forged],
        capture_output=True, text=True, timeout=300)
    if proc.returncode == 0:
        raise WitnessFailure(
            "substitution",
            f"substituting {declared[0]} was ACCEPTED -- the receipt does not "
            "bind artifact bytes")
    return {"substituted": declared[0]}


def witness_reach_back(package_prefix, forbidden_roots):
    """6. The BUILT prefix depends on no translator checkout.

    Scans the delivered bytes for absolute references to any forbidden root.
    This is an assertion about the artifact, so it holds whatever the source
    layout was -- which is exactly why it survives .
    """
    hits = []
    roots = [os.path.realpath(r) for r in forbidden_roots if r]
    if not roots:
        raise WitnessFailure(
            "reach-back", "no forbidden root supplied -- the scan would be vacuous")
    for root, _dirs, files in os.walk(package_prefix):
        for name in files:
            path = os.path.join(root, name)
            try:
                with open(path, "rb") as handle:
                    blob = handle.read()
            except OSError:
                continue
            for forbidden in roots:
                if forbidden.encode() in blob:
                    hits.append((os.path.relpath(path, package_prefix), forbidden))
    if hits:
        detail = "; ".join(f"{p} references {r}" for p, r in hits[:10])
        raise WitnessFailure("reach-back", f"{len(hits)} reference(s): {detail}")
    return {"scanned_roots": roots}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-prefix", required=True,
                        help="the BUILT package, treated as opaque")
    parser.add_argument("--core-prefix", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--receipt-verifier", required=True)
    parser.add_argument("--sql-oracle", required=True)
    parser.add_argument("--generator", required=True,
                        help="the CORE generator that drives the package over "
                             "the protocol; the package has no side-door "
                             "emission flag")
    parser.add_argument("--spec", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--behavioural-script", required=True,
                        help="committed assertions run against the emitted "
                             "SQL (run_db_test.sh semantics). External test "
                             "scaffolding; not shipped in the package.")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--forbidden-root", action="append", default=[],
                        help="absolute path that must NOT appear in the built "
                             "prefix; repeatable. Required.")
    args = parser.parse_args(argv)
    os.makedirs(args.work_dir, exist_ok=True)

    results, failures = {}, []
    try:
        results["protocol"] = witness_protocol(args.package_prefix, args.core_prefix)
        entry = results["protocol"]["entry"]
        results["sql-bytes"] = witness_sql_bytes(
            args.package_prefix, args.generator, args.spec, args.scenario,
            args.sql_oracle, args.work_dir)
        results["postgresql"] = witness_postgresql(
            os.path.join(args.work_dir, "sql"), args.behavioural_script)
        results["receipt"] = witness_receipt(
            args.package_prefix, args.receipt, args.receipt_verifier)
        results["substitution"] = witness_substitution(
            args.package_prefix, args.receipt, args.receipt_verifier, args.work_dir)
        results["reach-back"] = witness_reach_back(
            args.package_prefix, args.forbidden_root)
    except WitnessFailure as failure:
        failures.append(str(failure))

    for name, detail in results.items():
        print(f"  ok   {name}: {detail}")
    if failures:
        for failure in failures:
            print(f"  FAIL {failure}", file=sys.stderr)
        print(" endpoint witnesses FAILED", file=sys.stderr)
        return 1
    print(" endpoint witnesses OK (protocol, sql-bytes, postgresql, "
          "receipt, substitution, reach-back)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
