// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title Structs
 * @notice Shared data structures for Project Rebuild
 */

/// @notice Referral data for each NFT
struct ReferralData {
    uint256 totalReferralCount;
    uint256 totalReferralEarnings; // in USDC (6 decimals)
    uint256 lastReferralTimestamp;
}

/// @notice Ticket data for each NFT
struct TicketData {
    uint256 smallBlockTickets;
    uint256 bigBlockTickets;
    uint256 totalSmallBlockTicketsEarned; // lifetime
    uint256 totalBigBlockTicketsEarned; // lifetime
}

/// @notice Prize data for winners
struct PrizeData {
    uint256 tokenId;
    uint256 prizeAmount; // in USDC (6 decimals)
    uint256 blockNumber;
    uint256 timestamp;
    bool claimed;
    PrizeType prizeType;
}

/// @notice Pool data
struct PoolData {
    uint256 smallBlockPool; // target: $2,500
    uint256 bigBlockPool; // target: $100,000
    uint256 smallBlockTotalCollected; // lifetime
    uint256 bigBlockTotalCollected; // lifetime
    uint256 smallBlockDraws; // count
    uint256 bigBlockDraws; // count
}

/// @notice VRF request data
struct VRFRequestData {
    uint256 requestId;
    VRFRequestType requestType;
    uint256 timestamp;
    bool fulfilled;
    uint256[] randomWords;
}

/// @notice NFT metadata structure
struct NFTMetadata {
    uint256 tokenId;
    uint256 referralCode; // same as tokenId
    uint256 totalReferralCount;
    uint256 smallBlockTicketCount;
    uint256 bigBlockTicketCount;
    uint256 referralEarnings;
    uint256 prizeEarnings;
    bool hasWonPrize;
    bool hasClaimedPrize;
    string[] badges;
}

/// @notice Prize type enum
enum PrizeType {
    SMALL_BLOCK,
    BIG_BLOCK
}

/// @notice VRF request type enum
enum VRFRequestType {
    RANDOM_REFERRAL,
    SMALL_BLOCK_DRAW,
    BIG_BLOCK_DRAW
}

