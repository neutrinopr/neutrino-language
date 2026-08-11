"""Shared helpers for the M3 sample L1/L2/L3 contracts ([63]/[66]/[68]/[70]/[74],  S5l). Each sample
lowers its L1 .neu, generates its slot, then checks the L2 domain-semantics sidecar(s), branch-compat,
and the L3 binding manifest against the generated binding-topology — the same run_l2/run_l3/run_compat
shape the retired run_cpp_tests.sh blocks used, factored out so each per-sample driver stays small and
the assertions read identically across samples.

Not a lit test itself (no .test/.mlir/.neu suffix); imported by the co-located check_sample_*.py drivers.
"""
import json
import os
import subprocess
import sys
import tempfile


class M3:
    def __init__(self, scripts, examples, translate, gen):
        self.scripts = scripts
        self.examples = examples
        self.translate = translate
        self.gen = gen
        self.vl2 = os.path.join(scripts, "domain", "validate_l2_domain_semantics.py")
        self.vbm = os.path.join(scripts, "validators", "validate_binding_manifest.py")
        self.vbc = os.path.join(scripts, "domain", "validate_l2_branch_compat.py")
        self.topo = None
        self.fails = []
        self.tmp = tempfile.mkdtemp(prefix="m3.")

    # ---- paths ----
    def domain(self, name, *rest):
        return os.path.join(self.examples, "domains", name, *rest)

    def l2(self, *rest):
        return os.path.join(self.examples, "l2-domain-semantics", *rest)

    def manifest(self, *rest):
        return os.path.join(self.examples, "binding-manifests", *rest)

    # ---- runners ----
    def _run(self, *cmd):
        r = subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            return r.returncode, json.loads(r.stdout)
        except ValueError:
            return r.returncode, None

    def run_l2(self, p):
        return self._run(sys.executable, self.vl2, "--artifact", p)

    def run_l3(self, p):
        return self._run(sys.executable, self.vbm, "--manifest", p, "--binding-topology", self.topo, "--json")

    def run_compat(self, *paths):
        args = [sys.executable, self.vbc]
        for p in paths:
            args += ["--sidecar", p]
        return self._run(*args)

    def check(self, cond, msg):
        if not cond:
            self.fails.append(msg)

    # ---- L1 + slot ----
    def lower_and_slot(self, name, src_rel=None, scenario_rel=None):
        """Translate the L1 source and generate the slot; set self.topo to the binding-topology."""
        src = self.domain(name, "source", (src_rel or f"{name}.neu"))
        scen = self.domain(name, "scenario", (scenario_rel or f"{name}_happy_path.json"))
        return self.lower_and_slot_files(name, src, scen)

    def lower_and_slot_files(self, name, src, scen):
        """Like lower_and_slot, but with explicit absolute/repo-relative source + scenario paths.
        Used by synthetic sample fixtures that do not live under examples/domains/<name>/."""
        if subprocess.run([self.translate, src, "-o", os.path.join(self.tmp, name + ".mlir")],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
            self.fails.append(f"{name}: L1 source did not lower to IR")
            return
        out = os.path.join(self.tmp, name + "_slot")
        if subprocess.run([self.gen, "--target=slot", "--scenario=" + scen, src, "-o", out],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
            self.fails.append(f"{name}: slot generation failed")
            return
        self.topo = os.path.join(out, "binding-topology.json")
        return out

    # ---- assertions (each records a fail, none raise) ----
    def l2_positive(self, p, label="L2 positive"):
        rc, d = self.run_l2(p)
        self.check(rc == 0 and d and d["ok"] and d["diagnostics"] == [], f"{label}: rc={rc}")

    def l2_exact(self, p, code, label=None):
        rc, d = self.run_l2(p)
        codes = {x["code"] for x in d["diagnostics"]} if d else set()
        self.check(rc == 1 and d and d["ok"] is False and codes == {code},
                   f"{label or os.path.basename(p)}: rc={rc} codes={sorted(codes)} (want {code} only)")

    def l3_status(self, p, status, label="L3 positive"):
        rc, d = self.run_l3(p)
        self.check(rc == 0 and d and d["ok"] and d.get("status") == status,
                   f"{label}: rc={rc} status={(d or {}).get('status')} (want {status})")

    def l3_invalid(self, p, code, label=None):
        rc, d = self.run_l3(p)
        codes = {x["code"] for x in d["diagnostics"]} if d else set()
        self.check(rc == 1 and d and d["ok"] is False and d.get("status") == "invalid" and code in codes,
                   f"{label or os.path.basename(p)}: rc={rc} status={(d or {}).get('status')} "
                   f"codes={sorted(codes)} (want {code} + invalid)")

    def compat_positive(self, *paths):
        rc, d = self.run_compat(*paths)
        self.check(rc == 0 and d and d["ok"] and d["diagnostics"] == []
                   and d.get("kind") == "neutrino.l2-branch-compat-validation",
                   f"branch-compat positive: rc={rc}")

    def compat_exact(self, a, b, code, label="branch-compat neg"):
        rc, d = self.run_compat(a, b)
        codes = {x["code"] for x in d["diagnostics"]} if d else set()
        self.check(rc == 1 and d and d["ok"] is False and codes == {code},
                   f"{label}: rc={rc} codes={sorted(codes)} (want {code} only)")

    def finish(self, tag, ok_message):
        if self.fails:
            print(f"[{tag}] M3 sample contract FAILED:", file=sys.stderr)
            for f in self.fails:
                print("    FAIL: " + f, file=sys.stderr)
            sys.exit(1)
        print(f"[{tag}] OK: {ok_message}")
