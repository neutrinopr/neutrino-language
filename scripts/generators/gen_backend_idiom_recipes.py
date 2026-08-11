#!/usr/bin/env python3
"""Generate a backend package's RecipeModule .inc from its <Target>IdiomRecipes.td.

The declarative backend-idiom recipe generator ( /  §3.6). It runs
`llvm-tblgen --dump-json` over a backend recipe .td (which includes the
meta-model lib/backends/BackendIdiom.td), validates the recipes at generation
time, and emits a deterministic C++ .inc that constructs a
`neutrino::recipe::RecipeModule` (include/Neutrino/RecipeModule.h). The generic
runtime interprets that module; this generator makes NO semantic decision and
reads NO source/domain/spec/MLIR.

It emits, per §3.6, the closed key table, the reachable-key manifest, exact-key
resolver data, the recipe bytecode, hook references by registered id with their
exact (input,output) signature, generated typed input-view accessor ids
(`FinalizedFieldId`) with their value-type ids, backend node-type ids, slot
ids, result-type/cardinality proofs for every body and nested binding, and a
freshness hash. Every runtime handle is a generated numeric id: NO name or
field-path string is ever used for a runtime lookup (§3.5).

Generation-time validation (fail closed, non-zero exit):
  * single owning target; unique recipeId; non-empty Sequence bodies;
  * exact-key reachability: no duplicate (target,finalizedKind,mode,role);
  * Call targets exist in the same package; the call graph is acyclic;
  * closed op/binding kinds only; hooks have a valid closed kind + unique kind;
  * every Direct/Hook field path resolves to a DECLARED field of the slot's
    finalized type, and a Hook's field value type matches the hook input;
  * §3.3 result-cardinality AND result node type match each declared result.

Two runs from identical .td + toolchain pins are byte-identical.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys

# ---- closed vocabularies (mirror BackendIdiom.td / RecipeRuntime.h) ---------
OP_KINDS = {"Emit": "OpKind::Emit", "ForEach": "OpKind::ForEach",
            "Optional": "OpKind::OptionalOp", "Call": "OpKind::Call"}
BIND_KINDS = {"Direct": "BindKind::Direct", "Hook": "BindKind::Hook",
              "Nested": "BindKind::Nested"}
CARD = {"one": "Cardinality::One", "optional": "Cardinality::Optional",
        "many": "Cardinality::Many"}
UNBOUNDED = 0xFFFFFFFF


def die(msg: str) -> "None":
    sys.stderr.write("gen_backend_idiom_recipes: " + msg + "\n")
    sys.exit(1)


def load_records(td: str, includes: list[str], tblgen: str) -> dict:
    cmd = [tblgen, "--dump-json", td]
    for inc in includes:
        cmd += ["-I", inc]
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if out.returncode:
        die("llvm-tblgen failed:\n" + out.stderr.decode("utf-8", "replace"))
    return json.loads(out.stdout)


def deref(d: dict, v):
    """Resolve a tblgen JSON value that may be an anonymous def reference."""
    if isinstance(v, dict) and v.get("kind") == "def":
        return d[v["def"]]
    return v


def parse_max(s: str) -> int:
    return UNBOUNDED if s == "unbounded" else int(s)


class Flattener:
    """Flattens recipe body trees into the flat RecipeModule arrays.

    Two-phase per level: append a sequence's op rows (or an emit's binding rows)
    CONTIGUOUSLY first, then resolve nested bodies/bindings — which append AFTER
    the contiguous range. So an op's `[bb,be)` and a body's `[opsBegin,opsEnd)`
    are always contiguous even with nested ForEach/Nested structures. Each op and
    binding is stamped with the owning recipe index for later id resolution.
    """

    def __init__(self, d: dict):
        self.d = d
        self.bodies: list[tuple[int, int]] = []
        self.ops: list[dict] = []
        self.bindings: list[dict] = []
        self.op_recipe: list[int] = []
        self.binding_recipe: list[int] = []
        self._cur = -1

    def body(self, seq_ref, recipe_idx=None) -> int:
        if recipe_idx is not None:
            self._cur = recipe_idx
        seq = deref(self.d, seq_ref)
        ops = seq.get("Ops", [])
        if not ops:
            die("empty Sequence body (§3.4 forbids an empty sequence)")
        begin = len(self.ops)
        deferred = []  # (op_index, kind, op_record)
        for o_ref in ops:
            o = deref(self.d, o_ref)
            kind = o["OpKind"]
            if kind not in OP_KINDS:
                die("unknown op kind " + kind)
            row = {"kind": OP_KINDS[kind], "node": "", "slot": "",
                   "recipeId": "", "bb": 0, "be": 0, "body": -1,
                   "nodeTypeId": 0, "slotId": 0}
            oi = len(self.ops)
            self.ops.append(row)
            self.op_recipe.append(self._cur)
            deferred.append((oi, kind, o))
        end = len(self.ops)  # contiguous op range for this sequence
        for oi, kind, o in deferred:
            if kind in ("Emit", "Call"):
                if kind == "Emit":
                    self.ops[oi]["node"] = o["Node"]
                else:
                    self.ops[oi]["recipeId"] = o["RecipeId"]
                self.ops[oi]["bb"], self.ops[oi]["be"] = \
                    self.bindings_of(o.get("Bindings", []))
            elif kind in ("ForEach", "Optional"):
                self.ops[oi]["slot"] = o["Slot"]
                self.ops[oi]["body"] = self.body(o["Body"])
        self.bodies.append((begin, end))
        return len(self.bodies) - 1

    def bindings_of(self, binds: list) -> tuple[int, int]:
        begin = len(self.bindings)
        deferred = []  # (binding_index, nested_body_ref)
        for b_ref in binds:
            b = deref(self.d, b_ref)
            bk = b["BindKind"]
            if bk not in BIND_KINDS:
                die("unknown binding kind " + bk)
            row = {"kind": BIND_KINDS[bk], "field": "", "hookId": "",
                   "input": "", "nestedBody": -1, "fieldId": 0, "hook": 0,
                   "slotRef": 0, "targetField": 0, "nestedCategory": 0,
                   "nestedResult": ("one", 1, 1)}
            row["field"] = b["Field"]  # target node field / callee slot name
            if bk == "Direct":
                row["input"] = b["Input"]
            elif bk == "Hook":
                row["hookId"] = b["HookId"]
                row["input"] = b["Input"]
            bi = len(self.bindings)
            self.bindings.append(row)
            self.binding_recipe.append(self._cur)
            if bk == "Nested":
                deferred.append((bi, b["Body"]))
        end = len(self.bindings)  # contiguous binding range for this emit/call
        for bi, body_ref in deferred:
            self.bindings[bi]["nestedBody"] = self.body(body_ref)
        return begin, end


# ---- §3.3 result cardinality + node-type derivation ------------------------
def derive_cardinality(d, flat, body_idx, recipe_result):
    begin, end = flat.bodies[body_idx]
    total_min, total_max = 0, 0
    for i in range(begin, end):
        mn, mx = op_interval(d, flat, flat.ops[i], recipe_result)
        total_min += mn
        total_max = UNBOUNDED if UNBOUNDED in (total_max, mx) else total_max + mx
    return total_min, total_max


def op_interval(d, flat, op, recipe_result):
    if op["kind"] == "OpKind::Emit":
        return 1, 1
    if op["kind"] == "OpKind::Call":
        callee = recipe_result.get(op["recipeId"])
        if callee is None:
            die("Call to unknown recipe " + op["recipeId"])
        return callee
    if op["kind"] in ("OpKind::ForEach", "OpKind::OptionalOp"):
        bmn, bmx = derive_cardinality(d, flat, op["body"], recipe_result)
        if op["kind"] == "OpKind::OptionalOp":
            return 0, bmx
        smn, smx = op["_slot_min"], op["_slot_max"]
        lo = bmn * smn
        hi = UNBOUNDED if UNBOUNDED in (bmx, smx) else bmx * smx
        return lo, hi
    die("unhandled op interval for " + op["kind"])


def derive_category(flat, body_idx, by_id, node_category):
    """The single result CATEGORY a body yields (§3.3). Concrete Emit nodes map
    to their category, so a body may mix concrete nodes that share a category;
    it dies only if the body mixes distinct categories."""
    begin, end = flat.bodies[body_idx]
    found = None
    for i in range(begin, end):
        op = flat.ops[i]
        if op["kind"] == "OpKind::Emit":
            if op["node"] not in node_category:
                die("Emit of undeclared target node %r" % op["node"])
            c = node_category[op["node"]]
        elif op["kind"] == "OpKind::Call":
            c = by_id[op["recipeId"]]["resultType"]  # a category
        else:  # ForEach / Optional
            c = derive_category(flat, op["body"], by_id, node_category)
        if found is None:
            found = c
        elif found != c:
            die("body result mixes categories %r and %r" % (found, c))
    return found


def interval_to_card(lo, hi):
    if (lo, hi) == (1, 1):
        return ("one", 1, 1)
    if (lo, hi) == (0, 1):
        return ("optional", 0, 1)
    return ("many", lo, hi)


def cpp_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def cpp_key(k) -> str:
    return "{%s, %s, %s, %s}" % (cpp_str(k[0]), cpp_str(k[1]), cpp_str(k[2]),
                                 cpp_str(k[3]))


def card_cpp(card):
    kind, mn, mx = card
    if kind == "one":
        return "{Cardinality::One, 1, 1}"
    if kind == "optional":
        return "{Cardinality::Optional, 0, 1}"
    mxs = "ResultCardinality::kUnbounded" if mx == UNBOUNDED else str(mx)
    return "{Cardinality::Many, %d, %s}" % (mn, mxs)


def sanitize(s: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "_", s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--td", required=True)
    ap.add_argument("--tblgen", required=True)
    ap.add_argument("-I", dest="includes", action="append", default=[])
    ap.add_argument("--symbol", required=True,
                    help="generated accessor symbol, e.g. synthetic")
    ap.add_argument("-o", dest="out", required=True)
    args = ap.parse_args()

    d = load_records(args.td, args.includes, args.tblgen)
    io = d.get("!instanceof", {})
    recipe_names = sorted(io.get("TargetIdiomRecipe", []))
    hook_names = sorted(io.get("RegisterLeafHook", []))
    ftype_names = sorted(io.get("FinalizedType", []))
    tnode_names = sorted(io.get("TargetNode", []))
    if not recipe_names:
        die("no TargetIdiomRecipe rows in " + args.td)

    # ---- finalized-type field schema (§3.5) ----
    schema = {}  # typeName -> {fieldName: valueType}
    for name in ftype_names:
        ft = d[name]
        fields = {}
        for f_ref in ft.get("Fields", []):
            f = deref(d, f_ref)
            fields[f["Name"]] = f["ValueType"]
        schema[ft["Name"]] = fields

    # ---- target-node field schema (§3.6): nodeName -> ordered field list ----
    node_schema = {}    # nodeName -> [{name,kind,type,card,min,max}]
    node_category = {}  # nodeName -> §3.3 result category
    for name in tnode_names:
        tn = d[name]
        node_category[tn["Name"]] = tn["Category"]
        flds = []
        for f_ref in tn.get("Fields", []):
            f = deref(d, f_ref)
            flds.append({"name": f["Name"], "kind": f["Kind"],
                         "type": f["Type"], "card": f["Cardinality"],
                         "min": f["Min"], "max": parse_max(f["Max"])})
        node_schema[tn["Name"]] = flds
    categories = set(node_category.values())

    # ---- hooks (parsed early: field resolution needs hook signatures) ----
    hooks = []
    hook_by_id = {}
    seen_hook_kinds = set()
    for i, name in enumerate(hook_names):
        h = d[name]
        k = deref(d, h["Kind"])
        kind = k["Kind"]
        if kind in seen_hook_kinds:
            die("duplicate leaf-hook kind %r (default-deny: at most one)" % kind)
        seen_hook_kinds.add(kind)
        rec = {"hookId": h["HookId"], "id": i, "kind": kind, "impl": h["Impl"],
               "input": k["Input"], "output": k["Output"]}
        hooks.append(rec)
        hook_by_id[h["HookId"]] = rec

    # ---- collect + validate recipes; assign global slot ids ----
    target = None
    recipes = []
    by_id = {}
    seen_keys = {}
    all_slots = []  # global flattened slots
    flat = Flattener(d)
    for name in recipe_names:
        r = d[name]
        t = r["Target"]
        target = t if target is None else target
        if t != target:
            die("recipe %s target %r != package target %r" % (name, t, target))
        rid = r["RecipeId"]
        if rid in by_id:
            die("duplicate recipeId " + rid)
        key = (t, r["FinalizedKind"], r["Mode"], r["Role"])
        if key in seen_keys:
            die("duplicate reachable key %s (recipes %s, %s)" %
                (key, seen_keys[key], rid))
        seen_keys[key] = rid
        rec_idx = len(recipes)
        slot_begin = len(all_slots)
        slot_map = {}  # name -> (global_slot_index, finalizedType)
        for s_ref in r["Inputs"]:
            s = deref(d, s_ref)
            gidx = len(all_slots)
            all_slots.append({"name": s["Name"], "ft": s["FinalizedType"],
                              "card": s["Cardinality"], "min": s["Min"],
                              "max": parse_max(s["Max"]),
                              "orderKey": s["OrderKey"],
                              "parent": s.get("ParentSlot", ""),
                              "presence": s.get("Presence", 0),
                              "parentId": 0,
                              "id": gidx + 1})
            slot_map[s["Name"]] = (gidx, s["FinalizedType"])
        for gidx in range(slot_begin, len(all_slots)):
            parent = all_slots[gidx]["parent"]
            if parent and parent not in slot_map:
                die("related slot %s names unknown parent %s" %
                    (all_slots[gidx]["name"], parent))
            # Resolve the parent slot name to its generated slot id so the
            # provider can follow the finalized edge generically (0 = no parent).
            if parent:
                all_slots[gidx]["parentId"] = \
                    all_slots[slot_map[parent][0]]["id"]
        rc = deref(d, r["ResultCardinality"])
        body = flat.body(r["Body"], rec_idx)
        recipes.append({"name": name, "rid": rid, "key": key,
                        "sv": r["SchemaVersion"],
                        "slotBegin": slot_begin, "slotEnd": len(all_slots),
                        "slotMap": slot_map,
                        "resultType": r["ResultType"],
                        "resultCard": rc["Spelling"],
                        "resultMin": rc.get("Min", 1),
                        "resultMax": parse_max(str(rc.get("Max", "1"))),
                        "body": body})
        by_id[rid] = recipes[-1]

    # ---- ForEach slot bounds per owning recipe (for the §3.3 interval algebra)
    for rec in recipes:
        bounds = {all_slots[g]["name"]: (all_slots[g]["min"], all_slots[g]["max"])
                  for g in range(rec["slotBegin"], rec["slotEnd"])}
        _bind_foreach_bounds(flat, rec["body"], bounds)
        parents = {
            all_slots[g]["name"]: all_slots[g]["parent"]
            for g in range(rec["slotBegin"], rec["slotEnd"])
            if all_slots[g]["parent"]
        }

        def check_related(body_idx, active):
            begin, end = flat.bodies[body_idx]
            for oi in range(begin, end):
                op = flat.ops[oi]
                if op["kind"] in ("OpKind::ForEach",
                                  "OpKind::OptionalOp"):
                    parent = parents.get(op["slot"])
                    if parent and parent not in active:
                        die("related slot %s traversed outside parent %s" %
                            (op["slot"], parent))
                    check_related(op["body"], active | {op["slot"]})
                if op["kind"] == "OpKind::Emit":
                    for bi in range(op["bb"], op["be"]):
                        binding = flat.bindings[bi]
                        if binding["kind"] in ("BindKind::Direct",
                                              "BindKind::Hook"):
                            slot_name = binding["input"].split(".", 1)[0]
                            parent = parents.get(slot_name)
                            if parent and (slot_name not in active or
                                           parent not in active):
                                die("related field %s read outside %s/%s "
                                    "traversal" %
                                    (binding["input"], parent, slot_name))
                        if binding["kind"] == "BindKind::Nested":
                            check_related(binding["nestedBody"], active)

        check_related(rec["body"], set())

    _check_call_dag(flat, recipes, by_id)

    # ---- §3.3 result-cardinality + node-type proof per recipe ----
    result_intervals = {}
    for _ in range(len(recipes) + 1):
        for rec in recipes:
            try:
                result_intervals[rec["rid"]] = derive_cardinality(
                    d, flat, rec["body"], result_intervals)
            except SystemExit:
                raise
            except KeyError:
                pass
    for rec in recipes:
        lo, hi = result_intervals[rec["rid"]]
        _check_declared_result(rec, lo, hi)
        if rec["resultType"] not in categories:
            die("recipe %s resultType %r is not a declared category" %
                (rec["rid"], rec["resultType"]))
        derived_cat = derive_category(flat, rec["body"], by_id, node_category)
        if derived_cat != rec["resultType"]:
            die("recipe %s declared result category %r != derived %r" %
                (rec["rid"], rec["resultType"], derived_cat))

    # ---- value/leaf/node type id spaces (deterministic: sorted strings) ----
    value_type_strs = set()
    for s in all_slots:
        value_type_strs.add(s["ft"])
    for h in hooks:
        value_type_strs.add(h["input"])

    # ---- resolve every Direct/Hook input accessor -> FinalizedFieldId ----
    fields = []            # {id, type, slot(id), path}
    field_ids = {}         # (recipe_idx, input_path) -> field id
    for bi, b in enumerate(flat.bindings):
        if b["kind"] not in ("BindKind::Direct", "BindKind::Hook"):
            continue
        rec = recipes[flat.binding_recipe[bi]]
        path = b["input"]
        gslot, ft, vtype = _resolve_field(rec, path, schema, hook_by_id, b)
        value_type_strs.add(vtype)
        b["_valueType"] = vtype
        b["slotRef"] = all_slots[gslot]["id"]
        fkey = (flat.binding_recipe[bi], path)
        if fkey not in field_ids:
            field_ids[fkey] = len(fields) + 1
            fields.append({"id": field_ids[fkey], "type_str": vtype,
                           "slot": all_slots[gslot]["id"], "path": path})
        b["fieldId"] = field_ids[fkey]
        if b["kind"] == "BindKind::Hook":
            b["hook"] = hook_by_id[b["hookId"]]["id"]

    value_type_id = {s: i + 1 for i, s in enumerate(sorted(value_type_strs))}
    leaf_type_id = {s: i + 1 for i, s in
                    enumerate(sorted({h["output"] for h in hooks}))}
    # Concrete node ids (for Emit) and result-category ids (for result checks).
    node_strs = {op["node"] for op in flat.ops if op["kind"] == "OpKind::Emit"}
    node_strs |= set(node_schema.keys())
    node_type_id = {s: i + 1 for i, s in enumerate(sorted(node_strs))}
    category_id = {s: i + 1 for i, s in enumerate(sorted(categories))}

    # ---- back-fill numeric ids onto rows now the id spaces are fixed ----
    for f in fields:
        f["type"] = value_type_id[f["type_str"]]
    for s in all_slots:
        s["ftId"] = value_type_id[s["ft"]]
    for h in hooks:
        h["inputId"] = value_type_id[h["input"]]
        h["outputId"] = leaf_type_id[h["output"]]
    for rec in recipes:
        rec["resultCategory"] = category_id[rec["resultType"]]
    for oi, op in enumerate(flat.ops):
        if op["kind"] == "OpKind::Emit":
            op["nodeTypeId"] = node_type_id[op["node"]]
        elif op["kind"] in ("OpKind::ForEach", "OpKind::OptionalOp"):
            rec = recipes[flat.op_recipe[oi]]
            if op["slot"] not in rec["slotMap"]:
                die("op over unknown slot %r in %s" % (op["slot"], rec["rid"]))
            gidx = rec["slotMap"][op["slot"]][0]
            op["slotId"] = all_slots[gidx]["id"]

    # ---- target-node field-schema table + generated field ids ----
    node_fields = []         # {node(id), id, name, kind, typeId, card}
    node_field_ids = {}      # (nodeName, fieldName) -> TargetFieldId
    node_field_by_node = {}  # nodeName -> ordered [descriptor]
    for nname in sorted(node_schema.keys()):
        node_field_by_node[nname] = []
        for f in node_schema[nname]:
            fid = len(node_fields) + 1
            node_field_ids[(nname, f["name"])] = fid
            if f["kind"] == "value":
                type_id = value_type_id.get(f["type"])
            elif f["kind"] == "leaf":
                type_id = leaf_type_id.get(f["type"])
            else:  # nodes: the type names a child RESULT CATEGORY
                type_id = category_id.get(f["type"])
            if type_id is None:
                die("target field %s.%s references unknown %s type %r" %
                    (nname, f["name"], f["kind"], f["type"]))
            desc = {"node": node_type_id[nname], "id": fid, "name": f["name"],
                    "kind": f["kind"], "type": f["type"], "typeId": type_id,
                    "card": f["card"], "min": f["min"], "max": f["max"],
                    "card_tuple": (f["card"], f["min"], f["max"])}
            node_fields.append(desc)
            node_field_by_node[nname].append(desc)

    # ---- node -> category rows ----
    node_categories = [{"node": node_type_id[n], "category": category_id[c]}
                       for n, c in sorted(node_category.items())]

    # ---- validate every Emit/Call binding against the schema (§3.5/§3.6) ----
    _check_bindings(d, flat, recipes, by_id, all_slots, node_schema,
                    node_field_by_node, hook_by_id, result_intervals,
                    node_category)

    # ---- nested-binding result proofs, pinned to the target field (§3.6 ) --
    for bi, b in enumerate(flat.bindings):
        if b["kind"] == "BindKind::Nested":
            lo, hi = derive_cardinality(d, flat, b["nestedBody"],
                                        result_intervals)
            derived = derive_category(flat, b["nestedBody"], by_id,
                                      node_category)
            b["nestedResult"] = interval_to_card(lo, hi)
            b["nestedCategory"] = category_id[derived]

    reachable = sorted(((rec["key"], idx) for idx, rec in enumerate(recipes)),
                       key=lambda kr: kr[0])

    inc = emit_inc(args.symbol, target, recipes, all_slots, fields, node_fields,
                   node_categories, flat, hooks, reachable, value_type_id,
                   leaf_type_id, node_type_id, category_id)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(inc)
    return 0


def _card_contains(field, lo, hi):
    """Whether a declared target-node field's cardinality contains a derived
    (lo,hi) child count."""
    if field["card"] == "one":
        return (lo, hi) == (1, 1)
    if field["card"] == "optional":
        return lo >= 0 and hi <= 1
    hi_ok = field["max"] == UNBOUNDED or (hi != UNBOUNDED and hi <= field["max"])
    return lo >= field["min"] and hi_ok


def _check_bindings(d, flat, recipes, by_id, all_slots, node_schema,
                    node_field_by_node, hook_by_id, result_intervals,
                    node_category):
    """Validate every Emit binding against its target node's field schema and
    every Call argument against the callee's slots (§3.5/§3.6). Stamps each Emit
    binding's targetField id."""
    want_kind = {"BindKind::Direct": "value", "BindKind::Hook": "leaf",
                 "BindKind::Nested": "nodes"}
    for oi, op in enumerate(flat.ops):
        if op["kind"] == "OpKind::Emit":
            node = op["node"]
            if node not in node_schema:
                die("Emit of undeclared target node %r" % node)
            flds = node_field_by_node[node]
            nb = op["be"] - op["bb"]
            if nb != len(flds):
                die("Emit<%s> has %d bindings but the node declares %d fields"
                    % (node, nb, len(flds)))
            for k in range(nb):
                b = flat.bindings[op["bb"] + k]
                fd = flds[k]
                if b["field"] != fd["name"]:
                    die("Emit<%s> binding %d fills %r, field is %r" %
                        (node, k, b["field"], fd["name"]))
                if fd["kind"] != want_kind[b["kind"]]:
                    die("Emit<%s>.%s is a %s field but bound as %s" %
                        (node, fd["name"], fd["kind"], want_kind[b["kind"]]))
                if b["kind"] == "BindKind::Direct":
                    if b["_valueType"] != fd["type"]:
                        die("Emit<%s>.%s value type %r != bound %r" %
                            (node, fd["name"], fd["type"], b["_valueType"]))
                elif b["kind"] == "BindKind::Hook":
                    out = hook_by_id[b["hookId"]]["output"]
                    if out != fd["type"]:
                        die("Emit<%s>.%s leaf type %r != hook %s output %r" %
                            (node, fd["name"], fd["type"], b["hookId"], out))
                else:  # Nested
                    child = derive_category(flat, b["nestedBody"], by_id,
                                            node_category)
                    if child != fd["type"]:
                        die("Emit<%s>.%s accepts category %r but nested yields "
                            "%r" % (node, fd["name"], fd["type"], child))
                    lo, hi = derive_cardinality(d, flat, b["nestedBody"],
                                                result_intervals)
                    if not _card_contains(fd, lo, hi):
                        die("Emit<%s>.%s cardinality %s(%d,%s) excludes nested "
                            "(%d,%s)" % (node, fd["name"], fd["card"],
                                         fd["min"], fd["max"], lo, hi))
                b["targetField"] = fd["id"]
        elif op["kind"] == "OpKind::Call":
            callee = by_id.get(op["recipeId"])
            if callee is None:
                die("Call to unknown recipe " + op["recipeId"])
            cslots = list(range(callee["slotBegin"], callee["slotEnd"]))
            nb = op["be"] - op["bb"]
            if nb != len(cslots):
                die("Call %s passes %d args but the recipe has %d slots" %
                    (op["recipeId"], nb, len(cslots)))
            for k in range(nb):
                b = flat.bindings[op["bb"] + k]
                s = all_slots[cslots[k]]
                if b["kind"] != "BindKind::Direct":
                    die("Call %s arg %d must be a direct slot binding" %
                        (op["recipeId"], k))
                if b["field"] != s["name"]:
                    die("Call %s arg %d binds slot %r, expected %r" %
                        (op["recipeId"], k, b["field"], s["name"]))
                if b["_valueType"] != s["ft"]:
                    die("Call %s arg %d type %r != slot %s type %r" %
                        (op["recipeId"], k, b["_valueType"], s["name"], s["ft"]))


def _resolve_field(rec, path, schema, hook_by_id, binding):
    """Resolve 'slot.field'|'slot.item' to (global_slot_idx, finalizedType,
    valueType), validating the field is declared (§3.5)."""
    if "." not in path:
        die("field path %r must be 'slot.field' or 'slot.item'" % path)
    slot_name, tail = path.split(".", 1)
    if slot_name not in rec["slotMap"]:
        die("field %r references unknown slot in %s" % (path, rec["rid"]))
    gslot, ft = rec["slotMap"][slot_name]
    if tail == "item":
        vtype = ft
    else:
        flds = schema.get(ft)
        if flds is None or tail not in flds:
            die("field %r reads undeclared field of %s (recipe %s)" %
                (path, ft, rec["rid"]))
        vtype = flds[tail]
    if binding["kind"] == "BindKind::Hook":
        hk = hook_by_id.get(binding["hookId"])
        if hk is None:
            die("Hook binding references unregistered hook " + binding["hookId"])
        if vtype != hk["input"]:
            die("hook %s input %r != field %r value type %r" %
                (binding["hookId"], hk["input"], path, vtype))
    return gslot, ft, vtype


def _bind_foreach_bounds(flat, body_idx, bounds):
    begin, end = flat.bodies[body_idx]
    for i in range(begin, end):
        op = flat.ops[i]
        if op["kind"] == "OpKind::ForEach":
            b = bounds.get(op["slot"])
            if b is None:
                die("ForEach over unknown slot " + op["slot"])
            op["_slot_min"], op["_slot_max"] = b
            _bind_foreach_bounds(flat, op["body"], bounds)
        elif op["kind"] == "OpKind::OptionalOp":
            _bind_foreach_bounds(flat, op["body"], bounds)
        elif op["kind"] == "OpKind::Emit":
            for j in range(op["bb"], op["be"]):
                bd = flat.bindings[j]
                if bd["nestedBody"] >= 0:
                    _bind_foreach_bounds(flat, bd["nestedBody"], bounds)


def _check_call_dag(flat, recipes, by_id):
    edges = {rec["rid"]: set() for rec in recipes}

    def walk(body_idx, rid):
        begin, end = flat.bodies[body_idx]
        for i in range(begin, end):
            op = flat.ops[i]
            if op["kind"] == "OpKind::Call":
                if op["recipeId"] not in by_id:
                    die("Call to unknown recipe %r in %s" % (op["recipeId"], rid))
                edges[rid].add(op["recipeId"])
                continue
            if op["body"] >= 0:
                walk(op["body"], rid)
            for j in range(op["bb"], op["be"]):
                if flat.bindings[j]["nestedBody"] >= 0:
                    walk(flat.bindings[j]["nestedBody"], rid)

    for rec in recipes:
        walk(rec["body"], rec["rid"])
    WHITE, GREY, BLACK = 0, 1, 2
    color = {rid: WHITE for rid in edges}

    def dfs(rid):
        color[rid] = GREY
        for nxt in sorted(edges[rid]):
            if color[nxt] == GREY:
                die("recipe call cycle at %s -> %s" % (rid, nxt))
            if color[nxt] == WHITE:
                dfs(nxt)
        color[rid] = BLACK

    for rid in sorted(edges):
        if color[rid] == WHITE:
            dfs(rid)


def _check_declared_result(rec, lo, hi):
    card = rec["resultCard"]
    if card == "one":
        ok = (lo, hi) == (1, 1)
    elif card == "optional":
        ok = (lo, hi) == (0, 1)
    else:
        ok = lo == rec["resultMin"] and hi == rec["resultMax"]
    if not ok:
        die("recipe %s declared result cardinality %s(%s,%s) != derived (%s,%s)"
            % (rec["rid"], card, rec.get("resultMin"), rec.get("resultMax"),
               lo, hi if hi != UNBOUNDED else "unbounded"))


FIELD_KIND = {"value": "TargetFieldKind::Value", "leaf": "TargetFieldKind::Leaf",
              "nodes": "TargetFieldKind::Nodes"}


def emit_inc(symbol, target, recipes, all_slots, fields, node_fields,
             node_categories, flat, hooks, reachable, value_type_id,
             leaf_type_id, node_type_id, category_id) -> str:
    L = []
    L.append("// GENERATED by scripts/generators/gen_backend_idiom_recipes.py "
             "-- DO NOT EDIT.")
    L.append("// Source: <Target>IdiomRecipes.td (/). Regenerate; do "
             "not hand-edit.")
    L.append("namespace neutrino { namespace recipe { namespace generated {")
    L.append("")
    # bindings
    L.append("static const BindingRow k%s_bindings[] = {" % symbol)
    for b in flat.bindings:
        L.append("  {%s, %s, %s, %d, %d, %d, %d, %d, %d, %s}," % (
            b["kind"], cpp_str(b["field"]), cpp_str(b["hookId"]),
            b["nestedBody"], b["fieldId"], b["hook"], b["slotRef"],
            b["targetField"], b["nestedCategory"],
            card_cpp(b["nestedResult"])))
    L.append("};")
    # ops
    L.append("static const OpRow k%s_ops[] = {" % symbol)
    for o in flat.ops:
        L.append("  {%s, %s, %s, %s, %d, %d, %d, %d, %d}," % (
            o["kind"], cpp_str(o["node"]), cpp_str(o["slot"]),
            cpp_str(o["recipeId"]), o["bb"], o["be"], o["body"],
            o["nodeTypeId"], o["slotId"]))
    L.append("};")
    # bodies
    L.append("static const BodyRow k%s_bodies[] = {" % symbol)
    for (b, e) in flat.bodies:
        L.append("  {%d, %d}," % (b, e))
    L.append("};")
    # slots
    L.append("static const SlotRow k%s_slots[] = {" % symbol)
    for s in all_slots:
        mxs = ("ResultCardinality::kUnbounded" if s["max"] == UNBOUNDED
               else str(s["max"]))
        L.append("  {%s, %s, %d, %d, %s, %d, %s, %s, %d, %d}," % (
            cpp_str(s["name"]), cpp_str(s["ft"]), s["id"], s["ftId"],
            CARD[s["card"]], s["min"], mxs, cpp_str(s["orderKey"]),
            s["parentId"], s["presence"]))
    if not all_slots:
        L.append("  // (none)")
    L.append("};")
    # Optional-slot extent resolver (only when the table declares presence).
    # A mechanical typed read of the already-finalized parent posting selected
    # by the .td-declared presence ordinal (BackendIdiom.td PostingPresence): no
    # CoordinationPlan, no semantic inference. The provider follows the parent
    # edge and dispatches here; it holds no handwritten presence read.
    if any(s["presence"] for s in all_slots):
        L.append("inline unsigned %sOptionalSlotExtent(" % symbol)
        L.append("    unsigned presence,")
        L.append("    const ::neutrino::projection::FinalizedPostingProjection "
                 "&parent) {")
        L.append("  switch (presence) {")
        L.append("  case 1: return parent.memo.has_value() ? 1u : 0u; // Memo")
        L.append("  case 2: return parent.comparisonGuard ? 1u : 0u; // Guard")
        L.append("  case 3: return parent.comparisonGuard ? 0u : 1u; // Direct")
        L.append("  default: return 0u;")
        L.append("  }")
        L.append("}")
    # fields
    L.append("static const FieldRow k%s_fields[] = {" % symbol)
    for f in fields:
        L.append("  {%d, %d, %d, %s}," % (f["id"], f["type"], f["slot"],
                                          cpp_str(f["path"])))
    if not fields:
        L.append("  // (none)")
    L.append("};")
    # target-node field schema
    L.append("static const NodeFieldRow k%s_node_fields[] = {" % symbol)
    for nf in node_fields:
        L.append("  {%d, %d, %s, %s, %d, %s}," % (
            nf["node"], nf["id"], cpp_str(nf["name"]), FIELD_KIND[nf["kind"]],
            nf["typeId"], card_cpp(nf["card_tuple"])))
    if not node_fields:
        L.append("  // (none)")
    L.append("};")
    # node -> category
    L.append("static const NodeCategoryRow k%s_node_categories[] = {" % symbol)
    for nc in node_categories:
        L.append("  {%d, %d}," % (nc["node"], nc["category"]))
    if not node_categories:
        L.append("  // (none)")
    L.append("};")
    # recipes
    L.append("static const RecipeRow k%s_recipes[] = {" % symbol)
    for rec in recipes:
        L.append("  {%s, %s, %d, %d, %d, %s, %s, %d, %d}," % (
            cpp_str(rec["rid"]), cpp_key(rec["key"]), rec["sv"],
            rec["slotBegin"], rec["slotEnd"], cpp_str(rec["resultType"]),
            card_cpp((rec["resultCard"], rec["resultMin"], rec["resultMax"])),
            rec["body"], rec["resultCategory"]))
    L.append("};")
    # hooks
    L.append("static const HookRow k%s_hooks[] = {" % symbol)
    for h in hooks:
        L.append("  {%s, %d, %s, %s, %d, %d}," % (
            cpp_str(h["hookId"]), h["id"], cpp_str(h["kind"]),
            cpp_str(h["impl"]), h["inputId"], h["outputId"]))
    if not hooks:
        L.append("  // (none)")
    L.append("};")
    # reachable keys
    L.append("static const KeyRow k%s_keys[] = {" % symbol)
    for (key, idx) in reachable:
        L.append("  {%s, %d}," % (cpp_key(key), idx))
    L.append("};")
    L.append("")
    # ---- generated typed-id constants (provider references these; no lookup) --
    L.append("// Generated typed ids: the backend provider references these "
             "constants so")
    L.append("// no name/path string is ever resolved at runtime (§3.5).")
    for s, i in sorted(node_type_id.items(), key=lambda kv: kv[1]):
        L.append("inline constexpr BackendNodeTypeId %s_Node_%s = %d;" % (
            symbol, sanitize(s), i))
    for s, i in sorted(category_id.items(), key=lambda kv: kv[1]):
        L.append("inline constexpr BackendNodeCategoryId %s_Cat_%s = %d;" % (
            symbol, sanitize(s), i))
    for s, i in sorted(leaf_type_id.items(), key=lambda kv: kv[1]):
        L.append("inline constexpr BackendLeafTypeId %s_Leaf_%s = %d;" % (
            symbol, sanitize(s), i))
    for h in hooks:
        L.append("inline constexpr RegisteredHookId %s_Hook_%s = %d;" % (
            symbol, sanitize(h["hookId"]), h["id"]))
    for s, i in sorted(value_type_id.items(), key=lambda kv: kv[1]):
        L.append("inline constexpr FinalizedValueTypeId %s_Value_%s = %d;" % (
            symbol, sanitize(s), i))
    for s in all_slots:
        L.append("inline constexpr SlotId %s_Slot_%s = %d;" % (
            symbol, sanitize(s["name"]), s["id"]))
    for f in fields:
        L.append("inline constexpr FinalizedFieldId %s_Field_%s = %d;" % (
            symbol, sanitize(f["path"]), f["id"]))
    L.append("")
    # freshness hash over the canonical content
    body_txt = "\n".join(L)
    ghash = hashlib.sha256(body_txt.encode("utf-8")).hexdigest()

    def arr(name, rows):
        # A backend package legitimately declares zero rows for some tables (a
        # package with no leaf hooks is common — the Solidity evidence layer has
        # none). Emit an empty brace-init for the empty case: `{nullptr, 0}` is an
        # AMBIGUOUS ArrayRef constructor (const T*+size_t vs const T*+const T*),
        # while `{}` unambiguously value-initializes an empty ArrayRef.
        return ("{k%s_%s, sizeof(k%s_%s)/sizeof(k%s_%s[0])}"
                % (symbol, name, symbol, name, symbol, name)) if rows else "{}"
    L.append("inline const RecipeModule &%sRecipeModule() {" % symbol)
    L.append("  static const RecipeModule kModule = {")
    L.append("    /*target=*/%s," % cpp_str(target))
    L.append("    /*schemaVersion=*/1,")
    L.append("    /*recipes=*/%s," % arr("recipes", recipes))
    L.append("    /*slots=*/%s," % arr("slots", all_slots))
    L.append("    /*fields=*/%s," % arr("fields", fields))
    L.append("    /*nodeFields=*/%s," % arr("node_fields", node_fields))
    L.append("    /*nodeCategories=*/%s," % arr("node_categories",
                                                node_categories))
    L.append("    /*bodies=*/%s," % arr("bodies", flat.bodies))
    L.append("    /*ops=*/%s," % arr("ops", flat.ops))
    L.append("    /*bindings=*/%s," % arr("bindings", flat.bindings))
    L.append("    /*hooks=*/%s," % arr("hooks", hooks))
    L.append("    /*reachableKeys=*/%s," % arr("keys", reachable))
    L.append("    /*generationHash=*/%s," % cpp_str(ghash))
    L.append("  };")
    L.append("  return kModule;")
    L.append("}")
    L.append("")
    L.append("} } } // namespace neutrino::recipe::generated")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())
