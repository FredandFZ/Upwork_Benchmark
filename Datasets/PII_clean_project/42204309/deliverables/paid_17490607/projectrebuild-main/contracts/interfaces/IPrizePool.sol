// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title IPrizePool
 * @notice Interface for prize pool management
 */
interface IPrizePool {
    function addToSmallPool(uint256 amount) external returns (bool);
    function addToBigPool(uint256 amount) external returns (bool);
    function getSmallPoolBalance() external view returns (uint256);
    function getBigPoolBalance() external view returns (uint256);
    function processSmallBlockWinners(uint256[] memory winners) external;
    function processBigBlockWinners(uint256[] memory winners) external;
    function claimPrize(uint256 tokenId) external returns (uint256);
    function getPendingPrize(uint256 tokenId) external view returns (uint256);
}

