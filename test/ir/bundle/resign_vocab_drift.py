""" slice 2 tamper helper: stage a bundle whose semantic-vocabulary artifact
has a DIFFERENT semanticProfileVersion, then re-sign it self-consistently — the
artifact digest, the bundle self-digest, and the pack's exact digest pin are ALL
recomputed to agree. Only the INTERNAL version drifts (artifact vs the bundle's
own metadata/versions), which the verifier must still reject (not just stale bytes).

Usage: resign_vocab_drift.py <repo-root> <stage-dir> <pack.json>
"""
import hashlib
import json
import os
import shutil
import sys

repo, stage, pack_src = sys.argv[1:4]


def canonical(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(path):
    return "sha256:" + hashlib.sha256(open(path, "rb").read()).hexdigest()


bundle = json.load(open(os.path.join(repo, "docs/core-contract-bundle.json"), encoding="utf-8"))
vpath = bundle["semanticVocabulary"]["path"]

# Artifact with a drifted version, written into the stage; leave the bundle's own
# semanticVocabulary.semanticProfileVersion + versions.semanticProfileVersion at 3.
art = json.load(open(os.path.join(repo, vpath), encoding="utf-8"))
art["semanticProfileVersion"] = 999
dst = os.path.join(stage, vpath)
os.makedirs(os.path.dirname(dst), exist_ok=True)
open(dst, "w").write(json.dumps(art))

# Re-pin the artifact digest, then recompute the bundle self-digest, then the pack pin.
bundle["semanticVocabulary"]["sha256"] = sha(dst)
body = {k: v for k, v in bundle.items() if k != "bundleDigest"}
bundle["bundleDigest"] = "sha256:" + hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()
json.dump(bundle, open(os.path.join(stage, "core-contract-bundle.json"), "w"))

pack = json.load(open(pack_src, encoding="utf-8"))
pack["targetsBundle"]["bundleDigest"] = bundle["bundleDigest"]
json.dump(pack, open(os.path.join(stage, "pack.json"), "w"))
