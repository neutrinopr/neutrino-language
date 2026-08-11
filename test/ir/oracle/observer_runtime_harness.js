'use strict';
// [] Runtime API harness for a generated domain-bound oracle observer. Proves
// the EXECUTABLE observer leg of the observer -> guard -> coordination vector: the
// observer co-signs the  executionClaim it is given and returns it, and it
// FAILS CLOSED on a missing/short/non-hex executionClaim (the validation boundary
// the build-tools caller must honor). The keccak256 hasher + secp256k1 signer are
// injected (per the observer contract), stubbed here — the exact hash bytes are
// irrelevant to the API contract; what matters is that the executionClaim is
// validated, co-signed, and surfaced.
//
// usage: node observer_runtime_harness.js <path-to-generated-observer.js>
const crypto = require('crypto');
const obs = require(process.argv[2]);

// The committed  vector digest (execution-claim-vector.json).
const VEC = '0xf08e38690b06cf6770ea204af8ce6039c6b990aca51d6702e0df119e35632325';
const CLAIM_ID = '0x' + '11'.repeat(32);

// Injected stubs. keccak256 receives a Uint8Array and returns a 0x-prefixed hex
// word (the shape _word() consumes); the algorithm is irrelevant to this test.
const keccak256 = (u8) => '0x' + crypto.createHash('sha256').update(Buffer.from(u8)).digest('hex');
const signer = (digest) => '0xSIG:' + digest;
// The observer's CLAIM_FIELD is bound to "delivered" (binding-guard.json).
const source = () => ({ next: async () => ({ delivered: 'true' }) });

let failures = 0;
function check(cond, what) {
  if (!cond) { console.error('FAIL: ' + what); failures++; }
}
async function throwsAsync(fn, what) {
  try { await fn(); check(false, what + ' (did not throw)'); }
  catch (e) { /* expected */ }
}

(async () => {
  // (1) Correct: a valid executionClaim is co-signed and surfaced verbatim.
  const r = await obs.observe(source(), keccak256, signer, CLAIM_ID, VEC);
  check(r.executionClaim === VEC, 'observer surfaces the co-signed executionClaim unchanged');
  check(typeof r.signature === 'string' && r.signature.length > 0, 'observer produced a signature');
  check(r.claimId === CLAIM_ID, 'observer surfaces the claimId');

  // The signed digest must DEPEND on the executionClaim: a different execution
  // claim (same evidence) yields a different digest — the co-sign is non-vacuous.
  const other = '0x' + 'ab'.repeat(32);
  const r2 = await obs.observe(source(), keccak256, signer, CLAIM_ID, other);
  check(r.digest !== r2.digest, 'the signed digest depends on the executionClaim (co-signed, not decorative)');

  // (2) Fail-closed on a MISSING executionClaim (the 4-arg legacy caller shape).
  await throwsAsync(() => obs.observe(source(), keccak256, signer, CLAIM_ID), 'missing executionClaim rejected');
  // (3) Fail-closed on a SHORT / wrong-width value.
  await throwsAsync(() => obs.observe(source(), keccak256, signer, CLAIM_ID, '0x1234'), 'short executionClaim rejected');
  // (4) Fail-closed on a NON-HEX value.
  await throwsAsync(
    () => obs.observe(source(), keccak256, signer, CLAIM_ID, '0x' + 'zz'.repeat(32)),
    'non-hex executionClaim rejected');
  // (5) Fail-closed on a non-string value.
  await throwsAsync(() => obs.observe(source(), keccak256, signer, CLAIM_ID, 12345), 'non-string executionClaim rejected');

  if (failures) { console.error(failures + ' check(s) failed'); process.exit(1); }
  console.log('observer runtime API OK: co-signs + surfaces the  executionClaim; fails closed on missing/short/non-hex/non-string');
})().catch((e) => { console.error('harness error: ' + (e && e.stack || e)); process.exit(1); });
