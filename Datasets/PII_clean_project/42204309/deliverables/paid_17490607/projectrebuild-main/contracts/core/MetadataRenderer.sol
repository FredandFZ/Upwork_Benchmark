// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IMetadataRenderer} from "../interfaces/IMetadataRenderer.sol";
import {Base64} from "../libraries/Base64.sol";
import {Utils} from "../libraries/Utils.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title MetadataRenderer
 * @notice Generates dynamic on-chain metadata for NFTs
 * @dev Creates JSON metadata with referral stats, tickets, prizes, etc.
 */
contract MetadataRenderer is IMetadataRenderer, Ownable {
    /// @notice Base URI for images
    string public baseURI;

    /// @notice Base image URI (for referral code overlay)
    string public baseImageURI;

    /// @notice Contract that can update metadata
    address public metadataUpdater;

    /// @notice Interface to get NFT data
    address public nftContract;

    /// @notice Event emitted when metadata is updated
    event MetadataUpdated(uint256 indexed tokenId, uint256 timestamp);

    modifier onlyUpdater() {
        require(msg.sender == metadataUpdater || msg.sender == owner(), "Not authorized");
        _;
    }

    /**
     * @param _baseURI Base URI for metadata
     * @param _baseImageURI Base image URI
     * @param _nftContract NFT contract address
     * @param _metadataUpdater Address authorized to update metadata
     */
    constructor(
        string memory _baseURI,
        string memory _baseImageURI,
        address _nftContract,
        address _metadataUpdater
    ) Ownable(msg.sender) {
        require(_nftContract != address(0), "Invalid NFT contract");
        require(_metadataUpdater != address(0), "Invalid updater");
        baseURI = _baseURI;
        baseImageURI = _baseImageURI;
        nftContract = _nftContract;
        metadataUpdater = _metadataUpdater;
    }

    /**
     * @notice Generate token URI with dynamic metadata
     * @param tokenId Token ID
     * @return JSON metadata URI
     */
    function tokenURI(uint256 tokenId) external view override returns (string memory) {
        // Get NFT data from main contract
        (bool success, bytes memory data) = nftContract.staticcall(
            abi.encodeWithSignature("getNFTMetadata(uint256)", tokenId)
        );

        if (!success) {
            return _generateBasicMetadata(tokenId);
        }

        // Decode metadata
        (
            uint256 referralCode,
            uint256 totalReferralCount,
            uint256 smallBlockTicketCount,
            uint256 bigBlockTicketCount,
            uint256 referralEarnings,
            uint256 prizeEarnings,
            bool hasWonPrize,
            bool hasClaimedPrize
        ) = abi.decode(data, (uint256, uint256, uint256, uint256, uint256, uint256, bool, bool));

        // Generate image URI with referral code
        string memory imageURI = string(
            abi.encodePacked(baseImageURI, "/", Utils.toString(tokenId), ".png")
        );

        // Build attributes array
        string memory attributes = _buildAttributes(
            referralCode,
            totalReferralCount,
            smallBlockTicketCount,
            bigBlockTicketCount,
            referralEarnings,
            prizeEarnings,
            hasWonPrize,
            hasClaimedPrize
        );

        // Build JSON metadata
        string memory json = string(
            abi.encodePacked(
                '{"name":"Project Rebuild #',
                Utils.toString(tokenId),
                '","description":"Project Rebuild NFT with referral system and prize pools","image":"',
                imageURI,
                '","external_url":"',
                baseURI,
                '/',
                Utils.toString(tokenId),
                '","attributes":[',
                attributes,
                '],"properties":{"referral_code":"',
                Utils.toString(referralCode),
                '","total_referrals":"',
                Utils.toString(totalReferralCount),
                '","small_block_tickets":"',
                Utils.toString(smallBlockTicketCount),
                '","big_block_tickets":"',
                Utils.toString(bigBlockTicketCount),
                '","referral_earnings":"',
                Utils.toString(referralEarnings),
                '","prize_earnings":"',
                Utils.toString(prizeEarnings),
                '","has_won_prize":',
                hasWonPrize ? "true" : "false",
                ',"has_claimed_prize":',
                hasClaimedPrize ? "true" : "false",
                "}}"
            )
        );

        return string(
            abi.encodePacked("data:application/json;base64,", Base64.encode(bytes(json)))
        );
    }

    /**
     * @notice Build attributes array for metadata
     */
    function _buildAttributes(
        uint256 referralCode,
        uint256 totalReferralCount,
        uint256 smallBlockTicketCount,
        uint256 bigBlockTicketCount,
        uint256 referralEarnings,
        uint256 prizeEarnings,
        bool hasWonPrize,
        bool hasClaimedPrize
    ) internal pure returns (string memory) {
        string memory attr1 = string(
            abi.encodePacked(
                '{"trait_type":"Referral Code","value":"',
                Utils.toString(referralCode),
                '"}'
            )
        );
        string memory attr2 = string(
            abi.encodePacked(
                '{"trait_type":"Total Referrals","value":',
                Utils.toString(totalReferralCount),
                "}"
            )
        );
        string memory attr3 = string(
            abi.encodePacked(
                '{"trait_type":"Small Block Tickets","value":',
                Utils.toString(smallBlockTicketCount),
                "}"
            )
        );
        string memory attr4 = string(
            abi.encodePacked(
                '{"trait_type":"Big Block Tickets","value":',
                Utils.toString(bigBlockTicketCount),
                "}"
            )
        );
        string memory attr5 = string(
            abi.encodePacked(
                '{"trait_type":"Referral Earnings (USDC)","value":',
                Utils.toString(referralEarnings),
                "}"
            )
        );
        string memory attr6 = string(
            abi.encodePacked(
                '{"trait_type":"Prize Earnings (USDC)","value":',
                Utils.toString(prizeEarnings),
                "}"
            )
        );
        string memory attr7 = string(
            abi.encodePacked(
                '{"trait_type":"Prize Winner","value":',
                hasWonPrize ? "true" : "false",
                "}"
            )
        );

        return string(
            abi.encodePacked(attr1, ",", attr2, ",", attr3, ",", attr4, ",", attr5, ",", attr6, ",", attr7)
        );
    }

    /**
     * @notice Generate basic metadata if contract call fails
     */
    function _generateBasicMetadata(uint256 tokenId) internal view returns (string memory) {
        string memory json = string(
            abi.encodePacked(
                '{"name":"Project Rebuild #',
                Utils.toString(tokenId),
                '","description":"Project Rebuild NFT","image":"',
                baseImageURI,
                '/',
                Utils.toString(tokenId),
                '.png"}'
            )
        );

        return string(
            abi.encodePacked("data:application/json;base64,", Base64.encode(bytes(json)))
        );
    }

    /**
     * @notice Update metadata for a token (trigger refresh)
     * @param tokenId Token ID
     */
    function updateMetadata(uint256 tokenId) external override onlyUpdater {
        emit MetadataUpdated(tokenId, block.timestamp);
    }

    /**
     * @notice Set base URI
     * @param _baseURI New base URI
     */
    function setBaseURI(string memory _baseURI) external override onlyOwner {
        baseURI = _baseURI;
    }

    /**
     * @notice Set base image URI
     * @param _baseImageURI New base image URI
     */
    function setBaseImageURI(string memory _baseImageURI) external onlyOwner {
        baseImageURI = _baseImageURI;
    }

    /**
     * @notice Set metadata updater
     * @param _metadataUpdater New updater address
     */
    function setMetadataUpdater(address _metadataUpdater) external onlyOwner {
        require(_metadataUpdater != address(0), "Invalid updater");
        metadataUpdater = _metadataUpdater;
    }
}

