#include "Neutrino/ValueModel.h"

#include "llvm/ADT/StringSwitch.h"

namespace neutrino {

ValueCategory classifyValueType(llvm::StringRef ty) {
  return llvm::StringSwitch<ValueCategory>(ty)
      .Case("money", ValueCategory::Money)
      // `decimal` and the numeric spellings all carry as a scaled/whole
      // integer; folding them here preserves the historical `isNumericType` set
      // (money/decimal/number/int/ integer/uint) exactly, now as one typed
      // category.
      .Case("decimal", ValueCategory::Decimal)
      .Case("number", ValueCategory::Decimal)
      .Case("int", ValueCategory::Decimal)
      .Case("integer", ValueCategory::Decimal)
      .Case("uint", ValueCategory::Decimal)
      .Case("party", ValueCategory::Party)
      .Case("currency", ValueCategory::Currency)
      .Case("evidence", ValueCategory::Evidence)
      .Case("string", ValueCategory::String)
      .Default(ValueCategory::Extension);
}

bool isTemporalType(llvm::StringRef type) {
  return type == "timestamp" || type == "instant" || type == "datetime" ||
         type == "date" || type == "time" || type == "duration";
}

bool isCanonicalCategory(ValueCategory c) {
  return c != ValueCategory::Extension;
}

bool isNumericCategory(ValueCategory c) {
  return c == ValueCategory::Money || c == ValueCategory::Decimal;
}

llvm::ArrayRef<ValueCategory> governedCategories() {
  // The six canonical value types, in canonical order (mirrors the enum order,
  // Extension excluded). Kept here with the enum + categoryName() so the
  // governed set has a single home; consumers (e.g. language metadata) render
  // from this rather than re-listing the set.
  static const ValueCategory kGoverned[] = {
      ValueCategory::Money,    ValueCategory::Decimal,  ValueCategory::Party,
      ValueCategory::Currency, ValueCategory::Evidence, ValueCategory::String};
  return kGoverned;
}

ValueCategory categoryFromName(llvm::StringRef name) {
  return llvm::StringSwitch<ValueCategory>(name)
      .Case("money", ValueCategory::Money)
      .Case("decimal", ValueCategory::Decimal)
      .Case("party", ValueCategory::Party)
      .Case("currency", ValueCategory::Currency)
      .Case("evidence", ValueCategory::Evidence)
      .Case("string", ValueCategory::String)
      .Default(ValueCategory::Extension);
}

llvm::StringRef categoryName(ValueCategory c) {
  switch (c) {
  case ValueCategory::Money:
    return "money";
  case ValueCategory::Decimal:
    return "decimal";
  case ValueCategory::Party:
    return "party";
  case ValueCategory::Currency:
    return "currency";
  case ValueCategory::Evidence:
    return "evidence";
  case ValueCategory::String:
    return "string";
  case ValueCategory::Extension:
    return "extension";
  }
  return "extension";
}

} // namespace neutrino
