#!/usr/bin/env python3
"""M6 terminal P2c () — the declared Forge native-closure provisioning authority.

The `requires-forge` acceptance rows drive a PREBUILT Foundry `forge`. On macOS that binary
carries an ABSOLUTE Mach-O load command for `libusb` under the DEFAULT Homebrew prefix
(`/usr/local/opt/libusb/lib/libusb-1.0.0.dylib`). A box whose Homebrew lives anywhere else
(an offloaded / Apple-silicon / per-user prefix) therefore aborts in `dyld` BEFORE forge parses
its own arguments — every consuming row fails with `Abort trap: 6` and no conformance is ever
measured. The fix may not mutate the binary (`install_name_tool`), may not create a machine-global
`/usr/local` symlink, and may not depend on an interactive shell profile. What is left is the
supported dynamic-loader mechanism: hand the loader a DECLARED search prefix at the direct
child-spawn boundary.

macOS SIP strips `DYLD_*` from the environment of protected processes (`/bin/bash`, `/usr/bin/env`,
python from the system framework), so the declared value CANNOT be carried in `DYLD_LIBRARY_PATH`
itself — it is carried in the neutral `FORGE_DYLD_LIBRARY_PATH` and re-materialised as
`DYLD_LIBRARY_PATH` only where a launcher directly spawns forge. This module is the SINGLE place
that derives that prefix, so cmake, the Makefile and the acceptance dispatcher cannot drift.

This is toolchain PROVISIONING, not backend conformance: a broken closure must be reported as an
INFRASTRUCTURE failure with a non-zero exit BEFORE any render/compile/execute step runs, so a
provisioning defect can never be mistaken for (or mask) a conformance result.

Modes:

  --print-library-path            derive + print the declared native-library prefix ("" if none is
                                  needed / discoverable). Consumed by cmake at configure time and
                                  by the Makefile; NOTHING else may derive it.
  --preflight                     assert the configured forge's native closure RESOLVES under the
                                  declared prefix (exit 0), else emit `INFRASTRUCTURE: …` on stderr
                                  and exit 66. The acceptance dispatcher calls this first.
  --emit-receipt PATH             write the machine provisioning receipt (OS/arch, forge version +
                                  binary digest, native dependency paths + digests, LLVM/MLIR and
                                  Foundry coordinates).
  --verify-receipt PATH           re-derive on THIS machine and check the recorded receipt still
                                  describes it. A receipt recorded for another platform/prefix is
                                  reported as not-applicable (exit 77), never as a pass.
  --selftest                      run the NEGATIVE PROBE: build a private copy of the declared
                                  closure, prove --preflight passes against it, then RENAME the
                                  declared native dependency inside that copy and prove --preflight
                                  fails as infrastructure. Proves the probe bites without touching
                                  the real Homebrew tree.

Common options: --forge PATH (default: the discovered forge), --library-path DIR (default: derived).

Exit 0 ok / 1 receipt or selftest violation / 66 infrastructure (closure unresolved) /
77 not applicable on this machine / 2 usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RECEIPT_KIND = "neutrino.forge-toolchain-receipt.v1"
SCHEMA_VERSION = 1
EXIT_INFRA = 66
EXIT_NOT_APPLICABLE = 77

# The native dependency the prebuilt Foundry release hard-links on macOS. Recorded as the
# DECLARED requirement so the derivation is a named Homebrew formula, never a literal path.
DARWIN_NATIVE_FORMULA = "libusb"

# Load commands under these roots are provided by the OS and are never provisioned by us.
_SYSTEM_ROOTS = ("/usr/lib/", "/System/", "/Library/Frameworks/")


class ToolchainError(Exception):
    """A provisioning defect. Always reported as INFRASTRUCTURE, never as conformance."""


# ---------------------------------------------------------------------------
# derivation


def _run(argv, **kw):
    return subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False, **kw)


def brew_prefix(formula):
    """`brew --prefix <formula>` or None. Never raises — a box without brew simply has no
    declared prefix (Linux forge needs none; its closure resolves from the system loader)."""
    brew = shutil.which("brew")
    if not brew:
        return None
    proc = _run([brew, "--prefix", formula])
    if proc.returncode != 0:
        return None
    prefix = proc.stdout.strip()
    return prefix if prefix and os.path.isdir(prefix) else None


def derive_library_path():
    """The DECLARED native-library prefix for this machine, or "" when none applies.

    Parameterized in this order, so no workstation path is ever baked into a tracked file:
      1. an explicit `NEUTRINO_FORGE_LIBRARY_PATH` (cmake cache / operator override);
      2. `$(brew --prefix libusb)/lib` on Darwin;
      3. nothing (Linux / a box whose forge closure already resolves).
    """
    explicit = os.environ.get("NEUTRINO_FORGE_LIBRARY_PATH", "").strip()
    if explicit:
        return explicit
    if platform.system() != "Darwin":
        return ""
    prefix = brew_prefix(DARWIN_NATIVE_FORMULA)
    if not prefix:
        return ""
    libdir = os.path.join(prefix, "lib")
    return libdir if os.path.isdir(libdir) else ""


def discover_forge():
    """The configured forge. `FORGE` (cmake/ctest-declared) wins; else the repo-local
    `make setup-foundry` location; else `PATH`."""
    declared = os.environ.get("FORGE", "").strip()
    if declared and os.path.isfile(declared):
        return declared
    local = os.path.join(REPO, ".foundry", "bin", "forge")
    if os.path.isfile(local):
        return local
    return shutil.which("forge") or ""


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _otool_deps(binary):
    proc = _run(["otool", "-L", binary])
    if proc.returncode != 0:
        raise ToolchainError(f"otool -L {binary} failed: {proc.stdout.strip()}")
    deps = []
    for line in proc.stdout.splitlines()[1:]:
        match = re.match(r"\s+(\S+)\s+\(compatibility", line)
        if match:
            deps.append(match.group(1))
    return deps


def native_dependencies(binary):
    """The NON-system Mach-O load commands of `binary` (Darwin) — the closure we provision.
    Empty on non-Darwin, where forge's closure resolves through the ordinary system loader."""
    if platform.system() != "Darwin":
        return []
    return [d for d in _otool_deps(binary) if not d.startswith(_SYSTEM_ROOTS)]


def resolve_dependency(dep, library_path):
    """Where the loader will actually find `dep` given the declared prefix, or None.
    Mirrors the loader's rule: `DYLD_LIBRARY_PATH` entries are searched by LEAF NAME first,
    then the recorded absolute install path."""
    for entry in [e for e in library_path.split(os.pathsep) if e]:
        candidate = os.path.join(entry, os.path.basename(dep))
        if os.path.exists(candidate):
            return candidate
    if os.path.isabs(dep) and os.path.exists(dep):
        return dep
    return None


def forge_env(library_path, base=None):
    """The environment for a DIRECT forge spawn: the declared prefix re-materialised as
    `DYLD_LIBRARY_PATH` exactly here, at the child-spawn boundary."""
    env = dict(os.environ if base is None else base)
    if library_path:
        env["DYLD_LIBRARY_PATH"] = library_path
    return env


def forge_version(binary, library_path):
    proc = _run([binary, "--version"], env=forge_env(library_path))
    if proc.returncode != 0:
        raise ToolchainError(
            f"`{binary} --version` exited {proc.returncode} under the declared native "
            f"library path '{library_path or '(none)'}':\n{proc.stdout.strip()}")
    out = proc.stdout
    # `dyld: Library not loaded` can be printed while the process still reports 0 through a
    # pipe on some shells; treat any loader diagnostic as a hard closure failure.
    if "Library not loaded" in out or "image not found" in out:
        raise ToolchainError(
            f"the dynamic loader could not resolve {binary}'s native closure under "
            f"'{library_path or '(none)'}':\n{out.strip()}")
    version, commit = "", ""
    for line in out.splitlines():
        if line.startswith("forge Version:"):
            version = line.split(":", 1)[1].strip()
        elif line.startswith("Commit SHA:"):
            commit = line.split(":", 1)[1].strip()
    if not version:
        raise ToolchainError(f"`{binary} --version` printed no version line:\n{out.strip()}")
    return version, commit, out.strip()


# ---------------------------------------------------------------------------
# preflight


def preflight(binary, library_path):
    """Assert the configured forge is launchable and its native closure resolves. Raises
    ToolchainError (-> INFRASTRUCTURE, exit 66) on any provisioning defect."""
    if not binary:
        raise ToolchainError("no forge is configured (FORGE unset, no .foundry/bin/forge, "
                             "none on PATH)")
    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        raise ToolchainError(f"the configured forge '{binary}' is not an executable file")
    unresolved = []
    for dep in native_dependencies(binary):
        if resolve_dependency(dep, library_path) is None:
            unresolved.append(dep)
    if unresolved:
        raise ToolchainError(
            "the configured forge's native closure does not resolve.\n"
            f"  forge                 : {binary}\n"
            f"  declared library path : {library_path or '(none)'}\n"
            "  unresolved            : " + ", ".join(unresolved) + "\n"
            "  fix                   : provision the dependency and re-derive the declared prefix\n"
            "                          (see docs/testing/FORGE_TOOLCHAIN.md), or configure with\n"
            "                          -DNEUTRINO_FORGE_LIBRARY_PATH=<dir containing it>.")
    forge_version(binary, library_path)


# ---------------------------------------------------------------------------
# receipt


def build_receipt(binary, library_path):
    version, commit, _ = forge_version(binary, library_path)
    deps = []
    for dep in native_dependencies(binary):
        resolved = resolve_dependency(dep, library_path)
        deps.append({
            "recordedInstallName": dep,
            "resolvedPath": resolved,
            "digest": sha256_file(resolved) if resolved else None,
            "resolvedVia": ("declaredLibraryPath"
                            if resolved and os.path.dirname(resolved) != os.path.dirname(dep)
                            else "recordedInstallName"),
        })
    llvm_prefix = os.environ.get("LLVM_PREFIX") or brew_prefix("llvm@15") or ""
    llvm_version = ""
    llvm_config = os.path.join(llvm_prefix, "bin", "llvm-config") if llvm_prefix else ""
    if llvm_config and os.path.isfile(llvm_config):
        proc = _run([llvm_config, "--version"])
        if proc.returncode == 0:
            llvm_version = proc.stdout.strip()
    solc = os.environ.get("SOLC") or shutil.which("solc") or ""
    solc_version = ""
    if solc and os.path.isfile(solc):
        proc = _run([solc, "--version"])
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                if line.startswith("Version:"):
                    solc_version = line.split(":", 1)[1].strip()
    return {
        "kind": RECEIPT_KIND,
        "schemaVersion": SCHEMA_VERSION,
        "documentId": "urn:neutrino:document:forge-toolchain-v1",
        "note": ("Machine provisioning receipt for the requires-forge acceptance rows. The "
                 "absolute paths below RECORD one machine; the mechanism that derives them is "
                 "scripts/gates/check_forge_toolchain.py and is parameterized "
                 "(NEUTRINO_FORGE_LIBRARY_PATH / brew --prefix libusb)."),
        "machine": {
            "os": platform.system(),
            "osRelease": platform.release(),
            "osVersion": platform.mac_ver()[0] or "",
            "arch": platform.machine(),
        },
        # Foundry coordinates: the release the binary IS (version + upstream commit) plus the
        # exact bytes on this machine. The digest is the pin — a re-run of `foundryup` that moves
        # the binary makes --verify-receipt fail instead of silently changing the tool identity.
        "forge": {
            "path": binary,
            "version": version,
            "commitSha": commit,
            "digest": sha256_file(binary),
        },
        "declaredNativeLibraryPath": library_path,
        "declaredNativeFormula": DARWIN_NATIVE_FORMULA if platform.system() == "Darwin" else "",
        "nativeDependencies": deps,
        "llvm": {
            "prefix": llvm_prefix,
            "version": llvm_version,
            "mlirDir": os.path.join(llvm_prefix, "lib", "cmake", "mlir") if llvm_prefix else "",
        },
        "solc": {"path": solc, "version": solc_version},
    }


def verify_receipt(path, binary, library_path):
    with open(path, encoding="utf-8") as handle:
        recorded = json.load(handle)
    if recorded.get("kind") != RECEIPT_KIND:
        raise ToolchainError(f"{path}: not a {RECEIPT_KIND}")
    if recorded.get("machine", {}).get("os") != platform.system():
        print(f"NOT-APPLICABLE: {path} records "
              f"{recorded.get('machine', {}).get('os')}, this machine is {platform.system()}")
        return EXIT_NOT_APPLICABLE
    # A receipt records ONE machine. On any other box (a second developer's Mac, a runner with a
    # different Foundry location) it is simply not the subject — reporting it as a failure there
    # would be noise, and reporting it as a pass would be a lie. Say not-applicable.
    if os.path.abspath(recorded["forge"]["path"]) != os.path.abspath(binary or ""):
        print(f"NOT-APPLICABLE: {path} records forge at {recorded['forge']['path']}, "
              f"this machine is configured with {binary or '(none)'}")
        return EXIT_NOT_APPLICABLE
    current = build_receipt(binary, library_path)
    problems = []
    if current["forge"]["digest"] != recorded["forge"]["digest"]:
        problems.append(f"forge digest {current['forge']['digest']} != "
                        f"recorded {recorded['forge']['digest']}")
    if current["forge"]["version"] != recorded["forge"]["version"]:
        problems.append(f"forge version {current['forge']['version']} != "
                        f"recorded {recorded['forge']['version']}")
    recorded_deps = {d["recordedInstallName"]: d for d in recorded.get("nativeDependencies", [])}
    for dep in current["nativeDependencies"]:
        was = recorded_deps.get(dep["recordedInstallName"])
        if was is None:
            problems.append(f"undeclared native dependency {dep['recordedInstallName']}")
        elif dep["digest"] != was["digest"]:
            problems.append(f"{dep['recordedInstallName']}: digest {dep['digest']} != "
                            f"recorded {was['digest']}")
    for name in recorded_deps:
        if name not in {d["recordedInstallName"] for d in current["nativeDependencies"]}:
            problems.append(f"recorded native dependency {name} is gone from the closure")
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"OK: {path} still describes this machine "
          f"(forge {current['forge']['version']}, {len(current['nativeDependencies'])} "
          "provisioned native dependencies)")
    return 0


# ---------------------------------------------------------------------------
# negative probe


def selftest(binary, library_path):
    """NEGATIVE PROBE ( acceptance): with the DECLARED native dependency renamed, the
    preflight must fail as INFRASTRUCTURE before any conformance step. Runs against a PRIVATE
    copy of the closure so the real Homebrew tree is never mutated."""
    if not binary:
        print("SKIP: no forge configured; nothing to probe")
        return EXIT_NOT_APPLICABLE
    deps = native_dependencies(binary)
    if not deps:
        print("SKIP: this platform provisions no forge native dependencies "
              f"({platform.system()}); the probe has no declared subject")
        return EXIT_NOT_APPLICABLE
    resolved = [(d, resolve_dependency(d, library_path)) for d in deps]
    missing = [d for d, r in resolved if r is None]
    if missing:
        print("FAIL: baseline closure is already broken; provision it before probing: "
              + ", ".join(missing), file=sys.stderr)
        return 1
    failures = []
    with tempfile.TemporaryDirectory(prefix="forge-closure-probe-") as work:
        probe_dir = os.path.join(work, "lib")
        os.makedirs(probe_dir)
        for _, real in resolved:
            shutil.copy2(real, os.path.join(probe_dir, os.path.basename(real)))
        # 1. the private copy is a WORKING declared prefix -> preflight passes.
        try:
            preflight(binary, probe_dir)
            print(f"probe baseline: preflight PASSES against the private prefix {probe_dir}")
        except ToolchainError as exc:
            failures.append(f"private-copy baseline should pass but did not: {exc}")
        # 2. rename the declared dependency inside the copy -> preflight must BITE.
        victim = os.path.join(probe_dir, os.path.basename(resolved[0][0]))
        os.rename(victim, victim + ".renamed-by-probe")
        try:
            preflight(binary, probe_dir)
            failures.append(f"preflight PASSED with {os.path.basename(victim)} renamed — "
                            "the probe does not bite")
        except ToolchainError as exc:
            text = str(exc)
            if os.path.basename(victim) not in text and "Library not loaded" not in text:
                failures.append("preflight failed but its diagnostic does not name the missing "
                                f"dependency: {text}")
            else:
                print(f"probe bite: preflight FAILS as infrastructure with "
                      f"{os.path.basename(victim)} renamed")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("OK: the forge native-closure preflight bites on a removed declared dependency")
    return 0


# ---------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--print-library-path", action="store_true")
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--emit-receipt", metavar="PATH")
    mode.add_argument("--verify-receipt", metavar="PATH")
    mode.add_argument("--selftest", action="store_true")
    parser.add_argument("--forge", default=None)
    parser.add_argument("--library-path", default=None)
    args = parser.parse_args(argv)

    library_path = args.library_path if args.library_path is not None else derive_library_path()
    if args.print_library_path:
        print(library_path)
        return 0

    binary = args.forge or discover_forge()
    try:
        if args.preflight:
            preflight(binary, library_path)
            version, _, _ = forge_version(binary, library_path)
            print(f"forge {version} ready ({binary}); declared native library path: "
                  f"{library_path or '(none needed)'}")
            return 0
        if args.selftest:
            return selftest(binary, library_path)
        if args.emit_receipt:
            receipt = build_receipt(binary, library_path)
            os.makedirs(os.path.dirname(os.path.abspath(args.emit_receipt)), exist_ok=True)
            with open(args.emit_receipt, "w", encoding="utf-8") as handle:
                json.dump(receipt, handle, indent=2, sort_keys=False)
                handle.write("\n")
            print(f"wrote {args.emit_receipt}")
            return 0
        return verify_receipt(args.verify_receipt, binary, library_path)
    except ToolchainError as exc:
        print(f"INFRASTRUCTURE: {exc}", file=sys.stderr)
        return EXIT_INFRA


if __name__ == "__main__":
    sys.exit(main())
