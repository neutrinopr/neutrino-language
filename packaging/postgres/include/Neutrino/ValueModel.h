#ifndef NEUTRINO_VALUE_MODEL_H
#define NEUTRINO_VALUE_MODEL_H

#include "llvm/ADT/ArrayRef.h"
#include "llvm/ADT/StringRef.h"

namespace neutrino {

// The typed value model for the value types the language has today (M5 WP1a,
// ).
//
// This is the single source of truth for value-type classification. It replaces
// the ad-hoc string matching (`isNumericType`-style, and scattered `ty ==
// "money"` chains) that the frontend, verifier, scenario validation, and
// backends previously each re-derived from raw type strings — so a value's
// category is trustworthy before any backend generation (M5 ADR D5,
// docs/process/M5_DECISIONS_ADR.md).
//
// The governed model is exactly the six value types the language has today. Per
// D5, new types (timestamps, hashes, slot ids, ...) enter through the
// expression/extension process only when a gate sample demands them; until
// then, any type name outside the governed set classifies as `Extension`:
// accepted verbatim (the input type vocabulary is intentionally open,
// docs/language/NEU_LANGUAGE_SPEC.md), but carrying no type-specific validation
// or lowering semantics.
enum class ValueCategory {
  Money,     // integer minor units
  Decimal,   // scaled integer (also the home of the numeric spellings below)
  Party,     // participant id (string)
  Currency,  // ISO-4217 code (string)
  Evidence,  // hashable reference (string)
  String,    // opaque string
  Extension, // outside the governed value model — accepted, unclassified
};

// Classify a declared type name into its value category. Total and pure: an
// unknown / extension type name maps to ValueCategory::Extension (this never
// fails). The numeric spellings `number`/`int`/`integer`/`uint` are accepted
// aliases of the numeric category (folded to `Decimal`), preserving today's
// numeric-vs-string behavior exactly — they are alternate spellings, not new
// governed types.
ValueCategory classifyValueType(llvm::StringRef ty);

// True when `type` is a declared temporal type name. Temporal types remain
// ValueCategory::Extension; this separate closed classification lets shared
// consumers recognize caller-supplied time values without backend inference.
bool isTemporalType(llvm::StringRef type);

// True for the six governed value types (everything except Extension).
bool isCanonicalCategory(ValueCategory c);

// True for categories carried as an integer (Money, Decimal). The typed
// replacement for the old `isNumericType` string match.
bool isNumericCategory(ValueCategory c);

// A stable, lowercase, machine-readable name for the category (diagnostics /
// metadata).
llvm::StringRef categoryName(ValueCategory c);

// The inverse of categoryName: a category name back to its ValueCategory. Total
// — an unrecognized name maps to Extension. Used to restore a node's inferred
// dtype from its serialized/attribute form without re-running inference (),
// so categoryName(categoryFromName(s)) == s for every governed name.
ValueCategory categoryFromName(llvm::StringRef name);

// The governed value categories (the six canonical types — everything except
// Extension), in canonical order. This is the single enumerable source of the
// governed value-type set: language metadata and any other consumer render the
// set FROM here rather than re-listing it, so the governed vocabulary lives
// once, next to the enum and categoryName(). Adding a governed type is a
// one-line change here plus its categoryName() case.
llvm::ArrayRef<ValueCategory> governedCategories();

} // namespace neutrino

#endif // NEUTRINO_VALUE_MODEL_H
