"""[37] full language-intelligence contract for neutrino_lang.py (compiler-emitted metadata + parser
diagnostics). Ported verbatim from the retired run_cpp_tests.sh [37] block ( S5j). The lit driver
handles the committed-doc byte-match; this helper covers everything the shell block did beyond it:

  metadata content; the Python tool CONSUMES the compiler metadata (no grammar re-derivation);
  example-grammar drift; fail-closed when ANY required compiler-owned field is dropped (metadata
  rejects + completions -> ok:false + completions.no_metadata, table-driven over the required set);
  wrong `kind` rejected (artifact identity, not just fields); diagnostics: valid -> none, a known-bad
  source -> a stable coded diagnostic, a duplicate -> parse.duplicate_name; and a translator EXECUTION
  failure -> a translate.failed diagnostic, never ok:false with an empty list.

Usage: check_language_metadata.py <neutrino-translate> <neutrino_lang.py> <examples-dir> <ir-test-dir> <sponsored-offer-src>
"""
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

TRANSLATE, LANG, EXAMPLES, IRDIR, OK_SRC = sys.argv[1:6]


def run(*cmd, env=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run([str(c) for c in cmd], env=e,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)


def lang_json(*args, env=None):
    r = run(sys.executable, LANG, *args, env=env)
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip() else None)


fails = []
tmp = tempfile.mkdtemp(prefix="lang37.")

# The compiler-emitted metadata (the source of truth the Python tool must consume).
comp = json.loads(run(TRANSLATE, "--language-metadata").stdout)
comp_path = os.path.join(tmp, "compiler.json")
json.dump(comp, open(comp_path, "w"), indent=2, sort_keys=True)

# metadata: versioned; canonical .neu, no legacy; // and # comments; core keywords/types.
_, m = lang_json("metadata")
if not (m and m["schemaVersion"] == 2 and m["canonicalExtension"] == ".neu"
        and m["legacyExtensions"] == [] and "//" in m["lineComments"] and "#" in m["lineComments"]
        and m["stringDelimiters"] == ['"']
        and {"procedure", "participant", "debit", "assert"} <= set(m["keywords"])
        and {"money", "party", "decimal"} <= set(m["valueTypes"])):
    fails.append("language metadata content")

# drift: every compiler-owned grammar field matches byte-for-byte (Python adds presentation only).
for k in ("keywords", "keywordCategories", "valueTypes", "operators", "functions", "language",
          "canonicalExtension", "legacyExtensions", "lineComments", "blockComment",
          "blockDelimiters", "stringDelimiters", "schemaVersion", "kind"):
    if (m or {}).get(k) != comp.get(k):
        fails.append(f"neutrino_lang.py metadata diverges from the compiler (field: {k})")

# example-grammar drift: every leading token + `field =` name in the committed examples is covered.
kw, vt, lead, fields = set(m["keywords"]), set(m["valueTypes"]), set(), set()
for f in glob.glob(EXAMPLES + "/**/*.neu", recursive=True):
    for line in open(f, encoding="utf-8", errors="replace"):
        a = re.match(r"\s*([a-z_]+)", line)
        if a:
            lead.add(a.group(1))
        b = re.match(r"\s*([a-z_]+)\s*=", line)
        if b:
            fields.add(b.group(1))
if (lead - (kw | vt)) or (fields - kw):
    fails.append("language metadata drifted from the example grammar")

# fail-closed: dropping ANY required compiler-owned field makes the file unconsumable — metadata
# exits non-zero AND completions -> ok:false + completions.no_metadata (table-driven,  N2).
for field in ("keywords", "keywordCategories", "valueTypes", "operators", "functions"):
    dropped = os.path.join(tmp, f"no_{field}.json")
    d = dict(comp)
    d.pop(field, None)
    json.dump(d, open(dropped, "w"), indent=2, sort_keys=True)
    env = {"NEUTRINO_LANGUAGE_METADATA": dropped}
    if run(sys.executable, LANG, "metadata", env=env).returncode == 0:
        fails.append(f"metadata consumed a file missing compiler-owned '{field}' (should fail closed)")
    _, c = lang_json("completions", env=env)
    if not (c and c["ok"] is False and c["completions"] == []
            and c["diagnostics"][0]["code"] == "completions.no_metadata"):
        fails.append(f"completions did not fail closed on metadata missing '{field}'")

# fail-closed: wrong/missing `kind` (artifact identity, not just the field set).
bad_kind = os.path.join(tmp, "bad_kind.json")
d = dict(comp)
d["kind"] = "something.else"
json.dump(d, open(bad_kind, "w"), indent=2, sort_keys=True)
if run(sys.executable, LANG, "metadata", env={"NEUTRINO_LANGUAGE_METADATA": bad_kind}).returncode == 0:
    fails.append("metadata consumed a file whose kind is not neutrino.language-metadata")

# diagnostics: a valid .neu -> ok:true, no diagnostics.
_, ok = lang_json("diagnostics", OK_SRC, "--translate", TRANSLATE)
if not (ok and ok["ok"] and ok["diagnostics"] == []):
    fails.append("valid .neu reported diagnostics")

# diagnostics: a known-bad file -> a stable code + severity + line range.
_, bad = lang_json("diagnostics", os.path.join(IRDIR, "neg_missing_field.neu"), "--translate", TRANSLATE)
g = (bad or {}).get("diagnostics", [{}])[0]
if not (bad and bad["ok"] is False and g.get("code") == "parse.missing_field"
        and g.get("severity") == "error" and g.get("range", {}).get("start", {}).get("line") == 6):
    fails.append("parser diagnostic not structured as expected (parse.missing_field)")

_, dup = lang_json("diagnostics", os.path.join(IRDIR, "neg_duplicate_input.neu"), "--translate", TRANSLATE)
if not (dup and any(x.get("code") == "parse.duplicate_name" for x in dup.get("diagnostics", []))):
    fails.append("duplicate-name diagnostic code (parse.duplicate_name) missing")

# a translator EXECUTION failure must surface translate.failed, not ok:false with an empty list.
fake = os.path.join(tmp, "fake_translate.sh")
open(fake, "w").write('#!/bin/sh\necho "internal error: boom" >&2\nexit 2\n')
os.chmod(fake, 0o755)
_, fl = lang_json("diagnostics", OK_SRC, "--translate", fake)
if not (fl and fl["ok"] is False and len(fl["diagnostics"]) >= 1
        and fl["diagnostics"][0]["code"] == "translate.failed"):
    fails.append("translator failure returned ok:false with empty/wrong diagnostics (want translate.failed)")

if fails:
    print("[37] language-metadata contract FAILED:", file=sys.stderr)
    for f in fails:
        print("    FAIL: " + f, file=sys.stderr)
    sys.exit(1)
print("[37] OK: metadata consumed (no divergence); example-grammar drift guard; dropping any required "
      "field + wrong kind fail closed; diagnostics valid->none / bad->coded / exec-fail->translate.failed")
