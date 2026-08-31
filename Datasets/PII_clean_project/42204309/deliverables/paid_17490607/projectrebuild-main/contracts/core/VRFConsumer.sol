// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IVRFCoordinator} from "../interfaces/IVRFCoordinator.sol";
import {IVRFConsumerBaseV2} from "../interfaces/IVRFConsumerBaseV2.sol";
import {Structs} from "../libraries/Structs.sol";
import {VRFErrors} from "../errors/VRFErrors.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title VRFConsumer
 * @notice Handles Chainlink VRF requests for random number generation
 * @dev Supports random referral selection, small block draws, and big block draws
 * @dev Simplified version for testing - uses interfaces instead of full Chainlink contracts
 */
contract VRFConsumer is IVRFConsumerBaseV2, Ownable {
    /// @notice VRF Coordinator interface
    IVRFCoordinator public vrfCoordinator;

    /// @notice VRF subscription ID
    uint256 public subscriptionId;

    /// @notice Key hash for VRF
    bytes32 public keyHash;

    /// @notice Callback gas limit
    uint32 public callbackGasLimit;

    /// @notice Minimum request confirmations
    uint16 public minimumRequestConfirmations;

    /// @notice Number of words to request (5 for draws, 1 for referral)
    uint32 public constant NUM_WORDS_DRAW = 5;
    uint32 public constant NUM_WORDS_REFERRAL = 1;

    /// @notice Mapping from request ID to request data
    mapping(uint256 => Structs.VRFRequestData) public vrfRequests;

    /// @notice Address that can request VRF (main NFT contract)
    address public vrfRequester;

    /// @notice Event emitted when VRF is requested
    event VRFRequested(
        uint256 indexed requestId,
        Structs.VRFRequestType requestType,
        uint256 timestamp
    );

    /// @notice Event emitted when VRF is fulfilled
    event VRFFulfilled(
        uint256 indexed requestId,
        uint256[] randomWords,
        Structs.VRFRequestType requestType
    );

    modifier onlyRequester() {
        require(msg.sender == vrfRequester, "Not authorized");
        _;
    }

    /**
     * @param _vrfCoordinator VRF Coordinator address
     * @param _subscriptionId VRF subscription ID
     * @param _keyHash Key hash for VRF
     * @param _callbackGasLimit Callback gas limit
     * @param _minimumRequestConfirmations Minimum request confirmations
     * @param _vrfRequester Address authorized to request VRF
     */
    constructor(
        address _vrfCoordinator,
        uint256 _subscriptionId,
        bytes32 _keyHash,
        uint32 _callbackGasLimit,
        uint16 _minimumRequestConfirmations,
        address _vrfRequester
    ) Ownable(msg.sender) {
        require(_vrfCoordinator != address(0), "Invalid coordinator");
        require(_vrfRequester != address(0), "Invalid requester");
        vrfCoordinator = VRFCoordinatorV2_5Interface(_vrfCoordinator);
        subscriptionId = _subscriptionId;
        keyHash = _keyHash;
        callbackGasLimit = _callbackGasLimit;
        minimumRequestConfirmations = _minimumRequestConfirmations;
        vrfRequester = _vrfRequester;
    }

    /**
     * @notice Request random words for a draw
     * @param requestType Type of VRF request
     * @return requestId VRF request ID
     */
    function requestRandomWords(
        Structs.VRFRequestType requestType
    ) external onlyRequester returns (uint256 requestId) {
        uint32 numWords = (requestType == Structs.VRFRequestType.RANDOM_REFERRAL)
            ? NUM_WORDS_REFERRAL
            : NUM_WORDS_DRAW;

        requestId = vrfCoordinator.requestRandomWords(
            VRFV2PlusClient.RandomWordsRequest({
                keyHash: keyHash,
                subId: subscriptionId,
                requestConfirmations: minimumRequestConfirmations,
                callbackGasLimit: callbackGasLimit,
                numWords: numWords,
                extraArgs: VRFV2PlusClient._argsToBytes(
                    VRFV2PlusClient.ExtraArgsV1({nativePayment: false})
                )
            })
        );

        vrfRequests[requestId] = Structs.VRFRequestData({
            requestId: requestId,
            requestType: requestType,
            timestamp: block.timestamp,
            fulfilled: false,
            randomWords: new uint256[](0)
        });

        emit VRFRequested(requestId, requestType, block.timestamp);
        return requestId;
    }

    /**
     * @notice Callback function called by VRF Coordinator
     * @param requestId Request ID
     * @param randomWords Array of random words
     */
    function rawFulfillRandomWords(
        uint256 requestId,
        uint256[] memory randomWords
    ) external override {
        require(msg.sender == address(vrfCoordinator), "Only coordinator");
        _fulfillRandomWords(requestId, randomWords);
    }

    /**
     * @notice Internal function to fulfill random words
     */
    function _fulfillRandomWords(
        uint256 requestId,
        uint256[] memory randomWords
    ) internal {
        Structs.VRFRequestData storage request = vrfRequests[requestId];
        require(!request.fulfilled, "Already fulfilled");
        require(request.requestId == requestId, "Invalid request");

        request.fulfilled = true;
        request.randomWords = randomWords;

        emit VRFFulfilled(requestId, randomWords, request.requestType);
    }

    /**
     * @notice Get VRF request data
     * @param requestId Request ID
     * @return Request data struct
     */
    function getVRFRequest(
        uint256 requestId
    ) external view returns (Structs.VRFRequestData memory) {
        return vrfRequests[requestId];
    }

    /**
     * @notice Update VRF parameters
     * @param _keyHash New key hash
     * @param _callbackGasLimit New callback gas limit
     * @param _minimumRequestConfirmations New minimum confirmations
     */
    function updateVRFParams(
        bytes32 _keyHash,
        uint32 _callbackGasLimit,
        uint16 _minimumRequestConfirmations
    ) external onlyOwner {
        keyHash = _keyHash;
        callbackGasLimit = _callbackGasLimit;
        minimumRequestConfirmations = _minimumRequestConfirmations;
    }

    /**
     * @notice Update subscription ID
     * @param _subscriptionId New subscription ID
     */
    function setSubscriptionId(uint256 _subscriptionId) external onlyOwner {
        subscriptionId = _subscriptionId;
    }

    /**
     * @notice Update VRF requester
     * @param _vrfRequester New requester address
     */
    function setVRFRequester(address _vrfRequester) external onlyOwner {
        require(_vrfRequester != address(0), "Invalid requester");
        vrfRequester = _vrfRequester;
    }
}

