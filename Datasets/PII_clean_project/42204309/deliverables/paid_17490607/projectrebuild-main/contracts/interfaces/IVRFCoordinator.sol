// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title IVRFCoordinator
 * @notice Interface for Chainlink VRF Coordinator V2.5
 */
interface IVRFCoordinator {
    function requestRandomWords(
        bytes32 keyHash,
        uint256 subId,
        uint16 minimumRequestConfirmations,
        uint32 callbackGasLimit,
        uint32 numWords
    ) external returns (uint256 requestId);

    function getRequestConfig() external view returns (
        uint16 minimumRequestConfirmations,
        uint32 maxGasLimit,
        bytes32[] memory s_provingKeyHashes
    );
}

