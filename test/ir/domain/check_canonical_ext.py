"""[34] D0: .neu is the ONE canonical source extension. Ported verbatim from the retired
run_cpp_tests.sh [34] block ( S5k). .neu is accepted by gen/emit/translate/bundle (and the bundle
records the source path as metadata without it affecting the content sha256); the retired .finproc
alias is rejected by BOTH the gen entrypoint and the direct source->IR translate entrypoint (identical
bytes under a .finproc name are treated as textual MLIR and fail to parse, not silently aliased).

Usage: check_canonical_ext.py <neutrino-gen> <neutrino-emit> <neutrino-translate> <neutrino-bundle> <src.neu> <scenario.json>
"""
import os
import shutil
import subprocess
import sys
import tempfile

GEN, EMIT, TRANSLATE, BUNDLE, SRC, SCEN = sys.argv[1:7]
fails = []
tmp = tempfile.mkdtemp(prefix="canon34.")


def run(cmd, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run([str(c) for c in cmd], env=e,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


neu = os.path.join(tmp, "d0.neu")
shutil.copyfile(SRC, neu)

# .neu accepted by gen (slot), emit (events), translate (source->IR).
if run([GEN, "--target=slot", "--scenario=" + SCEN, neu, "-o", os.path.join(tmp, "d0_neu")]).returncode != 0:
    fails.append("slot gen did not accept .neu")
if b"Event choreography" not in run([EMIT, "--kind=events", neu]).stdout:
    fails.append("neutrino-emit did not accept .neu")
if run([TRANSLATE, neu, "-o", os.path.join(tmp, "d0.mlir")]).returncode != 0:
    fails.append("neutrino-translate did not accept .neu")

# bundle accepts source.neu and records the source path in bundle.json.
din = os.path.join(tmp, "d0in")
os.makedirs(din, exist_ok=True)
shutil.copyfile(neu, os.path.join(din, "source.neu"))
shutil.copyfile(SCEN, os.path.join(din, "scenario.json"))
open(os.path.join(din, "target.json"), "w").write('{ "targets": ["solidity"] }\n')
if run([BUNDLE, din, "-o", os.path.join(tmp, "d0out")], env={"NEUTRINO_GEN": GEN}).returncode != 0:
    fails.append("bundle did not accept source.neu")
else:
    bj = open(os.path.join(tmp, "d0out", "bundle.json")).read()
    if '"ok": true' not in bj:
        fails.append("source.neu bundle not ok")
    if "source.neu" not in bj:
        fails.append("bundle.json did not record the .neu source path")

# .finproc is no longer a recognized DSL source extension: gen AND translate must reject it rather than
# silently accept the byte-identical alias.
fp = os.path.join(tmp, "d0.finproc")
shutil.copyfile(SRC, fp)
if run([GEN, "--target=slot", "--scenario=" + SCEN, fp, "-o", os.path.join(tmp, "d0_fp")]).returncode == 0:
    fails.append(".finproc still accepted as a DSL source by gen (alias not removed)")
if run([TRANSLATE, fp, "-o", os.path.join(tmp, "d0_fp.mlir")]).returncode == 0:
    fails.append("neutrino-translate accepted a .finproc source (alias not removed)")

if fails:
    print("[34] canonical-extension contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[34] OK: .neu accepted by gen/emit/translate/bundle + recorded as source.neu; .finproc rejected "
      "by gen AND translate")
