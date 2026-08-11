#!/usr/bin/env python3
"""Generate the finalized-projection v1 JSON Schema from its C++ owner.

The M7 backend boundary freezes ``BackendProjectionGraph`` as the sole wire
object.  This generator deliberately derives the family set, nested owned
structs, fields, and closed enum spellings from BackendProjection.h rather than
maintaining a second field ledger.

Only the frozen C++→JSON mapping from
docs/process/M7_BACKEND_PACKAGE_BOUNDARY_ADR.md §6.1 is applied here.  Derived
views declared after BackendProjectionGraph are not wire objects and are never
discovered.
"""

import argparse
import json
import pathlib
import re
import sys
from dataclasses import dataclass


REPO = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_HEADER = REPO / "include" / "Neutrino" / "BackendProjection.h"
DEFAULT_COORDINATION_HEADER = REPO / "include" / "Neutrino" / "CoordinationPlan.h"
DEFAULT_GATE_MODE_HEADER = (
    REPO / "include" / "Neutrino" / "ProjectionGateMode.h"
)
DEFAULT_OUTPUT = REPO / "docs" / "schemas" / "finalized-projection-v1.schema.json"
WIRE_KIND = "neutrino.finalized-projection/1"
SCHEMA_ID = "https://neutrino.dev/schemas/finalized-projection-v1.schema.json"


class SchemaGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Field:
    cpp_type: str
    name: str


def strip_comments(text):
    """Remove C++ comments while preserving strings and line structure."""
    out = []
    i = 0
    state = "code"
    while i < len(text):
        char = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if state == "code":
            if char == "/" and nxt == "/":
                state = "line"
                out.extend("  ")
                i += 2
                continue
            if char == "/" and nxt == "*":
                state = "block"
                out.extend("  ")
                i += 2
                continue
            if char == '"':
                state = "string"
            elif char == "'":
                state = "char"
            out.append(char)
            i += 1
            continue
        if state == "line":
            if char == "\n":
                state = "code"
                out.append(char)
            else:
                out.append(" ")
            i += 1
            continue
        if state == "block":
            if char == "*" and nxt == "/":
                state = "code"
                out.extend("  ")
                i += 2
            else:
                out.append("\n" if char == "\n" else " ")
                i += 1
            continue
        out.append(char)
        if char == "\\":
            if i + 1 < len(text):
                out.append(text[i + 1])
                i += 2
            else:
                i += 1
        else:
            if (state == "string" and char == '"') or (
                state == "char" and char == "'"
            ):
                state = "code"
            i += 1
    return "".join(out)


def normalize_cpp_type(cpp_type):
    return re.sub(r"\s+", " ", cpp_type).strip()


def parse_structs(text):
    clean = strip_comments(text)
    structs = {}
    for match in re.finditer(r"\bstruct\s+([A-Za-z_]\w*)\s*\{(.*?)\};", clean, re.S):
        name, body = match.groups()
        fields = []
        for declaration in body.split(";"):
            declaration = re.sub(r"\s+", " ", declaration).strip()
            if not declaration:
                continue
            declaration = declaration.split("=", 1)[0].strip()
            field_match = re.fullmatch(
                r"(.+?)\s+([A-Za-z_]\w*)", declaration
            )
            if not field_match:
                raise SchemaGenerationError(
                    f"cannot parse {name} member declaration: {declaration!r}"
                )
            cpp_type, field_name = field_match.groups()
            fields.append(Field(normalize_cpp_type(cpp_type), field_name))
        structs[name] = fields
    return structs


def parse_enums(*texts):
    enums = {}
    for text in texts:
        clean = strip_comments(text)
        for match in re.finditer(
            r"\benum\s+class\s+([A-Za-z_]\w*)\s*\{(.*?)\};", clean, re.S
        ):
            name, body = match.groups()
            values = []
            for item in body.split(","):
                item = item.split("=", 1)[0].strip()
                if not item:
                    continue
                if not re.fullmatch(r"[A-Za-z_]\w*", item):
                    raise SchemaGenerationError(
                        f"cannot parse {name} enumerator: {item!r}"
                    )
                values.append(item)
            if not values:
                raise SchemaGenerationError(f"closed enum {name} has no values")
            prior = enums.get(name)
            if prior is not None and prior != values:
                raise SchemaGenerationError(f"conflicting definitions for enum {name}")
            enums[name] = values
    return enums


def vector_inner(cpp_type):
    match = re.fullmatch(r"std::vector\s*<\s*(.+)\s*>", cpp_type)
    return normalize_cpp_type(match.group(1)) if match else None


def optional_inner(cpp_type):
    match = re.fullmatch(r"std::optional\s*<\s*(.+)\s*>", cpp_type)
    return normalize_cpp_type(match.group(1)) if match else None


def ref(def_name):
    return {"$ref": f"#/$defs/{def_name}"}


class SchemaBuilder:
    def __init__(self, structs, enums, schema_version):
        self.structs = structs
        self.enums = enums
        self.schema_version = schema_version
        self.definitions = {
            "nodeId": {
                "description": "A collision-proof projectionNodeId spelling.",
                "minLength": 1,
                "type": "string",
            }
        }
        self.visiting = set()

    def field_schema(self, owner, field):
        cpp_type = field.cpp_type
        if field.name == "id":
            return ref("nodeId")
        if owner == "ProjectionEdge" and field.name in {"from", "to"}:
            return ref("nodeId")
        if owner == "PrimitiveObligation" and field.name == "typedOperands":
            return {"items": ref("nodeId"), "type": "array"}
        inner = vector_inner(cpp_type)
        if inner is not None:
            return {"items": self.type_schema(inner), "type": "array"}
        inner = optional_inner(cpp_type)
        if inner is not None:
            # Optional ownership fields are represented by omission, never null.
            return self.type_schema(inner)
        if cpp_type.endswith("*"):
            pointee = normalize_cpp_type(cpp_type[:-1].replace("const ", "", 1))
            return self.type_schema(pointee)
        return self.type_schema(cpp_type)

    def type_schema(self, cpp_type):
        if cpp_type == "std::string":
            return {"type": "string"}
        if cpp_type == "bool":
            return {"type": "boolean"}
        if cpp_type in {"int", "size_t"}:
            schema = {"type": "integer"}
            if cpp_type == "size_t":
                schema["minimum"] = 0
            return schema
        if cpp_type in self.enums:
            return {"enum": self.enums[cpp_type], "type": "string"}
        if cpp_type in self.structs:
            self.add_struct(cpp_type)
            return ref(cpp_type)
        raise SchemaGenerationError(
            f"unsupported field type {cpp_type!r}; update the frozen §6.1 mapping"
        )

    def add_struct(self, name):
        if name in self.definitions:
            return
        if name in self.visiting:
            raise SchemaGenerationError(f"owned struct cycle involving {name}")
        fields = self.structs.get(name)
        if fields is None:
            raise SchemaGenerationError(f"unknown owned struct {name}")
        self.visiting.add(name)
        properties = {}
        required = []
        for field in fields:
            properties[field.name] = self.field_schema(name, field)
            if optional_inner(field.cpp_type) is None and not field.cpp_type.endswith("*"):
                required.append(field.name)
        self.visiting.remove(name)
        self.definitions[name] = {
            "additionalProperties": False,
            "properties": properties,
            "required": required,
            "type": "object",
        }

    def build(self):
        graph_fields = self.structs.get("BackendProjectionGraph")
        if graph_fields is None:
            raise SchemaGenerationError("BackendProjectionGraph was not discovered")
        if not graph_fields or graph_fields[0].name != "schemaVersion":
            raise SchemaGenerationError(
                "BackendProjectionGraph must begin with schemaVersion"
            )

        node_properties = {}
        node_required = []
        edge_type = None
        for field in graph_fields[1:]:
            inner = vector_inner(field.cpp_type)
            if inner is None:
                raise SchemaGenerationError(
                    f"graph member {field.name} is not an owned vector"
                )
            self.add_struct(inner)
            if field.name == "edges":
                if inner != "ProjectionEdge":
                    raise SchemaGenerationError(
                        "graph edges must own ProjectionEdge records"
                    )
                edge_type = inner
                continue
            if inner == "ProjectionEdge":
                raise SchemaGenerationError(
                    f"ProjectionEdge vector must be named edges, got {field.name}"
                )
            node_properties[field.name] = {
                "description": (
                    "Deterministic source order: family/node-kind ordinal, then stable id."
                ),
                "items": ref(inner),
                "type": "array",
            }
            node_required.append(field.name)
        if edge_type is None:
            raise SchemaGenerationError("BackendProjectionGraph has no edges vector")

        return {
            "$defs": self.definitions,
            "$id": SCHEMA_ID,
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "additionalProperties": False,
            "description": (
                "Lossless canonical-JSON wire form generated from "
                "BackendProjectionGraph. Derived projection views are excluded."
            ),
            "properties": {
                "edges": {
                    "description": "Sorted lexicographically by (from, name, to).",
                    "items": ref(edge_type),
                    "type": "array",
                },
                "kind": {"const": WIRE_KIND},
                "nodes": {
                    "additionalProperties": False,
                    "properties": node_properties,
                    "required": node_required,
                    "type": "object",
                },
                "schemaVersion": {
                    "const": self.schema_version,
                    "description": "BackendProjectionGraph representation version.",
                    "minimum": 0,
                    "type": "integer",
                },
            },
            "required": ["kind", "schemaVersion", "nodes", "edges"],
            "title": "Neutrino finalized projection v1",
            "type": "object",
        }


def reachable_structs(structs):
    graph_fields = structs["BackendProjectionGraph"]
    pending = [
        vector_inner(field.cpp_type)
        for field in graph_fields[1:]
    ]
    result = set()
    while pending:
        name = pending.pop()
        if name in result:
            continue
        if name not in structs:
            raise SchemaGenerationError(f"unknown owned struct {name}")
        result.add(name)
        for field in structs[name]:
            cpp_type = optional_inner(field.cpp_type) or field.cpp_type
            inner = vector_inner(cpp_type)
            if inner in structs:
                pending.append(inner)
            elif cpp_type in structs:
                pending.append(cpp_type)
            elif cpp_type.endswith("*"):
                raise SchemaGenerationError(
                    f"owned pointer field {name}.{field.name} requires an explicit "
                    "wire ownership decision"
                )
    return sorted(result)


def codec_fields(structs, enums):
    """Emit the X-macro ownership map consumed by both codec directions."""
    owned = reachable_structs(structs)

    def scalar_type(cpp_type):
        cpp_type = optional_inner(cpp_type) or cpp_type
        return vector_inner(cpp_type) or cpp_type

    used_enums = sorted(
        {
            scalar_type(field.cpp_type)
            for name in owned
            for field in structs[name]
            if scalar_type(field.cpp_type) in enums
        }
    )
    lines = [
        "// Generated by scripts/generators/gen_finalized_projection_schema.py.",
        "// Multi-include ownership map: intentionally has no include guard.",
        "",
    ]
    for name in used_enums:
        lines.append(f"NEUTRINO_PROJECTION_WIRE_ENUM_BEGIN({name})")
        for value in enums[name]:
            lines.append(
                f"NEUTRINO_PROJECTION_WIRE_ENUM_VALUE({name}, {value})"
            )
        lines.append(f"NEUTRINO_PROJECTION_WIRE_ENUM_END({name})")
        lines.append("")
    for name in owned:
        lines.append(f"NEUTRINO_PROJECTION_WIRE_STRUCT_BEGIN({name})")
        for field in structs[name]:
            optional = optional_inner(field.cpp_type)
            macro = (
                "NEUTRINO_PROJECTION_WIRE_OPTIONAL_FIELD"
                if optional is not None
                else "NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD"
            )
            cpp_type = optional or field.cpp_type
            lines.append(f"{macro}({name}, {cpp_type}, {field.name})")
        lines.append(f"NEUTRINO_PROJECTION_WIRE_STRUCT_END({name})")
        lines.append("")
    graph_fields = structs["BackendProjectionGraph"]
    for field in graph_fields[1:]:
        inner = vector_inner(field.cpp_type)
        macro = (
            "NEUTRINO_PROJECTION_WIRE_EDGE_FAMILY"
            if field.name == "edges"
            else "NEUTRINO_PROJECTION_WIRE_NODE_FAMILY"
        )
        lines.append(f"{macro}({inner}, {field.name})")
    lines.append("")
    return ("\n".join(lines)).encode("utf-8")


def generate(header, coordination_header, gate_mode_header):
    header_text = pathlib.Path(header).read_text(encoding="utf-8")
    coordination_text = pathlib.Path(coordination_header).read_text(encoding="utf-8")
    gate_mode_text = pathlib.Path(gate_mode_header).read_text(encoding="utf-8")
    clean_header = strip_comments(header_text)
    graph_match = re.search(
        r"\bstruct\s+BackendProjectionGraph\s*\{.*?\};", clean_header, re.S
    )
    if not graph_match:
        raise SchemaGenerationError("BackendProjectionGraph was not discovered")
    # The graph and every owned struct it references are declared before this
    # boundary. Anything after it is a derived consumer view and is not wire.
    ownership_region = header_text[: graph_match.end()]
    version_match = re.search(
        r"\bkProjectionSchemaVersion\s*=\s*([0-9]+)\s*;",
        strip_comments(ownership_region),
    )
    if not version_match:
        raise SchemaGenerationError("kProjectionSchemaVersion was not discovered")
    structs = parse_structs(ownership_region)
    enums = parse_enums(ownership_region, coordination_text, gate_mode_text)
    schema = SchemaBuilder(structs, enums, int(version_match.group(1))).build()
    schema_bytes = (json.dumps(schema, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    return schema_bytes, codec_fields(structs, enums)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--header", type=pathlib.Path, default=DEFAULT_HEADER)
    parser.add_argument(
        "--coordination-header",
        type=pathlib.Path,
        default=DEFAULT_COORDINATION_HEADER,
    )
    parser.add_argument(
        "--gate-mode-header",
        type=pathlib.Path,
        default=DEFAULT_GATE_MODE_HEADER,
    )
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--codec-fields-output",
        type=pathlib.Path,
        help="required build-tree destination when generating codec fields",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless regenerated bytes equal the committed output",
    )
    args = parser.parse_args(argv)
    try:
        generated_schema, generated_codec_fields = generate(
            args.header, args.coordination_header, args.gate_mode_header
        )
        if args.check:
            if not args.output.is_file():
                raise SchemaGenerationError(f"committed schema missing: {args.output}")
            if args.output.read_bytes() != generated_schema:
                raise SchemaGenerationError(
                    "committed finalized-projection schema is stale; regenerate with "
                    f"{pathlib.Path(__file__).relative_to(REPO)}"
                )
            if args.codec_fields_output is not None:
                if not args.codec_fields_output.is_file():
                    raise SchemaGenerationError(
                        f"codec field map missing: {args.codec_fields_output}"
                    )
                if args.codec_fields_output.read_bytes() != generated_codec_fields:
                    raise SchemaGenerationError(
                        "finalized-projection codec field map is stale; "
                        "regenerate it with the schema"
                    )
            print(
                "finalized-projection schema fresh: "
                f"{len(json.loads(generated_schema)['$defs']) - 1} owned structs"
            )
            return 0
        if args.codec_fields_output is None:
            raise SchemaGenerationError(
                "--codec-fields-output is required when generating"
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.codec_fields_output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(generated_schema)
        args.codec_fields_output.write_bytes(generated_codec_fields)
        print(f"wrote {args.output} and {args.codec_fields_output}")
        return 0
    except (OSError, SchemaGenerationError, json.JSONDecodeError) as exc:
        print(f"gen_finalized_projection_schema: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
