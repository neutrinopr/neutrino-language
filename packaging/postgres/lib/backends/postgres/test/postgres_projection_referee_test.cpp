//===- postgres_projection_referee_test.cpp - R5b render referee ---------===//
//
// [977] R5b PostgreSQL render REFEREE — the dialect-free, in-process oracle for
// the finalized-view trio (project / slotExtent / slotItemOrder) that R5b
// retires to generated dispatch. Everything is asserted on the RENDER OUTPUT of
// the real recipe/provider path (planFromSpec -> projectBackendGraph ->
// materializePostgresProjection -> materializeProjectionProcedure ->
// materializeRecipe -> the provider's slotExtent/slotItemOrder/project ->
// renderPostgresProjection), never on the pre-dispatch input facts — a
// slotExtent that returns a constant, swaps ordinals, or ignores the finalized
// fields must fail here. No neutrino-gen (runs under make unittest); no
// leaf-only shim.
//
//   (1) Procedure byte oracle — the memo/gated witness must render
//   byte-for-byte
//       equal to the committed procedure.sql (the single representative
//       render).
//
//   (2) Each sequence-level selection the trio dispatches on must FLIP the
//   render
//       between the positive witness (WithMemo + Single attestation) and its
//       opposite arm:
//         * the attestation optional slot -> the gated attestation block is
//           present iff Single (slotExtent egated/eungatedWithAttestation);
//         * the postings memo field -> the posting INSERT carries the memo
//           column iff the memo fact is present (project of the memo field).
//       The opposite arm is DERIVED IN-TEST from the witness plan (strip the
//       attestation policy + the postings memo + the now-orphan evidence input)
//       and re-normalized through planFromSpec — no second committed spec, no
//       hand-authored plan that bypasses normalization.
//
// (The postings-table WithMemo *schema* slot renders only through
// materializePostgresSchema, which a test cannot drive: DdlCap::forge() AND
// RawSql::bytes() are both friend-sealed. The memo selection's trio dispatch is
// therefore witnessed at the procedure's project-driven memo column above.)
//
//===----------------------------------------------------------------------===//

#include "PostgresModel.h"

#include "Neutrino/CoordinationPlan.h"

#include "llvm/Support/Error.h"
#include "llvm/Support/JSON.h"

#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

using namespace neutrino;
using namespace neutrino::postgres_model;

static std::string slurp(const char *path) {
  std::ifstream in(path);
  if (!in) {
    std::fprintf(stderr, "referee: cannot open %s\n", path);
    std::exit(2);
  }
  std::stringstream ss;
  ss << in.rdbuf();
  return ss.str();
}

static std::string render(const llvm::json::Object &spec) {
  llvm::Expected<CoordinationPlan> plan = planFromSpec(spec);
  if (!plan)
    llvm::report_fatal_error("referee: coordination-plan normalization failed");
  llvm::Expected<projection::BackendProjectionGraph> graph =
      projection::projectBackendGraph(*plan);
  if (!graph)
    llvm::report_fatal_error("referee: backend projection failed");
  return renderPostgresProjection(materializePostgresProjection(*graph));
}

// Derive the opposite arm from the witness spec: strip the attestation policy
// (-> ungated / attestationKind None), the postings memo (-> Plain), and the
// now-orphan evidence input. planFromSpec re-normalizes the result, so this is
// a valid variant plan, not a hand-edited bypass.
static llvm::json::Object oppositeArm(const llvm::json::Object &witness) {
  llvm::json::Object variant = witness;
  variant.erase("attestations");
  if (llvm::json::Array *effects = variant.getArray("effects"))
    for (llvm::json::Value &effect : *effects)
      if (llvm::json::Object *obj = effect.getAsObject())
        obj->erase("memo");
  if (const llvm::json::Array *inputs = variant.getArray("inputs")) {
    llvm::json::Array kept;
    for (const llvm::json::Value &input : *inputs) {
      const llvm::json::Object *obj = input.getAsObject();
      const llvm::Optional<llvm::StringRef> name =
          obj ? obj->getString("name") : llvm::None;
      if (!name || *name != "clearance_proof")
        kept.push_back(input);
    }
    variant["inputs"] = std::move(kept);
  }
  return variant;
}

static int failures = 0;
static void expect(bool ok, const char *what) {
  if (!ok) {
    std::fprintf(stderr, "referee: FAIL: %s\n", what);
    ++failures;
  }
}

int main(int argc, char **argv) {
  if (argc < 3) {
    std::fprintf(stderr, "usage: postgres-projection-referee-test "
                         "<witness-spec> <witness-procedure.sql>\n");
    return 2;
  }
  llvm::Expected<llvm::json::Value> parsed = llvm::json::parse(slurp(argv[1]));
  if (!parsed || !parsed->getAsObject())
    llvm::report_fatal_error("referee: witness spec is not a JSON object");
  const llvm::json::Object witness = *parsed->getAsObject();

  const std::string witnessProc = render(witness);
  const std::string variantProc = render(oppositeArm(witness));

  // (1) Single representative byte oracle.
  expect(witnessProc == slurp(argv[2]),
         "witness procedure render == committed baseline");

  // (2) The dispatch output flips per selection — a constant slotExtent/project
  // renders both arms identically and fails these.
  const bool witGate =
      witnessProc.find("quorum_acceptance") != std::string::npos;
  const bool varGate =
      variantProc.find("quorum_acceptance") != std::string::npos;
  expect(witGate, "witness (Single) renders the gated attestation block");
  expect(!varGate, "variant (None) omits the gated attestation block");

  // The memo posting COLUMN in the postings INSERT (not the procedure name,
  // which itself contains "memo").
  const char *memoColumn = "idempotency_key, memo)";
  const bool witMemo = witnessProc.find(memoColumn) != std::string::npos;
  const bool varMemo = variantProc.find(memoColumn) != std::string::npos;
  expect(witMemo, "witness (WithMemo) renders the posting memo column");
  expect(!varMemo, "variant (Plain) omits the posting memo column");

  if (failures)
    return 1;
  std::printf("postgres-projection-referee-test: OK\n");
  return 0;
}
