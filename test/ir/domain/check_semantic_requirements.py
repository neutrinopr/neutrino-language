#!/usr/bin/env python3
import importlib.util
import json
import os
import sys

artifact_path, vocabulary_path, schema_path = sys.argv[1:]
repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
module_path = os.path.join(repo, "scripts", "samples", "make_core_feature_example_matrix.py")
spec = importlib.util.spec_from_file_location("core_feature_matrix", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with open(artifact_path, encoding="utf-8") as handle:
    artifact = json.load(handle)
with open(vocabulary_path, encoding="utf-8") as handle:
    vocabulary = json.load(handle)
with open(schema_path, encoding="utf-8") as handle:
    schema = json.load(handle)

errors = module.semantic_requirement_errors(artifact, set(vocabulary["features"]))
if artifact.get("semanticProfileVersion") != vocabulary.get("semanticProfileVersion"):
    errors.append("semanticProfileVersion differs from vocabulary")
if schema.get("additionalProperties") is not False:
    errors.append("semantic-requirements schema is not closed")
if set(schema.get("required", [])) != set(schema.get("properties", {})):
    errors.append("semantic-requirements schema required/properties drift")
if errors:
    for error in errors:
        print(error, file=sys.stderr)
    raise SystemExit(1)
print("semantic-requirements artifact OK")
