// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title ITicketManager
 * @notice Interface for ticket management system
 */
interface ITicketManager {
    function awardTickets(uint256 tokenId, uint256 smallTickets, uint256 bigTickets) external;
    function getSmallBlockTickets(uint256 tokenId) external view returns (uint256);
    function getBigBlockTickets(uint256 tokenId) external view returns (uint256);
    function resetAllTickets() external;
    function getTotalSmallBlockTickets() external view returns (uint256);
    function getTotalBigBlockTickets() external view returns (uint256);
    function getTicketHolders() external view returns (uint256[] memory);
}

