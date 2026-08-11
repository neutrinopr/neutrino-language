//===- LanguageVocabulary.h - shared .neu keyword vocabulary API --------===//
//
// Single keyword/field vocabulary shared by the frontend parser and
// languageMetadataJson() (). The declarative source is
// LanguageVocabulary.def; this header exposes the generated id enum, the
// table, and the ONLY approved recognition helpers the parser may use to
// match a vocabulary spelling against source text.
//
//===----------------------------------------------------------------------===//

#ifndef NEUTRINO_LANGUAGE_VOCABULARY_H
#define NEUTRINO_LANGUAGE_VOCABULARY_H

#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringRef.h"

namespace neutrino {

// Metadata category buckets (keywordCategories in language-metadata.json).
enum class VocabCategory { Statement, Field, Connector };

// One enumerator per vocabulary entry. Names come from LanguageVocabulary.def
// (EnumId column). A few spellings need a trailing underscore because they are
// C++ keywords or macros (`and` → and_, `assert` → assert_).
enum class VocabId {
#define NEUTRINO_VOCAB(Category, EnumId, Spelling) EnumId,
#include "Neutrino/LanguageVocabulary.def"
#undef NEUTRINO_VOCAB
};

struct VocabEntry {
  VocabId id;
  VocabCategory category;
  llvm::StringRef spelling;
};

// The full table, in .def order. languageMetadataJson() sorts when emitting.
llvm::ArrayRef<VocabEntry> languageVocabulary();

// Spelling / category for a VocabId. O(1).
llvm::StringRef vocabSpelling(VocabId id);
VocabCategory vocabCategory(VocabId id);

// --- Approved recognition API ----------------------------------------------
// Frontend keyword recognition MUST go through these helpers. A raw
// startswith("kw "), parts[N] == "kw", key == "field", consumeKeyword(_, "kw"),
// or similar idiom on a keyword-shaped literal outside this API fails the
// parser-keyword gate.

// True when `line` begins with the spelling followed by a space (statement
// leaders such as "procedure ", "debit ").
bool lineStartsWithKeyword(llvm::StringRef line, VocabId id);

// Like lineStartsWithKeyword, and on success sets `rest` to the text after the
// leading "kw " prefix.
bool matchKeywordPrefix(llvm::StringRef line, VocabId id, llvm::StringRef &rest);

// Exact equality: `token` is precisely the vocabulary spelling (no padding).
bool tokenIsKeyword(llvm::StringRef token, VocabId id);

// Whole-word consume from the front of `s` (after ltrim): advances past the
// spelling when followed by whitespace, EOL, or a quote. Same contract as
// ParseUtil::consumeKeyword, but bound to a VocabId.
bool consumeVocabKeyword(llvm::StringRef &s, VocabId id);

// True when `line` contains the spelling as a whole word bounded by spaces
// (e.g. " as " inside an allow-constraint line).
bool lineContainsKeywordWord(llvm::StringRef line, VocabId id);

} // namespace neutrino

#endif // NEUTRINO_LANGUAGE_VOCABULARY_H
