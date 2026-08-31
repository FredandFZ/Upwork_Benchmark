// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC721} from "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import {ERC721Enumerable} from "@openzeppelin/contracts/token/ERC721/extensions/ERC721Enumerable.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title ERC721C
 * @notice ERC721 with creator-controlled royalty enforcement (ERC-721C standard)
 * @dev Extends ERC721Enumerable with royalty enforcement capabilities
 */
contract ERC721C is ERC721, ERC721Enumerable, Ownable, ReentrancyGuard {
    /// @notice Royalty percentage (in basis points, e.g., 1000 = 10%)
    uint256 public royaltyBps;

    /// @notice Royalty recipient (founder wallet)
    address public royaltyRecipient;

    /// @notice Mapping to track if a marketplace is authorized
    mapping(address => bool) public authorizedMarketplaces;

    /// @notice Event emitted when royalty is paid
    event RoyaltyPaid(
        uint256 indexed tokenId,
        address indexed recipient,
        uint256 amount,
        address currency
    );

    /// @notice Event emitted when marketplace authorization is updated
    event MarketplaceAuthorizationUpdated(address indexed marketplace, bool authorized);

    /**
     * @param name Token name
     * @param symbol Token symbol
     * @param _royaltyBps Royalty in basis points (e.g., 1000 = 10%)
     * @param _royaltyRecipient Address to receive royalties
     */
    constructor(
        string memory name,
        string memory symbol,
        uint256 _royaltyBps,
        address _royaltyRecipient
    ) ERC721(name, symbol) Ownable(msg.sender) {
        require(_royaltyBps <= 10000, "Royalty exceeds 100%");
        require(_royaltyRecipient != address(0), "Invalid recipient");
        royaltyBps = _royaltyBps;
        royaltyRecipient = _royaltyRecipient;
    }

    /**
     * @notice Calculate royalty amount
     * @param salePrice Sale price in USDC
     * @return royaltyAmount Royalty amount in USDC
     */
    function calculateRoyalty(uint256 salePrice) public view returns (uint256 royaltyAmount) {
        return (salePrice * royaltyBps) / 10000;
    }

    /**
     * @notice Get royalty info for a token
     * @param tokenId Token ID
     * @param salePrice Sale price
     * @return receiver Royalty recipient
     * @return royaltyAmount Royalty amount
     */
    function royaltyInfo(
        uint256 tokenId,
        uint256 salePrice
    ) external view returns (address receiver, uint256 royaltyAmount) {
        receiver = royaltyRecipient;
        royaltyAmount = calculateRoyalty(salePrice);
    }

    /**
     * @notice Authorize or deauthorize a marketplace
     * @param marketplace Marketplace address
     * @param authorized Authorization status
     */
    function setMarketplaceAuthorization(address marketplace, bool authorized) external onlyOwner {
        authorizedMarketplaces[marketplace] = authorized;
        emit MarketplaceAuthorizationUpdated(marketplace, authorized);
    }

    /**
     * @notice Update royalty recipient
     * @param newRecipient New royalty recipient address
     */
    function setRoyaltyRecipient(address newRecipient) external onlyOwner {
        require(newRecipient != address(0), "Invalid recipient");
        royaltyRecipient = newRecipient;
    }

    /**
     * @notice Update royalty percentage
     * @param newBps New royalty in basis points
     */
    function setRoyaltyBps(uint256 newBps) external onlyOwner {
        require(newBps <= 10000, "Royalty exceeds 100%");
        royaltyBps = newBps;
    }

    /**
     * @notice Override supportsInterface for ERC721Enumerable
     */
    function supportsInterface(
        bytes4 interfaceId
    ) public view virtual override(ERC721, ERC721Enumerable) returns (bool) {
        return super.supportsInterface(interfaceId);
    }

    /**
     * @notice Override _update for ERC721Enumerable
     */
    function _update(
        address to,
        uint256 tokenId,
        address auth
    ) internal virtual override(ERC721, ERC721Enumerable) returns (address) {
        return super._update(to, tokenId, auth);
    }
}

