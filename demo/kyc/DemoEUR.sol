// SPDX-License-Identifier: Apache-2.0
// Demo scaffolding ONLY: a minimal ERC20 used by the demo script as the
// settlement rail beside the Neutrino-generated coordination contract. This
// token does not consult coordination state and its transfer is unrestricted;
// the coordination contract records whether the accounting obligation
// reconciled, and the requester SCRIPT chooses to transfer after reading that
// result. Neither contract holds or gates the other's funds.
pragma solidity ^0.8.20;
contract DemoEUR {
    string public constant name = "Demo EUR";
    string public constant symbol = "dEUR";
    uint8  public constant decimals = 2;
    mapping(address => uint256) public balanceOf;
    event Transfer(address indexed from, address indexed to, uint256 value);
    constructor() { balanceOf[msg.sender] = 1_000_000; }
    function transfer(address to, uint256 v) external returns (bool) {
        require(balanceOf[msg.sender] >= v, "insufficient");
        balanceOf[msg.sender] -= v; balanceOf[to] += v;
        emit Transfer(msg.sender, to, v); return true;
    }
}
