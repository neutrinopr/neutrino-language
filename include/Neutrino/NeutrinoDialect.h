#ifndef NEUTRINO_DIALECT_H
#define NEUTRINO_DIALECT_H

#include "mlir/IR/BuiltinTypes.h"
#include "mlir/IR/Dialect.h"
#include "mlir/IR/OpDefinition.h"
#include "mlir/Interfaces/SideEffectInterfaces.h"

// Dialect declaration (generated).
#include "Neutrino/NeutrinoDialect.h.inc"

// Type declarations (generated).
#define GET_TYPEDEF_CLASSES
#include "Neutrino/NeutrinoTypes.h.inc"

// Attribute declarations (generated). ExprAttr () is self-referential, so
// the generated header forward-declares it before the storage class.
#define GET_ATTRDEF_CLASSES
#include "Neutrino/NeutrinoAttrs.h.inc"

// Op declarations (generated).
#define GET_OP_CLASSES
#include "Neutrino/NeutrinoOps.h.inc"

#endif // NEUTRINO_DIALECT_H
