//===- DomainSemanticsTarget.cpp - the visible L2 sidecar () ----------===//
//
// Serialize a verified `l2.domain` to the deterministic, hashed domain-
// semantics sidecar. A faithful projection of the meta-model records, each
// array sorted by its full canonical form (a total order) so the bytes are
// canonical regardless of source order and reordered-equivalent input matches;
// the hash is sha256 over the compact canonical form with the hash field
// removed, matching the capability-spec / domain-dialect discipline so a C++
// emitter and a stdlib validator agree byte-for-byte.
//
//===----------------------------------------------------------------------===//

#include "Neutrino/GenDomainSemantics.h"
#include "Neutrino/JsonUtil.h"
#include "Neutrino/L2Dialect.h"
#include "Neutrino/VersionInfo.h"

#include "mlir/IR/Builders.h"
#include "mlir/IR/Diagnostics.h"
#include "mlir/IR/MLIRContext.h"
#include "mlir/IR/Verifier.h"

#include "llvm/ADT/STLExtras.h"
#include "llvm/ADT/SmallVector.h"
#include "llvm/Support/FormatVariadic.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/Regex.h"

#include <algorithm>
#include <vector>

using namespace mlir;
using namespace llvm;

namespace {
using neutrino::l2::ConceptOp;
using neutrino::l2::DomainOp;
using neutrino::l2::FailureModeOp;
using neutrino::l2::ImportOp;
using neutrino::l2::InvariantOp;
using neutrino::l2::L1FeatureOp;
using neutrino::l2::ProvenanceOp;
using neutrino::l2::ReduceOp;

// Sort an array by each record's FULL compact canonical JSON — a total order,
// so records that legitimately share one field (e.g. two provenance entries for
// the same subject) still sort deterministically and reordered-equivalent input
// yields byte-identical output.
void sortCanonical(json::Array &arr) {
  std::sort(arr.begin(), arr.end(),
            [](const json::Value &a, const json::Value &b) {
              return neutrino::compactJson(a) < neutrino::compactJson(b);
            });
}

// Only-if-present optional string field (accepts llvm::Optional /
// std::optional).
template <typename Opt> void setOpt(json::Object &o, StringRef field, Opt v) {
  if (v)
    o[field] = StringRef(*v);
}

json::Object buildSidecar(DomainOp domain) {
  json::Object root;
  // The SETTLED domain-semantics identity: `neutrino.l2-domain-semantics`. The
  // producer emits schemaVersion 3 () — v2's machine-emitted executable
  // reduction graph PLUS a REQUIRED intakeVersioning object. v2 is retained
  // UNCHANGED as the legacy compatibility baseline (still accepted on
  // re-ingest); same kind, explicitly versioned; not a second overlapping
  // model.
  root["kind"] = "neutrino.l2-domain-semantics";
  root["schemaVersion"] = 3;
  root["domain"] = domain.getSymName();
  root["version"] = domain.getVersion();
  root["implements"] = domain.getImplements();
  setOpt(root, "coverage", domain.getCoverage());

  json::Array l1Features, concepts, reductions, failureModes, invariants,
      provenance, imports;
  for (Operation &op : domain.getBody().front()) {
    if (auto imp = dyn_cast<ImportOp>(op)) {
      imports.push_back(json::Object{{"capability", imp.getCapability()},
                                     {"version", imp.getVersion()}});
    } else if (auto a = dyn_cast<L1FeatureOp>(op)) {
      l1Features.push_back(
          json::Object{{"name", a.getSymName()}, {"kind", a.getKind()}});
    } else if (auto c = dyn_cast<ConceptOp>(op)) {
      concepts.push_back(
          json::Object{{"name", c.getSymName()},
                       {"kind", c.getKind()},
                       {"classification", c.getClassification()}});
    } else if (auto r = dyn_cast<ReduceOp>(op)) {
      reductions.push_back(json::Object{{"id", r.getSymName()},
                                        {"from", r.getFrom()},
                                        {"to", r.getTo()},
                                        {"relation", r.getRelation()},
                                        {"lossiness", r.getLossiness()}});
    } else if (auto f = dyn_cast<FailureModeOp>(op)) {
      json::Object o{{"name", f.getSymName()}};
      setOpt(o, "compensation", f.getCompensation());
      failureModes.push_back(std::move(o));
    } else if (auto inv = dyn_cast<InvariantOp>(op)) {
      json::Object o{{"name", inv.getSymName()},
                     {"predicate", inv.getPredicate()}};
      setOpt(o, "onFailure", inv.getOnFailure());
      invariants.push_back(std::move(o));
    } else if (auto p = dyn_cast<ProvenanceOp>(op)) {
      json::Object o{{"subject", p.getSubject()},
                     {"source", p.getSource()},
                     {"status", p.getStatus()}};
      setOpt(o, "standardVersion", p.getStandardVersion());
      setOpt(o, "excerptHash", p.getExcerptHash());
      setOpt(o, "reviewer", p.getReviewer());
      provenance.push_back(std::move(o));
    }
  }
  sortCanonical(l1Features);
  sortCanonical(concepts);
  sortCanonical(reductions);
  sortCanonical(failureModes);
  sortCanonical(invariants);
  sortCanonical(provenance);
  sortCanonical(imports);

  root["l1Features"] = std::move(l1Features);
  root["concepts"] = std::move(concepts);
  root["reductions"] = std::move(reductions);
  root["failureModes"] = std::move(failureModes);
  root["invariants"] = std::move(invariants);
  root["provenance"] = std::move(provenance);
  root["imports"] = std::move(imports);
  // intakeVersioning (, v3): stamp the capability-vocabulary + reduction-
  // semantics contract versions this artifact was PRODUCED under. Part of the
  // hashed contract; the intake seam exact-matches both before reduction.
  root["intakeVersioning"] = json::Object{
      {"semanticProfileVersion", neutrino::kSemanticProfileVersion},
      {"reductionSemanticsVersion", neutrino::kReductionSemanticsVersion}};
  return root;
}
} // namespace

llvm::Expected<std::string>
neutrino::emitDomainSemanticsSidecar(ModuleOp module) {
  // The module body must be EXACTLY one direct l2.domain and nothing else, so
  // the hash covers the whole input and no sibling/nested operation can ride
  // along uncommitted.
  DomainOp domain;
  for (Operation &op : module.getBody()->getOperations()) {
    auto d = dyn_cast<DomainOp>(op);
    if (!d)
      return createStringError(inconvertibleErrorCode(),
                               "spec.ast: the module must contain exactly one "
                               "l2.domain and no other "
                               "operations (found " +
                                   op.getName().getStringRef().str() + ")");
    if (domain)
      return createStringError(
          inconvertibleErrorCode(),
          "spec.ast: input contains more than one l2.domain");
    domain = d;
  }
  if (!domain)
    return createStringError(inconvertibleErrorCode(),
                             "spec.ast: input contains no l2.domain");

  json::Object root = buildSidecar(domain);
  // Hash the canonical form WITHOUT the hash field, then attach it.
  std::string hash = neutrino::sha256Hex(
      neutrino::compactJson(json::Value(json::Object(root))));
  root["domainSemanticsHash"] = hash;
  return formatv("{0:2}", json::Value(std::move(root))).str() + "\n";
}

namespace {
llvm::Error astError(const Twine &msg) {
  return createStringError(inconvertibleErrorCode(),
                           ("spec.ast: " + msg).str());
}

// Read a required non-empty string field, or fail closed naming the location.
llvm::Expected<StringRef> reqStr(const json::Object &o, StringRef key,
                                 const Twine &where) {
  auto v = o.getString(key);
  if (!v || v->empty())
    return astError("l2v2.shape: " + where + " missing required '" + key + "'");
  return *v;
}

// One record field's declared type: "str" (a non-empty string), "sha256", or
// "enum:a|b|c". These field specs mirror validate_l2_domain_semantics_v2.py's
// per-record schema exactly, so the C++ re-ingest seam enforces the SAME shape
// contract (exact key sets via additionalProperties:false, required fields,
// types, enums/patterns, and optional-field non-emptiness) the stdlib validator
// does — the dialect verifier alone cannot see these, since reconstruction is
// lossy (it drops unknown nested fields and normalizes malformed ones away).
struct FieldSpec {
  StringRef name;
  StringRef type;
};

llvm::Error checkFieldType(const Twine &path, StringRef key,
                           const json::Value &v, StringRef type) {
  auto str = v.getAsString();
  if (type == "sha256") {
    static llvm::Regex sha("^[0-9a-f]{64}$");
    if (!str || !sha.match(*str))
      return astError("l2v2.shape: " + path + "." + key +
                      " is not a 64-char lowercase sha256");
  } else if (type == "semver") {
    static llvm::Regex semver("^[0-9]+\\.[0-9]+\\.[0-9]+$");
    if (!str || !semver.match(*str))
      return astError("l2v2.shape: " + path + "." + key +
                      " is not a semantic version");
  } else if (type.startswith("enum:")) {
    llvm::SmallVector<StringRef, 4> allowed;
    type.drop_front(5).split(allowed, '|');
    if (!str || !llvm::is_contained(allowed, *str))
      return astError("l2v2.shape: " + path + "." + key + " '" +
                      (str ? *str : StringRef("")) + "' is not one of " +
                      type.drop_front(5));
  } else if (!str || str->empty()) { // "str"
    return astError("l2v2.shape: " + path + "." + key +
                    " must be a non-empty string");
  }
  return llvm::Error::success();
}

// A record must be an object with every required field present, no unknown
// property (additionalProperties:false), and each present field well-typed.
llvm::Error checkRecordShape(const json::Value &item, const Twine &path,
                             ArrayRef<StringRef> required,
                             ArrayRef<FieldSpec> spec) {
  const json::Object *o = item.getAsObject();
  if (!o)
    return astError("l2v2.shape: " + path + " is not an object");
  for (StringRef r : required)
    if (!o->get(r))
      return astError("l2v2.shape: " + path + " is missing required '" + r +
                      "'");
  size_t known = 0;
  for (const FieldSpec &f : spec)
    if (const json::Value *v = o->get(f.name)) {
      ++known;
      if (llvm::Error e = checkFieldType(path, f.name, *v, f.type))
        return e;
    }
  if (o->size() != known)
    return astError("l2v2.shape: " + path + " has an unknown property");
  return llvm::Error::success();
}

llvm::Error checkArrayShape(const json::Object &s, StringRef field,
                            ArrayRef<StringRef> required,
                            ArrayRef<FieldSpec> spec) {
  const json::Array *arr = s.getArray(field);
  if (!arr)
    return astError("l2v2.shape: '" + field + "' must be an array");
  for (size_t i = 0; i < arr->size(); ++i)
    if (llvm::Error e = checkRecordShape(
            (*arr)[i], field + "[" + Twine(i) + "]", required, spec))
      return e;
  return llvm::Error::success();
}

// The complete v2 SHAPE contract (top-level envelope + every per-record
// schema), a faithful port of validate_l2_domain_semantics_v2.py's
// validate_shape. Run BEFORE reconstruction so lossy reconstruction can never
// hide a shape violation.
// The complete SHAPE contract, shared by v2 and v3 (). expectedVersion==2
// is the pristine v2 envelope; expectedVersion==3 additionally REQUIRES an
// intakeVersioning object. The cross-record contract (validateSemantics) and
// the hash are shared, not forked.
llvm::Error validateShapeV2(const json::Object &s, int expectedVersion) {
  static const StringRef kRequired[] = {
      "kind",         "schemaVersion", "domain",     "version",
      "implements",   "l1Features",    "concepts",   "reductions",
      "failureModes", "invariants",    "provenance", "domainSemanticsHash"};
  // `imports` is OPTIONAL for schemaVersion-2 back-compatibility: a pre- v2
  // artifact (no imports field) stays valid and keeps its original hash
  // preimage (an absent imports field is not part of it); absent ⇒ [].
  bool v3 = expectedVersion == 3;
  size_t allowed = s.get("coverage") ? 1 : 0;
  if (s.get("imports"))
    ++allowed;
  if (v3) {
    // intakeVersioning is REQUIRED under v3 (and forbidden under v2, where it
    // is an unknown top-level property).
    if (!s.get("intakeVersioning"))
      return astError("l2v2.shape: missing required 'intakeVersioning'");
    ++allowed;
  }
  for (StringRef k : kRequired) {
    if (!s.get(k))
      return astError("l2v2.shape: missing required '" + k + "'");
    ++allowed;
  }
  if (s.size() != allowed)
    return astError("l2v2.shape: sidecar has an unknown top-level property");

  auto kind = s.getString("kind");
  if (!kind || *kind != "neutrino.l2-domain-semantics")
    return astError(
        "l2v2.identity: kind must be 'neutrino.l2-domain-semantics'");
  auto schemaVersion = s.getInteger("schemaVersion");
  if (!schemaVersion || *schemaVersion != expectedVersion)
    return astError("l2v2.identity: schemaVersion must be " +
                    std::to_string(expectedVersion));
  for (StringRef f : {"domain", "implements"}) {
    auto v = s.getString(f);
    if (!v || v->empty())
      return astError("l2v2.shape: " + f + " must be a non-empty string");
  }
  auto version = s.getString("version");
  static llvm::Regex semver("^[0-9]+\\.[0-9]+\\.[0-9]+$");
  if (!version || !semver.match(*version))
    return astError("l2v2.shape: version is not a semantic version");
  if (const json::Value *cov = s.get("coverage")) {
    auto c = cov->getAsString();
    if (!c || (*c != "full" && *c != "partial"))
      return astError("l2v2.shape: coverage is not one of full/partial");
  }
  auto hash = s.getString("domainSemanticsHash");
  static llvm::Regex sha("^[0-9a-f]{64}$");
  if (!hash || !sha.match(*hash))
    return astError(
        "l2v2.shape: domainSemanticsHash is not a 64-char lowercase sha256");

  if (llvm::Error e = checkArrayShape(
          s, "l1Features", {"name", "kind"},
          {{"name", "str"}, {"kind", "enum:primitive|obligation"}}))
    return e;
  if (llvm::Error e =
          checkArrayShape(s, "concepts", {"name", "kind", "classification"},
                          {{"name", "str"},
                           {"kind", "enum:state|action|concept"},
                           {"classification", "enum:executable|descriptive"}}))
    return e;
  if (llvm::Error e = checkArrayShape(
          s, "reductions", {"id", "from", "to", "relation", "lossiness"},
          {{"id", "str"},
           {"from", "str"},
           {"to", "str"},
           {"relation", "enum:expands|discharges|protects|failure"},
           {"lossiness", "enum:lossless|lossy_preserved|unsupported"}}))
    return e;
  if (llvm::Error e =
          checkArrayShape(s, "failureModes", {"name"},
                          {{"name", "str"}, {"compensation", "str"}}))
    return e;
  if (llvm::Error e = checkArrayShape(
          s, "invariants", {"name", "predicate"},
          {{"name", "str"}, {"predicate", "str"}, {"onFailure", "str"}}))
    return e;
  if (llvm::Error e =
          checkArrayShape(s, "provenance", {"subject", "source", "status"},
                          {{"subject", "str"},
                           {"source", "str"},
                           {"status", "enum:proposed|accepted|rejected"},
                           {"standardVersion", "str"},
                           {"excerptHash", "sha256"},
                           {"reviewer", "str"}}))
    return e;
  if (s.get("imports"))
    if (llvm::Error e =
            checkArrayShape(s, "imports", {"capability", "version"},
                            {{"capability", "str"}, {"version", "semver"}}))
      return e;
  // intakeVersioning shape (, v3): an object with exactly the two
  // positive-int version axes. Mirrors validate_l2_domain_semantics_v2.py
  // (require_intake).
  if (v3) {
    const json::Object *iv = s.getObject("intakeVersioning");
    if (!iv)
      return astError("l2v2.shape: intakeVersioning must be an object");
    size_t ivAllowed = 0;
    for (StringRef f :
         {"semanticProfileVersion", "reductionSemanticsVersion"}) {
      auto n = iv->getInteger(f);
      if (!n || *n < 1)
        return astError("l2v2.shape: intakeVersioning." + f +
                        " must be a positive integer");
      ++ivAllowed;
    }
    if (iv->size() != ivAllowed)
      return astError("l2v2.shape: intakeVersioning has an unknown property");
  }
  return llvm::Error::success();
}

// Reconstruct the l2.domain from the sidecar so the AUTHORITATIVE dialect
// verifier can re-check the whole cross-record contract; missing/mistyped
// record fields fail closed here, before any verification.
llvm::Expected<neutrino::l2::DomainOp>
reconstructDomain(const json::Object &s, OpBuilder &b, ModuleOp module) {
  Location loc = b.getUnknownLoc();
  b.setInsertionPointToEnd(module.getBody());
  auto dom = reqStr(s, "domain", "domain");
  auto ver = reqStr(s, "version", "domain");
  auto impl = reqStr(s, "implements", "domain");
  if (!dom)
    return dom.takeError();
  if (!ver)
    return ver.takeError();
  if (!impl)
    return impl.takeError();
  StringAttr coverage = s.getString("coverage")
                            ? b.getStringAttr(*s.getString("coverage"))
                            : StringAttr();
  auto domain = b.create<neutrino::l2::DomainOp>(
      loc, b.getStringAttr(*dom), b.getStringAttr(*ver), b.getStringAttr(*impl),
      coverage);
  b.setInsertionPointToEnd(&domain.getBody().emplaceBlock());

  auto optAttr = [&](const json::Object &o, StringRef k) {
    return o.getString(k) ? b.getStringAttr(*o.getString(k)) : StringAttr();
  };

  for (const json::Value &v : *s.getArray("l1Features")) {
    const json::Object *o = v.getAsObject();
    if (!o)
      return astError("l2v2.shape: l1Features[] element is not an object");
    auto name = reqStr(*o, "name", "l1Feature");
    auto kind = reqStr(*o, "kind", "l1Feature");
    if (!name)
      return name.takeError();
    if (!kind)
      return kind.takeError();
    b.create<neutrino::l2::L1FeatureOp>(loc, b.getStringAttr(*name),
                                        b.getStringAttr(*kind));
  }
  for (const json::Value &v : *s.getArray("concepts")) {
    const json::Object *o = v.getAsObject();
    if (!o)
      return astError("l2v2.shape: concepts[] element is not an object");
    auto name = reqStr(*o, "name", "concept");
    auto kind = reqStr(*o, "kind", "concept");
    auto cls = reqStr(*o, "classification", "concept");
    if (!name)
      return name.takeError();
    if (!kind)
      return kind.takeError();
    if (!cls)
      return cls.takeError();
    b.create<neutrino::l2::ConceptOp>(loc, b.getStringAttr(*name),
                                      b.getStringAttr(*kind),
                                      b.getStringAttr(*cls));
  }
  for (const json::Value &v : *s.getArray("reductions")) {
    const json::Object *o = v.getAsObject();
    if (!o)
      return astError("l2v2.shape: reductions[] element is not an object");
    auto id = reqStr(*o, "id", "reduction");
    auto from = reqStr(*o, "from", "reduction");
    auto to = reqStr(*o, "to", "reduction");
    auto rel = reqStr(*o, "relation", "reduction");
    auto loss = reqStr(*o, "lossiness", "reduction");
    if (!id)
      return id.takeError();
    if (!from)
      return from.takeError();
    if (!to)
      return to.takeError();
    if (!rel)
      return rel.takeError();
    if (!loss)
      return loss.takeError();
    b.create<neutrino::l2::ReduceOp>(
        loc, b.getStringAttr(*id), b.getStringAttr(*from), b.getStringAttr(*to),
        b.getStringAttr(*rel), b.getStringAttr(*loss));
  }
  for (const json::Value &v : *s.getArray("failureModes")) {
    const json::Object *o = v.getAsObject();
    if (!o)
      return astError("l2v2.shape: failureModes[] element is not an object");
    auto name = reqStr(*o, "name", "failureMode");
    if (!name)
      return name.takeError();
    b.create<neutrino::l2::FailureModeOp>(loc, b.getStringAttr(*name),
                                          optAttr(*o, "compensation"));
  }
  for (const json::Value &v : *s.getArray("invariants")) {
    const json::Object *o = v.getAsObject();
    if (!o)
      return astError("l2v2.shape: invariants[] element is not an object");
    auto name = reqStr(*o, "name", "invariant");
    auto pred = reqStr(*o, "predicate", "invariant");
    if (!name)
      return name.takeError();
    if (!pred)
      return pred.takeError();
    b.create<neutrino::l2::InvariantOp>(loc, b.getStringAttr(*name),
                                        b.getStringAttr(*pred),
                                        optAttr(*o, "onFailure"));
  }
  for (const json::Value &v : *s.getArray("provenance")) {
    const json::Object *o = v.getAsObject();
    if (!o)
      return astError("l2v2.shape: provenance[] element is not an object");
    auto subj = reqStr(*o, "subject", "provenance");
    auto src = reqStr(*o, "source", "provenance");
    auto status = reqStr(*o, "status", "provenance");
    if (!subj)
      return subj.takeError();
    if (!src)
      return src.takeError();
    if (!status)
      return status.takeError();
    b.create<neutrino::l2::ProvenanceOp>(
        loc, b.getStringAttr(*subj), b.getStringAttr(*src),
        optAttr(*o, "standardVersion"), optAttr(*o, "excerptHash"),
        optAttr(*o, "reviewer"), b.getStringAttr(*status));
  }
  if (const json::Array *imps = s.getArray("imports"))
    for (const json::Value &v : *imps) {
      const json::Object *o = v.getAsObject();
      if (!o)
        return astError("l2v2.shape: imports[] element is not an object");
      auto cap = reqStr(*o, "capability", "import");
      auto ver = reqStr(*o, "version", "import");
      if (!cap)
        return cap.takeError();
      if (!ver)
        return ver.takeError();
      b.create<neutrino::l2::ImportOp>(loc, b.getStringAttr(*cap),
                                       b.getStringAttr(*ver));
    }
  return domain;
}
} // namespace

llvm::Error neutrino::validateDomainSemanticsSidecarV2(const json::Object &s) {
  // (1) The complete per-record v2 SHAPE contract (exact key sets, required
  // fields, types, enums/patterns, optional-field non-emptiness) — the SAME
  // contract validate_l2_domain_semantics_v2.py enforces. Run before
  // reconstruction so lossy reconstruction can never mask a shape violation
  // (e.g. an unknown nested field, or an empty optional the dialect ignores).
  // Re-ingest accepts BOTH the legacy v2 artifact and the v3 producer output
  // (); the schemaVersion selects the envelope, the rest of the contract is
  // shared. An unknown schemaVersion fails closed.
  auto sv = s.getInteger("schemaVersion");
  int version = sv ? static_cast<int>(*sv) : 0;
  if (version != 2 && version != 3)
    return astError("l2v2.identity: schemaVersion must be 2 or 3");
  if (llvm::Error e = validateShapeV2(s, version))
    return e;
  // (1b)  — enforce the version tuple at THIS trust seam, before any
  // reconstruction/reduction. Direct sidecar re-ingest is a public path into
  // reduction, so the version binding cannot live only in the Python admission
  // gate: a v3 sidecar whose intakeVersioning does not EXACTLY match the
  // compiler's own vocabulary + reducer contract versions is stale and is
  // refused here. Legacy v2 (no intakeVersioning) is unaffected.
  if (version == 3) {
    const json::Object *iv = s.getObject("intakeVersioning");
    // Compare the parsed 64-bit values WITHOUT narrowing: a shape-valid
    // positive JSON integer like 2^32+3 must NOT wrap to a matching 32-bit
    // value and slip through (validateShapeV2 already proved both are present
    // positive ints).
    int64_t spv = *iv->getInteger("semanticProfileVersion");
    int64_t rsv = *iv->getInteger("reductionSemanticsVersion");
    if (spv != static_cast<int64_t>(neutrino::kSemanticProfileVersion))
      return astError("l2v2.intake_version: stale-vocabulary — "
                      "intakeVersioning.semanticProfileVersion " +
                      std::to_string(spv) +
                      " != compiler kSemanticProfileVersion " +
                      std::to_string(neutrino::kSemanticProfileVersion));
    if (rsv != static_cast<int64_t>(neutrino::kReductionSemanticsVersion))
      return astError("l2v2.intake_version: stale-reducer — "
                      "intakeVersioning.reductionSemanticsVersion " +
                      std::to_string(rsv) +
                      " != compiler kReductionSemanticsVersion " +
                      std::to_string(neutrino::kReductionSemanticsVersion));
  }
  static const StringRef kArrays[] = {
      "l1Features", "concepts",   "reductions", "failureModes",
      "invariants", "provenance", "imports"};
  StringRef storedHash = *s.getString("domainSemanticsHash");

  // (2) Reconstruct + run the AUTHORITATIVE dialect verifier (the same cross-
  // record contract, enum shape, and reference resolution the emitter's input
  // satisfied). A dangling/mutated reduction reference is rejected HERE.
  mlir::MLIRContext ctx;
  ctx.getOrLoadDialect<neutrino::l2::L2Dialect>();
  OpBuilder b(&ctx);
  OwningOpRef<ModuleOp> module = ModuleOp::create(b.getUnknownLoc());
  llvm::Expected<neutrino::l2::DomainOp> domain =
      reconstructDomain(s, b, *module);
  if (!domain)
    return domain.takeError();
  std::string diag;
  llvm::raw_string_ostream os(diag);
  mlir::ScopedDiagnosticHandler handler(&ctx, [&](mlir::Diagnostic &d) {
    os << d.str() << "; ";
    return success();
  });
  if (failed(verify(*module)))
    return astError("l2v2: reconstructed artifact failed verification: " +
                    os.str());

  // (3) Recompute the canonical hash over the RAW body (arrays re-sorted, hash
  // removed) — the same discipline the emitter and the stdlib validator use —
  // so a stale or re-hashed tampered artifact cannot pass.
  json::Object body;
  if (s.get("coverage"))
    body["coverage"] = *s.get("coverage");
  // intakeVersioning (, v3) is part of the hash preimage when present; a
  // legacy v2 artifact has none and keeps its original hash.
  if (s.get("intakeVersioning"))
    body["intakeVersioning"] = *s.get("intakeVersioning");
  body["kind"] = *s.get("kind");
  body["schemaVersion"] = *s.get("schemaVersion");
  body["domain"] = *s.get("domain");
  body["version"] = *s.get("version");
  body["implements"] = *s.get("implements");
  // Copy each array present. `imports` is optional (compat): an absent imports
  // field is not part of the hash preimage, so a pre- v2 artifact keeps its
  // original domainSemanticsHash.
  for (StringRef k : kArrays)
    if (s.get(k)) {
      body[k] = *s.get(k);
      sortCanonical(*body.getArray(k));
    }
  std::string recomputed =
      neutrino::sha256Hex(neutrino::compactJson(json::Value(std::move(body))));
  if (recomputed != storedHash)
    return astError("l2v2.hash: domainSemanticsHash " + storedHash +
                    " != recomputed " + recomputed);
  return llvm::Error::success();
}
