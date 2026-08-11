#!/usr/bin/env python3
""" — closed idiom-table capability gate.

The generated target-printer table is allowed to carry only:

  * literal target shape / idiom strings;
  * dense positional bindings to finalized model operands; and
  * dispatch by the already-finalized projection-node kind ordinal.

It must not grow a second decision surface: no predicates, alternate dispatch
keys, ignored operands, semantic lookup, function calls, or value-dependent
branching in the table schema, table records, generated handler table, or generic
driver API.
"""

from __future__ import annotations

import argparse

import generated_artifacts
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCHEMA = REPO / "lib/backends/TargetPrinter.td"
TD = REPO / "lib/backends/solidity/model/SolidityTargetNodes.td"
# TEST-ONLY `Lines`-layout fixture (), NOT a production backend (it lives
# outside lib/backends and is not `*TargetNodes.td`, so discovery never sees it).
# The selftest validates it as a closed literal idiom and probes that a mutated
# multi-line record — and a conditional/operand-driven line — are rejected.
LINES_FIXTURE_TD = REPO / "lib/codetext/test/LinesPrinterFixture.td"
FRAMED_LINES_FIXTURE_TD = REPO / "lib/codetext/test/FramedLinesFixture.td"
PRINTER = REPO / "lib/backends/solidity/generated/SolidityPrinterHandlers.inc"
DRIVER_H = REPO / "include/Neutrino/TargetPrinter.h"
DRIVER_CPP = REPO / "lib/codetext/TargetPrinter.cpp"

ALLOWED_FIELD_BINDING_FIELDS = ("Name", "Index", "Prefix")
ALLOWED_HANDLER_FIELDS = (
    "ordinal",
    "target",
    "node",
    "handler",
    "layout",
    "isLeaf",
    "syntax",
    "closeSyntax",
    "fields",
    "fieldCount",
    # The optional repeated-field (list) projection ( §7): a closed triple of
    # literal C-strings (name + two delimiters), NOT an escape hatch — the driver
    # only joins the model's decided group values by these fixed delimiters.
    "listField",
    "listInner",
    "listOuter",
    # The optional CLOSED-ENUM projection (): a table of enum descriptors
    # plus its count. Each descriptor spells a model ordinal from a `.td`-owned
    # spelling table — NOT a free operand, and NOT an escape hatch (the driver
    # only indexes a fixed spelling list, failing closed on an unknown ordinal).
    "enumFields",
    "enumFieldCount",
    # The optional FRAMED-LINES projection (): a repeated item-line template
    # plus its dense item-field bindings + count. The layout repeats ItemSyntax
    # once per model tuple between a fixed header/footer — NOT an escape hatch:
    # the item SHAPE is a closed literal, only the COUNT is model data.
    "itemSyntax",
    "itemFields",
    "itemFieldCount",
    # The optional FRAMED-LINES empty-case placeholder (): a fixed line the
    # layout emits between header and footer when the model supplies ZERO tuples —
    # so a repeated section owns its own "nothing here" sentinel. Closed literal
    # shape (no projection), NOT an escape hatch.
    "emptyItemSyntax",
)
ALLOWED_TARGET_NODE_FIELDS = (
    "Target",
    "Model",
    "Ordinal",
    "PrinterHandler",
    "IsLeaf",
    "RequiredFeature",
    "Layout",
    "Syntax",
    "CloseSyntax",
    "Fields",
    "ListField",
    "ListInner",
    "ListOuter",
    "EnumFields",
    "ItemSyntax",
    "ItemFields",
    "EmptyItemSyntax",
    "GeneratedHandler",
    "Abbrev",
)
ALLOWED_TARGET_MODEL_FIELDS = ("Target", "Model", "Abbrev", "Primary")
# The CLOSED EnumField descriptor schema () — the ONLY fields an enum
# projection may carry: a name, a spelling table + count, the repeated flag, an
# inner separator, an optional-scalar prefix, and the model ordinal-group index.
ALLOWED_ENUM_FIELD_FIELDS = (
    "name",
    "spellings",
    "spellingCount",
    "repeated",
    "inner",
    "prefix",
    "groupIndex",
)
ALLOWED_LAYOUTS = {"line", "commented-line", "blank", "block", "flat-block",
                   "lines", "framed-lines"}
# The nesting (child-framing) layouts: an open pattern + closeSyntax close +
# typed children. `block` nests children one level; `flat-block` () keeps
# them at the frame's own indent. Both require closeSyntax; no other layout may.
NESTING_LAYOUTS = {"block", "flat-block"}
TAMPER_IDS = {
    "disguised-mode-selector",
    "generated-field-array-mismatch",
    "generated-resolver-semantic-lookup",
    "undiscovered-backend-table",
    "value-dependent-conditional",
    "alternate-dispatch-key",
    "unconsumed-extra-operand",
    "second-wrapper-hidden-record",
    "let-rebinding-scope",
    "let-nonliteral-rhs",
    "bang-outside-string",
    "control-keyword-construct",
}


# : generated .inc are build products. A path that names one is resolved
# from the configured build directory; there is no source-tree fallback, because
# after  a source-tree copy is itself a defect rather than an alternative.
BUILD_DIR = os.environ.get("NEUTRINO_BUILD_DIR", os.path.join(REPO, "out"))


def read(path: Path) -> str:
    try:
        relative = str(Path(path).resolve().relative_to(REPO.resolve()))
    except ValueError:
        relative = None
    if relative and generated_artifacts.is_migrated(relative):
        return generated_artifacts.read_text(relative, BUILD_DIR)
    return path.read_text(encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO.resolve()))
    except ValueError:
        return str(path)


def strip_line_comments(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines():
        i = 0
        in_string = False
        escaped = False
        cut = len(line)
        while i < len(line):
            ch = line[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                i += 1
                continue
            if ch == '"':
                in_string = True
                i += 1
                continue
            if ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
                cut = i
                break
            i += 1
        out.append(line[:cut])
    return "\n".join(out)


def strip_c_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def mask_string_literals(text: str) -> str:
    """Blank the INTERIOR of every double-quoted string literal (space for space;
    the quotes, newlines, and every offset are preserved). String contents are
    DATA: a `!`, an `in`, or an identifier inside a rendered template (e.g. a SQL
    guard string) must not be read as a TableGen bang operator, a `let ... in`
    rebinding scope, or a non-literal reference. String-aware in the same way as
    ``strip_line_comments`` (backslash escapes respected)."""
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
                out.append(" ")
            elif ch == "\\":
                escaped = True
                out.append(" ")
            elif ch == '"':
                in_string = False
                out.append('"')
            else:
                out.append("\n" if ch == "\n" else " ")
        elif ch == '"':
            in_string = True
            out.append('"')
        else:
            out.append(ch)
    return "".join(out)


def unquote(tok: str) -> str | None:
    tok = tok.strip()
    if re.fullmatch(r'"(?:[^"\\]|\\.)*"', tok):
        return bytes(tok[1:-1], "utf-8").decode("unicode_escape")
    return None


def split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    angle = bracket = paren = brace = 0
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "<":
            angle += 1
        elif ch == ">":
            angle -= 1
        elif ch == "[":
            bracket += 1
        elif ch == "]":
            bracket -= 1
        elif ch == "(":
            paren += 1
        elif ch == ")":
            paren -= 1
        elif ch == "{":
            brace += 1
        elif ch == "}":
            brace -= 1
        elif ch == "," and angle == bracket == paren == brace == 0:
            parts.append(text[start:i].strip())
            start = i + 1
    parts.append(text[start:].strip())
    return parts


def class_body(text: str, class_name: str) -> str | None:
    m = re.search(rf"\bclass\s+{re.escape(class_name)}\b", text)
    if not m:
        return None
    brace = text.find("{", m.end())
    if brace < 0:
        return None
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace + 1:i]
    return None


def class_header(text: str, class_name: str) -> str | None:
    m = re.search(rf"\bclass\s+{re.escape(class_name)}\s*<", text)
    if not m:
        return None
    start = text.find("<", m.start())
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "<":
            depth += 1
        elif text[i] == ">":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    return None


def assigned_fields(body: str) -> list[str]:
    return re.findall(
        r"(?m)^\s*(?:string|int|bit|EnumSpelling|list<PrinterField>|list<EnumField>|list<string>)\s+([A-Za-z_]\w*)\s*=",
        body,
    )


def fail(reasons: list[str], msg: str) -> None:
    reasons.append(msg)


def validate_schema(schema_text: str, driver_h: str, reasons: list[str]) -> None:
    schema = strip_line_comments(schema_text)
    fb = class_body(schema, "PrinterField")
    tn = class_body(schema, "TargetPrinterNode")
    tm = class_body(schema, "TargetPrinterModel")
    sol = class_header(schema, "TargetPrinterNode")
    if fb is None or tn is None or tm is None or sol is None:
        fail(reasons, "TargetPrinter.td must declare PrinterField, TargetPrinterModel, and TargetPrinterNode")
        return
    fb_fields = tuple(assigned_fields(fb))
    if fb_fields != ALLOWED_FIELD_BINDING_FIELDS:
        fail(reasons, f"PrinterField schema fields {fb_fields} are not the closed Name/Index/Prefix record")
    tn_fields = tuple(assigned_fields(tn))
    if tn_fields != ALLOWED_TARGET_NODE_FIELDS:
        fail(reasons, f"TargetPrinterNode schema fields {tn_fields} are not the closed handler record")
    tm_fields = tuple(assigned_fields(tm))
    if tm_fields != ALLOWED_TARGET_MODEL_FIELDS:
        fail(reasons, f"TargetPrinterModel schema fields {tm_fields} are not the closed model-role record")
    if re.search(r"\b(?:let|defvar|foreach|multiclass|dag|code)\b|![A-Za-z_]", fb + tm + tn):
        fail(reasons, "TargetPrinter.td schema contains TableGen control/code constructs; only literal record fields are allowed")

    h = re.sub(r"//.*", "", driver_h)
    fb_struct = re.search(r"struct\s+FieldBinding\s*\{(.*?)\};", h, re.S)
    handler_struct = re.search(r"struct\s+Handler\s*\{(.*?)\};", h, re.S)
    if not fb_struct or not handler_struct:
        fail(reasons, "TargetPrinter.h must expose closed FieldBinding and Handler structs")
        return
    fb_names = re.findall(r"\b(?:const\s+char\s*\*\s*|unsigned\s+)([A-Za-z_]\w*)\s*;", fb_struct.group(1))
    if tuple(fb_names) != ("name", "index", "prefix"):
        fail(reasons, f"FieldBinding API fields {fb_names} are not the closed name/index/prefix record")
    handler_names = re.findall(
        r"\b(?:int\s+|const\s+char\s*\*\s*|LayoutKind\s+|bool\s+|const\s+FieldBinding\s*\*\s*|const\s+struct\s+EnumField\s*\*\s*|std::size_t\s+)([A-Za-z_]\w*)\s*;",
        handler_struct.group(1),
    )
    if tuple(handler_names) != ALLOWED_HANDLER_FIELDS:
        fail(reasons, f"Handler API fields {handler_names} are not the closed generated-table API")

    # The CLOSED enum projection schema (): the EnumSpelling/EnumField `.td`
    # classes and the driver's EnumField struct must each carry EXACTLY their
    # closed field set — no extra field that could smuggle a value-dependent or
    # conditional spelling past the closed ordinal->literal projection.
    es_body = class_body(schema, "EnumSpelling")
    ef_body = class_body(schema, "EnumField")
    if es_body is None or ef_body is None:
        fail(reasons, "TargetPrinter.td must declare EnumSpelling and EnumField")
    else:
        es_fields = tuple(assigned_fields(es_body))
        if es_fields != ("CppType", "Symbols", "Spellings"):
            fail(reasons, f"EnumSpelling schema fields {es_fields} are not the closed CppType/Symbols/Spellings record")
        ef_fields = tuple(assigned_fields(ef_body))
        if ef_fields != ("Name", "Spelling", "Repeated", "Inner", "Prefix"):
            fail(reasons, f"EnumField schema fields {ef_fields} are not the closed Name/Spelling/Repeated/Inner/Prefix record")
        if re.search(r"\b(?:let|defvar|foreach|multiclass|dag|code)\b|![A-Za-z_]", es_body + ef_body):
            fail(reasons, "EnumSpelling/EnumField schema contains TableGen control/code constructs; only literal record fields are allowed")
    ef_struct = re.search(r"struct\s+EnumField\s*\{(.*?)\};", h, re.S)
    if not ef_struct:
        fail(reasons, "TargetPrinter.h must expose a closed EnumField struct")
    else:
        ef_names = re.findall(
            r"\b(?:const\s+char\s*\*\s*const\s*\*\s*|const\s+char\s*\*\s*|std::size_t\s+|bool\s+|unsigned\s+)([A-Za-z_]\w*)\s*;",
            ef_struct.group(1),
        )
        if tuple(ef_names) != ALLOWED_ENUM_FIELD_FIELDS:
            fail(reasons, f"EnumField API fields {ef_names} are not the closed enum-descriptor record")


def parse_printer_fields(td_text: str, reasons: list[str]) -> dict[str, tuple[str, int, str]]:
    fields: dict[str, tuple[str, int, str]] = {}
    for m in re.finditer(r"\bdef\s+([A-Za-z_]\w*)\s*:\s*PrinterField\s*<([^>]*)>\s*;", td_text, re.S):
        args = split_top_level(strip_c_comments(m.group(2)))
        # name, index, and an OPTIONAL literal Prefix (). 2 or 3 args only.
        if len(args) not in (2, 3):
            fail(reasons, f"PrinterField {m.group(1)} must have name,index[,prefix]")
            continue
        name = unquote(args[0])
        if name is None:
            fail(reasons, f"PrinterField {m.group(1)} name must be a literal string")
            continue
        if not re.fullmatch(r"\d+", args[1].strip()):
            fail(reasons, f"PrinterField {m.group(1)} index must be a non-negative integer literal")
            continue
        prefix = ""
        if len(args) == 3:
            prefix = unquote(args[2])
            if prefix is None:
                fail(reasons, f"PrinterField {m.group(1)} prefix must be a literal string")
                continue
        fields[m.group(1)] = (name, int(args[1]), prefix)
    return fields


def parse_enum_spellings(td_text: str, reasons: list[str]) -> dict[str, list[str]]:
    """Parse `def X : EnumSpelling<[...]>;` into sym -> list of literal spellings.

    Each spelling is a non-empty literal string; the list is the CLOSED, ordered
    ordinal->spelling table the driver indexes."""
    def _literal_list(sym, lst, what):
        lst = lst.strip()
        if not (lst.startswith("[") and lst.endswith("]")):
            fail(reasons, f"EnumSpelling {sym} {what} must be a literal list")
            return None
        items = [x.strip() for x in split_top_level(lst[1:-1].strip())] if lst[1:-1].strip() else []
        vals: list[str] = []
        for it in items:
            s = unquote(it)
            if s is None:
                fail(reasons, f"EnumSpelling {sym} {what} entry {it!r} must be a literal string")
                continue
            vals.append(s)
        return vals

    out: dict[str, list[str]] = {}
    for m in re.finditer(r"\bdef\s+([A-Za-z_]\w*)\s*:\s*EnumSpelling\s*<(.*?)>\s*;", td_text, re.S):
        sym = m.group(1)
        args = split_top_level(strip_c_comments(m.group(2)))
        # cppType, Symbols list, Spellings list (): the enum is generated from
        # this ONE record, so symbols and spellings are 1:1.
        if len(args) != 3:
            fail(reasons, f"EnumSpelling {sym} must take (cppType, symbols, spellings)")
            continue
        cpp_type = unquote(args[0])
        if cpp_type is None or not re.fullmatch(r"[A-Za-z_]\w*", cpp_type):
            fail(reasons, f"EnumSpelling {sym} cppType must be a literal C++ identifier")
        symbols = _literal_list(sym, args[1], "symbols") or []
        spellings = _literal_list(sym, args[2], "spellings") or []
        if any(s == "" for s in spellings):
            fail(reasons, f"EnumSpelling {sym} has an empty spelling")
            spellings = [s for s in spellings if s != ""]
        if not spellings:
            fail(reasons, f"EnumSpelling {sym} must list at least one spelling")
        if len(symbols) != len(spellings):
            fail(reasons, f"EnumSpelling {sym} has mismatched symbols/spellings lengths")
        for s in symbols:
            if not re.fullmatch(r"[A-Za-z_]\w*", s) or s == "Count":
                fail(reasons, f"EnumSpelling {sym} has an invalid or reserved C++ symbol {s!r}")
        if len(set(symbols)) != len(symbols):
            fail(reasons, f"EnumSpelling {sym} has duplicate C++ symbol(s)")
        # DUPLICATE spellings are forbidden ( review P1.3): two ordinals sharing
        # one target spelling would make the projection non-injective — two distinct
        # enum values would render identically, so the mapping is no longer a
        # faithful 1:1 closed vocabulary.
        if len(set(spellings)) != len(spellings):
            dups = sorted({s for s in spellings if spellings.count(s) > 1})
            fail(reasons, f"EnumSpelling {sym} has duplicate spelling(s) {dups}")
        out[sym] = spellings
    return out


def parse_enum_fields(td_text: str, spellings: dict[str, list[str]], reasons: list[str]) -> dict[str, dict[str, object]]:
    """Parse `def Y : EnumField<"name", Spelling, repeated, inner, prefix>;`.

    Returns sym -> {name, spelling, repeated, inner, prefix}. Only literal
    arguments and a reference to a known EnumSpelling are allowed (a repeated
    field requires an inner separator; a scalar field forbids one)."""
    out: dict[str, dict[str, object]] = {}
    for m in re.finditer(r"\bdef\s+([A-Za-z_]\w*)\s*:\s*EnumField\s*<(.*?)>\s*;", td_text, re.S):
        sym = m.group(1)
        args = split_top_level(strip_c_comments(m.group(2)))
        # name, spelling[, repeated[, inner[, prefix]]] — 2..5 literal args.
        if len(args) < 2 or len(args) > 5:
            fail(reasons, f"EnumField {sym} must have name,spelling[,repeated[,inner[,prefix]]]")
            continue
        name = unquote(args[0])
        if name is None:
            fail(reasons, f"EnumField {sym} name must be a literal string")
            continue
        spelling_sym = args[1].strip()
        if spelling_sym not in spellings:
            fail(reasons, f"EnumField {sym} references unknown EnumSpelling {spelling_sym}")
            continue
        repeated = False
        if len(args) >= 3:
            r = args[2].strip()
            if not re.fullmatch(r"[01]", r):
                fail(reasons, f"EnumField {sym} repeated must be a literal bit")
                continue
            repeated = r == "1"
        inner = unquote(args[3]) if len(args) >= 4 else ""
        prefix = unquote(args[4]) if len(args) >= 5 else ""
        if inner is None or prefix is None:
            fail(reasons, f"EnumField {sym} inner/prefix must be literal strings")
            continue
        if repeated and not inner:
            fail(reasons, f"EnumField {sym} is repeated but has no inner separator")
        if not repeated and inner:
            fail(reasons, f"EnumField {sym} is scalar but declares an inner separator")
        out[sym] = {"name": name, "spelling": spelling_sym,
                    "spellings": spellings.get(spelling_sym, []),
                    "repeated": repeated, "inner": inner, "prefix": prefix}
    return out


def parse_enum_field_list(arg: str, enum_fields: dict[str, dict[str, object]], sym: str, reasons: list[str]) -> list[dict[str, object]]:
    arg = arg.strip()
    if not (arg.startswith("[") and arg.endswith("]")):
        fail(reasons, f"{sym}: enumFields argument must be a literal list of EnumField defs")
        return []
    inner = arg[1:-1].strip()
    if not inner:
        return []
    out: list[dict[str, object]] = []
    for name in [x.strip() for x in split_top_level(inner)]:
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            fail(reasons, f"{sym}: enum field list contains non-symbol reference {name!r}")
            continue
        if name not in enum_fields:
            fail(reasons, f"{sym}: enum field list references unknown EnumField {name}")
            continue
        out.append(enum_fields[name])
    return out


def discover_wrappers(raw: str) -> list[tuple[str, str, str]]:
    """Return every (wrapper, target, model) TargetPrinterNode specialization."""
    wrappers = []
    for base in re.finditer(
            r":\s*TargetPrinterNode\s*<\s*\"([^\"]+)\"\s*,\s*\"([^\"]+)\"", raw):
        prior = list(re.finditer(r"\bclass\s+([A-Za-z_]\w*)\s*<", raw[:base.start()]))
        if prior:
            wrappers.append((prior[-1].group(1), base.group(1), base.group(2)))
    return wrappers


def discover_wrapper(raw: str) -> tuple[str | None, str | None, str | None]:
    wrappers = discover_wrappers(raw)
    return wrappers[0] if wrappers else (None, None, None)


def parse_model_declarations(raw: str, reasons: list[str]) -> dict[str, dict[str, object]]:
    declarations = {}
    rx = re.compile(r"\bdef\s+([A-Za-z_]\w*)\s*:\s*TargetPrinterModel\s*<(.*?)>\s*;", re.S)
    for match in rx.finditer(raw):
        args = split_top_level(strip_c_comments(match.group(2)))
        if len(args) != 4:
            fail(reasons, f"TargetPrinterModel {match.group(1)} must have target,model,abbrev,primary")
            continue
        target, model, abbrev = (unquote(arg) for arg in args[:3])
        primary = args[3].strip()
        if (None in (target, model, abbrev) or not all((target, model, abbrev))
                or not re.fullmatch(r"[A-Za-z_]\w*", model or "")
                or not re.fullmatch(r"[A-Z][A-Z0-9_]*", abbrev or "")
                or not re.fullmatch(r"[01]", primary)):
            fail(reasons, f"TargetPrinterModel {match.group(1)} identity and Primary must be literal")
            continue
        if model in declarations:
            fail(reasons, f"duplicate TargetPrinterModel declaration for {model}")
            continue
        declarations[model] = {"target": target, "abbrev": abbrev,
                               "primary": primary == "1"}
    return declarations


def iter_wrapper_defs(td_text: str, wrapper: str):
    rx = re.compile(rf"\bdef\s+([A-Za-z_]\w*)\s*:\s*{re.escape(wrapper)}\s*<")
    pos = 0
    while True:
        m = rx.search(td_text, pos)
        if not m:
            return
        start = td_text.find("<", m.end() - 1)
        depth = 0
        in_string = False
        escaped = False
        end = None
        for i in range(start, len(td_text)):
            ch = td_text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "<":
                depth += 1
            elif ch == ">":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is None:
            yield m.group(1), ""
            return
        yield m.group(1), td_text[start + 1:end]
        pos = end + 1


def parse_field_list(arg: str, fields: dict[str, tuple[str, int]], sym: str, reasons: list[str]) -> list[tuple[str, int]]:
    arg = arg.strip()
    if not (arg.startswith("[") and arg.endswith("]")):
        fail(reasons, f"{sym}: fields argument must be a literal list of PrinterField defs")
        return []
    inner = arg[1:-1].strip()
    if not inner:
        return []
    names = [x.strip() for x in split_top_level(inner)]
    out: list[tuple[str, int]] = []
    for name in names:
        if not re.fullmatch(r"[A-Za-z_]\w*", name):
            fail(reasons, f"{sym}: field list contains non-symbol binding {name!r}")
            continue
        if name not in fields:
            fail(reasons, f"{sym}: field list references unknown PrinterField {name}")
            continue
        out.append(fields[name])
    return out


def validate_td(td_text: str, reasons: list[str]) -> dict[str, dict[str, object]]:
    raw = strip_line_comments(td_text)
    # Scan with string literals masked: a `!`, an `in`, or an identifier that is
    # DATA inside a rendered template must not be mistaken for a control/value
    # construct ( recipe-builder field-overrides + guard-string `!` were both
    # literal-data false positives under the old blanket bans).
    masked = mask_string_literals(raw)
    # Genuine TableGen control/code constructs are never literal record data.
    if re.search(r"\b(?:defvar|foreach|multiclass|dag|code)\b", masked):
        fail(reasons, "target node table contains TableGen control/code constructs; records must be literal data")
    # A `let ... in` scope rebinds fields across records — cross-record
    # rebinding, not a per-record literal field. Forbidden.
    if re.search(r"\blet\b[^;{}]*\bin\b", masked):
        fail(reasons, "target node table contains a top-level `let ... in` rebinding scope; records must be literal data")
    # An in-record `let <field> = <rhs>;` override is literal data ONLY when the
    # RHS is a quoted string, a bit/int, or a list of those. A non-literal RHS (a
    # def reference, a bang op, nested `<...>` code) is a disguised computed value.
    for rhs in re.findall(r"\blet\s+[A-Za-z_]\w*\s*=\s*([^;]*);", masked):
        if not re.fullmatch(r'[\s\[\],"0-9-]*', rhs):
            fail(reasons, "target node table contains a `let` field-override with a non-literal RHS; records must be literal data")
            break
    # Bang operators (value-dependent expressions) outside string literals.
    if re.search(r"![A-Za-z_]", masked):
        fail(reasons, "target node table contains TableGen bang operators; value-dependent expressions are forbidden")

    wrappers = discover_wrappers(raw)
    if not wrappers:
        fail(reasons, "target node table must declare a TargetPrinterNode wrapper class")
        return {}
    declarations = parse_model_declarations(raw, reasons)
    wrapper_models = {model for _wrapper, _target, model in wrappers}
    if len(wrapper_models) != len(wrappers):
        fail(reasons, "each TargetPrinterNode wrapper must own a distinct model")
    if len({wrapper for wrapper, _target, _model in wrappers}) != len(wrappers):
        fail(reasons, "target node wrapper class names must be unique")
    if set(declarations) != wrapper_models:
        fail(reasons, f"TargetPrinterModel declarations {sorted(declarations)} must exactly cover "
                      f"wrapper models {sorted(wrapper_models)}")
    primary_models = [model for model, decl in declarations.items() if decl["primary"]]
    if len(primary_models) != 1:
        fail(reasons, "target node table must declare exactly one Primary model")
    if len({decl["target"] for decl in declarations.values()}) != 1:
        fail(reasons, "all TargetPrinterModel declarations in one table must share one target")
    if len({decl["abbrev"] for decl in declarations.values()}) != 1:
        fail(reasons, "all TargetPrinterModel declarations in one table must share one abbreviation")
    if len({target for _wrapper, target, _model in wrappers}) != 1:
        fail(reasons, "all target node wrappers in one table must share one target")

    for wrapper, target, model in wrappers:
        decl = declarations.get(model)
        if decl and decl["target"] != target:
            fail(reasons, f"TargetPrinterModel {model} target disagrees with wrapper {wrapper}")
        header = class_header(raw, wrapper)
        if header is None:
            fail(reasons, f"target node table must declare the {wrapper} wrapper")
            continue
        header_args = [re.sub(r"\s+", " ", a).strip()
                       for a in split_top_level(strip_c_comments(header))]
        expected_prefix = [
            "int ord",
            "string handler",
            "bit leaf",
            "string feature",
            'string layout = ""',
            'string syntax = ""',
            "list<PrinterField> fields = []",
            "bit generated = 0",
            'string closeSyntax = ""',
            'string listField = ""',
            'string listInner = ""',
            'string listOuter = ""',
            "list<EnumField> enumFields = []",
        ]
        # A framed-lines-capable wrapper () additionally forwards the closed
        # ItemSyntax/ItemFields tail; the  endpoint adds the closed
        # EmptyItemSyntax placeholder tail. The base, framed, and framed+empty
        # forms are the only closed schemas (no other extension is allowed).
        expected_framed = expected_prefix + [
            'string itemSyntax = ""',
            "list<PrinterField> itemFields = []",
        ]
        expected_framed_empty = expected_framed + [
            'string emptyItemSyntax = ""',
        ]
        if header_args not in (expected_prefix, expected_framed,
                               expected_framed_empty):
            fail(reasons, f"{wrapper} wrapper schema is not the closed projection table schema: {header_args}")
        forward = f'TargetPrinterNode<"{target}", "{model}", ord, handler, leaf, feature,'
        if forward not in re.sub(r"\s+", " ", raw):
            fail(reasons, f"{wrapper} wrapper must forward only the finalized {model} kind record to TargetPrinterNode")

    fields = parse_printer_fields(raw, reasons)
    enum_spellings = parse_enum_spellings(raw, reasons)
    enum_fields = parse_enum_fields(raw, enum_spellings, reasons)
    records: dict[str, dict[str, object]] = {}
    placeholders_rx = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
    wrapper_records = [
        (wrapper, target, model, sym, body)
        for wrapper, target, model in wrappers
        for sym, body in iter_wrapper_defs(raw, wrapper)
    ]
    for wrapper, target, model, sym, body in wrapper_records:
        args = split_top_level(strip_c_comments(body))
        # `generated=1` (the closed printer schema) is arg[7]; a short-form record
        # (fewer args, or an explicit generated=0) is a handwritten-dispatch kind
        # registered only for enum identity — no printer syntax — so it is validated
        # as literal data and left out of the generated reachability set below.
        generated = len(args) >= 8 and re.fullmatch(r"(?:/\*.*?\*/\s*)?1", args[7].strip(), re.S) is not None
        if not generated:
            if not re.fullmatch(r"\d+", args[0].strip()):
                fail(reasons, f"{sym}: ordinal must be a non-negative integer literal")
            if len(args) >= 2 and unquote(args[1]) is None:
                fail(reasons, f"{sym}: handler must be a literal string")
            if len(args) >= 8 and re.fullmatch(r"(?:/\*.*?\*/\s*)?0", args[7].strip(), re.S) is None:
                fail(reasons, f"{sym}: GeneratedHandler must be a literal bit")
            if any(unquote(a) for a in args[4:6]) or (len(args) > 6 and args[6].strip() not in ("", "[]")):
                fail(reasons, f"{sym}: non-generated record may not carry layout/syntax/fields")
            continue
        # A GENERATED record carries the closed 8/9/12/13/15/16 literal arguments:
        # 8/9 = the scalar record (± closeSyntax); 12 = a record that ALSO carries
        # the closed repeated-field triple (closeSyntax + listField/inner/outer,
        # which requires closeSyntax positionally); 13 = a record that ALSO carries
        # the closed enum-field list (, after the list triple positionally);
        # 15 = the framed-lines form (, itemSyntax + itemFields after the enum
        # list); 16 = the framed-lines form that ALSO carries the
        # EmptyItemSyntax placeholder. No other arity.
        if len(args) not in (8, 9, 12, 13, 15, 16):
            fail(reasons, f"{sym}: generated record must have only the closed 8/9/12/13/15/16 literal arguments, got {len(args)}")
            continue
        if not re.fullmatch(r"\d+", args[0].strip()):
            fail(reasons, f"{sym}: ordinal must be a non-negative integer literal")
        handler = unquote(args[1])
        feature = unquote(args[3])
        layout = unquote(args[4])
        syntax = unquote(args[5])
        close = unquote(args[8]) if len(args) >= 9 else ""
        # The repeated-field (list) triple — all three literal strings, or none.
        # Present positionally when the record carries the list (12) or the list +
        # enum (13) form.
        has_list_triple = len(args) >= 12
        list_field = unquote(args[9]) if has_list_triple else ""
        list_inner = unquote(args[10]) if has_list_triple else ""
        list_outer = unquote(args[11]) if has_list_triple else ""
        # The enum-field list () — present in the 13-arg form (and the 15-arg
        # framed-lines form, which extends it).
        enum_specs = parse_enum_field_list(args[12], enum_fields, sym, reasons) if len(args) >= 13 else []
        # The framed-lines () item-line template + item-field bindings — present
        # in the 15-arg form (after the enum list positionally) and the 16-arg
        # form, which additionally carries the  EmptyItemSyntax placeholder.
        item_syntax = unquote(args[13]) if len(args) >= 15 else ""
        item_fbs = parse_field_list(args[14], fields, sym, reasons) if len(args) >= 15 else []
        # The framed-lines empty-case placeholder () — present ONLY in the
        # 16-arg form.
        empty_item_syntax = unquote(args[15]) if len(args) >= 16 else ""
        if item_syntax is None:
            fail(reasons, f"{sym}: ItemSyntax must be a literal string")
            continue
        if handler is None or feature is None or layout is None or syntax is None or close is None:
            fail(reasons, f"{sym}: handler/feature/layout/syntax/closeSyntax must be literal strings")
            continue
        if list_field is None or list_inner is None or list_outer is None:
            fail(reasons, f"{sym}: listField/listInner/listOuter must be literal strings")
            continue
        if list_field:
            if not list_inner or not list_outer:
                fail(reasons, f"{sym}: a listField requires both listInner and listOuter delimiters")
            if ("${" + list_field + "}") in close:
                fail(reasons, f"{sym}: the list field may project into the open syntax only, not closeSyntax")
        elif list_inner or list_outer:
            fail(reasons, f"{sym}: listInner/listOuter without a listField are forbidden")
        if not re.fullmatch(r"(?:/\*.*?\*/\s*)?[01]", args[2].strip(), re.S):
            fail(reasons, f"{sym}: IsLeaf must be a literal bit")
        if not re.fullmatch(r"(?:/\*.*?\*/\s*)?[01]", args[7].strip(), re.S):
            fail(reasons, f"{sym}: GeneratedHandler must be a literal bit")
        if layout not in ALLOWED_LAYOUTS:
            fail(reasons, f"{sym}: unsupported layout {layout!r}")
        fbs = parse_field_list(args[6], fields, sym, reasons)
        names = [n for n, _i, _p in fbs]
        idxs = sorted(i for _n, i, _p in fbs)
        if len(set(names)) != len(names):
            fail(reasons, f"{sym}: duplicate projected field names are forbidden")
        if len(set(idxs)) != len(idxs):
            fail(reasons, f"{sym}: duplicate operand bindings are forbidden")
        if idxs != list(range(len(idxs))):
            fail(reasons, f"{sym}: operand bindings {idxs} are not dense 0..{len(idxs) - 1}")
        used = placeholders_rx.findall(syntax + " " + close)
        # The enum fields are declared placeholders too (): distinct closed-enum
        # projections spelled from `.td` tables — each must be referenced by the OPEN
        # syntax only (an enum spells from ordinals; expandClose is scalar-only), and
        # its name must not collide with a scalar or list field.
        enum_names = [str(e["name"]) for e in enum_specs]
        if len(set(enum_names)) != len(enum_names):
            fail(reasons, f"{sym}: duplicate enum field names are forbidden")
        for en in enum_names:
            if en in names:
                fail(reasons, f"{sym}: enum field {en!r} collides with a scalar field name")
            if list_field and en == list_field:
                fail(reasons, f"{sym}: enum field {en!r} collides with the list field name")
            if ("${" + en + "}") in close:
                fail(reasons, f"{sym}: enum field {en!r} may project into the open syntax only, not closeSyntax")
            if ("${" + en + "}") not in syntax:
                fail(reasons, f"{sym}: enum field {en!r} is not referenced by the syntax")
        # The list field is a declared placeholder too — distinct from the scalar
        # operand fields — and must itself be referenced by the open syntax.
        declared = set(names) | ({list_field} if list_field else set()) | set(enum_names)
        if list_field and list_field in names:
            fail(reasons, f"{sym}: listField {list_field!r} collides with a scalar field name")
        if list_field and list_field not in set(used):
            fail(reasons, f"{sym}: listField {list_field!r} is not referenced by the syntax")
        undeclared = sorted(set(used) - declared)
        unused = sorted(declared - set(used))
        if undeclared:
            fail(reasons, f"{sym}: syntax references undeclared field(s) {undeclared}")
        if unused:
            fail(reasons, f"{sym}: field binding(s) {unused} are ignored by syntax")
        if layout == "blank" and (syntax or close or fbs):
            fail(reasons, f"{sym}: blank layout may not carry syntax, close syntax, or fields")
        if layout in NESTING_LAYOUTS and not close:
            fail(reasons, f"{sym}: {layout} layout requires literal closeSyntax")
        # `block`/`flat-block` use closeSyntax as their close delimiter;
        # `framed-lines` uses it as the fixed FOOTER. No other layout may carry it.
        if layout not in (NESTING_LAYOUTS | {"framed-lines"}) and close:
            fail(reasons, f"{sym}: non-block/non-flat-block/non-framed-lines layout may not carry closeSyntax")
        # FRAMED-LINES (): fixed literal Header (syntax) + one closed ItemSyntax
        # repeated per model tuple + an optional fixed literal Footer (close).
        # Only ItemFields project, and only into ItemSyntax.
        if layout == "framed-lines":
            if not item_syntax:
                fail(reasons, f"{sym}: framed-lines layout requires a non-empty ItemSyntax")
            if placeholders_rx.findall(syntax) or placeholders_rx.findall(close):
                fail(reasons, f"{sym}: framed-lines Header/Footer must be fixed literal (no ${{...}} placeholders)")
            if fbs or list_field or enum_specs:
                fail(reasons, f"{sym}: framed-lines node may not declare scalar Fields / listField / enum fields (only ItemFields project, over the tuple)")
            item_names = [n for n, _i, _p in item_fbs]
            item_idxs = sorted(i for _n, i, _p in item_fbs)
            if len(set(item_names)) != len(item_names):
                fail(reasons, f"{sym}: duplicate item field names are forbidden")
            if not item_idxs or item_idxs != list(range(len(item_idxs))):
                fail(reasons, f"{sym}: item field indices {item_idxs} are not dense 0..N-1")
            item_used = placeholders_rx.findall(item_syntax)
            if not item_used:
                fail(reasons, f"{sym}: ItemSyntax has no ${{item field}} placeholder")
            if sorted(set(item_used)) != sorted(set(item_names)):
                fail(reasons, f"{sym}: ItemSyntax placeholders {sorted(set(item_used))} must match declared item fields {sorted(set(item_names))}")
            # The empty-case placeholder () is a fixed literal line — no
            # projection, so it cannot smuggle a value-dependent empty rendering.
            if placeholders_rx.findall(empty_item_syntax):
                fail(reasons, f"{sym}: EmptyItemSyntax must be a fixed literal (no ${{...}} placeholders)")
        elif item_syntax or item_fbs or empty_item_syntax:
            fail(reasons, f"{sym}: ItemSyntax/ItemFields/EmptyItemSyntax without a framed-lines layout are forbidden")
        identity = f"{model}::{sym}"
        if identity in records:
            fail(reasons, f"duplicate target node record {identity}")
        records[identity] = {
            "target": target,
            "model": model,
            "node": sym,
            "allModels": sorted(declarations),
            "ordinal": int(args[0].strip()) if re.fullmatch(r"\d+", args[0].strip()) else -1,
            "layout": layout,
            "fields": fbs,
            "syntax": syntax,
            "close": close,
            "listField": list_field,
            "listInner": list_inner,
            "listOuter": list_outer,
            "enumFields": enum_specs,
            "itemSyntax": item_syntax,
            "itemFields": item_fbs,
            "emptyItemSyntax": empty_item_syntax,
        }
    if not records:
        fail(reasons, "target node table has no generated wrapper records")
    return records


def handler_for_body(printer_text: str) -> str | None:
    bodies = handler_for_bodies(printer_text)
    return next(iter(bodies.values()), None)


def handler_for_bodies(printer_text: str) -> dict[str, str]:
    bodies = {}
    rx = re.compile(
        r"inline\s+const\s+target_printer::Handler\s+\*handlerFor\s*\("
        r"([A-Za-z_]\w*)::Kind\s+kind\s*\)\s*\{")
    for match in rx.finditer(printer_text):
        start = printer_text.find("{", match.end() - 1)
        depth = 0
        for i in range(start, len(printer_text)):
            if printer_text[i] == "{":
                depth += 1
            elif printer_text[i] == "}":
                depth -= 1
                if depth == 0:
                    bodies[match.group(1)] = printer_text[start + 1:i]
                    break
    return bodies


def function_body(text: str, name: str) -> str | None:
    m = re.search(rf"\b{name}\s*\([^)]*\)\s*\{{", text)
    if not m:
        return None
    start = text.find("{", m.end() - 1)
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
    return None


def parse_generated_field_arrays(printer_text: str, reasons: list[str]) -> dict[str, list[tuple[str, int]]]:
    arrays: dict[str, list[tuple[str, int]]] = {}
    for m in re.finditer(
        r"inline\s+constexpr\s+target_printer::FieldBinding\s+(k[A-Za-z_]\w*Fields)\s*\[\]\s*=\s*\{(.*?)\};",
        printer_text,
        re.S,
    ):
        entries: list[tuple[str, int, str]] = []
        body = m.group(2)
        # Each binding is `{"name", index, <prefix>}` where <prefix> is a literal
        # C-string or `nullptr` ( optional-scalar separator) — no expression.
        residue = re.sub(
            r"\{\s*\"(?:[^\"\\]|\\.)*\"\s*,\s*\d+\s*,\s*(?:nullptr|\"(?:[^\"\\]|\\.)*\")\s*\}\s*,?",
            "", strip_c_comments(body)).strip()
        if residue:
            fail(reasons, f"generated field array {m.group(1)} contains non-literal binding data")
        for name, index, prefix in re.findall(
                r"\{\s*\"((?:[^\"\\]|\\.)*)\"\s*,\s*(\d+)\s*,\s*(nullptr|\"(?:[^\"\\]|\\.)*\")\s*\}", body):
            pfx = "" if prefix == "nullptr" else bytes(prefix[1:-1], "utf-8").decode("unicode_escape")
            entries.append((bytes(name, "utf-8").decode("unicode_escape"), int(index), pfx))
        arrays[m.group(1)] = entries
    return arrays


def parse_generated_enum_tables(printer_text: str, reasons: list[str]) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Parse the generated `kX[] = {"a","b",}` spelling tables and `kXCount = N`
    length constants ()."""
    tables: dict[str, list[str]] = {}
    for m in re.finditer(
        r"inline\s+constexpr\s+const\s+char\s*\*\s*(k[A-Za-z_]\w*)\s*\[\]\s*=\s*\{(.*?)\};",
        printer_text, re.S):
        sym = m.group(1)
        body = strip_c_comments(m.group(2))
        residue = re.sub(r'"(?:[^"\\]|\\.)*"\s*,?', "", body).strip()
        if residue:
            fail(reasons, f"generated spelling table {sym} contains non-literal data")
        tables[sym] = [bytes(s, "utf-8").decode("unicode_escape")
                       for s in re.findall(r'"((?:[^"\\]|\\.)*)"', body)]
    counts: dict[str, int] = {}
    for m in re.finditer(
        r"inline\s+constexpr\s+std::size_t\s+(k[A-Za-z_]\w*Count)\s*=\s*(\d+)\s*;",
        printer_text):
        counts[m.group(1)] = int(m.group(2))
    return tables, counts


def parse_generated_enum_arrays(printer_text: str, reasons: list[str]) -> dict[str, list[dict[str, object]]]:
    """Parse the generated `kXEnums[] = { {descriptor}, ... }` EnumField arrays
    into ordered descriptor dicts (). Each descriptor is
    `{"name", kSpelling, kSpellingCount, repeated, inner, prefix, groupIndex}` —
    all literal, so a hand-edited generated table is caught on reconciliation."""
    lit_or_null = r'(?:nullptr|"(?:[^"\\]|\\.)*")'

    def _str(tok: str) -> str:
        return "" if tok == "nullptr" else bytes(tok[1:-1], "utf-8").decode("unicode_escape")

    arrays: dict[str, list[dict[str, object]]] = {}
    for m in re.finditer(
        r"inline\s+constexpr\s+target_printer::EnumField\s+(k[A-Za-z_]\w*Enums)\s*\[\]\s*=\s*\{(.*?)\};",
        printer_text, re.S):
        name = m.group(1)
        body = strip_c_comments(m.group(2))
        desc_rx = (r'\{\s*"((?:[^"\\]|\\.)*)"\s*,\s*(k[A-Za-z_]\w*)\s*,\s*'
                   r'(k[A-Za-z_]\w*Count)\s*,\s*(true|false)\s*,\s*'
                   r'(' + lit_or_null + r')\s*,\s*(' + lit_or_null + r')\s*,\s*(\d+)\s*\}')
        residue = re.sub(desc_rx + r"\s*,?", "", body).strip()
        if residue:
            fail(reasons, f"generated enum array {name} contains non-literal descriptor data")
        descs: list[dict[str, object]] = []
        for dname, spell, count_sym, repeated, inner, prefix, gidx in re.findall(desc_rx, body):
            descs.append({
                "name": bytes(dname, "utf-8").decode("unicode_escape"),
                "spellingSym": spell,
                "countSym": count_sym,
                "repeated": repeated == "true",
                "inner": _str(inner),
                "prefix": _str(prefix),
                "groupIndex": int(gidx),
            })
        arrays[name] = descs
    return arrays


def validate_resolve_field(printer_text: str, reasons: list[str],
                           expected_names: set[str] | None = None) -> None:
    names = re.findall(r"inline\s+std::string\s+(resolve[A-Za-z_]*Field)\s*\(",
                       printer_text)
    if not names:
        fail(reasons, "generated printer must expose resolveField operand projection")
        return
    if expected_names is not None and set(names) != expected_names:
        fail(reasons, f"generated resolver names {sorted(set(names))} do not match "
                      f"model-qualified names {sorted(expected_names)}")
    for name in names:
        body = function_body(printer_text, name)
        clean = strip_c_comments(strip_line_comments(body or ""))
        compact = re.sub(r"\s+", " ", clean).strip()
        returns = [r.strip() for r in re.findall(r"\breturn\s+([^;]+);", clean)]
        match = re.fullmatch(r"(stmt|node)\.operands\[index\]", returns[0]) \
            if len(returns) == 1 else None
        if not match:
            fail(reasons, f"generated resolver {name} must return only model operands[index]")
            continue
        variable = match.group(1)
        if f"if (index >= {variable}.operands.size())" not in compact:
            fail(reasons, f"generated resolver {name} must bounds-check the model operand count")
        semantic_tokens = (
            f"{variable}.kind", "handler", "feature", "RequiredFeature",
            "syntax", "closeSyntax", "PrinterHandler", "dispatch", "lookup",
            "semantic", "switch", "case ", "else",
        )
        for token in semantic_tokens:
            if token in clean:
                fail(reasons, f"generated resolver {name} exposes forbidden semantic lookup surface {token!r}")
                break
        without_allowed_bounds = re.sub(
            rf"if\s*\(\s*index\s*>=\s*{variable}\.operands\.size\(\)\s*\)", "", clean)
        if re.search(r"\bif\s*\(", without_allowed_bounds):
            fail(reasons, f"generated resolver {name} must not branch except for the operand-index bounds check")


def validate_generated_printer(printer_text: str, records: dict[str, dict[str, object]], expected_target: str, reasons: list[str]) -> None:
    record_models = {str(record["model"]) for record in records.values()}
    bodies = handler_for_bodies(printer_text)
    if set(bodies) != record_models:
        fail(reasons, f"generated printer handlerFor models {sorted(bodies)} do not match "
                      f"generated record models {sorted(record_models)}")
    for model, body in bodies.items():
        compact = re.sub(r"\s+", " ", body)
        if "static_cast<int>(kind)" not in compact or "handler.ordinal == ordinal" not in compact:
            fail(reasons, "generated printer dispatch must key only on finalized projection-node kind ordinal")
        forbidden = (
            "handler.node",
            "handler.handler",
            "handler.target",
            "strcmp",
            "StringRef",
            "find(",
            "switch",
            "case ",
        )
        for token in forbidden:
            if token in body:
                fail(reasons, f"generated printer dispatch for {model} uses forbidden alternate key/surface {token!r}")
                break

    arrays = parse_generated_field_arrays(printer_text, reasons)
    enum_tables, enum_counts = parse_generated_enum_tables(printer_text, reasons)
    enum_arrays = parse_generated_enum_arrays(printer_text, reasons)
    # Each handler row carries the scalar record followed by the closed
    # repeated-field triple (listField, listInner, listOuter) — each a literal
    # C-string or `nullptr`, no expression — so the list projection cannot smuggle
    # a value-dependent join in through the generated table.
    lit_or_null = r'(?:nullptr|"(?:[^"\\]|\\.)*")'
    row_rx = re.compile(
        r'\{\s*(\d+),\s*"([^"]+)",\s*"([^"]+)",\s*"[^"]+",\s*'
        r'target_printer::LayoutKind::(\w+),\s*(true|false),\s*'
        r'"(?:[^"\\]|\\.)*",\s*"(?:[^"\\]|\\.)*",\s*'
        r'(k[A-Za-z_]\w*Fields|nullptr),\s*(\d+),\s*'
        r'(' + lit_or_null + r'),\s*(' + lit_or_null + r'),\s*(' + lit_or_null + r'),\s*'
        r'(k[A-Za-z_]\w*Enums|nullptr),\s*(\d+),\s*'
        # The FRAMED-LINES triple (): itemSyntax (literal C-string or nullptr),
        # the item-field array (or nullptr), and the item-field count — so a
        # framed-lines node cannot smuggle a value-dependent item shape through the
        # generated table. Followed by the  empty-case placeholder (a literal
        # C-string or nullptr) — likewise closed, no value-dependent empty render.
        r'(' + lit_or_null + r'),\s*(k[A-Za-z_]\w*ItemFields|nullptr),\s*(\d+),\s*'
        r'(' + lit_or_null + r')\s*\}'
    )
    rows = []
    arrays_rx = re.compile(
        r"inline\s+constexpr\s+target_printer::Handler\s+k([A-Za-z_]\w*)?Handlers\[\]\s*=\s*\{(.*?)\n\};",
        re.S)
    for array in arrays_rx.finditer(printer_text):
        prefix = array.group(1) or ""
        if prefix:
            model = prefix
        elif len(record_models) == 1:
            model = next(iter(record_models))
        else:
            fail(reasons, "multi-model generated printer must model-qualify every handler array")
            continue
        if model not in record_models:
            fail(reasons, f"generated handler array model {model} has no target-table records")
        rows.extend((model,) + row for row in row_rx.findall(array.group(2)))

    def _row_str(tok):
        # A row list token is `nullptr` (→ absent) or a quoted C-string literal.
        return "" if tok == "nullptr" else bytes(tok[1:-1], "utf-8").decode("unicode_escape")

    seen = set()
    for (model, ordinal, target, node, _layout, _leaf, field_array, count, r_lfield,
         r_linner, r_louter, enum_array, enum_count, r_isyntax, item_array,
         item_count, r_empty_item) in rows:
        identity = f"{model}::{node}"
        seen.add(identity)
        rec = records.get(identity)
        if rec is None:
            fail(reasons, f"generated handler {identity}: unreachable from target node table")
            continue
        if target != rec["target"] or (expected_target and target != expected_target):
            fail(reasons, f"generated handler {identity}: target must be literal {rec['target']!r}")
        # FRAMED-LINES (): only a framed-lines record may carry ItemSyntax /
        # ItemFields; every other layout's row must be nullptr/nullptr/0. When
        # present, the row's itemSyntax + item field array + count must match the
        # TableGen record EXACTLY (a tampered item template/binding is caught here).
        if rec["layout"] == "framed-lines":
            if _row_str(r_isyntax) != rec["itemSyntax"]:
                fail(reasons, f"generated handler {node}: itemSyntax does not match the TableGen record")
            if int(item_count) != len(rec["itemFields"]):
                fail(reasons, f"generated handler {node}: itemFieldCount {item_count} does not match table projection")
            if rec["itemFields"]:
                actual_item = arrays.get(item_array)
                if actual_item is None:
                    fail(reasons, f"generated handler {node}: item field array {item_array} is missing")
                elif actual_item != rec["itemFields"]:
                    fail(reasons, f"generated handler {node}: item field array {item_array} does not match TableGen projection")
            # The empty-case placeholder () must match the TableGen record
            # EXACTLY — a tampered empty sentinel in the .inc is caught here.
            if _row_str(r_empty_item) != rec.get("emptyItemSyntax", ""):
                fail(reasons, f"generated handler {node}: EmptyItemSyntax does not match the TableGen record")
        else:
            if r_isyntax != "nullptr" or item_array != "nullptr" or int(item_count) != 0:
                fail(reasons, f"generated handler {node}: non-framed-lines row must have nullptr itemSyntax/itemFields and count 0")
            if r_empty_item != "nullptr":
                fail(reasons, f"generated handler {node}: non-framed-lines row must have nullptr EmptyItemSyntax")
        if int(ordinal) != rec["ordinal"]:
            fail(reasons, f"generated handler {node}: ordinal {ordinal} does not match table {rec['ordinal']}")
        if int(count) != len(rec["fields"]):
            fail(reasons, f"generated handler {node}: fieldCount {count} does not match table projection")
        # The generated list triple must match the TableGen record EXACTLY — a
        # tampered separator/inner delimiter in the .inc is caught here.
        if (_row_str(r_lfield), _row_str(r_linner), _row_str(r_louter)) != (
                rec["listField"], rec["listInner"], rec["listOuter"]):
            fail(reasons, f"generated handler {node}: repeated-field (list) triple does not match the "
                          "TableGen record (listField/listInner/listOuter)")
        expected_fields = rec["fields"]
        if expected_fields:
            actual_fields = arrays.get(field_array)
            if actual_fields is None:
                fail(reasons, f"generated handler {node}: field array {field_array} is missing")
            elif actual_fields != expected_fields:
                fail(reasons, f"generated handler {node}: field array {field_array} does not match TableGen projection")
        elif field_array != "nullptr":
            fail(reasons, f"generated handler {node}: empty projection must use nullptr, not {field_array}")
        # The generated enum-field count must match the TableGen record's enum list
        # (): an enum row present in the .inc but absent from the .td record (or
        # vice versa) is a mismatch. An empty enum list must use nullptr/0.
        expected_enums = rec.get("enumFields", [])
        if int(enum_count) != len(expected_enums):
            fail(reasons, f"generated handler {node}: enumFieldCount {enum_count} does not match "
                          f"the TableGen record's {len(expected_enums)} enum field(s)")
        if not expected_enums and enum_array != "nullptr":
            fail(reasons, f"generated handler {node}: empty enum projection must use nullptr, not {enum_array}")
        elif expected_enums and enum_array == "nullptr":
            fail(reasons, f"generated handler {node}: enum projection must reference a generated enum array, not nullptr")
        elif expected_enums:
            # IDENTITY-for-identity reconciliation ( review P1.3): each generated
            # descriptor — spelling table + count symbol, repeated flag, inner
            # separator, prefix, groupIndex — AND the referenced spelling-table
            # contents must match the TableGen record EXACTLY. A hand-edited/swapped
            # generated enum table (a changed groupIndex, flipped repeated flag,
            # tampered separator/prefix, or a duplicated/reordered spelling) is
            # caught here, not left to a downstream stale-output gate.
            gen_descs = enum_arrays.get(enum_array)
            if gen_descs is None:
                fail(reasons, f"generated handler {node}: enum array {enum_array} is missing")
            elif len(gen_descs) != len(expected_enums):
                fail(reasons, f"generated handler {node}: enum array {enum_array} has "
                              f"{len(gen_descs)} descriptor(s), TableGen record has {len(expected_enums)}")
            else:
                for i, (gd, spec) in enumerate(zip(gen_descs, expected_enums)):
                    want_spell = "k" + str(spec["spelling"])
                    tag = f"generated handler {node}: enum field #{i} ({spec['name']})"
                    if gd["name"] != spec["name"]:
                        fail(reasons, f"{tag}: name {gd['name']!r} does not match TableGen {spec['name']!r}")
                    if gd["spellingSym"] != want_spell:
                        fail(reasons, f"{tag}: spelling table {gd['spellingSym']} does not match TableGen {want_spell}")
                    if gd["countSym"] != want_spell + "Count":
                        fail(reasons, f"{tag}: count symbol {gd['countSym']} does not match {want_spell}Count")
                    if gd["repeated"] != spec["repeated"]:
                        fail(reasons, f"{tag}: repeated flag {gd['repeated']} does not match TableGen {spec['repeated']}")
                    if gd["inner"] != spec["inner"]:
                        fail(reasons, f"{tag}: inner separator {gd['inner']!r} does not match TableGen {spec['inner']!r}")
                    if gd["prefix"] != spec["prefix"]:
                        fail(reasons, f"{tag}: prefix {gd['prefix']!r} does not match TableGen {spec['prefix']!r}")
                    if gd["groupIndex"] != i:
                        fail(reasons, f"{tag}: groupIndex {gd['groupIndex']} is not the field's position {i}")
                    # The referenced generated spelling TABLE + its count must match
                    # the TableGen EnumSpelling ordinal-for-ordinal.
                    gen_spellings = enum_tables.get(gd["spellingSym"])
                    if gen_spellings is None:
                        fail(reasons, f"{tag}: spelling table {gd['spellingSym']} is missing")
                    elif gen_spellings != list(spec["spellings"]):
                        fail(reasons, f"{tag}: spelling table {gd['spellingSym']} {gen_spellings} does not "
                                      f"match TableGen EnumSpelling {list(spec['spellings'])}")
                    gen_count = enum_counts.get(gd["countSym"])
                    if gen_count is None:
                        fail(reasons, f"{tag}: count constant {gd['countSym']} is missing")
                    elif gen_count != len(spec["spellings"]):
                        fail(reasons, f"{tag}: count {gd['countSym']}={gen_count} does not match "
                                      f"{len(spec['spellings'])} TableGen spelling(s)")
    # Every generated enum array + spelling table must be REACHABLE from a handler
    # row's enum reference (no dangling generated enum data).
    used_enum_arrays = {row[11] for row in rows if row[11] != "nullptr"}
    unused_enum_arrays = sorted(n for n, d in enum_arrays.items() if n not in used_enum_arrays and d)
    if unused_enum_arrays:
        fail(reasons, f"generated enum array(s) are unreachable from handler rows: {unused_enum_arrays}")
    reachable_spell = {gd["spellingSym"] for n in used_enum_arrays for gd in enum_arrays.get(n, [])}
    unused_spell = sorted(n for n, s in enum_tables.items() if n not in reachable_spell and s)
    if unused_spell:
        fail(reasons, f"generated spelling table(s) are unreachable from enum descriptors: {unused_spell}")
    missing = sorted(n for n in records if n not in seen)
    if missing:
        fail(reasons, f"target table record(s) missing generated handler row(s): {missing}")
    # Reachable field arrays come from BOTH the scalar field-array column (row[5])
    # AND the framed-lines item-field-array column (row[13], ) — the two share
    # the one `arrays` table, so a dangling item-field array is caught here too.
    used_arrays = ({row[6] for row in rows if row[6] != "nullptr"}
                   | {row[14] for row in rows if row[14] != "nullptr"})
    unused_arrays = sorted(name for name, fields in arrays.items() if name not in used_arrays and fields)
    if unused_arrays:
        fail(reasons, f"generated field array(s) are unreachable from handler rows: {unused_arrays}")
    all_models = set()
    for record in records.values():
        all_models.update(record.get("allModels", []))
    expected_resolvers = {
        (f"resolve{model}Field" if len(all_models) > 1 else "resolveField")
        for model in record_models
    }
    validate_resolve_field(printer_text, reasons, expected_resolvers)


def validate_driver(driver_cpp: str, reasons: list[str]) -> None:
    # The generic driver may branch only on table-owned structure (layout, field
    # count, placeholder expansion). It must not know target node kinds or model
    # types, and it must not expose a semantic lookup / predicate callback.
    if "SolStmt" in driver_cpp or "Postgres" in driver_cpp or "PgStmt" in driver_cpp:
        fail(reasons, "generic target-printer driver contains target-specific model names")
    body = strip_c_comments(strip_line_comments(driver_cpp))
    forbidden_api = ("Predicate", "predicate", "semantic", "lookup", "dispatchKey")
    for token in forbidden_api:
        if re.search(rf"\b{re.escape(token)}\b", body):
            fail(reasons, f"generic target-printer driver exposes forbidden decision API token {token!r}")
            break
    if re.search(r"\bmode\b", body):
        fail(reasons, "generic target-printer driver exposes forbidden decision API token 'mode'")


def check_one(schema: Path, td: Path, printer: Path, driver_h: Path, driver_cpp: Path) -> list[str]:
    reasons: list[str] = []
    validate_schema(read(schema), read(driver_h), reasons)
    td_text = read(td)
    records = validate_td(td_text, reasons)
    _, target, _ = discover_wrapper(strip_line_comments(td_text))
    validate_generated_printer(read(printer), records, target or "", reasons)
    validate_driver(read(driver_cpp), reasons)
    return reasons


def discovered_backend_pairs(reasons: list[str]) -> list[tuple[Path, Path]]:
    root = REPO / "lib/backends"
    td_files = sorted(
        p for p in root.glob("**/*TargetNodes.td")
        if "TargetPrinter.td" in read(p) or "TargetPrinterNode" in read(p)
    )
    # : generated printers live in the BUILD tree. Discovery follows them
    # there, so the pairing below compares the same artifacts the compiler
    # consumes rather than finding nothing and reporting an empty inventory.
    printer_files = sorted(root.glob("**/*PrinterHandlers.inc"))
    if BUILD_DIR:
        build_root = Path(BUILD_DIR) / rel(root)
        printer_files = sorted(
            set(printer_files) | set(build_root.glob("**/*PrinterHandlers.inc")))
    pairs: list[tuple[Path, Path]] = []
    expected_printers: set[Path] = set()
    for td in td_files:
        if not td.name.endswith("TargetNodes.td"):
            fail(reasons, f"{rel(td)}: target-printer idiom table must use *TargetNodes.td naming")
            continue
        #  R1/R4: the generated printer lives beside the .td, except when the
        # backend is split into role subdirs — then the .td is in model/ and its
        # generated printer is in the sibling generated/. Flat backends are
        # unchanged (same-dir pairing).
        stem = td.name.replace("TargetNodes.td", "PrinterHandlers.inc")
        if td.parent.name == "model":
            printer = td.parent.parent / "generated" / stem
        else:
            printer = td.with_name(stem)
        # : if that derived path names a migrated artifact, its real
        # location is the build tree. Resolving here keeps ONE derivation rule
        # rather than a source rule and a build rule that can disagree.
        derived_rel = rel(printer)
        if generated_artifacts.is_migrated(derived_rel) and BUILD_DIR:
            printer = Path(generated_artifacts.resolve(derived_rel, BUILD_DIR))
        expected_printers.add(printer)
        printer_rel = rel(printer)
        try:
            exists = (bool(generated_artifacts.resolve(printer_rel, BUILD_DIR))
                      if generated_artifacts.is_migrated(printer_rel)
                      else printer.exists())
        except generated_artifacts.GeneratedArtifactError:
            exists = False
        if not exists:
            fail(reasons, f"{rel(td)}: missing paired generated printer {rel(printer)}")
            continue
        pairs.append((td, printer))
    unknown = sorted(p for p in printer_files if p not in expected_printers)
    for printer in unknown:
        fail(reasons, f"{rel(printer)}: generated printer has no paired *TargetNodes.td idiom table")
    if not pairs:
        fail(reasons, "no governed target-printer idiom tables were discovered")
    return pairs


def check_discovered(schema: Path, driver_h: Path, driver_cpp: Path) -> list[str]:
    reasons: list[str] = []
    validate_schema(read(schema), read(driver_h), reasons)
    validate_driver(read(driver_cpp), reasons)
    for td, printer in discovered_backend_pairs(reasons):
        td_text = read(td)
        records = validate_td(td_text, reasons)
        _, target, _ = discover_wrapper(strip_line_comments(td_text))
        validate_generated_printer(read(printer), records, target or "", reasons)
    return reasons


def check(schema: Path, td: Path | None, printer: Path | None, driver_h: Path, driver_cpp: Path) -> list[str]:
    if td is None and printer is None:
        return check_discovered(schema, driver_h, driver_cpp)
    if td is None or printer is None:
        return ["--td and --printer must be provided together"]
    return check_one(schema, td, printer, driver_h, driver_cpp)


def expect_probe_failure(name: str, mutate, needle: str, failures: list[str]) -> None:
    tmp = Path(tempfile.mkdtemp(prefix=f"idiom_table_{name}."))
    try:
        schema = tmp / "TargetPrinter.td"
        td = tmp / "SolidityTargetNodes.td"
        printer = tmp / "SolidityPrinterHandlers.inc"
        driver_h = tmp / "TargetPrinter.h"
        driver_cpp = tmp / "TargetPrinter.cpp"
        shutil.copyfile(SCHEMA, schema)
        shutil.copyfile(TD, td)
        printer.write_text(read(PRINTER), encoding="utf-8")
        shutil.copyfile(DRIVER_H, driver_h)
        shutil.copyfile(DRIVER_CPP, driver_cpp)
        mutate(schema, td, printer, driver_h, driver_cpp)
        reasons = check(schema, td, printer, driver_h, driver_cpp)
        if not reasons:
            failures.append(f"{name}: expected failure, got success")
        elif not any(needle in r for r in reasons):
            failures.append(f"{name}: expected {needle!r}, got {reasons}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def selftest() -> int:
    failures: list[str] = []
    clean = check(SCHEMA, TD, PRINTER, DRIVER_H, DRIVER_CPP)
    if clean:
        failures.append(f"clean gate failed: {clean}")

    def mode_selector(schema, _td, _printer, _driver_h, _driver_cpp):
        text = schema.read_text(encoding="utf-8")
        text = text.replace("bit GeneratedHandler = generated;", "bit GeneratedHandler = generated;\n  string Mode = \"runtime\";")
        schema.write_text(text, encoding="utf-8")

    def conditional(_schema, td, _printer, _driver_h, _driver_cpp):
        text = td.read_text(encoding="utf-8")
        text = text.replace('"${lhs} ${op} ${rhs};"', '!if(!eq(FOp, "+="), "${lhs} += ${rhs};", "${lhs} -= ${rhs};")')
        td.write_text(text, encoding="utf-8")

    def dispatch_key(_schema, _td, printer, _driver_h, _driver_cpp):
        text = printer.read_text(encoding="utf-8")
        text = text.replace("if (handler.ordinal == ordinal)", 'if (std::string(handler.node) == "Require")')
        printer.write_text(text, encoding="utf-8")

    def extra_operand(_schema, td, _printer, _driver_h, _driver_cpp):
        text = td.read_text(encoding="utf-8")
        text = text.replace('def FAsgnRhs   : PrinterField<"rhs",       1>;', 'def FAsgnRhs   : PrinterField<"rhs",       2>;')
        td.write_text(text, encoding="utf-8")

    def field_array_mismatch(_schema, _td, printer, _driver_h, _driver_cpp):
        text = printer.read_text(encoding="utf-8")
        text = text.replace('{"op", 1, nullptr },', '{"mode", 1, nullptr },')
        printer.write_text(text, encoding="utf-8")

    def resolver_semantic_lookup(_schema, _td, printer, _driver_h, _driver_cpp):
        text = printer.read_text(encoding="utf-8")
        text = text.replace(
            "const SolStmt &stmt = *static_cast<const SolStmt *>(model);",
            "const SolStmt &stmt = *static_cast<const SolStmt *>(model);\n"
            "  if (stmt.kind == SolStmt::Kind::CompoundAssign && index == 1)\n"
            "    return \"+=\";",
        )
        printer.write_text(text, encoding="utf-8")

    #  review P1.3: the enum spelling table + each generated descriptor is
    # reconciled identity-for-identity against the `.td`. Each probe tampers ONE
    # facet and must be rejected.
    def enum_duplicate_spelling(_schema, td, _printer, _driver_h, _driver_cpp):
        text = td.read_text(encoding="utf-8")
        text = text.replace('["function", "constructor"]', '["function", "function"]')
        td.write_text(text, encoding="utf-8")

    def enum_swap_spelling(_schema, _td, printer, _driver_h, _driver_cpp):
        text = printer.read_text(encoding="utf-8")
        text = text.replace('  "function",\n  "constructor",', '  "constructor",\n  "function",')
        printer.write_text(text, encoding="utf-8")

    def enum_groupindex(_schema, _td, printer, _driver_h, _driver_cpp):
        text = printer.read_text(encoding="utf-8")
        text = text.replace(', true, " ", " ", 1 },', ', true, " ", " ", 0 },')
        printer.write_text(text, encoding="utf-8")

    def enum_repeated_flag(_schema, _td, printer, _driver_h, _driver_cpp):
        text = printer.read_text(encoding="utf-8")
        text = text.replace(', true, " ", " ", 1 },', ', false, " ", " ", 1 },')
        printer.write_text(text, encoding="utf-8")

    def enum_separator(_schema, _td, printer, _driver_h, _driver_cpp):
        text = printer.read_text(encoding="utf-8")
        text = text.replace(', true, " ", " ", 1 },', ', true, "|", " ", 1 },')
        printer.write_text(text, encoding="utf-8")

    def enum_prefix(_schema, _td, printer, _driver_h, _driver_cpp):
        text = printer.read_text(encoding="utf-8")
        text = text.replace(', true, " ", " ", 1 },', ', true, " ", "|", 1 },')
        printer.write_text(text, encoding="utf-8")

    #  ( re-precision): the `let`/bang checks now mask string literals and
    # permit in-record literal `let` field-overrides. These four probes prove the
    # tightened checks still bite the genuine attacks (a `!` inside a guard STRING
    # is data; a bang/scope/reference OUTSIDE strings is not).
    def let_rebinding_scope(_schema, td, _printer, _driver_h, _driver_cpp):
        # A top-level `let ... in` rebinds a field across records — forbidden.
        text = td.read_text(encoding="utf-8")
        text = text + '\nlet BuilderName = "rebind" in def __ProbeRebind;\n'
        td.write_text(text, encoding="utf-8")

    def let_nonliteral_rhs(_schema, td, _printer, _driver_h, _driver_cpp):
        # An in-record `let` whose RHS is a def reference (not a literal).
        text = td.read_text(encoding="utf-8")
        text = text.replace('let BuilderName = "blank";', "let BuilderName = SomeDefRef;")
        td.write_text(text, encoding="utf-8")

    def bang_outside_string(_schema, td, _printer, _driver_h, _driver_cpp):
        # A real bang operator in a field value (outside any string literal).
        text = td.read_text(encoding="utf-8")
        text = text.replace('let BuilderName = "blank";',
                            'let BuilderName = !strconcat("bl", "ank");')
        td.write_text(text, encoding="utf-8")

    def control_keyword_construct(_schema, td, _printer, _driver_h, _driver_cpp):
        # A genuine TableGen control/code construct (defvar) is never literal data.
        text = td.read_text(encoding="utf-8")
        text = text + "\ndefvar __ProbeVar = 1;\n"
        td.write_text(text, encoding="utf-8")

    expect_probe_failure("disguised-mode-selector", mode_selector, "closed handler record", failures)
    expect_probe_failure("generated-field-array-mismatch", field_array_mismatch, "field array", failures)
    expect_probe_failure("generated-resolver-semantic-lookup", resolver_semantic_lookup, "resolveField", failures)
    expect_probe_failure("value-dependent-conditional", conditional, "literal strings", failures)
    expect_probe_failure("alternate-dispatch-key", dispatch_key, "finalized projection-node kind ordinal", failures)
    expect_probe_failure("unconsumed-extra-operand", extra_operand, "dense", failures)
    expect_probe_failure("enum-duplicate-spelling", enum_duplicate_spelling, "duplicate spelling", failures)
    expect_probe_failure("enum-swap-spelling", enum_swap_spelling, "spelling table", failures)
    expect_probe_failure("enum-tampered-groupindex", enum_groupindex, "groupIndex", failures)
    expect_probe_failure("enum-flipped-repeated-flag", enum_repeated_flag, "repeated flag", failures)
    expect_probe_failure("enum-tampered-separator", enum_separator, "inner separator", failures)
    expect_probe_failure("enum-tampered-prefix", enum_prefix, "prefix", failures)
    expect_probe_failure("let-rebinding-scope", let_rebinding_scope, "rebinding scope", failures)
    expect_probe_failure("let-nonliteral-rhs", let_nonliteral_rhs, "non-literal RHS", failures)
    expect_probe_failure("bang-outside-string", bang_outside_string, "bang operators", failures)
    expect_probe_failure("control-keyword-construct", control_keyword_construct, "control/code constructs", failures)

    tmp = Path(tempfile.mkdtemp(prefix="idiom_table_undiscovered_backend."))
    try:
        shutil.copyfile(SCHEMA, tmp / "TargetPrinter.td")
        shutil.copyfile(DRIVER_H, tmp / "TargetPrinter.h")
        shutil.copyfile(DRIVER_CPP, tmp / "TargetPrinter.cpp")
        backend = tmp / "lib/backends/postgres"
        backend.mkdir(parents=True)
        planted = backend / "PostgresTargetNodes.td"
        (backend / "PostgresPrinterHandlers.inc").write_text(
            read(PRINTER), encoding="utf-8")
        planted.write_text(
            read(TD).replace(
                "class SolNode<int ord, string handler, bit leaf, string feature,",
                "class SolNode<int ord, string handler, bit leaf, string feature, string Mode = \"runtime\",",
            ),
            encoding="utf-8",
        )
        old_repo = globals()["REPO"]
        globals()["REPO"] = tmp
        try:
            reasons = check_discovered(tmp / "TargetPrinter.td", tmp / "TargetPrinter.h", tmp / "TargetPrinter.cpp")
        finally:
            globals()["REPO"] = old_repo
        if not reasons:
            failures.append("undiscovered-backend-table: expected failure, got success")
        elif not any("SolNode wrapper schema" in r for r in reasons):
            failures.append(f"undiscovered-backend-table: expected wrapper schema failure, got {reasons}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # `Lines`-layout () non-vacuous probes, over the TEST-ONLY fixture. The
    # gate validates the record as a closed literal idiom (its multi-line Syntax
    # is data, not a schema); a MUTATED multi-line record and a
    # conditional/operand-driven line must both be rejected.
    fixture = read(LINES_FIXTURE_TD)
    accept_reasons: list[str] = []
    validate_td(fixture, accept_reasons)
    if accept_reasons:
        failures.append(f"lines-fixture-accepted: expected the closed Lines fixture to validate, got {accept_reasons}")

    def lines_probe(name, mutate, needle):
        mutated = mutate(fixture)
        if mutated == fixture:
            failures.append(f"{name}: mutation was vacuous (fixture unchanged)")
            return
        reasons: list[str] = []
        validate_td(mutated, reasons)
        if not reasons:
            failures.append(f"{name}: expected rejection, got success")
        elif not any(needle in r for r in reasons):
            failures.append(f"{name}: expected {needle!r}, got {reasons}")

    # A placeholder on the middle line rebound to an UNDECLARED field: the
    # mutated multi-line idiom is rejected.
    lines_probe("lines-undeclared-placeholder",
                lambda t: t.replace("${middle}", "${ghost}"),
                "undeclared field")
    # An operand-driven / conditional LINE selection (a TableGen bang operator)
    # is a decision, not a fixed literal idiom — rejected.
    lines_probe("lines-conditional-line",
                lambda t: t.replace(
                    '"first line\\nmiddle ${middle} line\\nthird line"',
                    '!if(!eq(ord, 0), "first line\\n${middle}", "other\\n${middle}")'),
                "bang operators")

    # `framed-lines` () non-vacuous probes, over the TEST-ONLY fixture. The
    # gate validates the closed framed-lines record; a Header with a placeholder
    # (not fixed literal), an operand-value-driven item (a bang op), and a
    # non-dense item field set must all be rejected.
    framed = read(FRAMED_LINES_FIXTURE_TD)
    framed_accept: list[str] = []
    validate_td(framed, framed_accept)
    if framed_accept:
        failures.append(f"framed-fixture-accepted: expected the closed framed-lines fixture to validate, got {framed_accept}")

    def framed_probe(name, mutate, needle):
        mutated = mutate(framed)
        if mutated == framed:
            failures.append(f"{name}: mutation was vacuous (fixture unchanged)")
            return
        reasons: list[str] = []
        validate_td(mutated, reasons)
        if not reasons:
            failures.append(f"{name}: expected rejection, got success")
        elif not any(needle in r for r in reasons):
            failures.append(f"{name}: expected {needle!r}, got {reasons}")

    # Header must be fixed literal — a `${...}` placeholder in it is a projection
    # (a decision channel), rejected.
    framed_probe("framed-header-placeholder",
                 lambda t: t.replace('/*header=*/"CASE p_policy"',
                                     '/*header=*/"CASE ${input}"'),
                 "Header/Footer must be fixed literal")
    # An operand-value-driven item (a TableGen bang operator in ItemSyntax) is a
    # decision, not a fixed item shape — rejected.
    framed_probe("framed-value-driven-item",
                 lambda t: t.replace(
                     '"  WHEN ${input} THEN v_set := ${set}; v_m := ${quorum};"',
                     '!if(!eq(ord, 0), "  WHEN ${input}", "  ELSE ${input}")'),
                 "bang operators")
    # A non-dense item field set (drop index 1) — the tuple would be
    # under-projected; rejected.
    framed_probe("framed-non-dense-item-fields",
                 lambda t: t.replace("[FInput, FSet, FQuorum]", "[FInput, FQuorum]"),
                 "not dense")
    if failures:
        print("idiom-table capability gate FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print("idiom-table capability selftest PASS (closed schema + literal records + ordinal-only dispatch + dense operands + Lines fixed-shape + framed-lines fixed-frame)")
    return 0


def run_probe(probe_id: str) -> int:
    if probe_id not in TAMPER_IDS:
        print(f"unknown idiom-table capability probe {probe_id}", file=sys.stderr)
        return 2

    if probe_id == "second-wrapper-hidden-record":
        td = read(REPO / "lib/backends/postgres/model/PostgresTargetNodes.td")
        printer = read(REPO / "lib/backends/postgres/generated/PostgresPrinterHandlers.inc")
        injected = td + '''
def HiddenSchema : PgSchemaNode<0, "hidden-schema", 1, "schema",
                                "line", "CREATE TYPE hidden AS ENUM ('x');",
                                [], 1>;
'''
        reasons: list[str] = []
        records = validate_td(injected, reasons)
        validate_generated_printer(printer, records, "postgres", reasons)
        if any("PgSchemaDecl::HiddenSchema" in reason for reason in reasons):
            print(f"probe-failed-as-expected:{probe_id}")
            return 1
        print(f"probe unexpectedly passed or failed setup for {probe_id}: {reasons}",
              file=sys.stderr)
        return 0

    if probe_id == "undiscovered-backend-table":
        failures: list[str] = []
        tmp = Path(tempfile.mkdtemp(prefix="idiom_table_undiscovered_backend."))
        try:
            shutil.copyfile(SCHEMA, tmp / "TargetPrinter.td")
            shutil.copyfile(DRIVER_H, tmp / "TargetPrinter.h")
            shutil.copyfile(DRIVER_CPP, tmp / "TargetPrinter.cpp")
            backend = tmp / "lib/backends/postgres"
            backend.mkdir(parents=True)
            (backend / "PostgresPrinterHandlers.inc").write_text(
                read(PRINTER), encoding="utf-8")
            (backend / "PostgresTargetNodes.td").write_text(
                read(TD).replace(
                    "class SolNode<int ord, string handler, bit leaf, string feature,",
                    "class SolNode<int ord, string handler, bit leaf, string feature, string Mode = \"runtime\",",
                ),
                encoding="utf-8",
            )
            old_repo = globals()["REPO"]
            globals()["REPO"] = tmp
            try:
                reasons = check_discovered(tmp / "TargetPrinter.td", tmp / "TargetPrinter.h", tmp / "TargetPrinter.cpp")
            finally:
                globals()["REPO"] = old_repo
            if not reasons or not any("SolNode wrapper schema" in r for r in reasons):
                failures.append(f"expected discovered backend schema failure, got {reasons}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        if failures:
            print(f"probe unexpectedly passed or failed setup for {probe_id}: {failures}", file=sys.stderr)
            return 0
        print(f"probe-failed-as-expected:{probe_id}")
        return 1

    mutations = {
        "disguised-mode-selector": lambda schema, td, printer, driver_h, driver_cpp:
            schema.write_text(schema.read_text(encoding="utf-8").replace(
                "bit GeneratedHandler = generated;",
                "bit GeneratedHandler = generated;\n  string Mode = \"runtime\";"), encoding="utf-8"),
        "generated-field-array-mismatch": lambda schema, td, printer, driver_h, driver_cpp:
            printer.write_text(printer.read_text(encoding="utf-8").replace(
                '{"op", 1, nullptr },',
                '{"mode", 1, nullptr },'), encoding="utf-8"),
        "generated-resolver-semantic-lookup": lambda schema, td, printer, driver_h, driver_cpp:
            printer.write_text(printer.read_text(encoding="utf-8").replace(
                "const SolStmt &stmt = *static_cast<const SolStmt *>(model);",
                "const SolStmt &stmt = *static_cast<const SolStmt *>(model);\n"
                "  if (stmt.kind == SolStmt::Kind::CompoundAssign && index == 1)\n"
                "    return \"+=\";"), encoding="utf-8"),
        "value-dependent-conditional": lambda schema, td, printer, driver_h, driver_cpp:
            td.write_text(td.read_text(encoding="utf-8").replace(
                '"${lhs} ${op} ${rhs};"',
                '!if(!eq(FOp, "+="), "${lhs} += ${rhs};", "${lhs} -= ${rhs};")'), encoding="utf-8"),
        "alternate-dispatch-key": lambda schema, td, printer, driver_h, driver_cpp:
            printer.write_text(printer.read_text(encoding="utf-8").replace(
                "if (handler.ordinal == ordinal)",
                'if (std::string(handler.node) == "Require")'), encoding="utf-8"),
        "unconsumed-extra-operand": lambda schema, td, printer, driver_h, driver_cpp:
            td.write_text(td.read_text(encoding="utf-8").replace(
                'def FAsgnRhs   : PrinterField<"rhs",       1>;',
                'def FAsgnRhs   : PrinterField<"rhs",       2>;'), encoding="utf-8"),
        "let-rebinding-scope": lambda schema, td, printer, driver_h, driver_cpp:
            td.write_text(td.read_text(encoding="utf-8") +
                          '\nlet BuilderName = "rebind" in def __ProbeRebind;\n', encoding="utf-8"),
        "let-nonliteral-rhs": lambda schema, td, printer, driver_h, driver_cpp:
            td.write_text(td.read_text(encoding="utf-8").replace(
                'let BuilderName = "blank";', "let BuilderName = SomeDefRef;"), encoding="utf-8"),
        "bang-outside-string": lambda schema, td, printer, driver_h, driver_cpp:
            td.write_text(td.read_text(encoding="utf-8").replace(
                'let BuilderName = "blank";',
                'let BuilderName = !strconcat("bl", "ank");'), encoding="utf-8"),
        "control-keyword-construct": lambda schema, td, printer, driver_h, driver_cpp:
            td.write_text(td.read_text(encoding="utf-8") +
                          "\ndefvar __ProbeVar = 1;\n", encoding="utf-8"),
    }
    failures: list[str] = []
    expect_probe_failure(probe_id, mutations[probe_id], "", failures)
    if failures:
        print(f"probe unexpectedly passed or failed setup for {probe_id}: {failures}", file=sys.stderr)
        return 0
    print(f"probe-failed-as-expected:{probe_id}")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="closed idiom-table capability gate ()")
    generated_artifacts.add_build_dir_argument(ap)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--probe", choices=sorted(TAMPER_IDS))
    ap.add_argument("--schema", default=str(SCHEMA))
    ap.add_argument("--td")
    ap.add_argument("--printer")
    ap.add_argument("--driver-header", default=str(DRIVER_H))
    ap.add_argument("--driver-cpp", default=str(DRIVER_CPP))
    args = ap.parse_args(argv)
    global BUILD_DIR
    if args.build_dir:
        BUILD_DIR = os.path.abspath(args.build_dir)
    if args.probe:
        return run_probe(args.probe)
    if args.selftest:
        return selftest()
    reasons = check(
        Path(args.schema),
        Path(args.td) if args.td else None,
        Path(args.printer) if args.printer else None,
        Path(args.driver_header),
        Path(args.driver_cpp),
    )
    if reasons:
        print("idiom-table capability gate FAILED:", file=sys.stderr)
        for r in reasons:
            print(f"    {r}", file=sys.stderr)
        return 1
    print("idiom-table capability gate OK: table schema/data are closed literal idioms with dense positional operand bindings and ordinal-only dispatch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
