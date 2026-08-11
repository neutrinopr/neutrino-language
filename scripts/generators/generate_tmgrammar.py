#!/usr/bin/env python3
"""Generate the .neu TextMate grammar from the compiler-owned LanguageMetadata ().

The grammar (docs/neutrino.tmLanguage.json) is DERIVED from docs/language-metadata.json
— itself emitted by `neutrino-translate --language-metadata` (source lib/LanguageMetadata.cpp).
The keyword/type/operator/function vocabulary and the comment/string delimiters all come
from the compiler; this script owns only PRESENTATION — the category -> TextMate scope map
and the regex assembly — never a grammar list of its own (M5 Python Boundary Policy, D10).
So this is the single generated `.neu` grammar surface for VS Code / Linguist / the console:
no hand-written second grammar, no surface-specific fork.

Fail-closed: a metadata token KIND/category with no scope mapping here aborts generation
(a new keyword category / comment marker / operator kind must be given a scope), so the
grammar can never silently fall behind the compiler.

Usage:
  generate_tmgrammar.py                  # print the grammar JSON (from the committed metadata)
  generate_tmgrammar.py --metadata FILE  # generate from a specific metadata file (tests)
  generate_tmgrammar.py --check          # drift gate: regenerate + byte-match the committed
                                         # grammar, token coverage, and fixture coverage; fail-closed
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
METADATA = os.path.join(REPO, "docs", "language-metadata.json")
GRAMMAR = os.path.join(REPO, "docs", "neutrino.tmLanguage.json")
FIXTURE = os.path.join(REPO, "test", "grammar", "neutrino_grammar_fixture.neu")

SCOPE = "source.neutrino"

# PRESENTATION only (D10): how each compiler-owned token category maps to a TextMate scope.
# A category present in the metadata but absent here fails closed in build_grammar().
KEYWORD_CATEGORY_SCOPES = {
    "statement": "keyword.control.neutrino",
    "field": "variable.other.property.neutrino",
    "connector": "keyword.operator.word.neutrino",
}
COMMENT_SCOPES = {
    "//": "comment.line.double-slash.neutrino",
    "#": "comment.line.number-sign.neutrino",
}
BLOCK_COMMENT_SCOPE = "comment.block.neutrino"
OPERATOR_KIND_SCOPES = {
    "binary": "keyword.operator.arithmetic.neutrino",
    "comparison": "keyword.operator.comparison.neutrino",
}
VALUE_TYPE_SCOPE = "storage.type.neutrino"
FUNCTION_SCOPE = "support.function.neutrino"
STRING_SCOPE = "string.quoted.double.neutrino"
REFERENCE_SCOPE = "variable.other.reference.neutrino"
NUMBER_SCOPE = "constant.numeric.neutrino"


def _fail(msg):
    print(f"generate_tmgrammar: {msg}", file=sys.stderr)
    sys.exit(1)


def load_metadata(path):
    try:
        m = json.load(open(path))
    except (OSError, ValueError) as e:
        _fail(f"cannot read language metadata {path}: {e}")
    if not isinstance(m, dict) or m.get("kind") != "neutrino.language-metadata":
        _fail(f"{path} is not neutrino.language-metadata")
    return m


def _alt(words):
    # a longest-first, regex-escaped alternation so multi-char operators (<=, ==) win over
    # their prefixes; deterministic (stable sort by length then value).
    return "|".join(re.escape(w) for w in sorted(set(words), key=lambda w: (-len(w), w)))


def _word_rule(scope, words):
    return {"name": scope, "match": r"\b(" + _alt(words) + r")\b"}


def build_grammar(m):
    """The compiler metadata -> a TextMate grammar dict. Fail-closed on an unmapped kind."""
    repo = {}
    top = []

    # comments (from metadata.lineComments + blockComment) — every compiler-owned comment
    # delimiter must produce a rule, so a future delimiter can't silently fall behind.
    comment_patterns = []
    # block comment: null (none, as .neu today) or a [begin, end] pair; anything else fails closed.
    bc = m.get("blockComment")
    if bc is not None:
        if not (isinstance(bc, list) and len(bc) == 2 and all(isinstance(x, str) for x in bc)):
            _fail(f"unsupported blockComment {bc!r}: expected null or a [begin, end] pair")
        comment_patterns.append(
            {"name": BLOCK_COMMENT_SCOPE, "begin": re.escape(bc[0]), "end": re.escape(bc[1])})
    for marker in m.get("lineComments", []):
        scope = COMMENT_SCOPES.get(marker)
        if not scope:
            _fail(f"no grammar scope for line-comment marker {marker!r}")
        comment_patterns.append({"name": scope, "match": re.escape(marker) + r".*$"})
    if comment_patterns:
        repo["comments"] = {"patterns": comment_patterns}
        top.append({"include": "#comments"})

    # strings (from metadata.stringDelimiters) — begin/end pairs.
    string_patterns = []
    for d in m.get("stringDelimiters", []):
        string_patterns.append({"name": STRING_SCOPE, "begin": re.escape(d), "end": re.escape(d)})
    if string_patterns:
        repo["strings"] = {"patterns": string_patterns}
        top.append({"include": "#strings"})

    # %-prefixed references to a declared input / computed value (a fixed .neu lexical sigil).
    repo["references"] = {"name": REFERENCE_SCOPE, "match": r"%[A-Za-z_][A-Za-z0-9_]*"}
    top.append({"include": "#references"})

    # keyword categories (from metadata.keywordCategories) — fail closed on an unmapped category.
    for category, words in m.get("keywordCategories", {}).items():
        scope = KEYWORD_CATEGORY_SCOPES.get(category)
        if not scope:
            _fail(f"no grammar scope for keyword category {category!r}")
        if words:
            key = f"keywords-{category}"
            repo[key] = _word_rule(scope, words)
            top.append({"include": "#" + key})

    # value types (from metadata.valueTypes).
    if m.get("valueTypes"):
        repo["value-types"] = _word_rule(VALUE_TYPE_SCOPE, m["valueTypes"])
        top.append({"include": "#value-types"})

    # functions (from metadata.functions).
    fn_names = [f["name"] for f in m.get("functions", [])]
    if fn_names:
        repo["functions"] = _word_rule(FUNCTION_SCOPE, fn_names)
        top.append({"include": "#functions"})

    # operators (from metadata.operators) — grouped by kind, each kind needs a scope.
    op_by_kind = {}
    for op in m.get("operators", []):
        kind = op.get("kind")
        if kind not in OPERATOR_KIND_SCOPES:
            _fail(f"no grammar scope for operator kind {kind!r}")
        op_by_kind.setdefault(kind, []).append(op["symbol"])
    for kind in sorted(op_by_kind):
        key = f"operators-{kind}"
        repo[key] = {"name": OPERATOR_KIND_SCOPES[kind], "match": "(" + _alt(op_by_kind[kind]) + ")"}
        top.append({"include": "#" + key})

    # numbers — minor-unit integer literals (a fixed lexical kind).
    repo["numbers"] = {"name": NUMBER_SCOPE, "match": r"\b[0-9]+\b"}
    top.append({"include": "#numbers"})

    return {
        "$schema": "https://raw.githubusercontent.com/martinring/tmlanguage/master/tmlanguage.json",
        "name": "Neutrino",
        "scopeName": SCOPE,
        "fileTypes": [m.get("canonicalExtension", ".neu").lstrip(".")],
        "patterns": top,
        "repository": repo,
    }


def render(m):
    return json.dumps(build_grammar(m), indent=2, ensure_ascii=False) + "\n"


# ---- drift gate ---------------------------------------------------------------

def _all_grammar_matches(grammar):
    """Every regex `match`/`begin` string in the grammar repository (for coverage checks)."""
    out = []
    for rule in grammar.get("repository", {}).values():
        for r in ([rule] if "patterns" not in rule else rule["patterns"]):
            if "match" in r:
                out.append(r["match"])
            if "begin" in r:
                out.append(r["begin"])
    return out


def check():
    m = load_metadata(METADATA)
    text = render(m)
    grammar = json.loads(text)

    # 1. STALE artifact: the committed grammar must byte-match a fresh regeneration.
    if not os.path.exists(GRAMMAR):
        _fail(f"committed grammar {GRAMMAR} is missing (run generate_tmgrammar.py > it)")
    committed = open(GRAMMAR).read()
    if committed != text:
        _fail("docs/neutrino.tmLanguage.json is STALE — regenerate: "
              "python3 scripts/generators/generate_tmgrammar.py > docs/neutrino.tmLanguage.json")

    # 2. TOKEN COVERAGE: every compiler-owned token must appear in some grammar rule.
    blob = "\n".join(_all_grammar_matches(grammar))
    missing = []
    for w in m.get("keywords", []):
        if not re.search(r"(?<![A-Za-z0-9_])" + re.escape(w) + r"(?![A-Za-z0-9_])", blob):
            missing.append(("keyword", w))
    for t in m.get("valueTypes", []):
        if re.escape(t) not in blob:
            missing.append(("valueType", t))
    for op in m.get("operators", []):
        if re.escape(op["symbol"]) not in blob:
            missing.append(("operator", op["symbol"]))
    for f in m.get("functions", []):
        if re.escape(f["name"]) not in blob:
            missing.append(("function", f["name"]))
    if missing:
        _fail("grammar rule missing for compiler token(s): "
              + ", ".join(f"{k}:{v}" for k, v in missing))

    # 3. FIXTURE: non-empty, and it exercises every highlightable metadata category — so it can
    #    neither rot to empty nor drift away from the vocabulary it is supposed to demonstrate.
    if not os.path.exists(FIXTURE):
        _fail(f"grammar fixture {FIXTURE} is missing")
    src = open(FIXTURE).read()
    if not src.strip():
        _fail("grammar fixture is empty")
    scanned = 0
    for pat in _all_grammar_matches(grammar):
        scanned += len(re.findall(pat, src, flags=re.MULTILINE))
    if scanned == 0:
        _fail("grammar fixture scan matched no tokens (empty scan)")
    fixture_missing = []
    for t in m.get("valueTypes", []):
        if not re.search(r"\b" + re.escape(t) + r"\b", src):
            fixture_missing.append(("valueType", t))
    for category, words in m.get("keywordCategories", {}).items():
        if words and not any(re.search(r"\b" + re.escape(w) + r"\b", src) for w in words):
            fixture_missing.append(("keywordCategory", category))
    for kind, examples in {"string": [r'"'], "reference": [r"%[A-Za-z_]"],
                           "number": [r"\b[0-9]+\b"], "comment": [r"//", r"#"]}.items():
        if not any(re.search(p, src, flags=re.MULTILINE) for p in examples):
            fixture_missing.append(("kind", kind))
    if fixture_missing:
        _fail("grammar fixture does not exercise: "
              + ", ".join(f"{k}:{v}" for k, v in fixture_missing))

    print(f"neu-grammar OK: generated from {os.path.basename(METADATA)}; committed grammar "
          f"byte-matches; every keyword/type/operator/function has a rule; fixture exercises "
          f"{scanned} tokens across all categories")


def main():
    ap = argparse.ArgumentParser(description="Generate the .neu TextMate grammar from LanguageMetadata")
    ap.add_argument("--metadata", default=METADATA, help="language-metadata.json to generate from")
    ap.add_argument("--check", action="store_true", help="drift gate (byte-match + coverage + fixture)")
    args = ap.parse_args()
    if args.check:
        check()
    else:
        sys.stdout.write(render(load_metadata(args.metadata)))


if __name__ == "__main__":
    main()
