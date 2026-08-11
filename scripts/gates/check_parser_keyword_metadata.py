#!/usr/bin/env python3
"""Parser keyword vocabulary boundary ().

Parser-recognized language keywords and field keys are defined ONCE in
`include/Neutrino/LanguageVocabulary.def`. Both consumers expand that table:

  * frontend recognition — only through the approved helpers in
    `LanguageVocabulary.h` (`matchKeywordPrefix` / `lineStartsWithKeyword` /
    `tokenIsKeyword` / `consumeVocabKeyword` / `lineContainsKeywordWord` /
    `vocabSpelling`);
  * `languageMetadataJson()` in `lib/LanguageMetadata.cpp`.

This gate establishes that metadata is definitionally identical to the
parser-recognized surface — not merely that the .def equals the committed JSON:

  * FAIL `vocab.metadata_mismatch` — docs/language-metadata.json keywords or
    keywordCategories do not equal the .def table.
  * FAIL `vocab.unused` — a .def EnumId is never passed to an approved recognition
    helper in the frontend (a mere `VocabId::X` mention does not count; a new
    row + regenerated metadata without helper-mediated recognition fails).
  * FAIL `vocab.orphan_use` — an approved helper is passed `VocabId::…` not in
    the .def.
  * FAIL `vocab.raw_recognition` — a frontend file contains a bare keyword-shaped
    string literal outside the value-literal allowlist (any novel raw recognizer
    that takes `"authorize"` fails closed; the method name is irrelevant).
  * FAIL `vocab.consumer_missing` — LanguageMetadata.cpp or a frontend file does
    not include / use the shared vocabulary.
  * FAIL `vocab.hand_table` — LanguageMetadata.cpp still carries a private
    keyword table.

Bounded exceptions (value enums that are NOT language keywords) live in
`_VALUE_LITERAL_ALLOWLIST`. Unused-VocabId exceptions, if any, live in
`_BOUNDED_UNUSED_VOCAB_IDS` (empty by construction today).

Usage: check_parser_keyword_metadata.py [--selftest]   (exit 0 ok / 1 violations)
"""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VOCAB_DEF = os.path.join(REPO, "include", "Neutrino", "LanguageVocabulary.def")
VOCAB_H = os.path.join(REPO, "include", "Neutrino", "LanguageVocabulary.h")
METADATA = os.path.join(REPO, "docs", "language-metadata.json")
METADATA_CPP = os.path.join(REPO, "lib", "LanguageMetadata.cpp")
FRONTEND_FILES = [
    os.path.join(REPO, "lib", "FrontendParser.cpp"),
    os.path.join(REPO, "lib", "FrontendDeclarations.cpp"),
    os.path.join(REPO, "lib", "FrontendPolicy.cpp"),
    os.path.join(REPO, "lib", "FrontendEntries.cpp"),
]

# Approved recognition helpers (and the spelling accessor). A call site using
# one of these with VocabId::X is the ONLY permitted way to bind source text to
# a vocabulary spelling in the frontend.
_APPROVED_HELPERS = (
    "matchKeywordPrefix",
    "lineStartsWithKeyword",
    "tokenIsKeyword",
    "consumeVocabKeyword",
    "lineContainsKeywordWord",
    "vocabSpelling",
)

# Value-enum / non-keyword literals the frontend may still compare against.
# These are NOT language keywords (they are attribute *values*), so they stay
# outside LanguageVocabulary.def by design.
_VALUE_LITERAL_ALLOWLIST = frozenset({
    "to_be_bound",
    "fixed",
})

# Explicit bounded exceptions: .def EnumIds that need not be passed to an
# approved helper. Empty — every vocabulary row is helper-consumed today.
# A future exception must be justified in a PR and listed here by EnumId.
_BOUNDED_UNUSED_VOCAB_IDS = frozenset()

# NEUTRINO_VOCAB(Category, EnumId, "spelling")
_VOCAB_ROW = re.compile(
    r'^\s*NEUTRINO_VOCAB\s*\(\s*(STATEMENT|FIELD|CONNECTOR)\s*,\s*'
    r'([a-z_][a-z0-9_]*)\s*,\s*"([a-z_][a-z0-9_]*)"\s*\)'
)
_CAT_JSON = {"STATEMENT": "statement", "FIELD": "field", "CONNECTOR": "connector"}

# Bare keyword-shaped string literals (the boundary that admits NO novel raw
# recognizer). Entire string content is a lowercase bareword, optionally with a
# single trailing space (the old startswith("kw ") form).
_BARE_KEYWORD_LIT = re.compile(r'"([a-z_][a-z0-9_]*)( )?"')
_VOCAB_ID_USE = re.compile(r'\bVocabId::([a-z_][a-z0-9_]*)\b')
# Call site of an approved helper: name + opening paren (args extracted with a
# balanced-paren scan so nested vocabSpelling(VocabId::x) inside other calls
# still counts).
_HELPER_CALL = re.compile(
    r'\b(' + '|'.join(_APPROVED_HELPERS) + r')\s*\('
)

MIN_KEYWORDS = 35


def _strip_comments(src):
    """Remove C++ // and /* */ comments, preserving string/char literals (and newlines)."""
    out = []
    i, n = 0, len(src)
    in_str = in_chr = in_line = in_block = False
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
            i += 1
        elif in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
            else:
                if c == "\n":
                    out.append(c)
                i += 1
        elif in_str or in_chr:
            out.append(c)
            if c == "\\":
                if nxt:
                    out.append(nxt)
                i += 2
                continue
            if (in_str and c == '"') or (in_chr and c == "'"):
                in_str = in_chr = False
            i += 1
        elif c == "/" and nxt == "/":
            in_line = True
            i += 2
        elif c == "/" and nxt == "*":
            in_block = True
            i += 2
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif c == "'":
            in_chr = True
            out.append(c)
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def load_vocabulary(def_src):
    """Return (cats, flat_spellings, rows) where rows is [(cat, enum_id, spelling)].

    cats maps JSON category name -> [spellings in def order].
    """
    cats = {"statement": [], "field": [], "connector": []}
    rows = []
    for line in def_src.splitlines():
        m = _VOCAB_ROW.match(line)
        if not m:
            continue
        cat = _CAT_JSON[m.group(1)]
        enum_id, spelling = m.group(2), m.group(3)
        cats[cat].append(spelling)
        rows.append((cat, enum_id, spelling))
    flat = {sp for _, _, sp in rows}
    return cats, flat, rows


def bare_keyword_literals(src):
    """Yield (spelling, has_trailing_space) for every bare keyword-shaped lit."""
    src = _strip_comments(src)
    for m in _BARE_KEYWORD_LIT.finditer(src):
        yield m.group(1), bool(m.group(2))


def raw_recognition_hits(src, value_allowlist=None):
    """Bare keyword-shaped string literals outside the value-literal allowlist.

    Method-agnostic: `recognizesBareword(t, "authorize")`, `t.startswith("kw ")`,
    `key == "field"`, and any future form all fail the same way — the boundary is
    the bare string literal, not a curated method list.
    """
    allow = value_allowlist if value_allowlist is not None else _VALUE_LITERAL_ALLOWLIST
    hits = []
    for spelling, trailed in bare_keyword_literals(src):
        if not trailed and spelling in allow:
            continue
        hits.append(spelling + (" " if trailed else ""))
    return hits


def _balanced_paren_args(src, open_paren_idx):
    """Return the text inside the paren pair starting at open_paren_idx, or None.

    open_paren_idx must point at '('. Nested parens and string/char literals are
    respected so a call like vocabSpelling(VocabId::memo) nested inside
    attrs.count(...) is extracted correctly when scanning the inner call.
    """
    if open_paren_idx >= len(src) or src[open_paren_idx] != '(':
        return None
    depth = 0
    i = open_paren_idx
    in_str = in_chr = False
    while i < len(src):
        c = src[i]
        nxt = src[i + 1] if i + 1 < len(src) else ""
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if in_chr:
            if c == "\\":
                i += 2
                continue
            if c == "'":
                in_chr = False
            i += 1
            continue
        if c == '"':
            in_str = True
            i += 1
            continue
        if c == "'":
            in_chr = True
            i += 1
            continue
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                return src[open_paren_idx + 1:i]
        i += 1
    return None


def helper_vocab_id_uses(src):
    """EnumIds passed as arguments to an approved recognition helper.

    A bare `VocabId::authorize` mention (assignment, cast, (void)…) does NOT
    count — only helper-mediated recognition establishes parser consumption.
    Nested calls are handled because every approved helper call is scanned
    independently with a balanced-paren extractor.
    """
    src = _strip_comments(src)
    ids = set()
    for m in _HELPER_CALL.finditer(src):
        args = _balanced_paren_args(src, m.end() - 1)
        if args is None:
            continue
        ids |= set(_VOCAB_ID_USE.findall(args))
    return ids


def uses_approved_helper(src):
    src = _strip_comments(src)
    return any(h in src for h in _APPROVED_HELPERS)


def check(vocab_def_src, metadata, metadata_cpp, frontend_sources,
          min_keywords=MIN_KEYWORDS,
          value_allowlist=None,
          bounded_unused=None):
    """frontend_sources: list of (path, src) pairs."""
    if value_allowlist is None:
        value_allowlist = _VALUE_LITERAL_ALLOWLIST
    if bounded_unused is None:
        bounded_unused = _BOUNDED_UNUSED_VOCAB_IDS

    reasons = []
    cats, flat, rows = load_vocabulary(vocab_def_src)
    if len(flat) < min_keywords:
        reasons.append(
            f"[vocab.scan] LanguageVocabulary.def has only {len(flat)} entries "
            f"(< {min_keywords}) — refuse to pass vacuously")
        return reasons, flat

    enum_ids = {eid for _, eid, _ in rows}
    spelling_of = {eid: sp for _, eid, sp in rows}

    # --- metadata must equal the .def (definitional, both directions) ---
    declared = set(metadata.get("keywords", []))
    if declared != flat:
        for k in sorted(flat - declared):
            reasons.append(
                f"[vocab.metadata_mismatch] vocabulary spelling '{k}' is in "
                "LanguageVocabulary.def but missing from docs/language-metadata.json "
                "keywords — regenerate via neutrino-translate --language-metadata")
        for k in sorted(declared - flat):
            reasons.append(
                f"[vocab.metadata_mismatch] keyword '{k}' is in "
                "docs/language-metadata.json but not in LanguageVocabulary.def")

    meta_cats = metadata.get("keywordCategories") or {}
    for cat, spellings in cats.items():
        got = set(meta_cats.get(cat) or [])
        want = set(spellings)
        for k in sorted(want - got):
            reasons.append(
                f"[vocab.metadata_mismatch] '{k}' missing from "
                f"keywordCategories.{cat} (def has it)")
        for k in sorted(got - want):
            reasons.append(
                f"[vocab.metadata_mismatch] '{k}' in keywordCategories.{cat} "
                "but not in LanguageVocabulary.def for that category")

    # --- LanguageMetadata.cpp must consume the shared vocabulary ---
    md = _strip_comments(metadata_cpp)
    if "LanguageVocabulary" not in metadata_cpp and "languageVocabulary" not in md:
        reasons.append(
            "[vocab.consumer_missing] lib/LanguageMetadata.cpp does not include / "
            "use LanguageVocabulary — languageMetadataJson() must derive keywords "
            "from the shared .def")
    for hand in ("kStatementKeywords", "kFieldKeywords", "kConnectorKeywords"):
        if re.search(rf'\b{hand}\b', md):
            reasons.append(
                f"[vocab.hand_table] lib/LanguageMetadata.cpp still defines {hand} "
                "— retire the hand mirror; expand LanguageVocabulary.def")

    # --- frontend: include vocabulary, helpers, complete VocabId use, no bare lits ---
    any_helper = False
    used_ids = set()
    for path, src in frontend_sources:
        base = os.path.basename(path)
        if "LanguageVocabulary" not in src:
            reasons.append(
                f"[vocab.consumer_missing] {base} does not include "
                "LanguageVocabulary.h — parser keyword recognition must go through "
                "the shared helper API")
        if uses_approved_helper(src):
            any_helper = True
        used_ids |= helper_vocab_id_uses(src)
        for lit in raw_recognition_hits(src, value_allowlist=value_allowlist):
            reasons.append(
                f"[vocab.raw_recognition] {base} contains bare keyword-shaped "
                f"string literal \"{lit}\" — language keywords must be recognized "
                "only via VocabId + approved helpers (matchKeywordPrefix / "
                "tokenIsKeyword / consumeVocabKeyword / lineContainsKeywordWord / "
                "vocabSpelling). Value enums belong in the value-literal allowlist; "
                "novel raw recognizers are not admitted.")
    if not any_helper and frontend_sources:
        reasons.append(
            "[vocab.consumer_missing] no frontend parser file calls an approved "
            "LanguageVocabulary recognition helper")

    # Every .def EnumId must be passed to an approved helper (table ↔ recognition).
    required = enum_ids - bounded_unused
    for eid in sorted(required - used_ids):
        reasons.append(
            f"[vocab.unused] LanguageVocabulary.def entry VocabId::{eid} "
            f"(spelling '{spelling_of[eid]}') is never passed to an approved "
            "recognition helper (matchKeywordPrefix / lineStartsWithKeyword / "
            "tokenIsKeyword / consumeVocabKeyword / lineContainsKeywordWord / "
            "vocabSpelling) — a bare VocabId mention does not count. Metadata "
            "would advertise syntax the parser does not recognize. Wire it "
            "through a helper, or document a bounded exception in "
            "_BOUNDED_UNUSED_VOCAB_IDS.")
    for eid in sorted(used_ids - enum_ids):
        reasons.append(
            f"[vocab.orphan_use] an approved helper is passed VocabId::{eid} "
            "which is not in LanguageVocabulary.def — add the row or remove the use")
    # A listed "unused" exception that is actually helper-consumed is stale.
    for eid in sorted(bounded_unused & used_ids):
        reasons.append(
            f"[vocab.unused] VocabId::{eid} is listed in _BOUNDED_UNUSED_VOCAB_IDS "
            "but IS passed to an approved helper — remove the stale exception")
    # A listed exception that is not in the .def is also stale.
    for eid in sorted(bounded_unused - enum_ids):
        reasons.append(
            f"[vocab.unused] _BOUNDED_UNUSED_VOCAB_IDS lists '{eid}' which is not "
            "in LanguageVocabulary.def — remove the stale exception")

    return reasons, flat


def _read(path):
    if not os.path.isfile(path):
        return None
    return open(path, encoding="utf-8").read()


def run():
    def_src = _read(VOCAB_DEF)
    meta_cpp = _read(METADATA_CPP)
    if def_src is None or meta_cpp is None or not os.path.isfile(METADATA):
        print("parser-vocabulary gate: missing LanguageVocabulary.def, "
              "LanguageMetadata.cpp, or docs/language-metadata.json",
              file=sys.stderr)
        return 1
    if not os.path.isfile(VOCAB_H):
        print("parser-vocabulary gate: missing LanguageVocabulary.h",
              file=sys.stderr)
        return 1
    front = []
    for path in FRONTEND_FILES:
        src = _read(path)
        if src is None:
            print(f"parser-vocabulary gate: missing {path}", file=sys.stderr)
            return 1
        front.append((path, src))
    reasons, flat = check(def_src, json.load(open(METADATA)), meta_cpp, front)
    if reasons:
        print("parser-keyword vocabulary gate FAILED:", file=sys.stderr)
        for r in reasons:
            print(f"    {r}", file=sys.stderr)
        return 1
    print(f"parser-keyword vocabulary gate OK: LanguageVocabulary.def "
          f"({len(flat)} spellings) equals metadata and every EnumId is passed "
          "to an approved recognition helper; no bare keyword-shaped string "
          "literals outside the value-literal allowlist")
    return 0


def selftest():
    """Prove the gate BITES — real tree clean + synthetic boundary violations."""
    if run() != 0:
        print("selftest: the current tree does not pass the gate", file=sys.stderr)
        return 1

    # Minimal shared vocabulary used only inside synthetic fixtures.
    mini_def = (
        'NEUTRINO_VOCAB(STATEMENT, procedure, "procedure")\n'
        'NEUTRINO_VOCAB(STATEMENT, attest, "attest")\n'
        'NEUTRINO_VOCAB(FIELD, quorum, "quorum")\n'
        'NEUTRINO_VOCAB(CONNECTOR, with, "with")\n'
    )
    mini_cats, mini_flat, _mini_rows = load_vocabulary(mini_def)
    meta_ok = {
        "keywords": sorted(mini_flat),
        "keywordCategories": {
            "statement": sorted(mini_cats["statement"]),
            "field": sorted(mini_cats["field"]),
            "connector": sorted(mini_cats["connector"]),
        },
    }
    meta_cpp_ok = (
        '#include "Neutrino/LanguageVocabulary.h"\n'
        "for (const VocabEntry &e : languageVocabulary()) { (void)e; }\n"
    )
    # Every mini EnumId is referenced — complete table↔helper-use.
    front_ok = [(
        "FrontendParser.cpp",
        '#include "Neutrino/LanguageVocabulary.h"\n'
        "if (lineStartsWithKeyword(t, VocabId::procedure)) {}\n"
        "if (tokenIsKeyword(key, VocabId::quorum)) {}\n"
        "if (consumeVocabKeyword(rest, VocabId::with)) {}\n"
        "if (matchKeywordPrefix(t, VocabId::attest, rest)) {}\n",
    )]
    FLOOR = 3

    def chk(defn, meta, mcpp, front, **kw):
        return check(defn, meta, mcpp, front, min_keywords=FLOOR, **kw)[0]

    fails = []

    # (a) metadata missing a vocab spelling -> vocab.metadata_mismatch
    meta_missing = dict(meta_ok)
    meta_missing["keywords"] = [k for k in meta_ok["keywords"] if k != "quorum"]
    meta_missing["keywordCategories"] = dict(meta_ok["keywordCategories"])
    meta_missing["keywordCategories"]["field"] = []
    r = chk(mini_def, meta_missing, meta_cpp_ok, front_ok)
    if not any("vocab.metadata_mismatch" in x and "quorum" in x for x in r):
        fails.append("a .def spelling missing from metadata must fail "
                     "[vocab.metadata_mismatch]")

    # (b) metadata ghost keyword not in .def -> vocab.metadata_mismatch
    meta_ghost = dict(meta_ok)
    meta_ghost["keywords"] = meta_ok["keywords"] + ["ghost"]
    r = chk(mini_def, meta_ghost, meta_cpp_ok, front_ok)
    if not any("vocab.metadata_mismatch" in x and "ghost" in x for x in r):
        fails.append("a metadata keyword absent from the .def must fail "
                     "[vocab.metadata_mismatch]")

    # (c) raw startswith recognition outside the helper -> vocab.raw_recognition
    front_raw = [(
        "FrontendParser.cpp",
        '#include "Neutrino/LanguageVocabulary.h"\n'
        'if (t.startswith("authorize ")) {}\n'
        "if (lineStartsWithKeyword(t, VocabId::procedure)) {}\n"
        "if (tokenIsKeyword(key, VocabId::quorum)) {}\n"
        "if (consumeVocabKeyword(rest, VocabId::with)) {}\n"
        "if (matchKeywordPrefix(t, VocabId::attest, rest)) {}\n",
    )]
    r = chk(mini_def, meta_ok, meta_cpp_ok, front_raw)
    if not any("vocab.raw_recognition" in x and "authorize" in x for x in r):
        fails.append("a raw startswith(\"authorize \") must fail "
                     "[vocab.raw_recognition]")

    # (d) NOVEL raw recognizer (not in any method list) -> vocab.raw_recognition
    #     This is the  escape  exists to eliminate: method-agnostic boundary.
    front_novel = [(
        "FrontendParser.cpp",
        '#include "Neutrino/LanguageVocabulary.h"\n'
        'if (recognizesBareword(t, "authorize")) {}\n'
        "if (lineStartsWithKeyword(t, VocabId::procedure)) {}\n"
        "if (tokenIsKeyword(key, VocabId::quorum)) {}\n"
        "if (consumeVocabKeyword(rest, VocabId::with)) {}\n"
        "if (matchKeywordPrefix(t, VocabId::attest, rest)) {}\n",
    )]
    r = chk(mini_def, meta_ok, meta_cpp_ok, front_novel)
    if not any("vocab.raw_recognition" in x and "authorize" in x for x in r):
        fails.append("recognizesBareword(t, \"authorize\") must fail "
                     "[vocab.raw_recognition] (method-agnostic bare-literal boundary)")

    # (e) value comparison must NOT be flagged (val == "to_be_bound")
    front_val = [(
        "FrontendParser.cpp",
        '#include "Neutrino/LanguageVocabulary.h"\n'
        "if (lineStartsWithKeyword(t, VocabId::procedure)) {}\n"
        "if (tokenIsKeyword(key, VocabId::quorum)) {}\n"
        "if (consumeVocabKeyword(rest, VocabId::with)) {}\n"
        "if (matchKeywordPrefix(t, VocabId::attest, rest)) {}\n"
        'if (val == "to_be_bound") {}\n',
    )]
    r = chk(mini_def, meta_ok, meta_cpp_ok, front_val)
    if any("to_be_bound" in x for x in r):
        fails.append("a val == value literal must NOT be treated as raw recognition")

    # (f) hand-maintained keyword table in LanguageMetadata.cpp fails
    mcpp_hand = meta_cpp_ok + '\nconst char *const kStatementKeywords[] = {"procedure"};\n'
    r = chk(mini_def, meta_ok, mcpp_hand, front_ok)
    if not any("vocab.hand_table" in x and "kStatementKeywords" in x for x in r):
        fails.append("a private kStatementKeywords table must fail [vocab.hand_table]")

    # (g) consumer missing LanguageVocabulary include fails
    front_noinc = [(
        "FrontendParser.cpp",
        "if (lineStartsWithKeyword(t, VocabId::procedure)) {}\n"
        "if (tokenIsKeyword(key, VocabId::quorum)) {}\n"
        "if (consumeVocabKeyword(rest, VocabId::with)) {}\n"
        "if (matchKeywordPrefix(t, VocabId::attest, rest)) {}\n",
    )]
    r = chk(mini_def, meta_ok, meta_cpp_ok, front_noinc)
    if not any("vocab.consumer_missing" in x for x in r):
        fails.append("frontend without LanguageVocabulary.h must fail "
                     "[vocab.consumer_missing]")

    # (h) in-sync def + metadata + complete helper use passes
    r = chk(mini_def, meta_ok, meta_cpp_ok, front_ok)
    if r:
        fails.append(f"an in-sync vocabulary/metadata/frontend should pass, got {r}")

    # (i) .def row without metadata fails [vocab.metadata_mismatch]
    extended_def = mini_def + 'NEUTRINO_VOCAB(STATEMENT, authorize, "authorize")\n'
    r = chk(extended_def, meta_ok, meta_cpp_ok, front_ok)
    if not any("vocab.metadata_mismatch" in x and "authorize" in x for x in r):
        fails.append("adding a .def row without metadata must fail "
                     "[vocab.metadata_mismatch]")

    # (j) P1: .def row + regenerated metadata, NO helper-mediated recognition
    #     must fail [vocab.unused] — metadata must not advertise unrecognized syntax.
    extended_meta = {
        "keywords": sorted(mini_flat | {"authorize"}),
        "keywordCategories": {
            "statement": sorted(mini_cats["statement"] + ["authorize"]),
            "field": sorted(mini_cats["field"]),
            "connector": sorted(mini_cats["connector"]),
        },
    }
    r = chk(extended_def, extended_meta, meta_cpp_ok, front_ok)
    if not any("vocab.unused" in x and "authorize" in x for x in r):
        fails.append("a .def row + regenerated metadata without any helper "
                     "use of VocabId::authorize must fail [vocab.unused]")

    # (k) P1: mere textual enum mention is NOT recognition
    #     auto merelyMentioned = VocabId::authorize; (void)merelyMentioned;
    front_mention = [(
        "FrontendParser.cpp",
        '#include "Neutrino/LanguageVocabulary.h"\n'
        "if (lineStartsWithKeyword(t, VocabId::procedure)) {}\n"
        "if (tokenIsKeyword(key, VocabId::quorum)) {}\n"
        "if (consumeVocabKeyword(rest, VocabId::with)) {}\n"
        "if (matchKeywordPrefix(t, VocabId::attest, rest)) {}\n"
        "auto merelyMentioned = VocabId::authorize;\n"
        "(void)merelyMentioned;\n",
    )]
    r = chk(extended_def, extended_meta, meta_cpp_ok, front_mention)
    if not any("vocab.unused" in x and "authorize" in x for x in r):
        fails.append("a mere VocabId::authorize mention (no approved helper) "
                     "must fail [vocab.unused]")

    # (l) commented-out bare keyword lit is not live
    front_comment = [(
        "FrontendParser.cpp",
        '#include "Neutrino/LanguageVocabulary.h"\n'
        "if (lineStartsWithKeyword(t, VocabId::procedure)) {}\n"
        "if (tokenIsKeyword(key, VocabId::quorum)) {}\n"
        "if (consumeVocabKeyword(rest, VocabId::with)) {}\n"
        "if (matchKeywordPrefix(t, VocabId::attest, rest)) {}\n"
        '// if (t.startswith("retired ")) {}\n'
        '/* key == "shelved" */\n',
    )]
    r = chk(mini_def, meta_ok, meta_cpp_ok, front_comment)
    if any("retired" in x or "shelved" in x for x in r):
        fails.append("commented-out raw recognition must not fail the gate")

    # (m) complete helper-mediated use of the extended def passes
    front_auth = [(
        "FrontendParser.cpp",
        '#include "Neutrino/LanguageVocabulary.h"\n'
        "if (lineStartsWithKeyword(t, VocabId::procedure)) {}\n"
        "if (tokenIsKeyword(key, VocabId::quorum)) {}\n"
        "if (consumeVocabKeyword(rest, VocabId::with)) {}\n"
        "if (matchKeywordPrefix(t, VocabId::attest, rest)) {}\n"
        "if (lineStartsWithKeyword(t, VocabId::authorize)) {}\n",
    )]
    r = chk(extended_def, extended_meta, meta_cpp_ok, front_auth)
    if r:
        fails.append(
            f"def+metadata+helper(VocabId::authorize) should pass, got {r}")

    if fails:
        print("parser-vocabulary SELFTEST FAILED:", file=sys.stderr)
        for f in fails:
            print(f"    {f}", file=sys.stderr)
        return 1
    print("parser-vocabulary selftest PASS (real tree clean; metadata mirrors "
          "LanguageVocabulary.def both ways; every .def EnumId is passed to an "
          "approved recognition helper; a mere VocabId mention does not count; "
          "bare keyword-shaped literals fail closed including novel recognizers; "
          "value literals are allowlisted; a .def row + metadata without helper "
          "use fails [vocab.unused]; hand tables fail closed; an in-sync triple "
          "passes)")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv[1:] else run())
