#!/usr/bin/env python3
"""Catalog ↔ registry reconciliation gate (M5  / ).

`docs/backends/BACKEND_TARGET_CATALOG.md` calls `include/Neutrino/TargetRegistry.def` the authoritative
target list, but nothing mechanically ties the catalog's generator-targets table to it — docs CI only
checks links. So a target added to the `.def` (or a `gated`/`scenarioFree` flag flipped) could silently
drift the catalog again. This gate makes the catalog's "reviewed against the registry" claim a durable
"must not drift" one by reconciling the two:

  - NAME coverage: every `.def` target has a catalog row and vice-versa. `oracle-observer` is the one
    allowed exception — a deliberately non-registry `--from-spec --binding` target — so it must appear
    in the catalog but NOT in the `.def` (if it ever becomes a registry row, both this gate and the
    catalog must be updated deliberately).
  - CLASSIFICATION: each registry row's `Gating · scenario` cell (`gated`/`non-gated`,
    `scenario`/`scenario-free`) matches the `.def` row's `Gated`/`ScenarioFree` columns exactly.
  - the `oracle-observer` row must stay marked `outside registry gating` (it has no `TargetSpec`, so no
    gated/scenarioFree to match — the catalog must not silently reclassify it as a normal gated target).

Fail-closed / non-vacuous: if the `.def` yields fewer than FLOOR targets, or the catalog's
generator-targets table can't be located / parsed to at least FLOOR rows, the gate FAILS rather than
passing on an empty reconciliation.

    check_catalog_registry.py [--selftest]

Exit: 0 = reconciled; 1 = drift; 2 = fail-closed (parse/floor).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEF_PATH = os.path.join(REPO, "include", "Neutrino", "TargetRegistry.def")
CATALOG_PATH = os.path.join(REPO, "docs", "backends", "BACKEND_TARGET_CATALOG.md")

# The one target that is deliberately NOT a registry row (a --from-spec --binding path handled directly
# in neutrino-gen); it must be a catalog row but absent from the .def.
SPECIAL = "oracle-observer"
EXTERNAL = {"solidity": (True, False)}
FLOOR = 8  # the registry has ~10 targets; a smaller parse means the format moved — fail closed.

_DEF_ORDINARY_RX = re.compile(
    r'NEUTRINO_TARGET\("([^"]+)",\s*\w+,\s*/\*gated=\*/(true|false),\s*/\*scenarioFree=\*/(true|false)\)')
_DEF_DRIVER_RX = re.compile(
    r'NEUTRINO_TARGET_DRIVER\("([^"]+)",\s*/\*gated=\*/(true|false),\s*/\*scenarioFree=\*/(true|false)\)')
# A catalog table data row: | `name` | ... | ... . The generator-targets table's header cell is
# `--target`; the module-map table's header is also `--target`, so we anchor on the "Gating" header.
_ROW_RX = re.compile(r'^\|\s*`([a-z][a-z-]*)`\s*\|(.*)$')


def parse_def(text):
    """({name: (gated, scenarioFree)}, [duplicate names]) from the declarative registry. Duplicates are
    surfaced (not last-wins collapsed) so a contradictory double declaration fails closed."""
    out, dups, seen = {}, [], set()
    rows = [
        (match.start(), match.groups())
        for row_rx in (_DEF_ORDINARY_RX, _DEF_DRIVER_RX)
        for match in row_rx.finditer(text)
    ]
    for _offset, (name, gated, sf) in sorted(rows):
        if name in seen and name not in dups:
            dups.append(name)
        seen.add(name)
        out[name] = (gated == "true", sf == "true")
    return out, sorted(dups)


def parse_catalog(text):
    """(({name: gating_cell} | None), [duplicate names]) from the generator-targets table (the one with
    a 'Gating' header). None map = table not found (fail closed). Duplicates are surfaced, not collapsed."""
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("|") and "`--target`" in ln and "Gating" in ln:
            start = i
            break
    if start is None:
        return None, []  # table not found -> fail closed
    rows, dups, seen = {}, [], set()
    for ln in lines[start + 1:]:
        if not ln.lstrip().startswith("|"):
            break  # end of the table
        if set(ln.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
            continue  # the |---|---| separator row
        m = _ROW_RX.match(ln)
        if not m:
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        # cells[0] = `name`, cells[2] = the Gating · scenario cell.
        if len(cells) < 3:
            continue
        name = m.group(1)
        if name in seen and name not in dups:
            dups.append(name)
        seen.add(name)
        rows[name] = cells[2]
    return rows, sorted(dups)


def classify_cell(cell):
    """(gated, scenarioFree, special) from a 'Gating · scenario' cell. gated/scenarioFree are None when
    special (oracle-observer)."""
    norm = cell.replace("**", "").replace("`", "").lower()
    if "outside registry gating" in norm:
        return (None, None, True)
    gated = None
    if "non-gated" in norm:
        gated = False
    elif "gated" in norm:
        gated = True
    # check scenario-free BEFORE scenario (the former contains the latter as a substring).
    if "scenario-free" in norm:
        sf = True
    elif "scenario" in norm:
        sf = False
    else:
        sf = None
    return (gated, sf, False)


def reconcile(def_parsed, cat_parsed):
    """Return a list of problem strings ([] = reconciled). Args are (map, duplicates) pairs from the
    parsers."""
    def_map, def_dups = def_parsed
    cat_map, cat_dups = cat_parsed
    problems = []
    # Duplicate/contradictory declarations are a malformed inventory — fail closed, never last-wins.
    for name in def_dups:
        problems.append(f"[fail-closed:duplicate] TargetRegistry.def declares '{name}' more than once — "
                        "an ambiguous registry (runtime lookup/list semantics are undefined)")
    for name in cat_dups:
        problems.append(f"[fail-closed:duplicate] the catalog generator-targets table has more than one "
                        f"'{name}' row — an ambiguous inventory (a reader can see a stale first row)")
    if def_map is None or len(def_map) < FLOOR:
        problems.append(f"[fail-closed] parsed only {0 if def_map is None else len(def_map)} registry "
                        f"targets from TargetRegistry.def (floor {FLOOR}) — the .def format moved")
        return problems
    if cat_map is None:
        problems.append("[fail-closed] could not locate the generator-targets table in the catalog "
                        "(no `--target` + `Gating` header row)")
        return problems
    if len(cat_map) < FLOOR:
        problems.append(f"[fail-closed] parsed only {len(cat_map)} catalog target rows (floor {FLOOR}) "
                        "— the table format moved")
        return problems

    def_names, cat_names = set(def_map), set(cat_map)
    for name in sorted(def_names - cat_names):
        problems.append(f"[missing-row] registry target '{name}' has no row in the catalog table")
    for name in sorted(cat_names - def_names - {SPECIAL} - set(EXTERNAL)):
        problems.append(f"[orphan-row] catalog row '{name}' is not a registry target (and is not the "
                        f"'{SPECIAL}' special case)")
    if SPECIAL not in cat_names:
        problems.append(f"[missing-special] the '{SPECIAL}' row is gone from the catalog — the special "
                        "--from-spec --binding target must stay documented")
    if SPECIAL in def_names:
        problems.append(f"[special-registered] '{SPECIAL}' is now a TargetRegistry.def row; update this "
                        "gate + the catalog's special-case prose deliberately")
    for name, expected in sorted(EXTERNAL.items()):
        if name not in cat_names:
            problems.append(
                f"[missing-external] extracted package target '{name}' has no "
                "catalog row")
            continue
        got_gated, got_sf, special = classify_cell(cat_map[name])
        if special or (got_gated, got_sf) != expected:
            problems.append(
                f"[classification] external package '{name}' catalog "
                f"classification does not match gated={expected[0]}, "
                f"scenarioFree={expected[1]}")
        if name in def_names:
            problems.append(
                f"[external-registered] extracted package target '{name}' "
                "must not return to TargetRegistry.def")

    for name in sorted(def_names & cat_names):
        want_gated, want_sf = def_map[name]
        got_gated, got_sf, special = classify_cell(cat_map[name])
        if special:
            problems.append(f"[classification] '{name}' is a registry target but the catalog marks it "
                            "'outside registry gating' — that phrase is reserved for the special case")
            continue
        if got_gated != want_gated:
            problems.append(f"[classification] '{name}': catalog says "
                            f"{'gated' if got_gated else 'non-gated' if got_gated is not None else '?'}, "
                            f".def says gated={want_gated}")
        if got_sf != want_sf:
            problems.append(f"[classification] '{name}': catalog says "
                            f"{'scenario-free' if got_sf else 'scenario' if got_sf is not None else '?'}, "
                            f".def says scenarioFree={want_sf}")

    if SPECIAL in cat_map:
        _g, _s, special = classify_cell(cat_map[SPECIAL])
        if not special:
            problems.append(f"[special-reclassified] the '{SPECIAL}' row no longer reads 'outside "
                            "registry gating' — it must not be documented as a normal gated target")
    return problems


def run(def_text, cat_text):
    problems = reconcile(parse_def(def_text), parse_catalog(cat_text))
    if problems:
        print("catalog↔registry gate FAILED:", file=sys.stderr)
        for p in problems:
            print("    " + p, file=sys.stderr)
        return 2 if any("fail-closed" in p for p in problems) else 1
    n = len(parse_def(def_text)[0])
    print(f"catalog↔registry OK: all {n} registry targets + the '{SPECIAL}' special case reconciled "
          "with the catalog (names + gated/scenario classification)")
    return 0


def selftest():
    """Prove the reconciliation bites: the real tree passes; a missing row, an orphan row, a flipped
    gated flag, a flipped scenario-free flag, a dropped/reclassified special, and an unparseable
    catalog each fail closed."""
    import contextlib
    import io

    def quiet_run(dtext, ctext):
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            return run(dtext, ctext)

    real_def = open(DEF_PATH, encoding="utf-8").read()
    real_cat = open(CATALOG_PATH, encoding="utf-8").read()
    fails = []
    if quiet_run(real_def, real_cat) != 0:
        fails.append("the real tree does not reconcile")

    # A minimal synthetic pair (>= FLOOR rows) we can mutate one axis at a time.
    names = ["solidity", "postgres", "slot", "capability-spec", "coordination-plan",
             "test-realization", "capability", "coverage", "security", "views"]
    dfl = {"postgres": (True, False), "slot": (True, True),
           "capability-spec": (False, True), "coordination-plan": (False, True),
           "test-realization": (False, False), "capability": (False, False),
           "coverage": (False, False), "security": (False, False), "views": (True, True)}
    catalog_dfl = {"solidity": EXTERNAL["solidity"], **dfl}

    def mk_def(d):
        return "\n".join(
            (f'NEUTRINO_TARGET_DRIVER("{n}", /*gated=*/{str(g).lower()}, '
             f'/*scenarioFree=*/{str(s).lower()})'
             if n == "coordination-plan" else
             f'NEUTRINO_TARGET("{n}", emitX, /*gated=*/{str(g).lower()}, '
             f'/*scenarioFree=*/{str(s).lower()})')
            for n, (g, s) in d.items())

    def cell(g, s):
        return ("gated" if g else "non-gated") + " · " + ("scenario-free" if s else "scenario")

    def mk_cat(d, extra_rows=""):
        head = "| `--target` | Emits | Gating · scenario | Maturity | Entry |\n|---|---|---|---|---|\n"
        body = "".join(f"| `{n}` | out | {cell(g, s)} | CI-gated | make {n} |\n" for n, (g, s) in d.items())
        special = ("| `oracle-observer` | js | **outside registry gating** · `--from-spec` only "
                   "| CI-gated | neutrino-gen |\n")
        return head + body + special + extra_rows

    def bites(name, dtext, ctext, code=1):
        if quiet_run(dtext, ctext) != code:
            fails.append(f"{name}: expected exit {code}, gate did not fail as required")

    # baseline synthetic pair reconciles.
    if quiet_run(mk_def(dfl), mk_cat(catalog_dfl)) != 0:
        fails.append("the synthetic baseline pair does not reconcile")
    # The driver-serialized row participates in the same authoritative
    # classification: dropping it or changing either flag must bite.
    driver_missing = {k: v for k, v in dfl.items() if k != "coordination-plan"}
    bites("missing-driver-row", mk_def(driver_missing), mk_cat(catalog_dfl))
    driver_flip = dict(dfl)
    driver_flip["coordination-plan"] = (True, True)
    bites("misclassified-driver-row", mk_def(driver_flip), mk_cat(catalog_dfl))
    # (a) a registry target missing its catalog row.
    d2 = dict(dfl); c = mk_cat({
        k: v for k, v in catalog_dfl.items() if k != "coverage"})
    bites("missing-row", mk_def(d2), c)
    # (b) an orphan catalog row not in the .def (and not the special).
    bites("orphan-row", mk_def(dfl), mk_cat(
        catalog_dfl,
        extra_rows="| `phantom` | out | gated · scenario | x | y |\n"))
    # (c) flipped gated flag: .def gated=True, catalog says non-gated.
    external_flip = dict(catalog_dfl)
    external_flip["solidity"] = (False, False)
    bites("flip-gated", mk_def(dfl), mk_cat(external_flip))
    # (d) flipped scenario-free: .def scenarioFree=True, catalog says scenario.
    dflip2 = dict(dfl); dflip2["slot"] = (True, False)
    bites("flip-sf", mk_def(dflip2), mk_cat(catalog_dfl))
    # (e) the special row dropped from the catalog.
    head = "| `--target` | Emits | Gating · scenario | M | E |\n|---|---|---|---|---|\n"
    body = "".join(
        f"| `{n}` | o | {cell(*catalog_dfl[n])} | c | e |\n"
        for n in names)
    bites("missing-special", mk_def(dfl), head + body)
    # (f) the special reclassified as a normal gated target.
    recl = mk_cat(catalog_dfl).replace(
        "**outside registry gating** · `--from-spec` only", "gated · scenario")
    bites("special-reclassified", mk_def(dfl), recl)
    # (g) fail-closed: an unparseable catalog (no header) -> exit 2.
    bites("no-table", mk_def(dfl), "# catalog with no target table\n", code=2)
    # (h) fail-closed: a duplicated + contradictory catalog row (last-wins would hide it) -> exit 2.
    dup_cat = mk_cat(catalog_dfl).replace(
        "| `solidity` | out | gated · scenario | CI-gated | make solidity |\n",
        "| `solidity` | out | non-gated · scenario | CI-gated | make solidity |\n"
        "| `solidity` | out | gated · scenario | CI-gated | make solidity |\n")
    bites("dup-catalog", mk_def(dfl), dup_cat, code=2)
    # (i) fail-closed: a duplicated + contradictory registry row -> exit 2.
    dup_def = mk_def(dfl) + '\nNEUTRINO_TARGET("postgres", emitX, /*gated=*/false, /*scenarioFree=*/false)\n'
    bites("dup-registry", dup_def, mk_cat(catalog_dfl), code=2)

    if fails:
        print("catalog↔registry SELFTEST FAILED:", file=sys.stderr)
        for f in fails:
            print("    FAIL: " + f, file=sys.stderr)
        return 1
    print("catalog↔registry selftest PASS (real tree reconciles; a missing or misclassified "
          "driver row, missing row, orphan row, flipped gated, flipped scenario-free, dropped "
          "special, reclassified special, an unparseable catalog, and a duplicated/contradictory "
          "catalog OR registry row all fail closed)")
    return 0


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    if not os.path.isfile(DEF_PATH) or not os.path.isfile(CATALOG_PATH):
        print("catalog↔registry gate: missing TargetRegistry.def or BACKEND_TARGET_CATALOG.md",
              file=sys.stderr)
        return 2
    return run(open(DEF_PATH, encoding="utf-8").read(), open(CATALOG_PATH, encoding="utf-8").read())


if __name__ == "__main__":
    sys.exit(main())
