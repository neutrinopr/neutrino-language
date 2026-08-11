// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "../src/OracleDelivery.sol";

interface VmRollback {
    function expectRevert(bytes calldata) external;
    function store(address target, bytes32 slot, bytes32 value) external;
}

contract RollbackAcceptanceGuard {
    mapping(bytes32 => bool) public accepted;

    function setAccepted(bytes32 claimId, bool value) external {
        accepted[claimId] = value;
    }

    function isAccepted(bytes32 claimId) external view returns (bool) {
        return accepted[claimId];
    }
}

/// Forces the generated contract's final balance check to fail after both
/// posting legs mutate state, then proves EVM revert restored every touched
/// mapping to its exact pre-call value.
contract OracleDeliveryRollbackTest {
    VmRollback constant vm =
        VmRollback(0x7109709ECfa91a80626fF3989D68f67F5b1DD12D);

    function test_post_mutation_failure_rolls_back_all_state() public {
        RollbackAcceptanceGuard guard = new RollbackAcceptanceGuard();
        OracleDelivery coordination = new OracleDelivery(address(guard));
        string memory orderId = "rollback-order";
        bytes32 key = keccak256(bytes(orderId));

        // OracleDelivery storage layout: statusOf=0, net=1, debitTotal=2,
        // creditTotal=3. Seed an imbalance so execution reaches the final
        // `not balanced` check only after mutating net and both totals.
        bytes32 creditSlot = keccak256(abi.encode(key, uint256(3)));
        vm.store(address(coordination), creditSlot, bytes32(uint256(1)));
        guard.setAccepted(key, true);

        vm.expectRevert(bytes("not balanced"));
        coordination.execute(
            orderId,
            "buyer",
            "seller",
            500,
            "USD",
            "sha256:rollback"
        );

        require(
            uint256(coordination.statusOf(key)) ==
                uint256(OracleDelivery.Status.None),
            "status mutation survived revert"
        );
        require(
            coordination.net(key, "buyer.escrow") == 0,
            "debit net mutation survived revert"
        );
        require(
            coordination.net(key, "seller.proceeds") == 0,
            "credit net mutation survived revert"
        );
        require(
            coordination.debitTotal(key) == 0,
            "debit total mutation survived revert"
        );
        require(
            coordination.creditTotal(key) == 1,
            "pre-call credit baseline was not restored"
        );
    }
}
