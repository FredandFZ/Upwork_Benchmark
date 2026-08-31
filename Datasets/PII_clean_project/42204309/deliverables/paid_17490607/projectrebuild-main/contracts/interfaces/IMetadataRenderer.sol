// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title IMetadataRenderer
 * @notice Interface for dynamic metadata generation
 */
interface IMetadataRenderer {
    function tokenURI(uint256 tokenId) external view returns (string memory);
    function updateMetadata(uint256 tokenId) external;
    function setBaseURI(string memory baseURI) external;
}

