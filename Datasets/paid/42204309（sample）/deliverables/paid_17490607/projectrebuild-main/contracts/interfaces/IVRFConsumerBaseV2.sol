// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title IVRFConsumerBaseV2
 * @notice Minimal interface for VRF Consumer Base V2
 * @dev Simplified version for testing - replace with actual Chainlink contracts in production
 */
abstract contract IVRFConsumerBaseV2 {
    function rawFulfillRandomWords(uint256 requestId, uint256[] memory randomWords) external virtual;
}

