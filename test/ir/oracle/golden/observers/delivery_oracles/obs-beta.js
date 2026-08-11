// Neutrino oracle observer (generated, M5 oracle S4 ) — observer 'obs-beta' of set 'delivery_oracles'.
// Off-chain half of the M-of-N attestation on evidence 'delivery_proof': subscribe -> canonicalize -> sign. Deterministic; the keccak256
// hasher and secp256k1 signer are INJECTED (real at deploy, mocked in tests), so this file carries no live dependency.
'use strict';

const OBSERVER = "obs-beta";
const OBSERVER_SET = "delivery_oracles";
const PUBLIC_KEY = "0xbb'02";
const CLAIM_FIELD = "delivered";

// Canonicalize an observation into the agreed claim value (mode: exact). N observers must produce the SAME canonical
// value to reach quorum — that is what turns a non-deterministic observation into a verifiable predicate.
function canonicalize(observation) {
  // exact: the discrete event value, trimmed — observers agree byte-for-byte.
  return String(observation[CLAIM_FIELD]).trim();
}

// The canonical claim every observer signs — single-sourced from the spec so the on-chain guard verifies the SAME encoding.
function claim(observation) {
  return { observerSet: OBSERVER_SET, input: "delivery_proof", field: CLAIM_FIELD, value: canonicalize(observation) };
}

// Stable byte encoding of the claim (fixed field order) that gets hashed + signed.
function encode(c) {
  return [c.observerSet, c.input, c.field, c.value].join('\u0000');
}

// Observe one event from `source`, canonicalize, and sign keccak256(claim) with `signer` (secp256k1).
// Fail-closed: never signs an observation missing the claim field.
async function observe(source, keccak256, signer) {
  const observation = await source.next();
  if (observation == null || observation[CLAIM_FIELD] === undefined)
    throw new Error("observation missing claim field '" + CLAIM_FIELD + "'");
  const c = claim(observation);
  const digest = keccak256(encode(c));
  const signature = signer(digest);
  return { observer: OBSERVER, publicKey: PUBLIC_KEY, claim: c, digest, signature };
}

module.exports = { canonicalize, claim, encode, observe, OBSERVER, OBSERVER_SET };
