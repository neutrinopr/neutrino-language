#!/usr/bin/env python3
"""[ C3 endpoint] Prohibit raw PgStmt procedure-statement authoring.

The raw `pgLine` / `PgStmt::rawLine` / `RawCap` / `PgStmt::Impl` seam is
deleted. Every production statement is a typed PgStmt whose fixed syntax is
owned by PostgresTargetNodes.td or a structured below-waist printer helper.

The trust anchor is construction-level: every PgStmt constructor reaches the
canonical constructor, whose kind initializer calls `ensureAuthorable`; that
predicate rejects the retired Kind::Line enum value regardless of spelling.
This scanner is defense in depth and gives early diagnostics for seam regrowth,
raw-kind references/casts, public factories, aggregate construction, mutation,
and detachment of the constructor guard. The only valid inventory is zero.
"""

import argparse
import json
import os
import re
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PG_DIR = os.path.join(REPO, "lib", "backends", "postgres")
INVENTORY = os.path.join(REPO, "scripts", "gates",
                         "postgres_syntax_authority_inventory.json")
SOURCE_EXT = (".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".inc")
EXCLUDED = {"PostgresDbTest.cpp"}

RAW_TOKEN = re.compile(
    r"\b(?:pgLine|rawLine|RawCap|PgStmtCtorProbe)\b|\bPgStmt\s*::\s*Impl\b")
PUBLIC_FACTORY = re.compile(r"\bPgStmt\s*::\s*line\b")
KIND_LINE = re.compile(r"(?:PgStmt\s*::\s*|(?<!::)\b)Kind\s*::\s*Line\b")
KIND_CAST = re.compile(
    r"(?:static_cast|reinterpret_cast)\s*<\s*(?:PgStmt\s*::\s*)?Kind\s*>")
AGGREGATE = re.compile(r"\bPgStmt\s*\{")
FIELD_MUTATION = re.compile(
    r"\b(?:s|stmt)\s*\.(?:kind|text|aux|aux2|flag|body|parts|operands|group)\s*=(?!=)")
CTOR_BIND = re.compile(r"[:,]\s*kind\s*\(")
CTOR_GUARDED = re.compile(r"[:,]\s*kind\s*\(\s*\(\s*ensureAuthorable\b")


def strip_comments_and_literals(src):
    """Return a same-line-shape lexical code view with comments/literals blank."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c in ('"', "'"):
            q = c
            out.append(" ")
            i += 1
            while i < n:
                if src[i] == "\\" and i + 1 < n:
                    out.extend("  ")
                    i += 2
                elif src[i] == q:
                    out.append(" ")
                    i += 1
                    break
                else:
                    out.append("\n" if src[i] == "\n" else " ")
                    i += 1
            continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                out.append(" ")
                i += 1
            continue
        if src.startswith("/*", i):
            out.extend("  ")
            i += 2
            while i < n and not src.startswith("*/", i):
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
            if i < n:
                out.extend("  ")
                i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def struct_body(src, name):
    """Return one named struct body from a comment/literal-stripped source."""
    match = re.search(r"\bstruct\s+" + re.escape(name) + r"\s*\{", src)
    if not match:
        return ""
    start = match.end() - 1
    depth = 0
    for pos in range(start, len(src)):
        if src[pos] == "{":
            depth += 1
        elif src[pos] == "}":
            depth -= 1
            if depth == 0:
                return src[start:pos + 1]
    return ""


def line_of(src, offset):
    return src.count("\n", 0, offset) + 1


def production_files(root):
    if os.path.isfile(root):
        return [root]
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {"test", "tests", "build", ".git"}]
        for name in files:
            if name.endswith(SOURCE_EXT) and name not in EXCLUDED:
                out.append(os.path.join(base, name))
    return sorted(out)


def scan(paths, require_endpoint=False):
    forbidden = []
    views = {}
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        view = strip_comments_and_literals(src)
        views[os.path.basename(path)] = view
        rel = os.path.relpath(path, REPO) if path.startswith(REPO) else path
        checks = (
            (RAW_TOKEN, "PROHIBITED raw PgStmt seam token"),
            (PUBLIC_FACTORY, "public PgStmt::line factory reintroduced — PROHIBITED"),
            (KIND_CAST, "cast to PgStmt::Kind is PROHIBITED (ordinal raw-kind bypass)"),
            (FIELD_MUTATION, "PgStmt field mutation is PROHIBITED"),
        )
        for regex, message in checks:
            for match in regex.finditer(view):
                forbidden.append(f"{rel}:{line_of(view, match.start())}: {message}")
        for match in AGGREGATE.finditer(view):
            if not re.search(r"\bstruct\s*$", view[max(0, match.start() - 20):match.start()]):
                forbidden.append(
                    f"{rel}:{line_of(view, match.start())}: "
                    "PgStmt aggregate/brace construction is PROHIBITED")

    # Kind::Line is allowed exactly once: inside ensureAuthorable's rejection.
    kind_sites = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            view = strip_comments_and_literals(fh.read())
        for match in KIND_LINE.finditer(view):
            kind_sites.append((path, view, match))
    for path, view, match in kind_sites:
        prefix = view[max(0, match.start() - 300):match.start()]
        if "void PgStmt::ensureAuthorable(Kind k)" not in prefix:
            forbidden.append(
                f"{path}:{line_of(view, match.start())}: PROHIBITED Kind::Line raw authoring")

    header = views.get("PostgresModel.h")
    model = views.get("PostgresModel.cpp")
    if header is not None:
        stmt = struct_body(header, "PgStmt")
        if re.search(r"\bfriend\b", stmt):
            forbidden.append(
                "PostgresModel.h: PgStmt constructor friendship is PROHIBITED; "
                "a namespace type could complete it in another TU")
        binds = len(CTOR_BIND.findall(stmt))
        guarded = len(CTOR_GUARDED.findall(stmt))
        if binds != 1 or guarded != 1:
            forbidden.append(
                "PostgresModel.h: canonical PgStmt constructor guard DETACHED "
                f"(kind bindings={binds}, ensureAuthorable bindings={guarded})")
        witness = len(re.findall(
            r"static\s+bool\s+rejectsAtConstructionForTest\s*\(\s*Kind\s+k\s*\)\s*;",
            stmt))
        if witness != 1:
            forbidden.append(
                "PostgresModel.h: constructor witness must be the single "
                "non-authoring bool(Kind) interface")
    if model is not None:
        guard_defs = len(re.findall(r"void\s+PgStmt\s*::\s*ensureAuthorable\s*\(", model))
        if guard_defs != 1 or len(kind_sites) != 1:
            forbidden.append(
                "PostgresModel.cpp: endpoint guard must define ensureAuthorable once "
                "and reject exactly one Kind::Line value")
    if require_endpoint and (header is None or model is None):
        forbidden.append("endpoint scan did not include PostgresModel.h and PostgresModel.cpp")
    return forbidden


def validate_inventory(path=INVENTORY):
    try:
        with open(path, encoding="utf-8") as fh:
            inv = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"inventory unreadable: {exc}"]
    errors = []
    if inv.get("kind") != "neutrino.postgres-syntax-authority.v2":
        errors.append("inventory kind must be endpoint v2")
    if inv.get("baseline") != 0 or inv.get("executable") != [] or inv.get("comments") != []:
        errors.append("endpoint inventory must have baseline=0, executable=[], comments=[]")
    if "implMembers" in inv:
        errors.append("endpoint inventory must not retain deleted Impl authority members")
    return errors


def run(paths, require_endpoint=False, check_inventory=False, quiet=False):
    errors = scan(paths, require_endpoint=require_endpoint)
    if check_inventory:
        errors.extend(validate_inventory())
    if errors:
        for error in errors:
            print(f"postgres-syntax-authority: {error}", file=sys.stderr)
        return 1
    if not quiet:
        print("postgres-syntax-authority: OK — 0 raw PgStmt authoring sites; "
              "legacy seam deleted and Kind::Line rejected at construction")
    return 0


def selftest(paths):
    if run(paths, require_endpoint=True, check_inventory=True, quiet=True):
        return 1
    with open(os.path.join(PG_DIR, "model", "PostgresModel.cpp"), encoding="utf-8") as fh:
        model = fh.read()
    with open(os.path.join(PG_DIR, "model", "PostgresModel.h"), encoding="utf-8") as fh:
        header = fh.read()
    probes = [
        (model + "\nvoid p(){ pgLine(cap, \"DROP TABLE x;\"); }\n", "raw seam"),
        (model + "\nvoid p(){ auto x = PgStmt::line(\"evil\"); }\n", "public factory"),
        (model + "\nvoid p(){ auto x = PgStmt{PgStmt::Kind::Blank}; }\n", "aggregate"),
        (model + "\nvoid p(PgStmt &s){ s.text = \"evil\"; }\n", "mutation"),
        (model + "\nvoid p(){ auto k = static_cast<PgStmt::Kind>(0); }\n", "ordinal cast"),
        (model + "\nvoid p(){ auto k = PgStmt::Kind::Line; }\n", "raw kind"),
        (model + "\nnamespace neutrino::postgres_model { struct "
         "PgStmtCtorProbe {}; }\n", "old friend completion"),
    ]
    for content, label in probes:
        with tempfile.NamedTemporaryFile("w", suffix=".cpp", delete=False) as tmp:
            tmp.write(content)
            name = tmp.name
        try:
            if run([name], quiet=True) == 0:
                print(f"postgres-syntax-authority selftest VACUOUS: accepted {label}", file=sys.stderr)
                return 1
        finally:
            os.unlink(name)
    with tempfile.TemporaryDirectory() as tmpdir:
        hp = os.path.join(tmpdir, "PostgresModel.h")
        cp = os.path.join(tmpdir, "PostgresModel.cpp")
        with open(hp, "w", encoding="utf-8") as fh:
            fh.write(header.replace("kind((ensureAuthorable(k), k))", "kind(k)"))
        with open(cp, "w", encoding="utf-8") as fh:
            fh.write(model)
        if run([hp, cp], quiet=True) == 0:
            print("postgres-syntax-authority selftest VACUOUS: accepted detached ctor", file=sys.stderr)
            return 1
    with tempfile.TemporaryDirectory() as tmpdir:
        hp = os.path.join(tmpdir, "PostgresModel.h")
        cp = os.path.join(tmpdir, "PostgresModel.cpp")
        with open(hp, "w", encoding="utf-8") as fh:
            fh.write(header.replace(
                "private:\n  PgStmt(Kind k,",
                "private:\n  friend struct AnyExternalAuthor;\n  PgStmt(Kind k,", 1))
        with open(cp, "w", encoding="utf-8") as fh:
            fh.write(model)
        if run([hp, cp], quiet=True) == 0:
            print("postgres-syntax-authority selftest VACUOUS: accepted constructor friend",
                  file=sys.stderr)
            return 1
    print("postgres-syntax-authority: selftest OK (zero endpoint + seam/kind/cast/ctor probes)")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cpp")
    parser.add_argument("--dir")
    parser.add_argument("--emit", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    root = args.cpp or args.dir or PG_DIR
    paths = production_files(root)
    if args.emit:
        print(json.dumps({"baseline": 0, "executable": [], "comments": []}, indent=2))
        return 0
    if args.selftest:
        return selftest(production_files(PG_DIR))
    return run(paths, require_endpoint=not (args.cpp or args.dir),
               check_inventory=not (args.cpp or args.dir))


if __name__ == "__main__":
    sys.exit(main())
