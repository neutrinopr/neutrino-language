// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

/// @title DemoAgentRegistry — local scaffolding modeled on the ERC-8004 registration shape.
/// @notice Demo-only. Deployed on anvil for the KYC paid-attestation demo. Not a mainnet
///         8004 deployment and not evidence of live-registry adoption.
///
/// Registration shape (intentionally minimal):
/// - an EOA registers once with an agentURI string;
/// - the registry assigns a monotonic agentId;
/// - agentOf[owner] and agents[id] are readable for auditor listing.
contract DemoAgentRegistry {
    struct Agent {
        address owner;
        string agentURI;
        uint64 registeredAt;
    }

    uint256 public nextAgentId = 1;
    mapping(uint256 => Agent) public agents;
    mapping(address => uint256) public agentOf;

    event Registered(
        uint256 indexed agentId,
        address indexed owner,
        string agentURI
    );

    /// @notice Register the caller as an agent. One registration per address.
    function register(string calldata agentURI) external returns (uint256 agentId) {
        require(agentOf[msg.sender] == 0, "DemoAgentRegistry: already registered");
        require(bytes(agentURI).length > 0, "DemoAgentRegistry: empty agentURI");
        agentId = nextAgentId++;
        agents[agentId] = Agent({
            owner: msg.sender,
            agentURI: agentURI,
            registeredAt: uint64(block.timestamp)
        });
        agentOf[msg.sender] = agentId;
        emit Registered(agentId, msg.sender, agentURI);
    }
}
