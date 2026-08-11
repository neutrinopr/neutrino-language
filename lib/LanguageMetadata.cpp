#include "Neutrino/LanguageMetadata.h"

#include "Neutrino/LanguageVocabulary.h"
#include "Neutrino/ValueModel.h"

#include "llvm/ADT/StringRef.h"
#include "llvm/Support/FormatVariadic.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"

#include <algorithm>
#include <set>
#include <string>
#include <vector>

using namespace llvm;

namespace neutrino {

namespace {

// Keyword categories are definitionally the LanguageVocabulary.def table
// () — the same table frontend recognition consumes via the approved
// helpers in LanguageVocabulary.h. Adding a vocabulary row updates both
// languageMetadataJson() and the parser's available spellings; there is no
// hand-maintained keyword mirror here.
//
// Operators/functions below remain a hand mirror of the Expr compiler (F2
// residual); only the keyword surface is definitionally closed.

json::Array sortedSpellings(VocabCategory cat) {
  std::vector<std::string> v;
  for (const VocabEntry &e : languageVocabulary())
    if (e.category == cat)
      v.push_back(e.spelling.str());
  std::sort(v.begin(), v.end());
  json::Array a;
  for (auto &s : v)
    a.push_back(s);
  return a;
}

// The governed value types come from the typed value model () — the SINGLE
// source of truth. Both the governed SET and each spelling are ValueModel's:
// governedCategories() enumerates the set and categoryName() names it, so a new
// value category is added in ValueModel alone and flows into the metadata here.
json::Array valueTypesArray() {
  json::Array a;
  for (ValueCategory c : governedCategories())
    a.push_back(categoryName(c).str());
  return a;
}

// The compute operators + functions the Expr compiler supports (Expr.h/.cpp):
// binary +,-,*,/ over integer minor units (`/` is integer division), and the
// `round(x, k)` function (round(x,k)==x).
//
// These still mirror the Expr compiler by hand — self-test [37] only proves the
// JSON matches these arrays, not that these arrays match Expr.cpp. `round`'s
// arity is "1..2". The durable fix is to derive operators/functions from an
// Expr-owned table so the extension process updates the metadata as a side
// effect (separate from the keyword vocabulary closed in ).
json::Array operatorsArray() {
  json::Array a;
  for (const char *op : {"+", "-", "*", "/"})
    a.push_back(json::Object{{"symbol", op}, {"kind", "binary"}});
  // Comparison operators: valid ONLY inside a leg's `when` guard predicate
  // (never as a value), lowered to SQL / Solidity / the reference evaluator.
  for (const char *op : {"<", "<=", ">", ">=", "==", "!="})
    a.push_back(json::Object{{"symbol", op}, {"kind", "comparison"}});
  return a;
}

json::Array functionsArray() {
  return json::Array{
      json::Object{{"name", "round"},
                   {"arity", "1..2"},
                   {"description", "round to k minor-unit places; identity on "
                                   "minor units (round(x, k) == x)"}}};
}

} // namespace

std::string languageMetadataJson() {
  // Deterministic: no gitSha / timestamp, so docs/language-metadata.json is
  // byte-reproducible and drift-testable. `schemaVersion` is the
  // language-metadata schema version.
  json::Object keywordCategories{
      {"statement", sortedSpellings(VocabCategory::Statement)},
      {"field", sortedSpellings(VocabCategory::Field)},
      {"connector", sortedSpellings(VocabCategory::Connector)},
  };

  // keywords = the sorted union of the three categories (barewords; value types
  // are separate).
  std::set<std::string> all;
  for (const VocabEntry &e : languageVocabulary())
    all.insert(e.spelling.str());
  json::Array keywords;
  for (auto &s : all)
    keywords.push_back(s);

  json::Object root{
      // schemaVersion 2: adds `stringDelimiters` — the lexical fact a generated
      // editor grammar (TextMate) needs, alongside the existing comment/block
      // delimiters. Additive; consumers ignoring it still work.
      {"schemaVersion", 2},
      {"kind", "neutrino.language-metadata"},
      {"language", "neutrino"},
      {"canonicalExtension", ".neu"},
      {"legacyExtensions", json::Array{}},
      {"lineComments", json::Array{"//", "#"}},
      {"blockComment", nullptr},
      {"blockDelimiters",
       json::Array{json::Array{"{", "}"}, json::Array{"[", "]"}}},
      // .neu string literals are double-quoted; owned here so the grammar
      // generator draws it from the compiler, not a hand-maintained rule.
      {"stringDelimiters", json::Array{"\""}},
      {"keywords", std::move(keywords)},
      {"keywordCategories", std::move(keywordCategories)},
      {"valueTypes", valueTypesArray()},
      {"operators", operatorsArray()},
      {"functions", functionsArray()},
  };
  return formatv("{0:2}", json::Value(std::move(root))).str();
}

bool handleLanguageMetadataFlag(int argc, char **argv) {
  for (int i = 1; i < argc; ++i) {
    if (StringRef(argv[i]) == "--language-metadata") {
      outs() << languageMetadataJson() << "\n";
      return true;
    }
  }
  return false;
}

} // namespace neutrino
