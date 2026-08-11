#include "Neutrino/DiagnosticTaxonomy.h"

#include "llvm/Support/FormatVariadic.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"

using namespace llvm;

namespace neutrino {

namespace {

// The shared failure taxonomy (M5 WP1c, ). Ordered by `precedence` (root
// cause first). Precedences are spaced so a follow-up kernel rule can slot in
// without renumbering. ACTIVE codes are emitted today; RESERVED codes name a
// future kernel rule / target-profile check so downstream can bind to a stable
// code before the emitter lands — they must never appear in real diagnostics.
//
// KEEP IN SYNC with docs/language/DIAGNOSTIC_TAXONOMY.md (self-test [76]
// byte-matches the emitted JSON against docs/diagnostic-taxonomy.json).
constexpr TaxonomyEntry kTaxonomy[] = {
// The table is generated from the declarative source
// include/Neutrino/DiagnosticTaxonomy.def (M5  D1, ) — this file no
// longer owns an independent hand-maintained table. Add/change a code THERE,
// not here; the emitted JSON (docs/diagnostic-taxonomy.json) is byte-matched by
// self-test [76]/[78].
#define NEUTRINO_DIAG(Cat, Code, Stat, Prec, Summary, Emit)                    \
  {Code, DiagCategory::Cat, DiagStatus::Stat, Prec, Summary, DiagEmitter::Emit},
#include "Neutrino/DiagnosticTaxonomy.def"
#undef NEUTRINO_DIAG
};

} // namespace

llvm::ArrayRef<TaxonomyEntry> diagnosticTaxonomy() { return kTaxonomy; }

llvm::StringRef categoryName(DiagCategory c) {
  switch (c) {
  case DiagCategory::Frontend:
    return "frontend";
  case DiagCategory::Kernel:
    return "kernel";
  case DiagCategory::Value:
    return "value";
  case DiagCategory::Expr:
    return "expr";
  case DiagCategory::Scenario:
    return "scenario";
  case DiagCategory::Security:
    return "security";
  case DiagCategory::Generate:
    return "generate";
  case DiagCategory::Equivalence:
    return "equivalence";
  case DiagCategory::Classification:
    return "classification";
  case DiagCategory::Spec:
    return "spec";
  case DiagCategory::Profile:
    return "profile";
  case DiagCategory::Legality:
    return "legality";
  case DiagCategory::Realization:
    return "realization";
  case DiagCategory::View:
    return "view";
  case DiagCategory::Observation:
    return "observation";
  case DiagCategory::Domain:
    return "domain";
  }
  return "unknown";
}

llvm::StringRef statusName(DiagStatus s) {
  return s == DiagStatus::Active ? "active" : "reserved";
}

llvm::StringRef emitterName(DiagEmitter e) {
  switch (e) {
  case DiagEmitter::Cpp:
    return "cpp";
  case DiagEmitter::Validator:
    return "validator";
  case DiagEmitter::Both:
    return "both";
  }
  return "unknown";
}

static const TaxonomyEntry *lookup(llvm::StringRef code) {
  for (const TaxonomyEntry &e : kTaxonomy)
    if (e.code == code)
      return &e;
  return nullptr;
}

bool isRegisteredCode(llvm::StringRef code) { return lookup(code) != nullptr; }

bool isActiveCode(llvm::StringRef code) {
  const TaxonomyEntry *e = lookup(code);
  return e && e->status == DiagStatus::Active;
}

int rootCausePrecedence(llvm::StringRef code) {
  const TaxonomyEntry *e = lookup(code);
  // An unregistered code sorts LAST so a stray/typo'd code can never mask a
  // real root cause; the membership self-test is what keeps codes from being
  // unknown.
  return e ? e->precedence : 1'000'000;
}

std::string diagnosticTaxonomyJson() {
  json::Array codes;
  for (const TaxonomyEntry &e : kTaxonomy)
    codes.push_back(json::Object{
        {"code", e.code},
        {"category", categoryName(e.category)},
        {"emitter", emitterName(e.emitter)},
        {"status", statusName(e.status)},
        {"precedence", e.precedence},
        {"summary", e.summary},
    });

  json::Object root{
      {"schemaVersion", 1},
      {"kind", "neutrino.diagnostic-taxonomy"},
      // The categories, in root-cause precedence order (frontend most primary).
      {"categories",
       json::Array{"frontend", "kernel", "value", "expr", "scenario",
                   "security", "generate", "equivalence", "classification",
                   "spec", "profile", "legality", "realization", "view",
                   "observation", "domain"}},
      {"codes", std::move(codes)},
  };
  return formatv("{0:2}", json::Value(std::move(root))).str();
}

bool handleDiagnosticTaxonomyFlag(int argc, char **argv) {
  for (int i = 1; i < argc; ++i) {
    if (StringRef(argv[i]) == "--diagnostic-taxonomy") {
      outs() << diagnosticTaxonomyJson() << "\n";
      return true;
    }
  }
  return false;
}

} // namespace neutrino
