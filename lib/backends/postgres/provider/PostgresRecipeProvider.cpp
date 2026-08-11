//===- PostgresRecipeProvider.cpp - generated-recipe PostgreSQL adapter ---===//
//
// The single PostgreSQL provider/bootstrap owned by  (the PostgreSQL analog
// of the merged Solidity  evidence extraction). It maps generated opaque
// node IDs to the existing typed PostgreSQL model carriers (PgStmt / PgParam /
// PgFunction / RawSql / PgProcedure), snapshots the finalized evidence VALUES
// so the runtime can project them by generated ID, and invokes the
// package-local  security resolvers during gate/revoke node construction.
// Recipe traversal, exact-key resolution, nesting, ordering, and cardinality
// remain in NeutrinoRecipe; the recipe orders gate -> execute -> revoke
// declaratively.
//
//===----------------------------------------------------------------------===//

#include "PgSqlSyntax.h" // postgres_detail::sqlEsc — the  string.escape hook
#include "PostgresEvidenceInputs.h"

#include "Neutrino/BackendProjectionDriver.h" // : finalizedProjectionIdiomKey
#include "Neutrino/CodeText.h" // : codetext::Document (renderer)
#include "Neutrino/RecipeModule.h"
#include "Neutrino/RecipeProviderRegistry.h"
#include "Neutrino/RecipeRuntime.h"
#include "Neutrino/RecipeSessionStore.h"

#include "llvm/Support/Error.h"

#include <atomic>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

// : the generic printer handlers + the completed-recipe-root renderer
// (renderPgStmtTree). The renderer is requested (NEUTRINO_PG_DEFINE_RENDERER)
// in this provider TU, which now owns renderPostgresProjection.
#include "PostgresPrinterHandlers.inc"
#define NEUTRINO_PG_DEFINE_RENDERER
#include "PostgresRecipeBuilders.inc" //  GeneratedRecipeBuilder (claim comment)
#undef NEUTRINO_PG_DEFINE_RENDERER
#include "PostgresRecipePackage.inc" // postgres_recipes.inc + PostgresRecipeAdapter.inc

using namespace llvm;
using namespace neutrino::recipe;
using namespace neutrino::recipe::generated;

namespace neutrino {
namespace postgres_model {
namespace {

//  B3: the one procedure input view for every rail. The caller hands the
// runtime the verified sequence + the DdlCap; `begin` selects the rail from the
// invocation's finalized idiom key (its `mode` component) and synthesizes that
// rail's finalized inputs from the sequence there — behind the recipe seam, so
// no per-rail view or backend branch survives.
struct PgProjectionRecipeView final
    : TaggedRecipeOpaque<PgProjectionRecipeView, FinalizedInputView> {
  const projection::FinalizedProjectionSequence *sequence = nullptr;
  const pgddl::DdlCap *ddlCap = nullptr;
};

// The coordination-schema view. The schema is a fixed per-rail shape EXCEPT the
// postings base table's memo variant, which the provider reads from the
// verified sequence (a finalized fact — no plan read); `sequence` is threaded
// for that.
struct PgSchemaRecipeView final
    : TaggedRecipeOpaque<PgSchemaRecipeView, FinalizedInputView> {
  const projection::FinalizedProjectionSequence *sequence = nullptr;
  const pgddl::DdlCap *ddlCap = nullptr;
};

// One produced node in the session store — exactly one carrier is populated.
struct PgRecipeNode {
  std::unique_ptr<PgStmt> stmt;
  std::unique_ptr<PgParam> param;
  std::unique_ptr<PgDeclaration> decl;
  std::unique_ptr<PgProcedurePart> part;
  std::optional<pgddl::RawSql> segment; //  B3 schema DDL segment
  std::optional<PgProcedure> procedure;
};

// The backend-owned build session: the immutable finalized-value snapshot (the
// flat `finalizedValues` pool the `directValue` ordinals index) + the
// produced-node store.
struct PgRecipeSession final : OpaqueBuildSession {
  // : the finalized rail. The already-finalized recipe key (schema view /
  // idiom-key `mode`) selects the representation ONCE in `begin`; the render
  // hooks dispatch on this typed selector, never re-reading a projection field
  // or the presence of an optional to decide behavior.
  enum class Rail { Evidence, Temporal, Effectful, Schema };
  Rail rail = Rail::Evidence;
  EvidenceProcedureInputs inputs;
  // : set for a temporal invocation (the field/slot ids are disjoint from
  // the evidence ones, so project/slotExtent branch on the id itself). When
  // set, `finalizedValues` is filled lazily by `project` (the nested groups
  // make a static ordinal layout impractical); the evidence path keeps its
  // eager pool.
  std::optional<TemporalProcedureInputs> temporal;
  // : set for an effectful invocation. Like the temporal path,
  // `finalizedValues` is filled lazily by `project` (the per-posting optional
  // guard makes a static ordinal layout impractical). `effectfulSequence` is
  // the verified sequence the optional-slot presence is read from
  // (attestationKind / posting guardKind).
  std::optional<EffectfulProcedureInputs> effectful;
  const projection::FinalizedProjectionSequence *effectfulSequence = nullptr;
  // : the verified sequence the temporal per-posting memo variant
  // (FinalizedPostingMemo) is read from — nested at effectGroups[g]
  // .finalizedPostings[p].memoPresence, the temporal analog of
  // effectfulSequence.
  const projection::FinalizedProjectionSequence *temporalSequence = nullptr;
  //  B2: set for a schema invocation — the verified sequence the postings
  // memo-variant optional-slot presence is read from.
  const projection::FinalizedProjectionSequence *schemaSequence = nullptr;
  const pgddl::DdlCap *ddlCap = nullptr;
  // The member conventions the shared emit-side store (RecipeSessionStore.h)
  // addresses: the flat finalized-value pool the `directValue` ordinals index,
  // the produced-leaf pool (the  postgres.string.escape hook's escaped
  // outputs), and the one ordered produced-node store holding carriers of every
  // kind.
  std::vector<std::string> finalizedValues;
  std::vector<std::string> leafValues;
  std::vector<std::unique_ptr<PgRecipeNode>> nodes;
};

struct PgRecipeArtifact final
    : TaggedRecipeOpaque<PgRecipeArtifact, OpaqueTargetArtifact> {
  std::optional<PgProcedure> procedure;
  std::optional<pgddl::RawSql> schema; //  B3 schema DDL artifact
};

// : generated finalized-view dispatch.  Included after PgRecipeSession is
// complete so the resolver can address its typed, already-finalized carriers.
#include "PostgresProjection.inc"

class PostgresRecipeProvider final : public TargetRecipeProvider {
public:
  using Node = PgStmt;

  StringRef target() const override { return "postgres"; }

  Expected<RecipeHandle> resolve(const FinalizedIdiomKey &key) const override {
    auto recipe = resolveRecipe(postgresRecipeModule(), key);
    if (!recipe)
      return recipe.takeError();
    return static_cast<RecipeHandle>(*recipe);
  }

  Expected<std::unique_ptr<OpaqueBuildSession>>
  begin(const FinalizedInvocation &invocation) const override {
    // The coordination-schema invocation carries the DdlCap + the verified
    // sequence (for the postings memo-variant fact).
    if (const auto *sview =
            checkedRecipeOpaque<PgSchemaRecipeView>(invocation.finalizedView)) {
      if (sview->ddlCap == nullptr || sview->sequence == nullptr)
        return recipeError(RecipeDiagnostic::InputUnbound,
                           "PostgreSQL schema recipe view");
      auto session = std::make_unique<PgRecipeSession>();
      session->rail = PgRecipeSession::Rail::Schema;
      session->schemaSequence = sview->sequence;
      session->ddlCap = sview->ddlCap;
      activeDdlCap = sview->ddlCap;
      session->sessionId = ++nextSession;
      return std::unique_ptr<OpaqueBuildSession>(std::move(session));
    }
    //  B3: every procedure rail arrives through the one projection view.
    // The rail is the invocation's finalized idiom-key `mode` component
    // (already finalized); the provider synthesizes that rail's finalized
    // inputs from the verified sequence HERE, behind the recipe seam — the
    // backend performs no rail branch. The invocation is a recipe-runtime
    // carrier, not a projection value, so this construction dispatch keys off
    // the resolved recipe, not a backend semantic read. `finalizedValues` is
    // filled eagerly for evidence (its legacy pool) and lazily by `project` for
    // the temporal/effectful rails.
    const auto *pview =
        checkedRecipeOpaque<PgProjectionRecipeView>(invocation.finalizedView);
    if (pview == nullptr || pview->ddlCap == nullptr ||
        pview->sequence == nullptr)
      return recipeError(RecipeDiagnostic::InputUnbound,
                         "PostgreSQL finalized recipe view");
    auto session = std::make_unique<PgRecipeSession>();
    session->ddlCap = pview->ddlCap;
    activeDdlCap = pview->ddlCap;
    const std::string &mode = invocation.key.mode;
    if (mode == "Temporal") {
      session->rail = PgRecipeSession::Rail::Temporal;
      session->temporal = computeTemporalInputs(*pview->sequence);
      session->temporalSequence = pview->sequence;
      activeAttestation = &session->temporal->attestation;
    } else if (mode == "Effectful") {
      session->rail = PgRecipeSession::Rail::Effectful;
      session->effectful = computeEffectfulInputs(*pview->sequence);
      session->effectfulSequence = pview->sequence;
    } else {
      session->rail = PgRecipeSession::Rail::Evidence;
      session->inputs = computeEvidenceInputs(*pview->sequence);
      const EvidenceProcedureInputs &in = session->inputs;
      session->finalizedValues = {
          in.name,      in.executeName,     in.procLiteral,
          in.key,       in.keyType,         in.observerSet,
          in.quorumM,   in.quorumPredicate, in.replayPredicate,
          in.statusAtom};
      for (const EvidenceProcedureInputs::Param &p : in.params) {
        session->finalizedValues.push_back(p.name);
        session->finalizedValues.push_back(p.type);
      }
    }
    session->sessionId = ++nextSession;
    return std::unique_ptr<OpaqueBuildSession>(std::move(session));
  }

  // : the registered PostgreSQL string.escape leaf hook (). Escapes a
  // raw already-projected spelling (procedure / ledger / posting name / memo)
  // to a SQL-literal-safe EscapedStringLiteral leaf, so the executable
  // ledger-upsert / posting-insert INSERTs consume escaped values while the
  // decorative effect-ledger comment keeps the RAW (Direct-bound) spelling.
  Expected<OpaqueLeafValueRef> applyHook(OpaqueBuildSession &opaque,
                                         RegisteredHookId hook,
                                         TypedHookInput input) const override {
    auto &session = static_cast<PgRecipeSession &>(opaque);
    if (hook != postgres_Hook_postgres_string_escape)
      return recipeError(RecipeDiagnostic::HookMissing,
                         "PostgreSQL generated hook id");
    if (input.value >= session.finalizedValues.size())
      return recipeError(RecipeDiagnostic::HookExecution,
                         "PostgreSQL hook input");
    std::string formatted =
        postgres_detail::sqlEsc(session.finalizedValues[input.value]);
    const LeafOrdinal ordinal = session.leafValues.size();
    session.leafValues.push_back(std::move(formatted));
    return OpaqueLeafValueRef{session.sessionId,
                              postgres_Leaf_EscapedStringLiteral, ordinal};
  }

  Expected<TargetNodeRef>
  emit(OpaqueBuildSession &opaque, BackendNodeTypeId node,
       ArrayRef<GeneratedFieldBinding> bindings,
       ArrayRef<TargetFieldDescriptor> fields) const override {
    return postgresBuildNode(*this, opaque, node, bindings, fields);
  }

  // ---- generated-adapter helpers (called by postgresBuildNode) ----

  Expected<std::string> valueOperand(OpaqueBuildSession &opaque,
                                     ArrayRef<GeneratedFieldBinding> bindings,
                                     ArrayRef<TargetFieldDescriptor> fields,
                                     unsigned index) const {
    auto &session = static_cast<PgRecipeSession &>(opaque);
    if (index >= bindings.size() || index >= fields.size())
      return recipeError(RecipeDiagnostic::ResultCardinality,
                         "PostgreSQL value field index");
    const GeneratedFieldBinding &binding = bindings[index];
    const TargetFieldDescriptor &field = fields[index];
    if (binding.targetField != field.id ||
        field.kind != TargetFieldKind::Value ||
        binding.kind != GeneratedFieldBinding::Kind::Direct ||
        binding.directType != field.typeId)
      return recipeError(RecipeDiagnostic::ResultType,
                         "PostgreSQL value field recheck");
    if (binding.directValue >= session.finalizedValues.size())
      return recipeError(RecipeDiagnostic::InputUnbound,
                         "PostgreSQL value ordinal");
    return session.finalizedValues[binding.directValue];
  }

  // : read one Hook<>-produced leaf operand (a string.escape-escaped
  // spelling) from the produced-leaf pool, with the §3.6 recheck (Leaf kind /
  // leaf output type / live session ordinal). The generated ledger-upsert /
  // posting-insert arms bind their escaped operands through this.
  Expected<std::string> leafOperand(OpaqueBuildSession &opaque,
                                    ArrayRef<GeneratedFieldBinding> bindings,
                                    ArrayRef<TargetFieldDescriptor> fields,
                                    unsigned index) const {
    auto &session = static_cast<PgRecipeSession &>(opaque);
    if (index >= bindings.size() || index >= fields.size())
      return recipeError(RecipeDiagnostic::ResultCardinality,
                         "PostgreSQL leaf field index");
    const GeneratedFieldBinding &binding = bindings[index];
    const TargetFieldDescriptor &field = fields[index];
    if (binding.targetField != field.id ||
        field.kind != TargetFieldKind::Leaf ||
        binding.kind != GeneratedFieldBinding::Kind::Leaf ||
        binding.leaf.type != field.typeId)
      return recipeError(RecipeDiagnostic::ResultType,
                         "PostgreSQL leaf field recheck");
    if (binding.leaf.session != session.sessionId ||
        binding.leaf.ordinal >= session.leafValues.size())
      return recipeError(RecipeDiagnostic::HookLifetime,
                         "PostgreSQL leaf ordinal");
    return session.leafValues[binding.leaf.ordinal];
  }

  Expected<std::vector<PgStmt>>
  takeStmts(OpaqueBuildSession &opaque,
            ArrayRef<GeneratedFieldBinding> bindings,
            ArrayRef<TargetFieldDescriptor> fields, unsigned index) const {
    return takeField<PgStmt>(
        static_cast<PgRecipeSession &>(opaque), postgresRecipeModule(),
        bindings, fields, index, "PostgreSQL", "statement",
        [](PgRecipeNode &n) -> PgStmt * { return n.stmt.get(); });
  }

  Expected<std::vector<PgParam>>
  takeParams(OpaqueBuildSession &opaque,
             ArrayRef<GeneratedFieldBinding> bindings,
             ArrayRef<TargetFieldDescriptor> fields, unsigned index) const {
    return takeField<PgParam>(
        static_cast<PgRecipeSession &>(opaque), postgresRecipeModule(),
        bindings, fields, index, "PostgreSQL", "parameter",
        [](PgRecipeNode &n) -> PgParam * { return n.param.get(); });
  }

  Expected<std::vector<PgDeclaration>>
  takeDecls(OpaqueBuildSession &opaque,
            ArrayRef<GeneratedFieldBinding> bindings,
            ArrayRef<TargetFieldDescriptor> fields, unsigned index) const {
    return takeField<PgDeclaration>(
        static_cast<PgRecipeSession &>(opaque), postgresRecipeModule(),
        bindings, fields, index, "PostgreSQL", "declaration",
        [](PgRecipeNode &n) -> PgDeclaration * { return n.decl.get(); });
  }

  Expected<std::vector<PgStmt>> takeCallableParts(
      OpaqueBuildSession &opaque, ArrayRef<GeneratedFieldBinding> bindings,
      ArrayRef<TargetFieldDescriptor> fields, unsigned index) const {
    return takeStmts(opaque, bindings, fields, index);
  }

  Expected<std::vector<PgProcedurePart>> takeProcedureParts(
      OpaqueBuildSession &opaque, ArrayRef<GeneratedFieldBinding> bindings,
      ArrayRef<TargetFieldDescriptor> fields, unsigned index) const {
    return takeField<PgProcedurePart>(
        static_cast<PgRecipeSession &>(opaque), postgresRecipeModule(),
        bindings, fields, index, "PostgreSQL", "procedure part",
        [](PgRecipeNode &n) -> PgProcedurePart * { return n.part.get(); });
  }

  PgStmt claimComment() const {
    // The  generated builder reaches PgStmt's sealed private constructor.
    return *emitEvidenceClaimComment();
  }

  Expected<PgFunction> buildQuorumGate(const std::string &name,
                                       const std::string &key,
                                       const std::string &keyType,
                                       const std::string &observerSet,
                                       const std::string &quorumM) const {
    int m = 0;
    for (char c : quorumM) {
      if (c < '0' || c > '9')
        return recipeError(RecipeDiagnostic::InputType,
                           "PostgreSQL quorum threshold");
      m = m * 10 + (c - '0');
    }
    return resolveQuorumGate(name, key, keyType, observerSet, m);
  }

  Expected<pgddl::RawSql> buildQuorumRevoke(const std::string &name,
                                            const std::string &keyType) const {
    // Bound within emit; the session (hence its DdlCap) outlives this call.
    return resolveQuorumRevoke(*activeDdlCap, name, keyType);
  }

  //  temporal  seam. The reviewed per-policy gate consumes the
  // finalized attestation (snapshot in `begin`); the recipe/provider path never
  // sees a CoordinationPlan (resolveTemporalGate builds the carrier
  // internally).
  Expected<PgFunction> buildTemporalGate(const std::string &name,
                                         const std::string &pkey,
                                         const std::string &keyType) const {
    if (activeAttestation == nullptr)
      return recipeError(RecipeDiagnostic::InputUnbound,
                         "PostgreSQL temporal attestation");
    return resolveTemporalGate(name, pkey, keyType, *activeAttestation);
  }

  Expected<pgddl::RawSql>
  buildTemporalRevoke(const std::string &name,
                      const std::string &keyType) const {
    return resolveTemporalRevoke(*activeDdlCap, name, keyType);
  }

  Expected<TargetNodeRef> storeStmt(OpaqueBuildSession &opaque,
                                    BackendNodeTypeId node,
                                    ArrayRef<GeneratedFieldBinding> bindings,
                                    ArrayRef<TargetFieldDescriptor> fields,
                                    PgStmt stmt) const {
    auto n = std::make_unique<PgRecipeNode>();
    n->stmt = std::make_unique<PgStmt>(std::move(stmt));
    return store(opaque, node, bindings, fields, std::move(n));
  }

  Expected<TargetNodeRef> storeParam(OpaqueBuildSession &opaque,
                                     BackendNodeTypeId node,
                                     ArrayRef<GeneratedFieldBinding> bindings,
                                     ArrayRef<TargetFieldDescriptor> fields,
                                     PgParam param) const {
    auto n = std::make_unique<PgRecipeNode>();
    n->param = std::make_unique<PgParam>(std::move(param));
    return store(opaque, node, bindings, fields, std::move(n));
  }

  Expected<TargetNodeRef> storeDecl(OpaqueBuildSession &opaque,
                                    BackendNodeTypeId node,
                                    ArrayRef<GeneratedFieldBinding> bindings,
                                    ArrayRef<TargetFieldDescriptor> fields,
                                    PgDeclaration decl) const {
    auto n = std::make_unique<PgRecipeNode>();
    n->decl = std::make_unique<PgDeclaration>(std::move(decl));
    return store(opaque, node, bindings, fields, std::move(n));
  }

  Expected<TargetNodeRef>
  storeReviewedCallable(OpaqueBuildSession &opaque, BackendNodeTypeId node,
                        ArrayRef<GeneratedFieldBinding> bindings,
                        ArrayRef<TargetFieldDescriptor> fields,
                        PgFunction fn) const {
    std::vector<PgStmt> parts;
    std::vector<std::vector<std::string>> params;
    params.reserve(fn.params.size());
    for (const PgParam &param : fn.params)
      params.push_back({param.name, param.type});
    auto signature = emitCallableSig(fn.name, std::move(params));
    if (!signature)
      return recipeError(RecipeDiagnostic::ResultType,
                         "reviewed PostgreSQL callable signature");
    parts.push_back(std::move(*signature));
    if (fn.declare) {
      std::vector<std::vector<std::string>> declarations;
      declarations.reserve(fn.declarations.size());
      for (const PgDeclaration &declaration : fn.declarations)
        declarations.push_back(
            {declaration.name, declaration.type, declaration.initializer});
      auto section = emitDeclareSection(std::move(declarations));
      if (!section)
        return recipeError(RecipeDiagnostic::ResultType,
                           "reviewed PostgreSQL declaration section");
      parts.push_back(std::move(*section));
    }
    auto body = emitCallableBody(std::move(fn.body));
    auto close = emitCallableClose();
    if (!body || !close)
      return recipeError(RecipeDiagnostic::ResultType,
                         "reviewed PostgreSQL callable framing");
    parts.push_back(std::move(*body));
    parts.push_back(std::move(*close));
    auto n = std::make_unique<PgRecipeNode>();
    n->part =
        std::make_unique<PgProcedurePart>(PgCallableRoot{std::move(parts)});
    return store(opaque, node, bindings, fields, std::move(n));
  }

  Expected<TargetNodeRef> storeRevoke(OpaqueBuildSession &opaque,
                                      BackendNodeTypeId node,
                                      ArrayRef<GeneratedFieldBinding> bindings,
                                      ArrayRef<TargetFieldDescriptor> fields,
                                      pgddl::RawSql revoke) const {
    auto n = std::make_unique<PgRecipeNode>();
    n->part =
        std::make_unique<PgProcedurePart>(PgProcedureRevoke{std::move(revoke)});
    return store(opaque, node, bindings, fields, std::move(n));
  }

  Expected<TargetNodeRef>
  storeCallableSignature(OpaqueBuildSession &opaque, BackendNodeTypeId node,
                         ArrayRef<GeneratedFieldBinding> bindings,
                         ArrayRef<TargetFieldDescriptor> fields,
                         const std::string &name,
                         std::vector<PgParam> params) const {
    std::vector<std::vector<std::string>> fieldsByParam;
    fieldsByParam.reserve(params.size());
    for (const PgParam &param : params)
      fieldsByParam.push_back({param.name, param.type});
    auto signature = emitCallableSig(name, std::move(fieldsByParam));
    if (!signature)
      return recipeError(RecipeDiagnostic::ResultType,
                         "PostgreSQL callable signature");
    return storeStmt(opaque, node, bindings, fields, std::move(*signature));
  }

  Expected<TargetNodeRef>
  storeCallableDeclaration(OpaqueBuildSession &opaque, BackendNodeTypeId node,
                           ArrayRef<GeneratedFieldBinding> bindings,
                           ArrayRef<TargetFieldDescriptor> fields,
                           std::vector<PgDeclaration> declarations) const {
    std::vector<std::vector<std::string>> items;
    items.reserve(declarations.size());
    for (const PgDeclaration &declaration : declarations)
      items.push_back(
          {declaration.name, declaration.type, declaration.initializer});
    auto section = emitDeclareSection(std::move(items));
    if (!section)
      return recipeError(RecipeDiagnostic::ResultType,
                         "PostgreSQL declaration section");
    return storeStmt(opaque, node, bindings, fields, std::move(*section));
  }

  Expected<TargetNodeRef>
  storeCallableBody(OpaqueBuildSession &opaque, BackendNodeTypeId node,
                    ArrayRef<GeneratedFieldBinding> bindings,
                    ArrayRef<TargetFieldDescriptor> fields,
                    std::vector<PgStmt> body) const {
    auto section = emitCallableBody(std::move(body));
    if (!section)
      return recipeError(RecipeDiagnostic::ResultType,
                         "PostgreSQL callable body");
    return storeStmt(opaque, node, bindings, fields, std::move(*section));
  }

  Expected<TargetNodeRef>
  storeCallableClose(OpaqueBuildSession &opaque, BackendNodeTypeId node,
                     ArrayRef<GeneratedFieldBinding> bindings,
                     ArrayRef<TargetFieldDescriptor> fields) const {
    auto close = emitCallableClose();
    if (!close)
      return recipeError(RecipeDiagnostic::ResultType,
                         "PostgreSQL callable close");
    return storeStmt(opaque, node, bindings, fields, std::move(*close));
  }

  Expected<TargetNodeRef>
  storeCallableRoot(OpaqueBuildSession &opaque, BackendNodeTypeId node,
                    ArrayRef<GeneratedFieldBinding> bindings,
                    ArrayRef<TargetFieldDescriptor> fields,
                    std::vector<PgStmt> parts) const {
    auto n = std::make_unique<PgRecipeNode>();
    n->part =
        std::make_unique<PgProcedurePart>(PgCallableRoot{std::move(parts)});
    return store(opaque, node, bindings, fields, std::move(n));
  }

  Expected<TargetNodeRef>
  storeProcedureHeader(OpaqueBuildSession &opaque, BackendNodeTypeId node,
                       ArrayRef<GeneratedFieldBinding> bindings,
                       ArrayRef<TargetFieldDescriptor> fields,
                       std::vector<std::string> lines) const {
    auto n = std::make_unique<PgRecipeNode>();
    n->part =
        std::make_unique<PgProcedurePart>(PgProcedureHeader{std::move(lines)});
    return store(opaque, node, bindings, fields, std::move(n));
  }

  Expected<TargetNodeRef>
  storeProcedureSeparator(OpaqueBuildSession &opaque, BackendNodeTypeId node,
                          ArrayRef<GeneratedFieldBinding> bindings,
                          ArrayRef<TargetFieldDescriptor> fields) const {
    auto n = std::make_unique<PgRecipeNode>();
    n->part = std::make_unique<PgProcedurePart>(PgProcedureSeparator{});
    return store(opaque, node, bindings, fields, std::move(n));
  }

  // ----  B3 schema segment builders (recipe COMPOSES exact leaves) ----

  // Render one SPECIFIC typed PgSchemaDecl node through the shared generated
  // printer (the leaf shape is .td-owned; renderSchemaDecl is printer-only).
  pgddl::RawSql renderSchema(const PgSchemaDecl &declaration) const {
    return renderSchemaDecl(*activeDdlCap, declaration);
  }
  // A fixed .td-owned raw-text leaf (schema separators + the single-quorum
  // banner) funneled through the DdlCap.
  pgddl::RawSql rawText(const std::string &text) const {
    return pgddl::rawSql(*activeDdlCap, text);
  }
  // The reviewed  coordination-envelope exact-body leaf (emitted from the
  // allowed-consumer resolver, byte-identical).
  pgddl::RawSql buildSchemaEnvelope() const {
    return resolveSchemaEnvelope(*activeDdlCap);
  }
  // Concatenate the ordered segments into the schema artifact's RawSql.
  Expected<pgddl::RawSql>
  buildSchemaRoot(std::vector<pgddl::RawSql> segments) const {
    if (segments.empty())
      return recipeError(RecipeDiagnostic::CardinalityError,
                         "PostgreSQL schema has no segments");
    pgddl::RawSql out = std::move(segments.front());
    for (size_t i = 1; i < segments.size(); ++i)
      out = std::move(out) + std::move(segments[i]);
    return out;
  }

  Expected<TargetNodeRef> storeSegment(OpaqueBuildSession &opaque,
                                       BackendNodeTypeId node,
                                       ArrayRef<GeneratedFieldBinding> bindings,
                                       ArrayRef<TargetFieldDescriptor> fields,
                                       pgddl::RawSql segment) const {
    auto n = std::make_unique<PgRecipeNode>();
    n->segment = std::move(segment);
    return store(opaque, node, bindings, fields, std::move(n));
  }

  // Many-cardinality schema segments: each child carries one RawSql.
  Expected<std::vector<pgddl::RawSql>>
  takeSegments(OpaqueBuildSession &opaque,
               ArrayRef<GeneratedFieldBinding> bindings,
               ArrayRef<TargetFieldDescriptor> fields, unsigned index) const {
    return takeField<pgddl::RawSql>(static_cast<PgRecipeSession &>(opaque),
                                    postgresRecipeModule(), bindings, fields,
                                    index, "PostgreSQL", "schema segment",
                                    [](PgRecipeNode &n) -> pgddl::RawSql * {
                                      return n.segment ? &*n.segment : nullptr;
                                    });
  }

  Expected<TargetNodeRef>
  storeProcedure(OpaqueBuildSession &opaque, BackendNodeTypeId node,
                 ArrayRef<GeneratedFieldBinding> bindings,
                 ArrayRef<TargetFieldDescriptor> fields, bool evidenceOnly,
                 bool gated, std::vector<PgProcedurePart> parts) const {
    PgProcedure procedure;
    procedure.evidenceOnly = evidenceOnly;
    procedure.gated = gated;
    procedure.root = std::move(parts);
    auto n = std::make_unique<PgRecipeNode>();
    n->procedure = std::move(procedure);
    return store(opaque, node, bindings, fields, std::move(n));
  }

  Expected<std::unique_ptr<OpaqueTargetArtifact>>
  finish(std::unique_ptr<OpaqueBuildSession> opaque,
         ArrayRef<TargetNodeRef> roots) const override {
    auto session = std::unique_ptr<PgRecipeSession>(
        static_cast<PgRecipeSession *>(opaque.release()));
    if (roots.size() != 1)
      return recipeError(RecipeDiagnostic::ResultCardinality,
                         "PostgreSQL evidence expects one procedure root");
    auto artifact = std::make_unique<PgRecipeArtifact>();
    if (Error error = consumeRoots(
            *session, roots, "PostgreSQL", [&](PgRecipeNode &n) -> Error {
              if (n.procedure) {
                artifact->procedure = std::move(*n.procedure);
                return Error::success();
              }
              if (n.segment) { //  B3 schema DDL root
                artifact->schema = std::move(*n.segment);
                return Error::success();
              }
              return recipeError(RecipeDiagnostic::ResultConsumption,
                                 "PostgreSQL root has no generated value");
            }))
      return std::move(error);
    return std::unique_ptr<OpaqueTargetArtifact>(std::move(artifact));
  }

  Error render(const OpaqueTargetArtifact &, OutputSink &) const override {
    return recipeError(RecipeDiagnostic::OperationForbidden,
                       "PostgreSQL evidence artifact renders via the model");
  }

  // : the provider retains only typed forwarding.  Slot/field mappings,
  // presence rules, and ordering live in the generated PostgreSQL projection
  // resolver and its byte-fresh TableGen schema.
  Expected<unsigned> slotExtent(OpaqueBuildSession &opaque, SlotId slot,
                                ArrayRef<SlotIndex> ctx) const override {
    return postgresSlotExtentResolve(static_cast<PgRecipeSession &>(opaque),
                                     slot, ctx);
  }

  Expected<uint64_t> slotItemOrder(OpaqueBuildSession &opaque, SlotId slot,
                                   ArrayRef<SlotIndex> ctx,
                                   unsigned index) const override {
    return postgresSlotItemOrderResolve(static_cast<PgRecipeSession &>(opaque),
                                        slot, ctx, index);
  }

  Expected<TypedHookInput> project(OpaqueBuildSession &opaque,
                                   FinalizedFieldId field,
                                   ArrayRef<SlotIndex> ctx,
                                   SlotIndex owner) const override {
    return postgresProjectFieldResolve(static_cast<PgRecipeSession &>(opaque),
                                       field, ctx, owner);
  }

private:
  Expected<TargetNodeRef> store(OpaqueBuildSession &opaque,
                                BackendNodeTypeId node,
                                ArrayRef<GeneratedFieldBinding> bindings,
                                ArrayRef<TargetFieldDescriptor> fields,
                                std::unique_ptr<PgRecipeNode> made) const {
    auto &session = static_cast<PgRecipeSession &>(opaque);
    if (Error error = recheckBindings(session, postgresRecipeModule(), bindings,
                                      fields, "PostgreSQL"))
      return std::move(error);
    return storeNode(session, node, std::move(*made));
  }

  mutable const pgddl::DdlCap *activeDdlCap = nullptr;
  mutable const projection::AttestationProjection *activeAttestation = nullptr;
  static std::atomic<BuildSessionId> nextSession;
};

std::atomic<BuildSessionId> PostgresRecipeProvider::nextSession{0};

Error ensureProviderRegistered() {
  static const std::string registrationError = [] {
    Error error = RecipeProviderRegistry::get().registerProvider(
        "postgres", [] { return std::make_unique<PostgresRecipeProvider>(); });
    return error ? toString(std::move(error)) : std::string();
  }();
  if (!registrationError.empty())
    return recipeError(RecipeDiagnostic::OperationForbidden, registrationError);
  return Error::success();
}

//  B3: the one procedure impl for every rail. The caller-passed finalized
// idiom `key` selects the rail's recipe; the verified `sequence` flows through
// the one projection view, and `begin` synthesizes the rail's finalized inputs
// from it. No per-rail impl or view survives.
Expected<PgProcedure> materializeProjectionProcedureImpl(
    const FinalizedIdiomKey &key,
    const projection::FinalizedProjectionSequence &sequence,
    const pgddl::DdlCap &ddlCap) {
  const RecipeModule &module = postgresRecipeModule();
  if (Error error = ensureProviderRegistered())
    return std::move(error);
  auto provider = RecipeProviderRegistry::get().create("postgres");
  if (!provider)
    return provider.takeError();
  FinalizedInvocation invocation;
  invocation.key = key;
  PgProjectionRecipeView view;
  view.sequence = &sequence;
  view.ddlCap = &ddlCap;
  invocation.finalizedView = &view;
  auto artifact = materializeRecipe(module, **provider, invocation);
  if (!artifact)
    return artifact.takeError();
  auto *pg = checkedRecipeOpaque<PgRecipeArtifact>(artifact->get());
  if (pg == nullptr || !pg->procedure)
    return recipeError(RecipeDiagnostic::Finish,
                       "PostgreSQL provider returned a foreign artifact");
  return std::move(*pg->procedure);
}

// Materialize the coordination-schema DDL through the schema recipe keyed on
// the finalized rail; the recipe composes the base + quorum/temporal typed
// schema nodes + the reviewed  envelope leaf into the complete schema
// RawSql. The caller passes the exact schema key; the verified sequence
// supplies the memo fact.
Expected<pgddl::RawSql>
materializeSchemaImpl(const FinalizedIdiomKey &key,
                      const projection::FinalizedProjectionSequence &sequence,
                      const pgddl::DdlCap &ddlCap) {
  const RecipeModule &module = postgresRecipeModule();
  if (Error error = ensureProviderRegistered())
    return std::move(error);
  auto provider = RecipeProviderRegistry::get().create("postgres");
  if (!provider)
    return provider.takeError();
  FinalizedInvocation invocation;
  invocation.key = key;
  PgSchemaRecipeView view;
  view.sequence = &sequence;
  view.ddlCap = &ddlCap;
  invocation.finalizedView = &view;
  auto artifact = materializeRecipe(module, **provider, invocation);
  if (!artifact)
    return artifact.takeError();
  auto *pg = checkedRecipeOpaque<PgRecipeArtifact>(artifact->get());
  if (pg == nullptr || !pg->schema)
    return recipeError(
        RecipeDiagnostic::Finish,
        "PostgreSQL provider returned a foreign schema artifact");
  return std::move(*pg->schema);
}

} // namespace

PgProcedure materializeProjectionProcedure(
    const recipe::FinalizedIdiomKey &key,
    const projection::FinalizedProjectionSequence &sequence,
    const pgddl::DdlCap &ddlCap) {
  auto procedure = materializeProjectionProcedureImpl(key, sequence, ddlCap);
  if (!procedure)
    fail("PG_PROJECTION_RECIPE", toString(procedure.takeError()));
  return std::move(*procedure);
}

pgddl::RawSql materializeCoordinationSchema(
    const projection::FinalizedProjectionSequence &sequence,
    const recipe::FinalizedIdiomKey &key, const pgddl::DdlCap &ddlCap) {
  auto schema = materializeSchemaImpl(key, sequence, ddlCap);
  if (!schema)
    fail("PG_COORDINATION_SCHEMA", toString(schema.takeError()));
  return std::move(*schema);
}

// : the completed-recipe-root renderer, relocated here from the model TU.
// Target-blind traversal of the typed procedure parts: the recipe grammar
// selects and orders every part; this only recurses each typed node through the
// generic printer (renderPgStmtTree) and buffers the text. It composes no
// target node of its own.
std::string renderPostgresProjection(const PgProcedure &model) {
  if (model.root.empty())
    fail("PG_RECIPE_ROOT_MISSING",
         "PostgreSQL procedure has no completed recipe root");
  std::string rendered;
  for (const PgProcedurePart &part : model.root) {
    std::visit(
        [&](const auto &value) {
          using Part = std::decay_t<decltype(value)>;
          if constexpr (std::is_same_v<Part, PgProcedureHeader>) {
            codetext::Document document;
            for (const std::string &line : value.lines)
              document.add(codetext::line(line));
            rendered += document.print("    ");
          } else if constexpr (std::is_same_v<Part, PgCallableRoot>) {
            codetext::Document document;
            for (const PgStmt &node : value.parts)
              document.add(renderPgStmtTree(node));
            rendered += document.print("    ");
          } else if constexpr (std::is_same_v<Part, PgProcedureSeparator>) {
            rendered += "\n";
          } else {
            rendered += value.sql.bytes();
          }
        },
        part);
  }
  return rendered;
}

// : the two projection/schema orchestrators moved here from the model TU.
// They are thin, target-blind dispatch over the generated `materializeRecipe`
// runtime (via materializeProjectionProcedure/materializeCoordinationSchema
// above) — finalize the sequence, derive the finalized idiom key, and route the
// rail through the one recipe-resolving call. No handwritten target-node
// construction of their own; the recipe grammar owns all composition.
PgProcedure
materializePostgresProjection(const projection::BackendProjectionGraph &proj) {
  // The single mint of the DDL-authoring capability ( slice 2): threaded to
  // the revoke-trailer builders so their raw DDL flows through the RawSql
  // funnel.
  const pgddl::DdlCap ddlCap = pgddl::DdlCap::forge();
  llvm::Expected<projection::FinalizedProjectionSequence> sequence =
      projection::consumeFinalizedProjectionSequence(proj);
  if (!sequence)
    fail("spec.ast", toString(sequence.takeError()));
  llvm::Expected<recipe::FinalizedIdiomKey> key =
      projection_driver::finalizedProjectionIdiomKey("postgres", *sequence);
  if (!key)
    fail("spec.ast", toString(key.takeError()));
  return materializeProjectionProcedure(*key, *sequence, ddlCap);
}

pgddl::RawSql
materializePostgresSchema(const pgddl::DdlCap &cap,
                          const projection::BackendProjectionGraph &proj) {
  // The finalized idiom key (with the `Schema` role) selects the rail's exact
  // schema recipe straight from the verified rail — no handwritten per-rail key
  // literals, no callback selection, no fallback.
  llvm::Expected<projection::FinalizedProjectionSequence> sequence =
      projection::consumeFinalizedProjectionSequence(proj);
  if (!sequence)
    fail("spec.ast", toString(sequence.takeError()));
  llvm::Expected<recipe::FinalizedIdiomKey> key =
      projection_driver::finalizedProjectionIdiomKey("postgres", *sequence);
  if (!key)
    fail("spec.ast", toString(key.takeError()));
  key->role = "Schema";
  return materializeCoordinationSchema(*sequence, *key, cap);
}

//  R4d: the roled from-spec seam. The public ABI adapter dispatches the
// verified graph here; the render/materialize composition it used to spell
// inline now lives behind this provider entry (the Solidity  mirror).
std::string materializePostgresProcedureArtifact(
    const projection::BackendProjectionGraph &projection) {
  return renderPostgresProjection(materializePostgresProjection(projection));
}

pgddl::RawSql materializePostgresQuorumSchemaArtifact(
    const pgddl::DdlCap &cap,
    const projection::BackendProjectionGraph &projection) {
  return materializePostgresSchema(cap, projection);
}

} // namespace postgres_model
} // namespace neutrino
