""": finalized-projection schema is source-derived and deterministic."""

import json
import pathlib

from _fastcase import FastCase, PY, REPO


HEADER = "include/Neutrino/BackendProjection.h"
SCHEMA = "docs/schemas/finalized-projection-v1.schema.json"


class FinalizedProjectionSchema(FastCase):
    def test_committed_schema_is_fresh_and_deterministic(self):
        self.assert_ok(
            "committed installable schema freshness",
            PY,
            "scripts/generators/gen_finalized_projection_schema.py",
            "--check",
        )
        first = pathlib.Path(self.tmp) / "first.json"
        second = pathlib.Path(self.tmp) / "second.json"
        first_fields = pathlib.Path(self.tmp) / "first.inc"
        second_fields = pathlib.Path(self.tmp) / "second.inc"
        self.assert_ok(
            "first deterministic generation",
            PY,
            "scripts/generators/gen_finalized_projection_schema.py",
            "--output",
            first,
            "--codec-fields-output",
            first_fields,
        )
        self.assert_ok(
            "second deterministic generation",
            PY,
            "scripts/generators/gen_finalized_projection_schema.py",
            "--output",
            second,
            "--codec-fields-output",
            second_fields,
        )
        committed = pathlib.Path(REPO, SCHEMA).read_bytes()
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(first.read_bytes(), committed)
        self.assertEqual(first_fields.read_bytes(), second_fields.read_bytes())

    def test_generation_requires_explicit_codec_destination(self):
        self.assert_reject(
            "source-tree codec output has no default",
            PY,
            "scripts/generators/gen_finalized_projection_schema.py",
            "--output",
            pathlib.Path(self.tmp) / "must-not-complete.json",
        )

    def test_new_owner_field_changes_the_generated_schema(self):
        header = pathlib.Path(REPO, HEADER).read_text(encoding="utf-8")
        anchor = (
            "struct LedgerPosting {\n"
            "  std::string id;\n"
        )
        self.assertEqual(header.count(anchor), 1, "mutation anchor must be unique")
        mutated = header.replace(
            anchor,
            anchor + "  std::string schemaMutationProbe;\n",
            1,
        )
        mutated_header = pathlib.Path(self.tmp) / "BackendProjection.h"
        mutated_output = pathlib.Path(self.tmp) / "mutated-schema.json"
        mutated_fields = pathlib.Path(self.tmp) / "mutated-fields.inc"
        mutated_header.write_text(mutated, encoding="utf-8")
        self.assert_ok(
            "new graph-owned field is discovered",
            PY,
            "scripts/generators/gen_finalized_projection_schema.py",
            "--header",
            mutated_header,
            "--output",
            mutated_output,
            "--codec-fields-output",
            mutated_fields,
        )
        schema = json.loads(mutated_output.read_text(encoding="utf-8"))
        posting = schema["$defs"]["LedgerPosting"]
        self.assertIn("schemaMutationProbe", posting["properties"])
        self.assertIn("schemaMutationProbe", posting["required"])
        self.assertIn(
            "NEUTRINO_PROJECTION_WIRE_REQUIRED_FIELD("
            "LedgerPosting, std::string, schemaMutationProbe)",
            mutated_fields.read_text(encoding="utf-8"),
        )
        self.assertNotEqual(
            mutated_output.read_bytes(), pathlib.Path(REPO, SCHEMA).read_bytes()
        )

    def test_unknown_owner_type_fails_closed(self):
        header = pathlib.Path(REPO, HEADER).read_text(encoding="utf-8")
        anchor = (
            "struct LedgerPosting {\n"
            "  std::string id;\n"
        )
        self.assertEqual(header.count(anchor), 1, "mutation anchor must be unique")
        mutated = header.replace(
            anchor,
            anchor + "  UndeclaredWireType unsupportedMutationProbe;\n",
            1,
        )
        mutated_header = pathlib.Path(self.tmp) / "BackendProjection.h"
        mutated_header.write_text(mutated, encoding="utf-8")
        self.assert_reject(
            "unknown §6.1 type mapping",
            PY,
            "scripts/generators/gen_finalized_projection_schema.py",
            "--header",
            mutated_header,
            "--output",
            pathlib.Path(self.tmp) / "must-not-exist.json",
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
