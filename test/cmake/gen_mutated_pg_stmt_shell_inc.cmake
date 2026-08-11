# [] Regenerate a PG printer-handlers include from a MUTATED copy of a node's
# syntax record, so the render harness can be compiled against it and prove the
# mutation changes production output. The PostgreSQL parallel of
# gen_mutated_stmt_shell_inc.cmake.
#
# Invoked from an add_custom_command:
#   cmake -DGEN=... -DTD=... -DSCHEMA=... -DTBLGEN=... -DWORK=... -DOUT=... [-DNODE=...] -P this
#
# NODE selects which node's syntax record to mutate (default `progressflag`):
#   * progressflag       -> `v_progress := ${value};`  -> `v_progress ::= ${value};`
#   * posting_idempotency -> `ON CONFLICT DO NOTHING;`  -> `ON CONFLICT DO NOTHINGX;`
#   * key_claim          -> `v_claim);`                -> `v_claimX);`
#   * committed_group    -> `${ordinal});`             -> `${ordinal}X);`
#   * quorum_accept      -> `observer_count)`          -> `observer_countX)`
#   * temporal_accept    -> `execution_claim, observer_count)` -> `execution_claim, observer_countX)`
#   * idempotent_return  -> `no double posting`               -> `no double postinX`
#   * evidence_claim_comment -> `move NO ledger value.`        -> `move NO ledger valueX.`
#   * idempotency_guard_comment -> `one row per workflow key`  -> `one row per workflow keX`
#   * balanced_invariant_comment -> `must net to zero`          -> `must net to zerX`
#   * coordination_status -> `attested boolean`                 -> `attested bigint`
#   * ledger_balance -> `balance bigint`                         -> `balance numeric`
#   * posting_idempotency_table -> `entry text`                  -> `entry jsonb`
#   * committed_group_table -> `committed_at timestamptz`        -> `committed_at timestamp`
#
# NOTE (idempotent_return): the token is the TAIL of the syntax with no trailing
# delimiter, so an append (`…postingX`) would leave the committed token as a
# SUBSTRING of the mutated one and trip the committed-absent sanity FIND below.
# The mutation therefore SUBSTITUTES the final char (g->X) instead of appending.
#
# NOTE (evidence_claim_comment): the token ends in `value.`; the mutation INSERTS
# `X` before the trailing `.` (`value.` -> `valueX.`) so the committed token
# `…value.` is NOT a substring of the mutated `…valueX.` (the char after `value`
# differs), keeping the committed-absent sanity FIND below honest.
#
# The generator resolves tblgen's include dir as the .td's GRANDPARENT and the
# record `include "TargetPrinter.td"`, so mirror that layout under WORK:
#   ${WORK}/backends/TargetPrinter.td       (schema copy)
#   ${WORK}/backends/postgres/mutated.td    (mutated record)
# The templates are defined here (not passed via -D) because a `${...};` value
# would be mangled by CMake list-splitting / variable expansion on the command line.

if(NOT DEFINED NODE)
  set(NODE "progressflag")
endif()
if(NODE STREQUAL "posting_idempotency")
  set(_committed_tpl "ON CONFLICT DO NOTHING;")
  set(_mutated_tpl "ON CONFLICT DO NOTHINGX;")
elseif(NODE STREQUAL "key_claim")
  set(_committed_tpl "v_claim);")
  set(_mutated_tpl "v_claimX);")
elseif(NODE STREQUAL "committed_group")
  set(_committed_tpl "\${ordinal});")
  set(_mutated_tpl "\${ordinal}X);")
elseif(NODE STREQUAL "quorum_accept")
  set(_committed_tpl "observer_count)")
  set(_mutated_tpl "observer_countX)")
elseif(NODE STREQUAL "temporal_accept")
  set(_committed_tpl "execution_claim, observer_count)")
  set(_mutated_tpl "execution_claim, observer_countX)")
elseif(NODE STREQUAL "idempotent_return")
  set(_committed_tpl "no double posting")
  set(_mutated_tpl "no double postinX")
elseif(NODE STREQUAL "evidence_claim_comment")
  set(_committed_tpl "move NO ledger value.")
  set(_mutated_tpl "move NO ledger valueX.")
elseif(NODE STREQUAL "idempotency_guard_comment")
  set(_committed_tpl "one row per workflow key")
  set(_mutated_tpl "one row per workflow keX")
elseif(NODE STREQUAL "balanced_invariant_comment")
  set(_committed_tpl "must net to zero")
  set(_mutated_tpl "must net to zerX")
elseif(NODE STREQUAL "authorized_observer")
  set(_committed_tpl "observer_id  text NOT NULL")
  set(_mutated_tpl "observer_id  bigint NOT NULL")
elseif(NODE STREQUAL "coordination_status")
  set(_committed_tpl "attested        boolean NOT NULL DEFAULT false")
  set(_mutated_tpl "attested        bigint  NOT NULL DEFAULT 0")
elseif(NODE STREQUAL "ledger_balance")
  set(_committed_tpl "balance    bigint NOT NULL DEFAULT 0")
  set(_mutated_tpl "balance    numeric NOT NULL DEFAULT 0")
elseif(NODE STREQUAL "posting_idempotency_table")
  set(_committed_tpl "entry           text NOT NULL")
  set(_mutated_tpl "entry           jsonb NOT NULL")
elseif(NODE STREQUAL "committed_group_table")
  set(_committed_tpl "committed_at    timestamptz NOT NULL DEFAULT now()")
  set(_mutated_tpl "committed_at    timestamp   NOT NULL DEFAULT now()")
elseif(NODE STREQUAL "postings_base")
  # A column shared by both postings records; on the memo-LESS effectful path only
  # the base PostingsTable renders, so this proves the BASE record drives that path.
  set(_committed_tpl "signed_amount  bigint NOT NULL")
  set(_mutated_tpl "signed_amount  numeric NOT NULL")
elseif(NODE STREQUAL "postings_memo")
  # The memo column exists ONLY in PostingsWithMemoTable; mutating it proves the
  # MEMO record drives the memo path and cannot leak onto the memo-less path.
  set(_committed_tpl "memo           text")
  set(_mutated_tpl "memo           jsonb")
elseif(NODE STREQUAL "key_claim_table")
  # The bound_at column type (unique to KeyClaimTable) proves the record drives
  # the temporal schema.
  set(_committed_tpl "bound_at        timestamptz NOT NULL DEFAULT now()")
  set(_mutated_tpl "bound_at        timestamp   NOT NULL DEFAULT now()")
elseif(NODE STREQUAL "quorum_acceptance_table")
  # Every column of the single QuorumAcceptanceTable shape is byte-identical to
  # the temporal shape, so a shared-column mutation would hit BOTH .td records.
  # The single-policy primary key `(procedure, claim_id)` is the discriminator:
  # the temporal record ends `(procedure, claim_id, policy)`, so this full token
  # matches only the single record.
  set(_committed_tpl "PRIMARY KEY (procedure, claim_id)")
  set(_mutated_tpl "PRIMARY KEY (procedure, claim_idX)")
elseif(NODE STREQUAL "temporal_quorum_acceptance_table")
  # The execution_claim column exists ONLY in the temporal per-policy
  # quorum_acceptance shape (the single shape and key_claim carry no such
  # column at this alignment), so this only touches the temporal quorum schema.
  set(_committed_tpl "execution_claim      text        NOT NULL")
  set(_mutated_tpl "execution_claim      bytea       NOT NULL")
elseif(NODE STREQUAL "policy_case")
  # Flip the framed-lines ITEM operator (unique to PolicyCaseSelect's ItemSyntax)
  # so each rendered WHEN line changes — proving the per-item template drives
  # production output.
  set(_committed_tpl "THEN v_set := \${observerSet}")
  set(_mutated_tpl "THEN v_set ::= \${observerSet}")
elseif(NODE STREQUAL "effect_ledger_comment")
  # Flip the fixed ledger-paren shape (unique to EffectLedgerComment's syntax) so
  # the rendered comment header changes — proving the .td template drives the
  # production comment bytes.
  set(_committed_tpl "(\${ledger})")
  set(_mutated_tpl "{\${ledger}}")
elseif(NODE STREQUAL "if")
  # Flip the fixed block-close (unique to the `If` node's `IF <cond> THEN`/`END
  # IF;` guard frame, ) so the rendered guard-close changes — proving the .td
  # node drives the production `END IF;` frame literal through the real legalize/
  # print path (via the sealed authorGuard carrier). Substitutes `END IF;`->`END
  # IFX;` (committed `END IF;` is NOT a substring of `END IFX;`, and is disjoint
  # from CallableBody's `END;`, keeping the committed-absent sanity FIND honest).
  set(_committed_tpl "END IF;")
  set(_mutated_tpl "END IFX;")
elseif(NODE STREQUAL "flat-if")
  # Flip the flat  guard's block-close (). `FlatIf` and `If` render the
  # SAME `END IF;` close text, so a GLOBAL replace would hit both records; this
  # mutation is NODE-SCOPED via a `.td` anchor UNIQUE to the FlatIf def — FlatIf
  # keeps `/*generated=*/1, /*closeSyntax=*/"END IF;"` on ONE line, while `If`
  # splits `/*generated=*/1,` and `/*closeSyntax=*/` across two lines — so only
  # the FlatIf record's close becomes `END IFX;`. The If-rendered guards keep
  # `END IF;`, so the paired harness normalizes `END IFX;`->`END IF;` and proves
  # the ONLY change is the FlatIf frames (see run_pg_flat_if_real_path_mutation).
  set(_td_committed_tpl "/*generated=*/1, /*closeSyntax=*/\"END IF;\">;")
  set(_td_mutated_tpl "/*generated=*/1, /*closeSyntax=*/\"END IFX;\">;")
  set(_committed_tpl "END IF;")
  set(_mutated_tpl "END IFX;")
  # The If node legitimately keeps rendering `END IF;` in the .inc, so the
  # committed close is NOT globally absent after this node-scoped mutation.
  set(_inc_committed_absent FALSE)
elseif(NODE STREQUAL "callable_body")
  # Flip the fixed block-close (unique to CallableBody's `BEGIN … END;` block
  # frame,  slice 3) so the rendered body-close changes — proving the .td node
  # drives the production `END;` frame literal through the real legalize/print
  # path. Substitutes `END;`->`DONE;` (committed `END;` is NOT a substring of
  # `DONE;`, keeping the committed-absent sanity FIND honest).
  set(_committed_tpl "END;")
  set(_mutated_tpl "DONE;")
elseif(NODE STREQUAL "callable_close")
  # Flip the fixed `$$;` dollar-quote function-close (unique to CallableClose's
  # leaf syntax,  endpoint) so the rendered terminator changes — proving the
  # .td node drives the production `$$;` close through the real legalize/print
  # path. Substitutes `$$;`->`@@;` (committed `$$;` is NOT a substring of `@@;`,
  # and `AS $$` — which has no trailing `;` — is untouched, keeping the
  # committed-absent sanity FIND honest).
  set(_committed_tpl "$$;")
  set(_mutated_tpl "@@;")
elseif(NODE STREQUAL "callable_sig")
  # Flip the fixed RETURNS clause (unique to CallableSig's header syntax, ) so
  # the rendered `CREATE OR REPLACE FUNCTION … RETURNS void` header changes —
  # proving the .td node drives the production callable-header bytes through the
  # real legalize/print path. Substitutes `void`->`trigger` (committed `RETURNS
  # void` is NOT a substring of `RETURNS trigger`, keeping the committed-absent
  # sanity FIND honest).
  set(_committed_tpl "RETURNS void")
  set(_mutated_tpl "RETURNS trigger")
elseif(NODE STREQUAL "declare_section")
  # Flip the fixed header unique to DeclareSection. The declaration tuples and
  # C++ section-selection decision are unchanged; only .td-owned framing moves.
  set(_committed_tpl "DECLARE")
  set(_mutated_tpl "DECLARX")
else()
  set(_committed_tpl "v_progress := \${value};")
  set(_mutated_tpl "v_progress ::= \${value};")
endif()

# Most nodes mutate the same token in the `.td` record and the emitted `.inc`
# handler; a NODE-SCOPED mutation (e.g. flat-if, whose close text is shared with
# another record) sets a distinct `_td_*` anchor for the `.td` replace while
# keeping `_committed_tpl`/`_mutated_tpl` for the `.inc` sanity + harness.
if(NOT DEFINED _td_committed_tpl)
  set(_td_committed_tpl "${_committed_tpl}")
  set(_td_mutated_tpl "${_mutated_tpl}")
endif()
if(NOT DEFINED _inc_committed_absent)
  set(_inc_committed_absent TRUE)
endif()

file(READ "${TD}" _td)
string(REPLACE "${_td_committed_tpl}" "${_td_mutated_tpl}" _td_mut "${_td}")
if(_td_mut STREQUAL _td)
  message(FATAL_ERROR
    "gen-mutated-pg-stmt-shell VACUOUS: the syntax record anchor "
    "`${_td_committed_tpl}` was not found in ${TD} to mutate.")
endif()

file(MAKE_DIRECTORY "${WORK}/backends/postgres")
configure_file("${SCHEMA}" "${WORK}/backends/TargetPrinter.td" COPYONLY)
file(WRITE "${WORK}/backends/postgres/mutated.td" "${_td_mut}")

execute_process(
  COMMAND python3 "${GEN}"
    --td "${WORK}/backends/postgres/mutated.td"
    --out "${WORK}/mutated_registry.inc"
    --printer-out "${OUT}"
    --tblgen "${TBLGEN}"
  RESULT_VARIABLE _rc OUTPUT_VARIABLE _out ERROR_VARIABLE _err)
if(NOT _rc EQUAL 0)
  message(FATAL_ERROR "gen-mutated-pg-stmt-shell: generator failed:\n${_out}${_err}")
endif()

# Sanity: the regenerated handler must carry the mutated grammar (the generator
# consumed the record) and not the committed grammar.
file(READ "${OUT}" _printer)
string(FIND "${_printer}" "${_mutated_tpl}" _has_mut)
if(_has_mut EQUAL -1)
  message(FATAL_ERROR
    "gen-mutated-pg-stmt-shell: regenerated handler did not adopt the mutated "
    "grammar `${_mutated_tpl}` (generator does not consume the syntax record).")
endif()
# For a GLOBAL mutation the committed token must vanish entirely; a NODE-SCOPED
# mutation leaves it on the OTHER records (e.g. flat-if leaves the If close), so
# the committed-absent assertion is skipped there.
if(_inc_committed_absent)
  string(FIND "${_printer}" "${_committed_tpl}" _has_committed)
  if(NOT _has_committed EQUAL -1)
    message(FATAL_ERROR
      "gen-mutated-pg-stmt-shell: regenerated handler still carries the "
      "committed grammar `${_committed_tpl}` after a global mutation.")
  endif()
endif()
