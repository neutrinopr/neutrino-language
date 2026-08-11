R"NEUSOL(// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// The  EXECUTION-ENVELOPE digest, reproduced on chain byte-for-byte from the
/// target-neutral reference (lib/spec-contract/CoordinationEnvelope.cpp). It is a
/// domain-separated SHA-256 over the coordination identity + workflow key + the
/// declared typed payload, with explicit big-endian length framing so no field
/// boundary is ambiguous — the SAME preimage the reference evaluator and every
/// rail hash. A coordination recomputes this from its execute() inputs and requires
/// it to equal the guard's `acceptedExecutionClaim(claimId)` before committing, so
/// acceptance of one payload never authorizes a different one on the same key.
///
/// Inputs are pre-sorted by (name, category, value) by the caller. Declared input
/// names are unique, so that order is a compile-time constant the generated
/// coordination emits — no on-chain sort. A numeric value is its decimal
/// minor-units string; a symbolic value is its token, matching the reference's
/// ExecutionInput canonicalization.
///
/// Hand-authored, security-reviewed REFERENCE artifact — pinned to the committed
/// cross-implementation vector (see test/CoordinationEnvelope.t.sol and
/// ../threshold-quorum/execution-claim-vector.json). NOT generated.
library CoordinationEnvelope {
    string private constant DOMAIN = "neutrino.coordination-envelope.v1";

    /// frame(x) = big-endian uint64(byteLength(x)) ‖ x — mirrors appendFramed. In
    /// abi.encodePacked a uint64 is 8 bytes big-endian, so this is exactly BE64(len).
    function _frame(bytes memory x) private pure returns (bytes memory) {
        return abi.encodePacked(uint64(x.length), x);
    }

    /// Decimal string of a uint — the input arity, and (for the caller) numeric
    /// minor-unit values. Matches std::to_string on a non-negative integer.
    function u2s(uint256 v) internal pure returns (string memory) {
        if (v == 0) {
            return "0";
        }
        uint256 digits;
        for (uint256 n = v; n != 0; n /= 10) {
            digits++;
        }
        bytes memory b = new bytes(digits);
        for (uint256 i = digits; v != 0; v /= 10) {
            b[--i] = bytes1(uint8(48 + (v % 10)));
        }
        return string(b);
    }

    /// executionClaim = sha256(
    ///   frame(DOMAIN) ‖ frame(coordId) ‖ frame(key) ‖ frame(str(N))
    ///   ‖ for each input i (sorted): frame(name_i) ‖ frame(category_i) ‖ frame(value_i)).
    function claim(
        string memory coordinationIdentity,
        string memory workflowKey,
        string[] memory names,
        string[] memory categories,
        string[] memory values
    ) internal pure returns (bytes32) {
        require(
            names.length == categories.length && names.length == values.length,
            "envelope: ragged input arrays"
        );
        bytes memory p = abi.encodePacked(
            _frame(bytes(DOMAIN)),
            _frame(bytes(coordinationIdentity)),
            _frame(bytes(workflowKey)),
            _frame(bytes(u2s(names.length)))
        );
        for (uint256 i = 0; i < names.length; i++) {
            p = abi.encodePacked(
                p,
                _frame(bytes(names[i])),
                _frame(bytes(categories[i])),
                _frame(bytes(values[i]))
            );
        }
        return sha256(p);
    }
}
)NEUSOL"
