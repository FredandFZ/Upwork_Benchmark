// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IVRFCoordinator} from "../interfaces/IVRFCoordinator.sol";

/**
 * @title MockVRFCoordinator
 * @notice Mock VRF Coordinator for testing
 */
contract MockVRFCoordinator is IVRFCoordinator {
    uint256 private _requestIdCounter;
    mapping(uint256 => address) private _consumers;

    function requestRandomWords(
        bytes32 keyHash,
        uint256 subId,
        uint16 minimumRequestConfirmations,
        uint32 callbackGasLimit,
        uint32 numWords
    ) external override returns (uint256 requestId) {
        requestId = ++_requestIdCounter;
        _consumers[requestId] = msg.sender;
        return requestId;
    }

    function fulfillRequest(uint256 requestId, uint256[] memory randomWords) external {
        address consumer = _consumers[requestId];
        require(consumer != address(0), "Invalid request");

        // Call rawFulfillRandomWords on consumer
        (bool success, ) = consumer.call(
            abi.encodeWithSignature("rawFulfillRandomWords(uint256,uint256[])", requestId, randomWords)
        );
        require(success, "Fulfillment failed");
    }

    function getRequestConfig() external pure override returns (
        uint16 minimumRequestConfirmations,
        uint32 maxGasLimit,
        bytes32[] memory s_provingKeyHashes
    ) {
        return (3, 2_500_000, new bytes32[](0));
    }
}

