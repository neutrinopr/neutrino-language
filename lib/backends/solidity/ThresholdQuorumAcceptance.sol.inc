// ThresholdQuorumAcceptance.sol.inc — the SECURITY-REVIEWED M-of-N threshold-quorum acceptance
// guard (), embedded VERBATIM from the vetted reference golden
// (examples/oracle-reference/threshold-quorum/src/ThresholdQuorumAcceptance.sol). Included as a
// raw-string literal by GenSolidityQuorumGuard.cpp; the byte-golden diff test
// (test/ir/oracle/oracle_delivery.neu) PROVES the emitted bytes equal the reference, so any drift
// on either side fails CI. Regenerate by copying the reference bytes verbatim.
R"NEUSOL(// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title ThresholdQuorumAcceptance — M-of-N threshold-signature acceptance guard.
/// @notice The ON-CHAIN half of the spec-declared attestation policy (Neutrino oracle S1, ): a leg
/// fires only once at least `threshold` (M) DISTINCT AUTHORIZED observers have signed the SAME canonical
/// claim. Off-chain, the generated serverless observers (S4, ) each sign the canonical claim; this
/// contract verifies that quorum on chain before the coordination proceeds.
///
/// @dev This is the SECURITY-REVIEWED REFERENCE for oracle slice 2 (/): it is authored + vetted
/// as a static artifact BEFORE the lowering exists, and the S2 lowering () must then reproduce it
/// byte-identically from the policy — the golden-diff PROVES the render, it does not pattern-match this
/// sample. See REVIEW_NOTES.md for the canonical-claim preimage, signature scheme, identity binding,
/// replay key, and the timeout/fallback deferral ().
///
/// Fail-closed by construction — it NEVER accepts on: fewer than M signatures, a divergent canonical
/// claim, an unknown or duplicate signer, an invalid/malleable signature, or a replay. Non-custodial:
/// it records acceptance only; it moves no value.
contract ThresholdQuorumAcceptance {
    /// @notice M — the acceptance threshold (portable spec value ).
    uint256 public immutable threshold;
    /// @notice N — the number of distinct authorized observers (resolved at binding,  slice 5).
    uint256 public immutable observerCount;
    /// @notice The bound observer key set — the ONLY signers that count toward quorum.
    mapping(address observer => bool authorized) public isObserver;
    /// @dev EIP-712 domain, cached at deploy and REBUILT if `block.chainid` changes (a chainId-changing
    /// hard fork): the cached separator is returned only while the chainId matches, else it is recomputed
    /// from the current chainId — so a signature valid pre-fork does NOT verify on the forked chain
    /// (OpenZeppelin's EIP712 pattern). Read via `domainSeparator()`.
    bytes32 private immutable _cachedDomainSeparator;
    uint256 private immutable _cachedChainId;
    address private immutable _cachedThis;
    bytes32 private immutable _capabilityHash;
    /// @notice Replay/idempotency guard (reuses the  coordination-status concept): a `claimId` is
    /// accepted at most once, so a re-submitted quorum can never double-fire the leg.
    mapping(bytes32 claimId => bool) public accepted;
    /// @notice The canonical claim hash the quorum actually signed for a `claimId` (). Persisting it
    /// records what the quorum attested to. Zero until accepted.
    mapping(bytes32 claimId => bytes32 canonicalClaimHash) public acceptedClaim;
    /// @notice The  EXECUTION CLAIM the quorum co-signed for a `claimId`: the domain-separated digest
    /// of the coordination identity + workflow key + declared typed payload. A downstream coordination
    /// recomputes this digest from its inputs and requires it to equal this value before committing, so
    /// acceptance of payload A never authorizes execution of a different payload B on the same key. The
    /// observers co-sign it ALONGSIDE the evidence `canonicalClaimHash`, so the evidence is bound to the
    /// exact execution it authorizes. Zero until accepted.
    mapping(bytes32 claimId => bytes32 executionClaim) public acceptedExecutionClaim;

    /// @dev EIP-712 domain type hash: (chainId, verifyingContract, capabilityHash).
    bytes32 private constant DOMAIN_TYPEHASH = keccak256(
        "NeutrinoThresholdQuorumAcceptance(uint256 chainId,address verifyingContract,bytes32 capabilityHash)"
    );
    /// @dev EIP-712 claim type hash — the domain-separated preimage the observers sign. The evidence
    /// `canonicalClaimHash` and the  `executionClaim` are co-signed, authenticating their relationship.
    bytes32 private constant CLAIM_TYPEHASH =
        keccak256("QuorumClaim(bytes32 claimId,bytes32 canonicalClaimHash,bytes32 executionClaim)");

    event QuorumAccepted(bytes32 indexed claimId, bytes32 indexed claimDigest, uint256 signatures);

    error EmptyObserverSet();
    error BadThreshold(uint256 threshold, uint256 observerCount);
    error AlreadyAccepted(bytes32 claimId);
    error QuorumNotMet(uint256 got, uint256 need);
    error UnauthorizedSigner(address recovered);
    error SignersNotStrictlyAscending(address prev, address recovered);
    error MalformedSignature(uint256 index);
    error MalleableSignature(uint256 index);

    /// @param observers the authorized observer set (deduplicated here; the concrete N is binding-level).
    /// @param threshold_ M — 1 <= M <= N (a wider threshold could never be met).
    /// @param capabilityHash the capability this acceptance guard is bound to (identity binding).
    constructor(address[] memory observers, uint256 threshold_, bytes32 capabilityHash) {
        uint256 n;
        for (uint256 i = 0; i < observers.length; i++) {
            address o = observers[i];
            if (o != address(0) && !isObserver[o]) {
                isObserver[o] = true;
                n++;
            }
        }
        if (n == 0) revert EmptyObserverSet();
        if (threshold_ == 0 || threshold_ > n) revert BadThreshold(threshold_, n);
        threshold = threshold_;
        observerCount = n;
        _capabilityHash = capabilityHash;
        _cachedThis = address(this);
        _cachedChainId = block.chainid;
        _cachedDomainSeparator = _buildDomainSeparator();
    }

    /// @dev The EIP-712 domain: (chainId, verifyingContract, capabilityHash). Recomputed on demand.
    function _buildDomainSeparator() private view returns (bytes32) {
        return keccak256(abi.encode(DOMAIN_TYPEHASH, block.chainid, _cachedThis, _capabilityHash));
    }

    /// @notice Binds every signature to THIS deployment + capability (EIP-712 domain): a signature for a
    /// claim here can never be replayed on another chain, contract, or capability. Returns the cached
    /// value only while `block.chainid` is unchanged; after a chainId-changing fork it rebuilds, so a
    /// pre-fork signature is invalid on the forked chain (no cross-fork replay).
    function domainSeparator() public view returns (bytes32) {
        return block.chainid == _cachedChainId ? _cachedDomainSeparator : _buildDomainSeparator();
    }

    /// @notice The EIP-712 digest the observers sign for a given claim. Domain-separated (chain +
    /// contract + capability) and bound to the replay key `claimId`, so a signature can be counted only
    /// for THIS claim on THIS deployment. `canonicalClaimHash` is keccak256 of the canonicalized evidence
    /// claim (the "exact" canonicalization of ); `executionClaim` is the  coordination-envelope
    /// digest. Co-signing both authenticates that the attested evidence justifies THAT execution — the
    /// observer↔guard parity point (slice 7): the rendered observers MUST sign exactly this digest.
    function claimDigest(bytes32 claimId, bytes32 canonicalClaimHash, bytes32 executionClaim)
        public
        view
        returns (bytes32)
    {
        bytes32 structHash =
            keccak256(abi.encode(CLAIM_TYPEHASH, claimId, canonicalClaimHash, executionClaim));
        return keccak256(abi.encodePacked("\x19\x01", domainSeparator(), structHash));
    }

    /// @notice Accept a claim iff at least M distinct authorized observers signed its digest.
    /// @dev `signatures` MUST be ordered by STRICTLY ASCENDING recovered signer address. That single
    /// invariant enforces distinctness with no per-call storage: a duplicate signer (or an out-of-order
    /// batch) breaks the strict ordering and reverts. An unknown signer reverts; an invalid signature
    /// recovers address(0)/a non-observer and reverts. Fires the acceptance exactly once, then locks the
    /// `claimId` against replay. Timeout/fallback (`abort | escalate`) is intentionally NOT encoded here
    /// — it is deferred until  settles the fallback semantics (see REVIEW_NOTES.md).
    function accept(
        bytes32 claimId,
        bytes32 canonicalClaimHash,
        bytes32 executionClaim,
        bytes[] calldata signatures
    ) external {
        if (accepted[claimId]) revert AlreadyAccepted(claimId);
        if (signatures.length < threshold) revert QuorumNotMet(signatures.length, threshold);

        bytes32 digest = claimDigest(claimId, canonicalClaimHash, executionClaim);
        address prev = address(0);
        for (uint256 i = 0; i < signatures.length; i++) {
            address signer = _recover(digest, signatures[i], i);
            if (!isObserver[signer]) revert UnauthorizedSigner(signer);
            if (signer <= prev) revert SignersNotStrictlyAscending(prev, signer);
            prev = signer;
        }
        // signatures.length >= threshold and every entry is a distinct authorized signer -> quorum met.
        accepted[claimId] = true;
        acceptedClaim[claimId] = canonicalClaimHash;
        acceptedExecutionClaim[claimId] = executionClaim;
        emit QuorumAccepted(claimId, digest, signatures.length);
    }

    /// @notice True once `claimId` has been accepted (idempotent read for downstream consumers).
    function isAccepted(bytes32 claimId) external view returns (bool) {
        return accepted[claimId];
    }

    /// @dev ecrecover with an EIP-2 low-s malleability guard and explicit v handling. Reverts on a
    /// malformed (non-65-byte) or malleable signature rather than silently recovering a wrong address.
    function _recover(bytes32 digest, bytes calldata sig, uint256 index) private pure returns (address) {
        if (sig.length != 65) revert MalformedSignature(index);
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(sig.offset)
            s := calldataload(add(sig.offset, 32))
            v := byte(0, calldataload(add(sig.offset, 64)))
        }
        // EIP-2: reject the high-s half to eliminate signature malleability.
        if (uint256(s) > 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0) {
            revert MalleableSignature(index);
        }
        if (v < 27) v += 27;
        return ecrecover(digest, v, r, s); // address(0) on an invalid signature -> not an observer -> revert
    }
}
)NEUSOL"
