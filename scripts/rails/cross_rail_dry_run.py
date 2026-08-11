#!/usr/bin/env python3
"""Phase 13 — cross-rail dry run.

Moves one sample domain from `.neu` to a slot-ready bundle and exercises the
boundaries to the other rails **without merging their runtimes** and without
modifying them (the sibling repos are read-only here):

  translator  -> slot-ready bundle (generate.{solidity,postgres,slot})
  agents      -> the bundle is an artifact-producing task result (bundle.json +
                 per-target manifest.json/diagnostics.json + content hashes)
  network     -> the slot operation set aligns with neutrino-network's
  simulation  -> the slot capability maps to a payment-network-simulation flow
                 (via neutrino-finance-poc)

Mandatory (translator-produced) stages gate the exit code; cross-rail alignment
is reported and any unresolved items are listed as gaps.

  make cross-rail   # runs this script directly
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # neutrino-translator (rails/ -> scripts -> repo, )
ROOT = os.path.dirname(HERE)                                          # project root
GEN = os.path.join(HERE, "out", "tools", "neutrino-gen", "neutrino-gen")
BUNDLE = os.path.join(HERE, "out", "tools", "neutrino-bundle", "neutrino-bundle")
NETWORK = os.path.join(ROOT, "neutrino-network")
FINANCE = os.path.join(ROOT, "neutrino-finance-poc")
OPS = ["OPEN", "NEGOTIATE", "PROPOSE", "COMMIT", "REJECT", "COMPENSATE", "CLOSE"]
DOMAIN = "core_sample_installment"

# Capabilities that MUST have a Fabric bridge vector when neutrino-network is
# present. A missing/stale/mismatched vector is a hard failure, not a silent
# "gap" — capability_name -> the slot fixture dir under examples/slot/.
BRIDGE_REQUIRED = {"coordinate.core_sponsored_offer": "core_sponsored_offer"}


def slot_lock_path(dom):
    """Resolve a domain's slot capability.lock across both layouts: domain-major
    (examples/domains/<dom>/generated/slot) takes precedence, falling back to the
    legacy family-major examples/slot/<dom> for un-migrated domains ()."""
    dm = os.path.join(HERE, "examples", "domains", dom, "generated", "slot", "capability.lock")
    if os.path.exists(dm):
        return dm
    return os.path.join(HERE, "examples", "slot", dom, "capability.lock")


stages, gaps = [], []


def stage(name, status, detail=""):
    stages.append({"stage": name, "status": status, "detail": detail})
    mark = {"ok": "ok  ", "gap": "GAP ", "skip": "skip", "fail": "FAIL"}[status]
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))
    if status in ("gap", "skip"):
        gaps.append(f"{name}: {detail}")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(65536), b""):
            h.update(c)
    return h.hexdigest()


def network_op_set():
    """Read-only: operation names neutrino-network references in its spec/proto/conformance."""
    found = set()
    for sub in ("spec", "proto", "conformance"):
        base = os.path.join(NETWORK, sub)
        for dp, _, files in os.walk(base) if os.path.isdir(base) else []:
            for fn in files:
                try:
                    text = open(os.path.join(dp, fn), errors="ignore").read().lower()
                except OSError:
                    continue
                for op in OPS:
                    if op.lower() in text:
                        found.add(op)
    return found


def main():
    if not (os.path.exists(GEN) and os.path.exists(BUNDLE)):
        print(f"SKIP: translator not built ({BUNDLE})")
        return 0

    work = tempfile.mkdtemp(prefix="dryrun_")
    inb = os.path.join(work, "in")
    os.makedirs(inb)
    import shutil
    dom_dir = os.path.join(HERE, "examples", "domains", DOMAIN)
    shutil.copy(os.path.join(dom_dir, "source", f"{DOMAIN}.neu"), os.path.join(inb, "source.neu"))
    shutil.copy(os.path.join(dom_dir, "scenario", f"{DOMAIN}_happy_path.json"), os.path.join(inb, "scenario.json"))
    json.dump({"targets": ["solidity", "postgres", "slot"]}, open(os.path.join(inb, "target.json"), "w"))
    out = os.path.join(work, "out")

    print("cross-rail dry run:", DOMAIN)
    print("\nrail: translator")
    rc = subprocess.run([BUNDLE, inb, "-o", out], env=dict(os.environ, NEUTRINO_GEN=GEN,
                        SOURCE_DATE_EPOCH="1700000000"), capture_output=True).returncode
    bundle_ok = rc == 0 and os.path.exists(os.path.join(out, "slot", "capability.json"))
    stage("translator: .neu -> slot-ready bundle", "ok" if bundle_ok else "fail",
          "generate.{solidity,postgres,slot}")
    if not bundle_ok:
        return 1

    # slot-contract conformance
    slot = os.path.join(out, "slot")
    need = ["capability.json", "operations.json", "compensation.json", "transcript.json",
            "envelope.schema.json", "capability.lock"]
    present = all(os.path.exists(os.path.join(slot, f)) for f in need)
    ops = [o["operation"] for o in json.load(open(os.path.join(slot, "operations.json")))["operations"]]
    cap = json.load(open(os.path.join(slot, "capability.json")))
    # capability.lock binds the wire contract to a single capabilityHash, which is
    # decoded to EnvelopeHeader.schema_hash downstream — the Fabric identity handoff.
    # Recompute it from the emitted files (per the lock's documented method) and
    # confirm the lock is consistent; otherwise the dry run could pass on a stale or
    # wrong identity.
    capability_hash, lock_ok = None, False
    if os.path.exists(os.path.join(slot, "capability.lock")):
        lock = json.load(open(os.path.join(slot, "capability.lock")))
        wire = ["capability.json", "operations.json", "compensation.json", "transcript.json"]
        entries = sorted(f"{w}:{sha256(os.path.join(slot, w))}\n" for w in wire)
        recomputed = hashlib.sha256("".join(entries).encode()).hexdigest()
        # The lock must cover exactly the wire files — no more, no less — so a file
        # silently added to or dropped from the hashed set is caught, not just a
        # content change to a file already listed.
        keyset_ok = set(lock.get("files", {})) == set(wire)
        files_ok = all(sha256(os.path.join(slot, f)) == h for f, h in lock.get("files", {}).items())
        lock_ok = recomputed == lock.get("capabilityHash") and files_ok and keyset_ok
        capability_hash = lock.get("capabilityHash")
    stage("translator: slot contract conformance",
          "ok" if (present and ops == OPS and lock_ok) else "fail",
          f"{len(need)} files (incl. capability.lock capabilityHash bridge); "
          f"operations={'/'.join(ops)}")

    # The slot bundle must derive from the CANONICAL SPEC (/), the one frozen contract the
    # migrated renderers consume. Emit the spec (scenario-free) and confirm the slot capability is a
    # faithful projection of it: same procedure/trigger identity, and every spec input/compute/
    # effect-ledger present in the slot capability. This is the dry run consuming the spec as the
    # contract, not re-deriving structure from the slot alone.
    spec_dir = os.path.join(work, "spec")
    prc = subprocess.run([GEN, "--target=capability-spec", os.path.join(inb, "source.neu"), "-o", spec_dir],
                         capture_output=True).returncode
    spec_mismatches = []
    if prc != 0 or not os.path.exists(os.path.join(spec_dir, "capability-spec.json")):
        spec_mismatches.append("neutrino-gen --target=capability-spec did not produce capability-spec.json")
    else:
        spec = json.load(open(os.path.join(spec_dir, "capability-spec.json")))
        cap_inputs = {i["name"] for i in cap.get("typedInputs", []) + cap.get("partyTypedInputs", [])}
        spec_inputs = {i.get("name") for i in spec.get("inputs", [])}
        spec_computes = {c.get("name") for c in spec.get("computes", [])}
        spec_ledgers = {e.get("ledger") for e in spec.get("effects", [])}
        if spec.get("procedure") != cap.get("procedure"):
            spec_mismatches.append(f"procedure {spec.get('procedure')!r} != slot {cap.get('procedure')!r}")
        if spec.get("trigger") != cap.get("trigger"):
            spec_mismatches.append(f"trigger {spec.get('trigger')!r} != slot {cap.get('trigger')!r}")
        if not spec_inputs <= cap_inputs:
            spec_mismatches.append(f"inputs not in slot capability: {sorted(spec_inputs - cap_inputs)}")
        if not spec_computes <= set(cap.get("computed", [])):
            spec_mismatches.append(f"computes not in slot capability: {sorted(spec_computes - set(cap.get('computed', [])))}")
        if not spec_ledgers <= set(cap.get("ledgers", [])):
            spec_mismatches.append(f"effect ledgers not in slot capability: {sorted(spec_ledgers - set(cap.get('ledgers', [])))}")
    stage("translator: slot bundle derives from the canonical spec",
          "ok" if not spec_mismatches else "fail",
          "spec {procedure,trigger,inputs,computes,effect-ledgers} all project into the slot capability"
          if not spec_mismatches else "; ".join(spec_mismatches))

    print("\nrail: agents (artifact ingestion)")
    art_ok = all(os.path.exists(os.path.join(out, p)) for p in
                 ("bundle.json", "solidity/manifest.json", "postgres/manifest.json", "slot/manifest.json"))
    slot_hashes = {f: sha256(os.path.join(slot, f)) for f in need}
    stage("agents: bundle consumable as a task result", "ok" if art_ok else "fail",
          "bundle.json + per-target manifest/diagnostics + content hashes")

    print("\nrail: network (slot operation alignment)")
    if not os.path.isdir(NETWORK):
        stage("network: operation-set alignment", "skip", "neutrino-network not present")
    else:
        net = network_op_set()
        missing = [o for o in OPS if o not in net]
        if not missing:
            stage("network: operation-set alignment", "ok",
                  f"all {len(OPS)} slot ops present in neutrino-network spec/proto/conformance")
        else:
            stage("network: operation-set alignment", "gap", f"network missing: {missing}")

    print("\nrail: bridge (capabilityHash <-> EnvelopeHeader.schema_hash)")
    vectors_dir = os.path.join(NETWORK, "conformance", "vectors", "envelope-v1")
    if not os.path.isdir(vectors_dir):
        # Cross-repo check unverifiable here. The translator side stays pinned by
        # the capability.lock fixture self-test; the network side by its own
        # conformance suite. This is the only honest 'skip'.
        stage("bridge: capabilityHash == schema_hash", "skip",
              "neutrino-network conformance vectors not present")
    else:
        # Index Fabric envelope vectors by capability_name. A vector naming a
        # translator capability MUST carry that capability's exact
        # capability_version AND capability.lock.capabilityHash (schema_hash =
        # hexDecode(capabilityHash)).
        vecs = {}
        for fn in sorted(os.listdir(vectors_dir)):
            if not fn.endswith(".json"):
                continue
            hdr = json.load(open(os.path.join(vectors_dir, fn))).get("header", {})
            name = hdr.get("capability_name", "")
            if name.startswith("coordinate.") and hdr.get("schema_hash_hex"):
                vecs[name] = (hdr.get("capability_version", ""), hdr["schema_hash_hex"])

        def cross_check(name, lockp):
            lock = json.load(open(lockp))
            ver, sh = vecs[name]
            out = []
            if sh != lock.get("capabilityHash"):
                out.append(f"{name}: vector schema_hash {sh[:12]}.. != capability.lock "
                           f"{str(lock.get('capabilityHash'))[:12]}..")
            if ver != lock.get("capabilityVersion"):
                out.append(f"{name}: vector capability_version {ver!r} != capability.lock "
                           f"{lock.get('capabilityVersion')!r}")
            return out

        problems, checked = [], 0
        # Required M1 capabilities: a missing vector is a hard failure (no gap).
        for name, dom in BRIDGE_REQUIRED.items():
            lockp = slot_lock_path(dom)
            if name not in vecs:
                problems.append(f"{name}: required bridge vector missing in neutrino-network")
            elif os.path.exists(lockp):
                checked += 1
                problems += cross_check(name, lockp)
        # Any other bridge vector matching a local fixture is also checked.
        for name in vecs:
            if name in BRIDGE_REQUIRED:
                continue
            lockp = slot_lock_path(name[len("coordinate."):])
            if os.path.exists(lockp):
                checked += 1
                problems += cross_check(name, lockp)

        if problems:
            stage("bridge: capabilityHash == schema_hash", "fail", "; ".join(problems))
        else:
            stage("bridge: capabilityHash == schema_hash", "ok",
                  f"{checked} capability(ies) pinned: Fabric schema_hash + version "
                  f"== capability.lock")

    print("\nrail: simulation (capability -> finance flow)")
    if not os.path.isdir(FINANCE):
        stage("simulation: capability mapping", "skip", "neutrino-finance-poc not present")
    else:
        hit = subprocess.run(["grep", "-rl", DOMAIN, FINANCE], capture_output=True).returncode == 0
        stage("simulation: capability mapping", "ok" if hit else "gap",
              f"{cap['capability']} maps to a finance scenario" if hit
              else "no finance-poc scenario references this domain")

    # Known integration gaps a full connection still needs.
    gaps.append("transcript/evidence hashes are recorded per artifact; full cross-rail "
                "transcript replay needs the network runtime (out of scope for a dry run)")
    gaps.append("agents does not yet schedule generate.slot as a task type (Phase 6 capability split)")

    report = {"kind": "neutrino.cross-rail-dry-run", "domain": DOMAIN,
              "capability": cap["capability"], "capabilityHash": capability_hash,
              "stages": stages, "slotArtifactHashes": slot_hashes, "remainingGaps": gaps,
              "ok": all(s["status"] != "fail" for s in stages)}
    os.makedirs(os.path.join(HERE, "build"), exist_ok=True)
    rp = os.path.join(HERE, "build", "cross-rail-dry-run.json")
    json.dump(report, open(rp, "w"), indent=2)

    print("\nremaining integration gaps:")
    for g in gaps:
        print(f"  - {g}")
    print(f"\nreport -> {rp}")
    ok = all(s["status"] != "fail" for s in stages)
    print("\nCROSS-RAIL DRY RUN " + ("PASSED" if ok else "FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
