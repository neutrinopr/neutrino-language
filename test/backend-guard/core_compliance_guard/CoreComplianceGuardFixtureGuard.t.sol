// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

// M5 token S1 () — BACKEND guard-loss proof, Solidity rail (review  finding 2). Drives the
// GENERATED CoreComplianceGuardFixture contract (imported from ../src) with compliance_approved = 1 / 0 / 2 and
// asserts the guard actually holds IN THE RENDERED SOLIDITY: an approval (== 1) posts both legs, and a
// denial (0) or a malformed value (2) moves NO value while the workflow still reconciles as a no-op.
// This exercises the rendered `if (u_compliance_approved == 1)` guard on the real backend — the
// test-realization event chain proves suppression at the model level; this proves it at the Solidity
// level, so a backend renderer that mishandled 0/2 in this rail would be caught here (not silently
// passed by the happy-path-only generated harness).
import "../src/CoreComplianceGuardFixture.sol";

contract CoreComplianceGuardFixtureGuardTest {
    CoreComplianceGuardFixture c;

    function setUp() public {
        c = new CoreComplianceGuardFixture();
    }

    function _k(string memory id) internal pure returns (bytes32) {
        return keccak256(bytes(id));
    }

    // Drive one transfer for a fresh key and return the debited total for that key.
    function _run(string memory id, uint256 approved) internal returns (bytes32 k) {
        k = _k(id);
        c.attest(id);
        c.execute(id, "sender-001", "receiver-001", 2500, "EUR", approved);
    }

    // APPROVED (== 1): both legs post; balanced.
    function test_approved_posts_both_legs() public {
        bytes32 k = _run("xfer-approved", 1);
        require(c.debitTotal(k) == 2500, "approved: debit must post");
        require(c.creditTotal(k) == 2500, "approved: credit must post");
        require(uint256(c.statusOf(k)) == uint256(CoreComplianceGuardFixture.Status.Reconciled), "approved: reconciled");
    }

    // DENIED (== 0): NO value moves; still reconciles as a no-op.
    function test_denied_moves_no_value() public {
        bytes32 k = _run("xfer-denied", 0);
        require(c.debitTotal(k) == 0, "denied: no debit");
        require(c.creditTotal(k) == 0, "denied: no credit");
        require(uint256(c.statusOf(k)) == uint256(CoreComplianceGuardFixture.Status.Reconciled), "denied: reconciled no-op");
    }

    // MALFORMED (== 2, out of range): fail-closed — only an exact 1 posts, so NO value moves.
    function test_malformed_moves_no_value() public {
        bytes32 k = _run("xfer-malformed", 2);
        require(c.debitTotal(k) == 0, "malformed: no debit");
        require(c.creditTotal(k) == 0, "malformed: no credit");
        require(uint256(c.statusOf(k)) == uint256(CoreComplianceGuardFixture.Status.Reconciled), "malformed: reconciled no-op");
    }
}
