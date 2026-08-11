#!/usr/bin/env python3
"""Canonical recipe-record grammar, parser, and re-emitter ( R5a).

Closed production surface only: `TargetIdiomRecipe` rows owned by a backend
package's recipe `.td` files. Explicit residue (never reconstructed from
llvm-tblgen dump-json alone):

  * TableGen includes, comments, macros, and class templates
  * TargetNode / FinalizedType / leaf-hook registrations
  * Arbitrary original source spelling outside the recipe-record fields

The canonical IR is pure data: identity, key tuple, typed inputs, result
cardinality, and the closed body grammar (Sequence of Emit / ForEach /
OptionalOp / Call with Direct / Hook / Nested bindings). Two canonicalize
runs over the same dump-json view are byte-identical. Re-emission produces a
deterministic TableGen `def` that dump-json's to the same IR.

Usage (library + CLI):
  recipe_canonicalizer.py --td PATH --tblgen PATH -I DIR ... --emit-json
  recipe_canonicalizer.py --td PATH --tblgen PATH -I DIR ... --emit-td
  recipe_canonicalizer.py --td PATH --tblgen PATH -I DIR ... --canonicalize-files
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

GRAMMAR_KIND = "neutrino.recipe-record"
GRAMMAR_SCHEMA_VERSION = 1
OP_KINDS = frozenset({"Emit", "ForEach", "Optional", "Call"})
BIND_KINDS = frozenset({"Direct", "Hook", "Nested"})
SLOT_CARD = frozenset({"one", "optional", "many"})

# Production Solidity recipe corpus roots (relative to repo).
SOLIDITY_RECIPE_ROOT = Path("lib/backends/solidity/recipes")
SOLIDITY_ENTRY_TD = SOLIDITY_RECIPE_ROOT / "SolidityIdiomRecipes.td"
SOLIDITY_CORPUS = (
    SOLIDITY_RECIPE_ROOT / "SolidityIdiomRecipes.td",
    SOLIDITY_RECIPE_ROOT / "SolidityTemporalIdiomRecipes.td",
    SOLIDITY_RECIPE_ROOT / "SolidityEffectfulIdiomRecipes.td",
    SOLIDITY_RECIPE_ROOT / "SolidityEvidenceIdiomRecipes.td",
)


def die(msg: str) -> None:
    sys.stderr.write(f"recipe_canonicalizer: {msg}\n")
    sys.exit(1)


def compact(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def render(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_records(td: Path, includes: list[str], tblgen: str) -> dict:
    cmd = [tblgen, "--dump-json", str(td)]
    for inc in includes:
        cmd += ["-I", inc]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode:
        die("llvm-tblgen failed:\n" + proc.stderr.decode("utf-8", "replace"))
    return json.loads(proc.stdout)


def deref(d: dict, v: Any) -> Any:
    if isinstance(v, dict) and v.get("kind") == "def":
        name = v["def"]
        if name not in d or not isinstance(d[name], dict):
            die(f"dangling def ref {name!r}")
        return d[name]
    return v


def _field(rec: dict, name: str, default: Any = None) -> Any:
    return rec[name] if name in rec else default


# ---- IR extraction ----------------------------------------------------------


def _input_slot(d: dict, ref: Any) -> dict:
    rec = deref(d, ref)
    card = _field(rec, "Cardinality", "")
    if card not in SLOT_CARD:
        die(f"input slot has unknown cardinality {card!r}")
    slot = {
        "name": _field(rec, "Name", ""),
        "finalizedType": _field(rec, "FinalizedType", ""),
        "cardinality": card,
        "min": int(_field(rec, "Min", 0)),
        "max": str(_field(rec, "Max", "0")),
        "orderKey": str(_field(rec, "OrderKey", "") or ""),
        "parentSlot": str(_field(rec, "ParentSlot", "") or ""),
    }
    # RelatedOptional presence ordinal (closed PostingPresence).
    if "Presence" in rec:
        slot["presence"] = int(rec["Presence"])
    if not slot["name"] or not slot["finalizedType"]:
        die(f"input slot missing name/type: {slot!r}")
    return slot


def _binding(d: dict, ref: Any) -> dict:
    rec = deref(d, ref)
    kind = _field(rec, "BindKind", "")
    if kind not in BIND_KINDS:
        die(f"unknown binding kind {kind!r}")
    field = _field(rec, "Field", "")
    if not field:
        die("binding missing Field")
    out: dict[str, Any] = {"bindKind": kind, "field": field}
    if kind == "Direct":
        out["input"] = _field(rec, "Input", "")
        if not out["input"]:
            die(f"Direct binding {field!r} missing Input")
    elif kind == "Hook":
        out["hookId"] = _field(rec, "HookId", "")
        out["input"] = _field(rec, "Input", "")
        if not out["hookId"] or not out["input"]:
            die(f"Hook binding {field!r} incomplete")
    else:  # Nested
        out["body"] = _body(d, _field(rec, "Body"))
    return out


def _op(d: dict, ref: Any) -> dict:
    rec = deref(d, ref)
    kind = _field(rec, "OpKind", "")
    if kind not in OP_KINDS:
        die(f"unknown op kind {kind!r}")
    if kind == "Emit":
        node = _field(rec, "Node", "")
        if not node:
            die("Emit missing Node")
        binds = [_binding(d, b) for b in (_field(rec, "Bindings") or [])]
        return {"opKind": "Emit", "node": node, "bindings": binds}
    if kind == "Call":
        rid = _field(rec, "RecipeId", "")
        if not rid:
            die("Call missing RecipeId")
        binds = [_binding(d, b) for b in (_field(rec, "Bindings") or [])]
        return {"opKind": "Call", "recipeId": rid, "bindings": binds}
    if kind == "ForEach":
        slot = _field(rec, "Slot", "")
        if not slot:
            die("ForEach missing Slot")
        return {"opKind": "ForEach", "slot": slot, "body": _body(d, _field(rec, "Body"))}
    # Optional (OptionalOp in TD)
    slot = _field(rec, "Slot", "")
    if not slot:
        die("Optional missing Slot")
    return {"opKind": "Optional", "slot": slot, "body": _body(d, _field(rec, "Body"))}


def _body(d: dict, ref: Any) -> dict:
    rec = deref(d, ref)
    ops = _field(rec, "Ops")
    if not isinstance(ops, list) or not ops:
        die("empty Sequence body is forbidden")
    return {"ops": [_op(d, o) for o in ops]}


def _result_cardinality(d: dict, rec: dict) -> dict:
    rc = deref(d, _field(rec, "ResultCardinality"))
    spelling = _field(rc, "Spelling", "")
    out: dict[str, Any] = {"spelling": spelling}
    if spelling == "many":
        out["min"] = int(_field(rc, "Min", 0))
        out["max"] = str(_field(rc, "Max", "0"))
    elif spelling not in ("one", "optional"):
        # Named CardinalityOne / CardinalityOptional defs only carry Spelling.
        if not spelling:
            die(f"result cardinality missing Spelling: {rc!r}")
    return out


def extract_recipe(d: dict, def_name: str) -> dict:
    rec = d[def_name]
    if "TargetIdiomRecipe" not in (rec.get("!superclasses") or []):
        die(f"{def_name} is not a TargetIdiomRecipe")
    if rec.get("!anonymous"):
        die(f"{def_name} is anonymous; production recipes must be named defs")
    inputs = [_input_slot(d, s) for s in (_field(rec, "Inputs") or [])]
    ir = {
        "kind": GRAMMAR_KIND,
        "schemaVersion": GRAMMAR_SCHEMA_VERSION,
        "defName": def_name,
        "recipeId": _field(rec, "RecipeId", ""),
        "target": _field(rec, "Target", ""),
        "finalizedKind": _field(rec, "FinalizedKind", ""),
        "mode": _field(rec, "Mode", ""),
        "role": _field(rec, "Role", ""),
        "schemaVersionField": int(_field(rec, "SchemaVersion", 1)),
        "inputs": inputs,
        "resultType": _field(rec, "ResultType", ""),
        "resultCardinality": _result_cardinality(d, rec),
        "body": _body(d, _field(rec, "Body")),
    }
    if not ir["recipeId"] or not ir["target"] or not ir["finalizedKind"]:
        die(f"{def_name}: incomplete recipe identity/key")
    if not ir["resultType"]:
        die(f"{def_name}: missing ResultType")
    return canonicalize_recipe(ir)


def production_recipe_names(d: dict) -> list[str]:
    io = d.get("!instanceof") or {}
    names = list(io.get("TargetIdiomRecipe") or [])
    # Named, non-anonymous only.
    out = []
    for name in names:
        rec = d.get(name)
        if not isinstance(rec, dict):
            continue
        if rec.get("!anonymous"):
            continue
        out.append(name)
    return sorted(out, key=lambda n: (_field(d[n], "RecipeId", ""), n))


def extract_corpus(d: dict) -> list[dict]:
    """Extract all named production recipes (order: RecipeId, defName)."""
    recipes = [extract_recipe(d, n) for n in production_recipe_names(d)]
    seen: set[str] = set()
    for r in recipes:
        rid = r["recipeId"]
        if rid in seen:
            die(f"duplicate recipeId {rid!r}")
        seen.add(rid)
    return recipes


def extract_corpus_ordered(
    repo: Path, d: dict, corpus: list[Path],
) -> list[dict]:
    """Extract recipes in configured source-file / def appearance order.

    Record order is part of the production referee: swapping two defs in a
    configured corpus file changes the ordered identity and must fail the gate.
    """
    named = set(production_recipe_names(d))
    ordered_defs: list[str] = []
    for path in corpus:
        text = (repo / path).read_text(encoding="utf-8")
        for m in _DEF_START.finditer(text):
            name = m.group(1)
            if name in named and name not in ordered_defs:
                ordered_defs.append(name)
    missing = named - set(ordered_defs)
    if missing:
        die(f"production defs not found in configured corpus: {sorted(missing)}")
    extra_in_files = set(ordered_defs) - named
    if extra_in_files:
        die(f"corpus def scan disagree with dump-json: {sorted(extra_in_files)}")
    recipes = [extract_recipe(d, n) for n in ordered_defs]
    seen: set[str] = set()
    for r in recipes:
        rid = r["recipeId"]
        if rid in seen:
            die(f"duplicate recipeId {rid!r}")
        seen.add(rid)
    return recipes

def canonicalize_recipe(ir: dict) -> dict:
    """Stable pure form. Op/input order is semantic and preserved; keys sorted
    only at JSON serialization time via `compact`/`render`."""
    # Round-trip through JSON to drop non-canonical types / key insertion noise.
    return json.loads(compact(ir))


def canonicalize_corpus(recipes: list[dict]) -> list[dict]:
    # Corpus identity order: RecipeId, then defName.
    ordered = sorted(
        (canonicalize_recipe(r) for r in recipes),
        key=lambda r: (r["recipeId"], r["defName"]),
    )
    return ordered


# ---- TableGen re-emission ---------------------------------------------------


def _emit_string(s: str) -> str:
    return json.dumps(s)


def _emit_input(slot: dict) -> str:
    name = _emit_string(slot["name"])
    ft = _emit_string(slot["finalizedType"])
    card = slot["cardinality"]
    if card == "one":
        return f"One<{name}, {ft}>"
    if card == "optional" and not slot.get("parentSlot"):
        return f"Optional<{name}, {ft}>"
    if card == "optional" and slot.get("parentSlot"):
        parent = _emit_string(slot["parentSlot"])
        presence = int(slot.get("presence", 0))
        # Map closed ordinals back to Presence* defs.
        pres_map = {0: "PresenceNone", 1: "PresenceMemo", 2: "PresenceGuard", 3: "PresenceDirect"}
        pres = pres_map.get(presence, "PresenceNone")
        return f"RelatedOptional<{name}, {ft}, {parent}, {pres}>"
    # many
    mn = int(slot["min"])
    mx = _emit_string(slot["max"])
    ok = _emit_string(slot.get("orderKey") or "")
    parent = slot.get("parentSlot") or ""
    if parent:
        return (
            f"RelatedMany<{name}, {ft}, {mn}, {mx}, {ok}, {_emit_string(parent)}>"
        )
    return f"Many<{name}, {ft}, {mn}, {mx}, {ok}>"


def _emit_card(rc: dict) -> str:
    sp = rc["spelling"]
    if sp == "one":
        return "CardinalityOne"
    if sp == "optional":
        return "CardinalityOptional"
    return f"CardinalityMany<{int(rc['min'])}, {_emit_string(rc['max'])}>"


def _emit_binding(b: dict) -> str:
    kind = b["bindKind"]
    field = _emit_string(b["field"])
    if kind == "Direct":
        return f"Direct<{field}, {_emit_string(b['input'])}>"
    if kind == "Hook":
        return (
            f"Hook<{field}, {_emit_string(b['hookId'])}, {_emit_string(b['input'])}>"
        )
    return f"Nested<{field}, {_emit_body(b['body'])}>"


def _emit_op(op: dict) -> str:
    kind = op["opKind"]
    if kind == "Emit":
        node = _emit_string(op["node"])
        binds = op.get("bindings") or []
        if not binds:
            return f"Emit<{node}, []>"
        inner = ", ".join(_emit_binding(b) for b in binds)
        return f"Emit<{node}, [{inner}]>"
    if kind == "Call":
        rid = _emit_string(op["recipeId"])
        binds = op.get("bindings") or []
        if not binds:
            return f"Call<{rid}, []>"
        inner = ", ".join(_emit_binding(b) for b in binds)
        return f"Call<{rid}, [{inner}]>"
    if kind == "ForEach":
        return f"ForEach<{_emit_string(op['slot'])}, {_emit_body(op['body'])}>"
    return f"OptionalOp<{_emit_string(op['slot'])}, {_emit_body(op['body'])}>"


def _emit_body(body: dict) -> str:
    ops = body["ops"]
    if not ops:
        die("refuse to emit empty body")
    # Prefer multi-line when more than one op or any nested structure.
    if len(ops) == 1 and not any(
        (o.get("bindings") or o.get("body")) for o in ops
    ):
        return f"Sequence<[{_emit_op(ops[0])}]>"
    parts = [",\n      ".join(_emit_op(o) for o in ops)]
    return "Sequence<[\n      " + parts[0] + "\n    ]>"


def emit_recipe_td(ir: dict) -> str:
    """Emit one complete `def Name : TargetIdiomRecipe<...>;` block."""
    ir = canonicalize_recipe(ir)
    inputs = ir["inputs"]
    if inputs:
        input_txt = ",\n    ".join(_emit_input(s) for s in inputs)
        inputs_block = f"[\n    {input_txt}\n  ]"
    else:
        inputs_block = "[]"
    body = _emit_body(ir["body"])
    # schemaVersion default 1 is omitted when 1 (matches historical spelling).
    schema = ir.get("schemaVersionField", 1)
    schema_arg = f", {schema}" if schema != 1 else ""
    return (
        f"def {ir['defName']} : TargetIdiomRecipe<\n"
        f"  {_emit_string(ir['recipeId'])}, {_emit_string(ir['target'])},\n"
        f"  {_emit_string(ir['finalizedKind'])}, {_emit_string(ir['mode'])}, "
        f"{_emit_string(ir['role'])}, {inputs_block},\n"
        f"  {_emit_string(ir['resultType'])}, {_emit_card(ir['resultCardinality'])},\n"
        f"  {body}{schema_arg}>;\n"
    )


def emit_corpus_td(recipes: list[dict]) -> str:
    """Emit recipes preserving the caller's order (production referee order)."""
    chunks = [emit_recipe_td(r) for r in recipes]
    return "\n".join(chunks)

# ---- Source-file rewrite (one-time normalization) ---------------------------

# Match a top-level `def Name : ...` that ends at the matching `;` after the
# template argument list — used to locate recipe definitions for replacement.
# `def Name` may place the colon on the following line.
_DEF_START = re.compile(
    r"^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?::|\n\s*:)",
    re.MULTILINE,
)


def _find_def_span(text: str, def_name: str) -> tuple[int, int] | None:
    """Return [start, end) of `def Name : ...;` including trailing newline."""
    for m in _DEF_START.finditer(text):
        if m.group(1) != def_name:
            continue
        # Land just after the colon.
        colon = text.find(":", m.start())
        if colon < 0:
            continue
        i = colon + 1
        # Skip class/template name and land on the first '<' of template args,
        # or on ';' for a non-template def.
        while i < len(text) and text[i] not in "<;":
            # Skip quoted strings if any appear before '<' (should not).
            if text[i] == '"':
                i += 1
                while i < len(text) and text[i] != '"':
                    if text[i] == "\\":
                        i += 1
                    i += 1
            i += 1
        if i < len(text) and text[i] == "<":
            depth = 0
            while i < len(text):
                ch = text[i]
                if ch == "<":
                    depth += 1
                elif ch == ">":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                elif ch == '"':
                    i += 1
                    while i < len(text) and text[i] != '"':
                        if text[i] == "\\":
                            i += 1
                        i += 1
                i += 1
        while i < len(text) and text[i] in " \t\n\r":
            i += 1
        if i >= len(text) or text[i] != ";":
            die(f"def {def_name}: could not find terminating ';'")
        i += 1
        if i < len(text) and text[i] == "\n":
            i += 1
        return m.start(), i
    return None


def rewrite_file_recipes(text: str, recipes_by_def: dict[str, dict]) -> str:
    """Replace each known recipe def in `text` with its canonical emission."""
    # Apply replacements from end to start so offsets stay valid.
    spans: list[tuple[int, int, str]] = []
    for def_name, ir in recipes_by_def.items():
        span = _find_def_span(text, def_name)
        if span is None:
            continue
        spans.append((span[0], span[1], emit_recipe_td(ir)))
    spans.sort(key=lambda s: s[0], reverse=True)
    out = text
    for start, end, replacement in spans:
        out = out[:start] + replacement + out[end:]
    return out


def map_defs_to_files(repo: Path, def_names: list[str], corpus: list[Path]) -> dict[str, Path]:
    """Locate which corpus file owns each def name (simple text search)."""
    mapping: dict[str, Path] = {}
    for path in corpus:
        text = (repo / path).read_text(encoding="utf-8")
        for name in def_names:
            if re.search(
                rf"^def\s+{re.escape(name)}\s*(?::|\n\s*:)", text, re.MULTILINE
            ):
                if name in mapping and mapping[name] != path:
                    die(f"def {name} found in both {mapping[name]} and {path}")
                mapping[name] = path
    missing = [n for n in def_names if n not in mapping]
    if missing:
        die(f"could not locate recipe defs in corpus: {missing}")
    return mapping


def default_includes(repo: Path) -> list[str]:
    return [str(repo / "lib" / "backends")]


def load_solidity_corpus(repo: Path, tblgen: str) -> tuple[dict, list[dict]]:
    entry = repo / SOLIDITY_ENTRY_TD
    records = load_records(entry, default_includes(repo), tblgen)
    recipes = extract_corpus(records)
    return records, recipes


# ---- CLI --------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, default=None)
    ap.add_argument("--td", type=Path, help="entry .td (defaults to Solidity root)")
    ap.add_argument("--tblgen", required=True)
    ap.add_argument("-I", dest="includes", action="append", default=[])
    ap.add_argument("--emit-json", action="store_true")
    ap.add_argument("--emit-td", action="store_true")
    ap.add_argument(
        "--canonicalize-files",
        action="store_true",
        help="rewrite production Solidity recipe defs in place to canonical form",
    )
    ap.add_argument("--check-idempotent", action="store_true",
                    help="fail unless two canonicalize runs match")
    args = ap.parse_args(argv)

    repo = (args.repo or Path(__file__).resolve().parents[2]).resolve()
    td = args.td or (repo / SOLIDITY_ENTRY_TD)
    includes = args.includes or default_includes(repo)

    records = load_records(td, includes, args.tblgen)
    recipes = extract_corpus_ordered(repo, records, list(SOLIDITY_CORPUS))
    c1 = [canonicalize_recipe(r) for r in recipes]
    c2 = [canonicalize_recipe(copy.deepcopy(r)) for r in recipes]
    if args.check_idempotent and compact(c1) != compact(c2):
        die("canonicalize is not idempotent")
    if compact(c1) != compact(c2):
        die("internal: canonicalize non-deterministic")

    if args.emit_json:
        sys.stdout.write(render({"kind": "neutrino.recipe-record-corpus",
                                 "schemaVersion": 1,
                                 "recipes": c1}))
        return 0
    if args.emit_td:
        sys.stdout.write(emit_corpus_td(c1))
        return 0
    if args.canonicalize_files:
        by_def = {r["defName"]: r for r in c1}
        mapping = map_defs_to_files(repo, list(by_def), list(SOLIDITY_CORPUS))
        per_file: dict[Path, dict[str, dict]] = {}
        for def_name, path in mapping.items():
            per_file.setdefault(path, {})[def_name] = by_def[def_name]
        for path, group in sorted(per_file.items()):
            full = repo / path
            text = full.read_text(encoding="utf-8")
            rewritten = rewrite_file_recipes(text, group)
            if rewritten != text:
                full.write_text(rewritten, encoding="utf-8")
                print(f"normalized {path} ({len(group)} recipes)")
            else:
                print(f"unchanged {path} ({len(group)} recipes)")
        records2 = load_records(td, includes, args.tblgen)
        c_after = [
            canonicalize_recipe(r)
            for r in extract_corpus_ordered(repo, records2, list(SOLIDITY_CORPUS))
        ]
        if compact(c_after) != compact(c1):
            die("post-normalize dump-json IR diverged from pre-normalize IR")
        print(f"ok: {len(c1)} production recipes; IR stable after normalize")
        return 0

    print(f"production recipes: {len(c1)}")
    for r in c1:
        print(f"  {r['recipeId']}  def={r['defName']}")
    print("digest", sha256_text(compact(c1)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
