//===- GenOracleObserverSpec.cpp - the off-chain oracle observer renderer -===//
//
// M5 oracle S4 (): render the deterministic serverless observers +
// aggregation from the frozen capability-spec's attestation policy () plus
// an observation binding. Consumes ONLY the spec JSON + binding JSON + the
// AttestationPolicy leaf contract — no ProcedureView — so it links only
// NeutrinoSpecContract. See Neutrino/GenOracleObserverSpec.h.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenOracleObserverSpec.h"

#include "Neutrino/Attestation.h"
#include "Neutrino/CodeText.h"
#include "Neutrino/Expr.h"
#include "Neutrino/JsonUtil.h"

#include <cctype>
#include <string>
#include <vector>

using namespace llvm;

namespace neutrino {

namespace {

// The single fail-closed funnel (keeps this TU at one `throw` per the
// policy ratchet): every rejected spec/binding shape routes through here.
[[noreturn]] void fail(const char *code, const std::string &msg) {
  throw ExprError(code, msg);
}

// A JS string literal from a spec/binding value (deterministic). DOUBLE-quoted
// + jsonEscape (a JSON double-quoted-string escaper), so a value containing an
// apostrophe or a double quote cannot break out of the literal or inject code:
// jsonEscape escapes `"`/`\`/controls, and `'` is inert inside
// a double-quoted JS string.
std::string js(StringRef s) { return "\"" + jsonEscape(s) + "\""; }

// An identifier from the untrusted spec/binding that reaches BOTH a generated
// file path (observers/<ref>/<id>.js) AND an output position outside a string
// literal (the observer's header comments interpolate the ref/id/input raw). A
// blocklist is not enough: a control character such as a newline both
// makes an unusable filename AND breaks out of a `//` comment into code
// position (comment injection), and `..`/slashes escape the -o dir (path
// traversal). So require a strict ALLOWLIST — a non-empty `[A-Za-z0-9._-]`
// token, never `.`/`..` — which kills traversal, control-char filenames, and
// comment injection at once.
const std::string &safeIdent(const std::string &s, const char *what) {
  bool ok = !s.empty() && s != "." && s != "..";
  for (char c : s)
    ok = ok &&
         (std::isalnum((unsigned char)c) || c == '.' || c == '_' || c == '-');
  if (!ok)
    fail("binding.unsafe_ident",
         std::string("oracle ") + what + " '" + s +
             "' is not a safe identifier (allow only non-empty [A-Za-z0-9._-], "
             "not '.'/'..') — refused so an untrusted spec/binding cannot "
             "escape "
             "the output directory or inject into the generated code");
  return s;
}

// One observer-set entry from the binding: the concrete mock source + members,
// plus the OPTIONAL EIP-712 acceptance-guard domain (oracle S7, ). When the
// domain is bound (chainId + verifyingContract set, capabilityHash from the
// spec), the observer signs the domain-separated digest the on-chain guard
// verifies (the observer↔guard parity point); when absent it signs the naked
// canonical-claim digest (the S4 default).
struct BoundSet {
  std::string ref, sourceType, sourceId, claimField;
  std::vector<std::pair<std::string, std::string>> members; // (id, publicKey)
  std::string chainId, verifyingContract, capabilityHash;
  bool hasDomain() const { return !chainId.empty(); }
};

BoundSet resolveSet(const json::Object &binding, const AttestationPolicy &p) {
  const json::Array *sets = binding.getArray("observerSets");
  if (!sets)
    fail("binding.schema", "observation-binding has no observerSets[]");
  for (const json::Value &sv : *sets) {
    const json::Object *s = sv.getAsObject();
    if (!s || s->getString("ref").value_or("") != p.observerSet)
      continue;
    BoundSet b;
    b.ref = p.observerSet;
    // Require an EXPLICIT source object + type (no silent `mock` default): a
    // binding that omits the descriptor must fail closed, not be treated as a
    // supported mock source.
    const json::Object *src = s->getObject("source");
    if (!src)
      fail("binding.schema",
           "observer-set '" + p.observerSet + "' has no source object");
    b.sourceType = src->getString("type").value_or("").str();
    b.sourceId = src->getString("id").value_or("").str();
    b.claimField = src->getString("claimField").value_or("").str();
    // Optional EIP-712 guard domain (S7, ): present iff a bound acceptance
    // guard domain-separates the signed digest.
    if (const json::Object *dom = s->getObject("domain")) {
      if (auto cid = dom->getInteger("chainId"))
        b.chainId = std::to_string(*cid);
      b.verifyingContract =
          dom->getString("verifyingContract").value_or("").str();
    }
    if (const json::Array *ms = s->getArray("members"))
      for (const json::Value &mv : *ms)
        if (const json::Object *m = mv.getAsObject())
          b.members.push_back({m->getString("id").value_or("").str(),
                               m->getString("publicKey").value_or("").str()});
    return b;
  }
  fail("binding.unbound_observer_set",
       "attestation observer-set '" + p.observerSet +
           "' has no entry in the observation binding");
}

// Render one observer module (member of the set). Deterministic; the keccak256
// hasher and the secp256k1 signer are INJECTED so CI needs no crypto
// dependency.
std::string renderObserver(const AttestationPolicy &p, const BoundSet &b,
                           const std::string &memberId,
                           const std::string &publicKey) {
  // Structural framing is described with the codetext block/line model (,
  // ): the printer owns indentation + structural newlines, so the JS below
  // is codetext nodes, not raw string concatenation. This CLOSES the
  // comment-injection class by construction: the header comments interpolate
  // the (untrusted) memberId/ref/input, but they are `line()` nodes now, and
  // codetext's line() REJECTS an embedded newline — so a control-char/newline
  // value fails closed at the emitter (report_fatal_error), not silently
  // breaking out of a `//` comment into code position. safeIdent stays as
  // defense-in-depth (and for the FILE PATH), but structural safety no longer
  // relies on it.
  using namespace codetext;
  std::string tol = p.tolerance.empty() ? "1" : p.tolerance;
  std::vector<Node> canon;
  if (p.canonicalization == "median") {
    canon.push_back(
        line("// median: round the numeric reading to the agreement "
             "band so near-equal readings collapse to one canonical "
             "value."));
    canon.push_back(line("const TOLERANCE = Number(" + js(tol) + ");"));
    canon.push_back(line("const v = Number(observation[CLAIM_FIELD]);"));
    canon.push_back(
        line("return String(Math.round(v / TOLERANCE) * TOLERANCE);"));
  } else {
    canon.push_back(line("// exact: the discrete event value, trimmed — "
                         "observers agree byte-for-byte."));
    canon.push_back(line("return String(observation[CLAIM_FIELD]).trim();"));
  }

  Document doc;
  doc.add(line("// Neutrino oracle observer (generated, M5 oracle S4 ) — "
               "observer '" +
               memberId + "' of set '" + b.ref + "'."));
  doc.add(line("// Off-chain half of the M-of-N attestation on evidence '" +
               p.input +
               "': subscribe -> canonicalize -> sign. Deterministic; the "
               "keccak256"));
  doc.add(line("// hasher and secp256k1 signer are INJECTED (real at deploy, "
               "mocked in tests), so this file carries no live dependency."));
  doc.add(line("'use strict';"));
  doc.add(blank());
  doc.add(line("const OBSERVER = " + js(memberId) + ";"));
  doc.add(line("const OBSERVER_SET = " + js(b.ref) + ";"));
  doc.add(line("const PUBLIC_KEY = " + js(publicKey) + ";"));
  doc.add(line("const CLAIM_FIELD = " + js(b.claimField) + ";"));
  doc.add(blank());
  doc.add(line("// Canonicalize an observation into the agreed claim value "
               "(mode: " +
               p.canonicalization +
               "). N observers must produce the SAME canonical"));
  doc.add(line("// value to reach quorum — that is what turns a "
               "non-deterministic observation into a verifiable predicate."));
  doc.add(block("function canonicalize(observation) {", "}", std::move(canon)));
  doc.add(blank());
  doc.add(line("// The canonical claim every observer signs — single-sourced "
               "from the spec so the on-chain guard verifies the SAME "
               "encoding."));
  doc.add(
      block("function claim(observation) {", "}",
            {line("return { observerSet: OBSERVER_SET, input: " + js(p.input) +
                  ", field: CLAIM_FIELD, value: canonicalize(observation) "
                  "};")}));
  doc.add(blank());
  doc.add(line("// Stable byte encoding of the claim (fixed field order) that "
               "gets hashed + signed."));
  doc.add(block("function encode(c) {", "}",
                {line("return [c.observerSet, c.input, c.field, "
                      "c.value].join('\\u0000');")}));
  doc.add(blank());

  if (!b.hasDomain()) {
    // S4 default (no bound guard): sign the naked canonical-claim digest.
    doc.add(line("// Observe one event from `source`, canonicalize, and sign "
                 "keccak256(claim) with `signer` (secp256k1)."));
    doc.add(line(
        "// Fail-closed: never signs an observation missing the claim field."));
    doc.add(block(
        "async function observe(source, keccak256, signer) {", "}",
        {line("const observation = await source.next();"),
         block("if (observation == null || observation[CLAIM_FIELD] === "
               "undefined)",
               "",
               {line("throw new Error(\"observation missing claim field '\" + "
                     "CLAIM_FIELD + \"'\");")}),
         line("const c = claim(observation);"),
         line("const digest = keccak256(encode(c));"),
         line("const signature = signer(digest);"),
         line("return { observer: OBSERVER, publicKey: PUBLIC_KEY, claim: c, "
              "digest, signature };")}));
    doc.add(blank());
    doc.add(line("module.exports = { canonicalize, claim, encode, observe, "
                 "OBSERVER, OBSERVER_SET };"));
    return doc.print("  ");
  }

  // S7 (): a bound acceptance guard domain-separates the signed digest, so
  // the observer signs EXACTLY the EIP-712 digest the on-chain guard
  // (ThresholdQuorumAcceptance.sol, ) verifies — the observer↔guard parity
  // point. Same type strings, same domain (chainId + verifyingContract +
  // capabilityHash), same recipe, so an off-chain signature verifies on chain
  // and cannot be replayed onto another chain/contract/capability. keccak256
  // here hashes BYTES (a Uint8Array); the type strings + canonical claim are
  // UTF-8 bytes, the 32-byte words are left-padded big-endian.
  doc.add(line("const CAPABILITY_HASH = " + js(b.capabilityHash) + ";"));
  doc.add(line("const CHAIN_ID = " + b.chainId + ";"));
  doc.add(line("const VERIFYING_CONTRACT = " + js(b.verifyingContract) + ";"));
  doc.add(line("// The guard's EIP-712 type strings — byte-identical to "
               "ThresholdQuorumAcceptance.sol (parity)."));
  doc.add(
      line("const DOMAIN_TYPE = \"NeutrinoThresholdQuorumAcceptance(uint256 "
           "chainId,address verifyingContract,bytes32 capabilityHash)\";"));
  doc.add(line("const CLAIM_TYPE = \"QuorumClaim(bytes32 claimId,bytes32 "
               "canonicalClaimHash,bytes32 executionClaim)\";"));
  doc.add(line("const _utf8 = (s) => new TextEncoder().encode(s);"));
  doc.add(line(
      "const _hex = (h) => { h = String(h).replace(/^0x/, \"\"); if (h.length "
      "% 2) h = \"0\" + h; const a = new Uint8Array(h.length / 2); for (let i "
      "= 0; i < a.length; i++) a[i] = parseInt(h.substr(2 * i, 2), 16); return "
      "a; };"));
  doc.add(line(
      "const _word = (v) => _hex((typeof v === \"number\" ? v.toString(16) "
      ": String(v).replace(/^0x/, \"\")).padStart(64, \"0\"));"));
  doc.add(line(
      "const _cat = (...xs) => { let n = 0; for (const x of xs) n += x.length; "
      "const o = new Uint8Array(n); let k = 0; for (const x of xs) { o.set(x, "
      "k); k += x.length; } return o; };"));
  doc.add(blank());
  doc.add(line("// EIP-712 digest = keccak256(0x1901 || domainSeparator || "
               "hashStruct(claim)), mirroring the guard's claimDigest()."));
  doc.add(block(
      "function claimDigest(keccak256, claimId, canonicalClaimHash, "
      "executionClaim) {",
      "}",
      {line("const domainSeparator = keccak256(_cat(keccak256(_utf8(DOMAIN_TYPE"
            ")), _word(CHAIN_ID), _word(VERIFYING_CONTRACT), "
            "_word(CAPABILITY_HASH)));"),
       line("const structHash = keccak256(_cat(keccak256(_utf8(CLAIM_TYPE)), "
            "_word(claimId), _word(canonicalClaimHash), "
            "_word(executionClaim)));"),
       line("return keccak256(_cat(_hex(\"1901\"), domainSeparator, "
            "structHash));")}));
  doc.add(blank());
  doc.add(
      line("// Observe one event, canonicalize, and CO-SIGN the EIP-712 digest "
           "over both the evidence"));
  doc.add(line(
      "// claim and the  `executionClaim` (the coordination's recomputable "
      "payload digest), so the"));
  doc.add(line("// attested evidence is bound to the exact execution it "
               "authorizes for checkpoint `claimId`."));
  doc.add(line(
      "// Fail-closed: never signs an observation missing the claim field."));
  doc.add(block(
      "async function observe(source, keccak256, signer, claimId, "
      "executionClaim) {",
      "}",
      {line(
           "// Fail-closed: the  executionClaim MUST be a 32-byte hex word "
           "(0x + 64 hex). A"),
       line(
           "// missing/malformed value would otherwise be coerced to a garbage "
           "digest and co-signed."),
       block("if (typeof executionClaim !== \"string\" || "
             "!/^0x[0-9a-fA-F]{64}$/.test(executionClaim))",
             "",
             {line("throw new Error(\"executionClaim must be a 0x-prefixed "
                   "32-byte hex word\");")}),
       line("const observation = await source.next();"),
       block("if (observation == null || observation[CLAIM_FIELD] === "
             "undefined)",
             "",
             {line("throw new Error(\"observation missing claim field '\" + "
                   "CLAIM_FIELD + \"'\");")}),
       line("const c = claim(observation);"),
       line("const canonicalClaimHash = keccak256(_utf8(encode(c))); // the "
            "observers' evidence claim digest"),
       line(
           "const digest = claimDigest(keccak256, claimId, "
           "canonicalClaimHash, executionClaim); // EIP-712, domain-separated"),
       line("const signature = signer(digest);"),
       line("return { observer: OBSERVER, publicKey: PUBLIC_KEY, claim: c, "
            "claimId, canonicalClaimHash, executionClaim, digest, signature "
            "};")}));
  doc.add(blank());
  doc.add(line("module.exports = { canonicalize, claim, encode, claimDigest, "
               "observe, OBSERVER, OBSERVER_SET };"));
  return doc.print("  ");
}

// Render the aggregator: collects attestations that signed the SAME canonical
// claim and packages the quorum for the on-chain guard. Fail-closed on < M.
std::string renderAggregator(const AttestationPolicy &p, const BoundSet &b) {
  using namespace codetext;
  std::string observers = "const OBSERVERS = [";
  for (size_t i = 0; i < b.members.size(); ++i)
    observers += (i ? ", " : "") + js(b.members[i].first);
  observers += "]; // N (binding)";
  std::string authorized = "const AUTHORIZED = new Set([";
  for (size_t i = 0; i < b.members.size(); ++i)
    authorized += (i ? ", " : "") + js(b.members[i].second);
  authorized += "]); // the bound observer public keys — the ONLY signers "
                "that count";

  Document doc;
  doc.add(line("// Neutrino oracle aggregator (generated, M5 oracle S4 ) — "
               "set '" +
               b.ref + "', quorum " + std::to_string(p.quorum) + "-of-" +
               std::to_string(b.members.size()) + "."));
  doc.add(line("// Packages the M-of-N quorum the on-chain acceptance guard "
               "consumes: a leg fires ONLY on >= M signatures over the SAME "
               "canonical claim"));
  doc.add(line("// (fail-closed — never on a partial or divergent set; " +
               p.fallback + " on timeout)."));
  doc.add(line("'use strict';"));
  doc.add(blank());
  doc.add(
      line("const THRESHOLD = " + std::to_string(p.quorum) + "; // M (spec)"));
  doc.add(line(observers));
  doc.add(line(authorized));
  doc.add(blank());
  doc.add(line("// Fire ONLY on >= M signatures over the SAME canonical claim "
               "from DISTINCT AUTHORIZED observers: a signature whose public "
               "key is not in the"));
  doc.add(line("// bound set is ignored, and each authorized signer counts at "
               "most once — so a duplicate signer or an unknown key can never "
               "satisfy the quorum"));
  doc.add(line("// (fail-closed on < M; " + p.fallback + " on timeout)."));
  doc.add(block(
      "function aggregate(attestations) {", "}",
      {line("const byDigest = {};"),
       block(
           "for (const a of attestations) {", "}",
           {line("if (!AUTHORIZED.has(a.publicKey)) continue; // unknown "
                 "signer -> not counted"),
            line("const signers = (byDigest[a.digest] = byDigest[a.digest] || "
                 "new Map());"),
            line("if (!signers.has(a.publicKey)) signers.set(a.publicKey, a); "
                 "// distinct signers only")}),
       block("for (const digest of Object.keys(byDigest).sort()) {", "}",
             {line("const group = [...byDigest[digest].values()]; // distinct "
                   "authorized signers over one claim"),
              block("if (group.length >= THRESHOLD)", "",
                    {line("return { met: true, digest, claim: group[0].claim, "
                          "signatures: group.map(g => g.signature), signers: "
                          "group.map(g => g.publicKey) };")})}),
       line("return { met: false, threshold: THRESHOLD, observed: "
            "attestations.length };")}));
  doc.add(blank());
  doc.add(line(
      "module.exports = { aggregate, THRESHOLD, OBSERVERS, AUTHORIZED };"));
  return doc.print("  ");
}

} // namespace

std::vector<OracleFile>
generateOracleObserverFromSpec(const json::Object &spec,
                               const json::Object &binding) {
  std::vector<AttestationPolicy> policies = attestationPoliciesFromSpec(spec);
  if (policies.empty())
    fail("spec.no_attestation",
         "capability-spec declares no attestation policy; the oracle observer "
         "backend renders from an `attest` policy ()");

  // Fail-closed on the binding ENVELOPE on our own — the standalone validator
  // () is the richer diagnostic surface, but the renderer must not trust an
  // unvalidated binding: the kind/schemaVersion tag and unique observer-set
  // refs. Per-set shape (source/members/keys/ids) is enforced as each set is
  // resolved + rendered below.
  if (binding.getString("kind").value_or("") != "neutrino.observation-binding")
    fail("binding.schema",
         "observation-binding 'kind' must be 'neutrino.observation-binding'");
  if (binding.getInteger("schemaVersion").value_or(0) != 1)
    fail("binding.schema", "observation-binding 'schemaVersion' must be 1");
  if (const json::Array *sets = binding.getArray("observerSets")) {
    std::vector<std::string> refs;
    for (const json::Value &sv : *sets)
      if (const json::Object *s = sv.getAsObject()) {
        std::string r = s->getString("ref").value_or("").str();
        for (const std::string &prev : refs)
          if (prev == r)
            fail("binding.duplicate_observer_set",
                 "observer-set '" + r + "' is bound more than once");
        refs.push_back(r);
      }
  }

  std::vector<OracleFile> out;
  for (const AttestationPolicy &p : policies) {
    // The contract must be valid before we render code from it.
    if (std::string err = validateAttestationPolicy(p); !err.empty())
      fail("spec.ast", err);
    BoundSet b = resolveSet(binding, p);
    if ((int)b.members.size() < p.quorum)
      fail("binding.quorum_unreachable",
           "observer-set '" + b.ref + "' binds " +
               std::to_string(b.members.size()) +
               " observers but the policy requires a quorum of " +
               std::to_string(p.quorum) +
               " — the M-of-N quorum could never be met");
    if (b.claimField.empty())
      fail("binding.schema", "observer-set '" + b.ref +
                                 "' binds no source.claimField to observe");
    // Fail-closed on the binding shapes the observation-binding contract ()
    // rejects, so a malformed binding can never reach the generated observers
    // or guard: an unsupported source descriptor, a missing observer public key
    // (the aggregator authorizes the quorum BY public key, so an empty key
    // would admit an unauthenticated attestation), or a duplicate observer
    // identity (which would collide generated files and silently drop a
    // signer).
    if (b.sourceType != "mock")
      fail("binding.unsupported_source",
           "observer-set '" + b.ref + "' binds an unsupported source type '" +
               b.sourceType + "' (expected: mock)");
    for (size_t i = 0; i < b.members.size(); ++i) {
      if (b.members[i].second.empty())
        fail("binding.missing_public_key",
             "observer-set '" + b.ref + "' observer '" + b.members[i].first +
                 "' has no public key");
      for (size_t k = 0; k < i; ++k)
        if (b.members[k].first == b.members[i].first)
          fail("binding.duplicate_observer",
               "observer-set '" + b.ref + "' binds observer id '" +
                   b.members[i].first + "' more than once");
    }

    // EIP-712 acceptance-guard domain (S7, ): when the binding names a
    // guard (chainId + verifyingContract), the observer signs the
    // domain-separated digest the on-chain guard verifies — which needs the
    // capability identity from the spec. A domain without a capabilityHash
    // cannot domain-separate.
    if (b.hasDomain()) {
      if (b.verifyingContract.empty())
        fail("binding.schema", "observer-set '" + b.ref +
                                   "' guard domain has no verifyingContract");
      if (const json::Object *id = spec.getObject("identity"))
        b.capabilityHash = id->getString("capabilityHash").value_or("").str();
      if (b.capabilityHash.empty())
        fail(
            "spec.ast",
            "observer-set '" + b.ref +
                "' binds a guard domain but the capability-spec has no "
                "identity.capabilityHash to domain-separate the signed digest");
    }

    // Containment + no-injection: every untrusted
    // identifier that reaches a file path OR a raw output position (the
    // observer's header comments) must be an allowlisted token — the ref + each
    // member id (path + comment) AND the evidence input name `p.input`
    // (interpolated raw in the observer comment). Validated BEFORE any render
    // so a bad value fails closed.
    safeIdent(p.input, "attestation input");
    std::string dir = "observers/" + safeIdent(b.ref, "observer-set ref") + "/";
    for (const auto &m : b.members)
      out.push_back({dir + safeIdent(m.first, "observer id") + ".js",
                     renderObserver(p, b, m.first, m.second)});
    out.push_back({dir + "aggregate.js", renderAggregator(p, b)});
  }
  return out;
}

} // namespace neutrino
