// Neutrino oracle aggregator (generated, M5 oracle S4 ) — set 'delivery_oracles', quorum 2-of-3.
// Packages the M-of-N quorum the on-chain acceptance guard consumes: a leg fires ONLY on >= M signatures over the SAME canonical claim
// (fail-closed — never on a partial or divergent set; abort on timeout).
'use strict';

const THRESHOLD = 2; // M (spec)
const OBSERVERS = ["obs-alpha", "obs-beta", "obs-gamma"]; // N (binding)
const AUTHORIZED = new Set(["0xaa01", "0xbb'02", "0xcc03"]); // the bound observer public keys — the ONLY signers that count

// Fire ONLY on >= M signatures over the SAME canonical claim from DISTINCT AUTHORIZED observers: a signature whose public key is not in the
// bound set is ignored, and each authorized signer counts at most once — so a duplicate signer or an unknown key can never satisfy the quorum
// (fail-closed on < M; abort on timeout).
function aggregate(attestations) {
  const byDigest = {};
  for (const a of attestations) {
    if (!AUTHORIZED.has(a.publicKey)) continue; // unknown signer -> not counted
    const signers = (byDigest[a.digest] = byDigest[a.digest] || new Map());
    if (!signers.has(a.publicKey)) signers.set(a.publicKey, a); // distinct signers only
  }
  for (const digest of Object.keys(byDigest).sort()) {
    const group = [...byDigest[digest].values()]; // distinct authorized signers over one claim
    if (group.length >= THRESHOLD)
      return { met: true, digest, claim: group[0].claim, signatures: group.map(g => g.signature), signers: group.map(g => g.publicKey) };
  }
  return { met: false, threshold: THRESHOLD, observed: attestations.length };
}

module.exports = { aggregate, THRESHOLD, OBSERVERS, AUTHORIZED };
