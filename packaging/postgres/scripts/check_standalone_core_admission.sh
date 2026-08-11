#!/usr/bin/env bash
# : POSITIVE and NEGATIVE witnesses for the standalone installed-core seam.
#
# The committed standalone-configure check sets NBP_STANDALONE_CORE=OFF, so it
# cannot exercise the ON path at all — which is how a forbidden C++ ABI edge
# (Neutrino::SpecContract / Neutrino::CodeText) survived in that branch. This
# witness configures the ON path against a materialized core fixture and proves:
#   * POSITIVE — a WELL-FORMED core prefix configures AND GENERATES with no core
#     C++ target linked (generation is what fails on a missing imported target).
#   * NEGATIVE — empty-but-executable artifacts, a missing prefix-local manifest,
#     an artifact substituted under an unchanged out-of-band receipt, a receipt
#     whose body no longer hashes to its own receiptDigest, a receipt resolving
#     inside the admitted prefix, and a receipt for another buildTarget are each
#     REFUSED.
#
# Admission is byte-bound to a producer-emitted release receipt (/)
# delivered out-of-band, so these are authenticity witnesses, not seam-only
# ones. The prefix-local digest sidecar this used to build is gone: it was
# derived from the prefix it described, so the substitution case above passed it
# by construction.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG="$(dirname "$HERE")"; ROOT="$(dirname "$(dirname "$PKG")")"
FX="$(mktemp -d)"; BUILD="$(mktemp -d)"; rc=0
trap 'rm -rf "$FX" "$BUILD" "$FX.receipt.json"' EXIT
mkdir -p "$FX/bin" "$FX/share/neutrino"
cp "$ROOT/docs/m7-core-installed-export.json" "$FX/share/neutrino/"

mk_real() { for b in bundle emit equiv gen opt translate; do
  printf '#!/bin/sh\nexit 0\n' > "$FX/bin/neutrino-$b"; chmod +x "$FX/bin/neutrino-$b"; done; }
mk_empty() { for b in bundle emit equiv gen opt translate; do
  : > "$FX/bin/neutrino-$b"; chmod +x "$FX/bin/neutrino-$b"; done; }
# The receipt is written OUTSIDE the fixture prefix: Mode A refuses a record
# that travels with, or is selected from within, the artifacts it describes.
RECEIPT="$FX.receipt.json"
TARGET="witness-target"
receipt() { python3 -c "
import json,hashlib,os,sys
fx,out,target=sys.argv[1],sys.argv[2],sys.argv[3]
export=fx+'/share/neutrino/m7-core-installed-export.json'
d=json.load(open(export))
sha=lambda b: hashlib.sha256(b).hexdigest()
r={'kind':'neutrino.m7-core-release-receipt/1','schemaVersion':1,
   'sourceCommit':'0'*39+'a','buildTarget':target,
   'installedExportSha256':sha(open(export,'rb').read()),
   'runtimeArtifacts':[{'path':a,
     'sha256':sha(open(os.path.join(fx,a),'rb').read()),
     'mode':format(os.stat(os.path.join(fx,a)).st_mode & 0o777,'04o')}
     for a in sorted(d['runtimeArtifacts'])]}
body=json.dumps(r,sort_keys=True,separators=(',',':'),ensure_ascii=False)
r['receiptDigest']='sha256:'+sha(body.encode('utf-8'))
json.dump(r,open(out,'w'),indent=2,sort_keys=True)" "$FX" "$RECEIPT" "$TARGET"; }
cfg() { rm -rf "$BUILD"; cmake -S "$PKG" -B "$BUILD" -DNBP_STANDALONE_CORE=ON \
        -DNBP_CORE_PREFIX="$FX" -DNBP_CORE_RECEIPT="$RECEIPT" \
        -DNBP_CORE_BUILD_TARGET="$TARGET" >"$BUILD.log" 2>&1; }
expect() { local want=$1 desc=$2; cfg; local got=$?
  if [ "$want" = pass ] && [ $got -ne 0 ]; then echo "  FAIL(expected pass) $desc"; rc=1
  elif [ "$want" = fail ] && [ $got -eq 0 ]; then echo "  FAIL(expected refusal) $desc"; rc=1
  else echo "  ok   $desc"; fi; }

mk_real; receipt
expect pass "POSITIVE: authenticated prefix configures and GENERATES, no core C++ target linked"
mk_empty; receipt
expect fail "NEGATIVE: empty-but-executable artifacts are refused"
mk_real; receipt; rm -f "$FX/share/neutrino/m7-core-installed-export.json"
expect fail "NEGATIVE: missing prefix-local manifest is refused (no source-tree fallback)"

# The decisive case. Substitute an artifact AND rewrite every prefix-local
# record consistently; only the out-of-band receipt is left alone. A
# prefix-derived check passes this by construction -- that is exactly why the
# transitional sidecar was deleted rather than kept alongside the receipt.
cp "$ROOT/docs/m7-core-installed-export.json" "$FX/share/neutrino/"; mk_real; receipt
printf '#!/bin/sh\nexit 1\n' > "$FX/bin/neutrino-emit"; chmod +x "$FX/bin/neutrino-emit"
expect fail "NEGATIVE(decisive): artifact substituted, out-of-band receipt unchanged"

mk_real; receipt
python3 -c "
import json,sys; p=sys.argv[1]
r=json.load(open(p)); r['runtimeArtifacts'][0]['sha256']='0'*64; json.dump(r,open(p,'w'))" "$RECEIPT"
expect fail "NEGATIVE: a receipt whose body no longer hashes to its receiptDigest is refused"

mk_real; receipt; cp "$RECEIPT" "$FX/share/neutrino/receipt.json"
RECEIPT_SAVED="$RECEIPT"; RECEIPT="$FX/share/neutrino/receipt.json"
expect fail "NEGATIVE(Mode A): a receipt resolving inside the admitted prefix is refused"
RECEIPT="$RECEIPT_SAVED"

mk_real; receipt; TARGET_SAVED="$TARGET"; TARGET="a-different-platform"
expect fail "NEGATIVE: a receipt for another buildTarget is refused"
TARGET="$TARGET_SAVED"

[ $rc -eq 0 ] && echo "standalone-core admission witness OK (byte-bound to an out-of-band release receipt; artifact substitution, in-prefix delivery, digest tamper and wrong target all refused)" || echo "standalone-core admission witness FAILED"
exit $rc
