#ifndef NEUTRINO_VERSIONINFO_H
#define NEUTRINO_VERSIONINFO_H

// Single source of truth for the translator's language/artifact compatibility
// surface (). Every shipped tool exposes it via `--version` /
// `--version-json` so downstream console/agents/network/wrappers can detect and
// fail-closed on an unsupported language level or schema bundle. Field names
// align with docs/schemas/component-compatibility-manifest.schema.json where
// they overlap.

#include "Neutrino/BuildInfo.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"

namespace neutrino {

// Tool/contract versions. kToolVersion is the one tool-version constant
// (manifests reference it too, so a single edit moves the whole toolchain).
inline constexpr const char *kToolVersion = "0.2.0";
inline constexpr const char *kMlirDialectVersion = "0.1.0";
inline constexpr const char *kSchemaBundleVersion = "v1";
inline constexpr const char *kConformanceVectorVersion = "envelope-v1";
inline constexpr const char *kCompatibilityManifestVersion = "v1";
// The capability-spec (canonical capability-spec) CONTRACT version — the `vN`
// of docs/schemas/capability-spec.schema.json's `$id`. Side artifacts that
// consume the capability-spec (target profiles, domain dialects) pin this via a
// `capabilitySpecVersion` field, and scripts/gates/check_artifact_pins.py fails
// closed on a mismatch with this emitted value (R3, ). A contract bump is a
// single edit here, kept in lockstep with the schema `$id` by that checker's
// self-test.
inline constexpr const char *kCapabilitySpecVersion = "v1";
// Per-contract trust/binding schema versions — the values `versionInfo()` emits
// under `schemas` and that downstream consumers pin on. Named constants (not
// inline literals) so a per-contract bump is a single edit here and is caught
// by the cross-rail catalog validator.
inline constexpr const char *kSchemaBindingPolicy = "v1";
inline constexpr const char *kSchemaBindingReceipt = "v1";
inline constexpr const char *kSchemaRuntimeEvidence = "v1";
inline constexpr int kVersionEnvelopeSchema = 1;

// The semantic-realization-profile CONTRACT version: the version of the
// normalized-semantic-requirement registry + limits vocabulary that a target
// profile's `semanticProfile` block and the built-in reference evaluator
// profile are matched against. DISTINCT from the target-profile schemaVersion
// and the tool version (deliberately not overloaded) — a coordination plan is
// matched to a profile only when the profile pins THIS version; a missing or
// unknown `semanticProfile.version` fails closed before evaluator/lowering
// dispatch. Bumped whenever the closed registry or the profile-limits
// vocabulary changes.
inline constexpr int kSemanticProfileVersion = 3;

// The L2->L1 REDUCTION-SEMANTICS contract version (): the version of the
//  reduction rules that interpret an executable reduction edge (relation +
// lossiness) into a CoordinationPlan requirement. DISTINCT from the envelope
// schemaVersion (the domain-semantics artifact shape) and from
// kSemanticProfileVersion (the capability vocabulary). Stamped into every
// emitted v2 domain-semantics artifact under `intakeVersioning` so the
// intake seam can reject a stale artifact whose reducer semantics no longer
// match. Bumped whenever the reduction interpretation of an edge changes.
inline constexpr int kReductionSemanticsVersion = 1;

// The semantic-agreement LANGUAGE version (): the version of the neutrino
// semantic-agreement language the portable agreement identity is expressed in.
// It is domain-separated into the agreementHash preimage and re-checked on
// ingest — an agreement-identity object declaring an unknown semanticLanguage
// version fails closed. DISTINCT from the per-agreement `specVersion` (the
// authored DSL version carried inside the capability-spec) and from the
// capability-spec / profile contract versions; this versions the identity
// language contract as a whole. Bumped when the identity language changes.
inline constexpr const char *kSemanticLanguageVersion = "0.1.0";

// The agreement-identity domain-separation tag (): the versioned domain
// prefix hashed into the agreementHash preimage so an agreement digest can
// never collide with any other neutrino hash (capabilityHash, an oracle claim
// digest,
// ...). The trailing `.vN` is the identity-object domain version.
inline constexpr const char *kAgreementDomain = "neutrino.agreement.v1";

// The agreement-envelope schema version (): the versioned identity-level
// semantics (consent/amendment policy, clause semantic IDs) carried alongside
// the capability-spec. An envelope declaring an unknown schema version fails
// closed on ingest.
inline constexpr int kAgreementEnvelopeVersion = 1;

// The complete version/compatibility surface as a stable, versioned JSON
// envelope.
inline llvm::json::Value versionInfo(llvm::StringRef tool) {
  return llvm::json::Object{
      {"schemaVersion", kVersionEnvelopeSchema},
      {"kind", "neutrino.translator-version"},
      {"tool", tool},
      {"toolVersion", kToolVersion},
      {"gitSha", kGitSha},
      {"buildTarget", kBuildTarget},
      // L1-L5 are the translator-owned language levels; L2 (state machines) is
      // not in the current DSL. L6-L10 are network/runtime concerns. See
      // LANGUAGE_LEVELS.md.
      {"languageLevels",
       llvm::json::Object{
           {"supported", llvm::json::Array{"L1", "L3", "L4", "L5"}},
           {"future", llvm::json::Array{"L2"}},
           {"max", "L5"}}},
      {"mlirDialectVersion", kMlirDialectVersion},
      {"schemaBundleVersion", kSchemaBundleVersion},
      {"capabilitySpecVersion", kCapabilitySpecVersion},
      // The semantic-realization-profile contract version a target profile's
      // `semanticProfile` block must pin for the coordination-plan legality
      // gate to accept it. Published here so a downstream profile author can
      // discover which contract the installed translator accepts.
      {"semanticProfileVersion", kSemanticProfileVersion},
      // The semantic-agreement language version the portable agreement identity
      // () is expressed in; published so a downstream consumer can discover
      // which identity-language contract the installed translator accepts.
      {"semanticLanguageVersion", kSemanticLanguageVersion},
      {"schemas",
       llvm::json::Object{{"bindingPolicy", kSchemaBindingPolicy},
                          {"bindingReceipt", kSchemaBindingReceipt},
                          {"runtimeEvidence", kSchemaRuntimeEvidence}}},
      {"conformanceVectorVersion", kConformanceVectorVersion},
      {"compatibilityManifestVersion", kCompatibilityManifestVersion},
  };
}

// Intercept `--version` / `--version-json` from argv BEFORE any llvm::cl
// parsing (so it works with no inputs and never collides with cl's own
// --version). Returns true when handled — the caller should then exit(0).
// `--version-json` prints the stable JSON envelope; `--version` a short human
// line.
inline bool handleVersionFlag(int argc, char **argv, llvm::StringRef tool) {
  for (int i = 1; i < argc; ++i) {
    llvm::StringRef a(argv[i]);
    if (a == "--version-json") {
      llvm::outs() << llvm::formatv("{0:2}", versionInfo(tool)) << "\n";
      return true;
    }
    if (a == "--version") {
      llvm::outs() << tool << " " << kToolVersion << " (" << kGitSha << ", "
                   << kBuildTarget << "); language L1-L5 (L2 future), dialect "
                   << kMlirDialectVersion << ", schemas "
                   << kSchemaBundleVersion << "\n";
      return true;
    }
  }
  return false;
}

} // namespace neutrino

#endif // NEUTRINO_VERSIONINFO_H
