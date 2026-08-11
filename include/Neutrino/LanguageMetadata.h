#ifndef NEUTRINO_LANGUAGE_METADATA_H
#define NEUTRINO_LANGUAGE_METADATA_H

#include <string>

namespace neutrino {

// The canonical grammar/language metadata the COMPILER owns. Keywords come from
// LanguageVocabulary.def (shared with frontend recognition helpers). Governed
// value types come from the typed value model (ValueModel); compute operators /
// functions still mirror Expr by hand. Emitted as deterministic JSON so Python
// tooling (scripts/generators/neutrino_lang.py) consumes it instead of
// hand-maintaining these lists. The output carries a `schemaVersion` and is
// byte-stable (no gitSha/timestamp), so the committed docs/language-metadata.json
// is regenerated + byte-matched by a drift test.
std::string languageMetadataJson();

// Early argv intercept (mirrors handleVersionFlag): `--language-metadata`
// prints the JSON and returns true so the caller exits(0). Works with no
// inputs, before any llvm::cl parsing.
bool handleLanguageMetadataFlag(int argc, char **argv);

} // namespace neutrino

#endif // NEUTRINO_LANGUAGE_METADATA_H
