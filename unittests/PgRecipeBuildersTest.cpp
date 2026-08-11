// SPDX-License-Identifier: Apache-2.0
//===- PgRecipeBuildersTest.cpp - generated PostgreSQL node builders () =//
//
// Exercises the generated construction dispatch for the  B1 Emit-catalog
// nodes: the extracted, generated replacement for the retired handwritten
// PgStmt factories. The first extracted vertical is CallableClose; its
// generated builder constructs a PgStmt of the exact kind, and an unknown
// ordinal fails closed.
//
//===----------------------------------------------------------------------===//

#include "PostgresModel.h"

// The generated builder dispatch + per-node emit entries (also compiled into
// the renderer TU; the inline definitions are ODR-safe across TUs).
#include "PostgresRecipeBuilders.inc"

#include "gtest/gtest.h"

using namespace neutrino::postgres_model;

namespace {

TEST(PgRecipeBuilders, EmitCallableCloseConstructsTheKind) {
  std::optional<PgStmt> node = emitCallableClose();
  ASSERT_TRUE(node.has_value());
  EXPECT_EQ(node->kind, PgStmt::Kind::CallableClose);
}

TEST(PgRecipeBuilders, EmitCommonCallableSectionsCarrySchemaFields) {
  std::optional<PgStmt> signature =
      emitCallableSig("execute_example", {{"p_key", "text"}});
  ASSERT_TRUE(signature.has_value());
  EXPECT_EQ(signature->kind, PgStmt::Kind::CallableSig);
  EXPECT_EQ(signature->operands, (std::vector<std::string>{"execute_example"}));
  EXPECT_EQ(signature->group,
            (std::vector<std::vector<std::string>>{{"p_key", "text"}}));

  std::optional<PgStmt> declaration =
      emitDeclareSection({{"v_total", "bigint", "0"}});
  ASSERT_TRUE(declaration.has_value());
  EXPECT_EQ(declaration->kind, PgStmt::Kind::DeclareSection);
  EXPECT_EQ(declaration->group, (std::vector<std::vector<std::string>>{
                                    {"v_total", "bigint", "0"}}));

  std::optional<PgStmt> body = emitCallableBody({});
  ASSERT_TRUE(body.has_value());
  EXPECT_EQ(body->kind, PgStmt::Kind::CallableBody);
  EXPECT_TRUE(body->body.empty());
}

//  (/): the handwritten section-role -> node-kind dispatch
// (`generatedSectionNodeKind`) and the guard-carrier membership helper
// (`generatedIsGuardCarrier`) were retired by the generated typed-root renderer
// / recipe-owned dispatch. The two assertions that exercised them are removed
// (not restored) to match; recipes now own section selection and the generic
// renderer dispatches on the typed node, byte-pinned by postgres-model-test and
// the PostgreSQL golden lit tests.

TEST(PgRecipeBuilders, CommonB1FactoriesCarryExactTypedFields) {
  const PgStmt blank = PgStmt::blank();
  EXPECT_EQ(blank.kind, PgStmt::Kind::Blank);

  // : the no-arg RAISE and the arg-bearing RAISE are distinct generated
  // kinds (Raise / RaiseArg); both project their message/arg as operands.
  const PgStmt raise = PgStmt::raise("not accepted");
  EXPECT_EQ(raise.kind, PgStmt::Kind::Raise);
  EXPECT_EQ(raise.operands, (std::vector<std::string>{"not accepted"}));

  const PgStmt formattedRaise = PgStmt::raiseArg("not balanced for %", "p_key");
  EXPECT_EQ(formattedRaise.kind, PgStmt::Kind::RaiseArg);
  EXPECT_EQ(formattedRaise.operands,
            (std::vector<std::string>{"not balanced for %", "p_key"}));

  const PgStmt assign = PgStmt::assign("v_total", "p_amount");
  EXPECT_EQ(assign.kind, PgStmt::Kind::Assign);
  EXPECT_EQ(assign.operands, (std::vector<std::string>{"v_total", "p_amount"}));

  // : the DO-NOTHING and DO-UPDATE coordination_status writes are distinct
  // generated kinds (StatusWrite / StatusWriteUpdate); both carry the same
  // [proc, pkey, field] operands (no doUpdate Boolean on the render path).
  const PgStmt status =
      PgStmt::statusWrite("execute_demo", "p_key", "reconciled");
  EXPECT_EQ(status.kind, PgStmt::Kind::StatusWrite);
  EXPECT_EQ(status.operands,
            (std::vector<std::string>{"execute_demo", "p_key", "reconciled"}));

  const PgStmt statusUpdate =
      PgStmt::statusWriteUpdate("execute_demo", "p_key", "reconciled");
  EXPECT_EQ(statusUpdate.kind, PgStmt::Kind::StatusWriteUpdate);
  EXPECT_EQ(statusUpdate.operands,
            (std::vector<std::string>{"execute_demo", "p_key", "reconciled"}));
}

TEST(PgRecipeBuilders, LedgerAndPostingFactoriesCarryExactTypedOperands) {
  // : ledgerUpsert / postingInsert now store operands (rendered by the
  // generated lines nodes); the ledger + proc/entry/memo operands are escaped
  // upstream by the string.escape hook, so the factories carry them verbatim.
  const PgStmt ledger =
      PgStmt::ledgerUpsert("cash", "p_from", "p_currency", "-p_amount");
  EXPECT_EQ(ledger.kind, PgStmt::Kind::LedgerUpsert);
  EXPECT_EQ(ledger.operands, (std::vector<std::string>{"cash", "p_from",
                                                       "p_currency",
                                                       "-p_amount"}));

  // The no-memo posting INSERT (8 operands, no memo column).
  const PgStmt posting = PgStmt::postingInsert(
      "execute_transfer", "debit", "cash", "p_from", "p_amount", "p_currency",
      "-p_amount", "p_key");
  EXPECT_EQ(posting.kind, PgStmt::Kind::PostingInsert);
  EXPECT_EQ(posting.operands,
            (std::vector<std::string>{"execute_transfer", "debit", "cash",
                                      "p_from", "p_amount", "p_currency",
                                      "-p_amount", "p_key"}));

  // The with-memo posting INSERT (9 operands, adds the escaped memo).
  const PgStmt postingMemo = PgStmt::postingInsertWithMemo(
      "execute_transfer", "debit", "cash", "p_from", "p_amount", "p_currency",
      "-p_amount", "p_key", "p_memo");
  EXPECT_EQ(postingMemo.kind, PgStmt::Kind::PostingInsertWithMemo);
  EXPECT_EQ(postingMemo.operands,
            (std::vector<std::string>{"execute_transfer", "debit", "cash",
                                      "p_from", "p_amount", "p_currency",
                                      "-p_amount", "p_key", "p_memo"}));
}

TEST(PgRecipeBuilders, RemainingB1FactoriesCarryExactTypedFields) {
  const PgStmt child = PgStmt::blank();
  const PgStmt nested = PgStmt::ifThen("p_ready", {child});
  EXPECT_EQ(nested.kind, PgStmt::Kind::If);
  EXPECT_EQ(nested.operands, (std::vector<std::string>{"p_ready"}));
  ASSERT_EQ(nested.body.size(), 1u);
  EXPECT_EQ(nested.body.front().kind, PgStmt::Kind::Blank);

  const PgStmt flat = PgStmt::flatIf("p_flat", {child});
  EXPECT_EQ(flat.kind, PgStmt::Kind::FlatIf);
  EXPECT_EQ(flat.operands, (std::vector<std::string>{"p_flat"}));
  ASSERT_EQ(flat.body.size(), 1u);

  EXPECT_EQ(PgStmt::progressFlag(true).operands,
            (std::vector<std::string>{"true"}));
  EXPECT_EQ(PgStmt::progressFlag(false).operands,
            (std::vector<std::string>{"false"}));
  EXPECT_EQ(PgStmt::postingIdempotency("p_key", "debit").operands,
            (std::vector<std::string>{"p_key", "debit"}));
  EXPECT_EQ(PgStmt::keyClaimInsert("'execute'", "p_key").operands,
            (std::vector<std::string>{"'execute'", "p_key"}));
  EXPECT_EQ(PgStmt::committedGroupInsert("'execute'", "p_key", "2").operands,
            (std::vector<std::string>{"'execute'", "p_key", "2"}));
  EXPECT_EQ(PgStmt::quorumAcceptInsert("'execute'", "p_key").operands,
            (std::vector<std::string>{"'execute'", "p_key"}));

  const std::vector<std::vector<std::string>> policies = {
      {"'buyer_accepts'", "'buyer-set'", "2"}};
  EXPECT_EQ(PgStmt::policyCaseSelect(policies).group, policies);
  EXPECT_EQ(
      PgStmt::effectLedgerComment("debit", "payment", "cash", " when ready")
          .operands,
      (std::vector<std::string>{"debit", "payment", "cash", " when ready"}));

  EXPECT_EQ(PgStmt::idempotencyGuardComment().kind,
            PgStmt::Kind::IdempotencyGuardComment);
  EXPECT_EQ(PgStmt::balancedInvariantComment().kind,
            PgStmt::Kind::BalancedInvariantComment);
  EXPECT_EQ(PgStmt::idempotentReturn().kind, PgStmt::Kind::IdempotentReturn);
}

TEST(PgRecipeBuilders, SchemaCarrierMismatchFailsClosed) {
  GeneratedRecipeBuildArgs args;
  args.operands = {"unexpected"};
  EXPECT_FALSE(
      GeneratedRecipeBuilder::build(
          static_cast<unsigned>(PgStmt::Kind::CallableClose), std::move(args))
          .has_value());
}

TEST(PgRecipeBuilders, UnknownOrdinalFailsClosed) {
  EXPECT_FALSE(GeneratedRecipeBuilder::build(9999u).has_value());
}

} // namespace
