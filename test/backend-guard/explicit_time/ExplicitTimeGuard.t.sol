// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "../src/TimeProbe.sol";

/// Production-path behavioral witness for . The translator generates
/// TimeProbe.sol from the ordinary source/scenario path; this test drives that
/// generated contract with both temporal orderings.
contract ExplicitTimeGuardTest {
    TimeProbe private c;

    function setUp() public {
        c = new TimeProbe();
    }

    function test_before_deadline_suppresses_and_at_deadline_transfers() public {
        string memory beforeKey = "before-deadline";
        bytes32 beforeId = keccak256(bytes(beforeKey));
        c.attest(beforeKey);
        c.execute(beforeKey, "buyer-1", 100, "EUR", 4, 5);

        require(
            uint256(c.statusOf(beforeId)) == uint256(TimeProbe.Status.Reconciled),
            "before-deadline terminal"
        );
        require(c.debitTotal(beforeId) == 0, "before-deadline debit");
        require(c.creditTotal(beforeId) == 0, "before-deadline credit");
        require(c.net(beforeId, "a.src") == 0, "before-deadline a.src");
        require(c.net(beforeId, "b.dst") == 0, "before-deadline b.dst");

        string memory atKey = "at-deadline";
        bytes32 atId = keccak256(bytes(atKey));
        c.attest(atKey);
        c.execute(atKey, "buyer-1", 100, "EUR", 5, 5);

        require(
            uint256(c.statusOf(atId)) == uint256(TimeProbe.Status.Reconciled),
            "at-deadline terminal"
        );
        require(c.debitTotal(atId) == 100, "at-deadline debit");
        require(c.creditTotal(atId) == 100, "at-deadline credit");
        require(c.net(atId, "a.src") == -100, "at-deadline a.src");
        require(c.net(atId, "b.dst") == 100, "at-deadline b.dst");
    }
}
