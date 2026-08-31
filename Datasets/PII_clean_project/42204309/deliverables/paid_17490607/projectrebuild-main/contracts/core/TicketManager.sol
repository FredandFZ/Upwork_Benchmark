// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ITicketManager} from "../interfaces/ITicketManager.sol";
import {TicketErrors} from "../errors/TicketErrors.sol";
import {Structs} from "../libraries/Structs.sol";

/**
 * @title TicketManager
 * @notice Manages ticket storage and operations for NFTs
 * @dev Tickets are stored per NFT token ID, not per wallet
 */
contract TicketManager is ITicketManager {
    /// @notice Mapping from token ID to ticket data
    mapping(uint256 => Structs.TicketData) private _tickets;

    /// @notice Total small block tickets across all NFTs
    uint256 private _totalSmallBlockTickets;

    /// @notice Total big block tickets across all NFTs
    uint256 private _totalBigBlockTickets;

    /// @notice Array of token IDs that have tickets (for efficient iteration)
    uint256[] private _ticketHolders;

    /// @notice Mapping to track if a token ID is in the holders array
    mapping(uint256 => bool) private _isInHoldersArray;

    /// @notice Address that can award tickets (main NFT contract)
    address public ticketAwarder;

    /// @notice Event emitted when tickets are awarded
    event TicketsAwarded(
        uint256 indexed tokenId,
        uint256 smallBlockTickets,
        uint256 bigBlockTickets
    );

    /// @notice Event emitted when all tickets are reset
    event AllTicketsReset(uint256 timestamp);

    modifier onlyAwarder() {
        require(msg.sender == ticketAwarder, "Not authorized");
        _;
    }

    /**
     * @param _ticketAwarder Address authorized to award tickets
     */
    constructor(address _ticketAwarder) {
        require(_ticketAwarder != address(0), "Invalid awarder");
        ticketAwarder = _ticketAwarder;
    }

    /**
     * @notice Award tickets to a specific NFT
     * @param tokenId Token ID to award tickets to
     * @param smallTickets Number of small block tickets
     * @param bigTickets Number of big block tickets
     */
    function awardTickets(
        uint256 tokenId,
        uint256 smallTickets,
        uint256 bigTickets
    ) external override onlyAwarder {
        if (smallTickets > 0 || bigTickets > 0) {
            _tickets[tokenId].smallBlockTickets += smallTickets;
            _tickets[tokenId].bigBlockTickets += bigTickets;
            _tickets[tokenId].totalSmallBlockTicketsEarned += smallTickets;
            _tickets[tokenId].totalBigBlockTicketsEarned += bigTickets;

            _totalSmallBlockTickets += smallTickets;
            _totalBigBlockTickets += bigTickets;

            // Add to holders array if not already present
            if (!_isInHoldersArray[tokenId]) {
                _ticketHolders.push(tokenId);
                _isInHoldersArray[tokenId] = true;
            }

            emit TicketsAwarded(tokenId, smallTickets, bigTickets);
        }
    }

    /**
     * @notice Get small block tickets for a token
     * @param tokenId Token ID
     * @return Number of small block tickets
     */
    function getSmallBlockTickets(uint256 tokenId) external view override returns (uint256) {
        return _tickets[tokenId].smallBlockTickets;
    }

    /**
     * @notice Get big block tickets for a token
     * @param tokenId Token ID
     * @return Number of big block tickets
     */
    function getBigBlockTickets(uint256 tokenId) external view override returns (uint256) {
        return _tickets[tokenId].bigBlockTickets;
    }

    /**
     * @notice Get full ticket data for a token
     * @param tokenId Token ID
     * @return Ticket data struct
     */
    function getTicketData(uint256 tokenId) external view returns (Structs.TicketData memory) {
        return _tickets[tokenId];
    }

    /**
     * @notice Reset all tickets to zero (called after block draws)
     */
    function resetAllTickets() external override onlyAwarder {
        uint256 length = _ticketHolders.length;
        for (uint256 i = 0; i < length; i++) {
            uint256 tokenId = _ticketHolders[i];
            _tickets[tokenId].smallBlockTickets = 0;
            _tickets[tokenId].bigBlockTickets = 0;
        }

        _totalSmallBlockTickets = 0;
        _totalBigBlockTickets = 0;

        // Clear holders array
        delete _ticketHolders;
        // Note: We don't clear _isInHoldersArray mapping to save gas on future resets

        emit AllTicketsReset(block.timestamp);
    }

    /**
     * @notice Get total small block tickets across all NFTs
     * @return Total small block tickets
     */
    function getTotalSmallBlockTickets() external view override returns (uint256) {
        return _totalSmallBlockTickets;
    }

    /**
     * @notice Get total big block tickets across all NFTs
     * @return Total big block tickets
     */
    function getTotalBigBlockTickets() external view override returns (uint256) {
        return _totalBigBlockTickets;
    }

    /**
     * @notice Get all token IDs that have tickets
     * @return Array of token IDs
     */
    function getTicketHolders() external view override returns (uint256[] memory) {
        return _ticketHolders;
    }

    /**
     * @notice Update the ticket awarder address
     * @param newAwarder New awarder address
     */
    function setTicketAwarder(address newAwarder) external {
        require(msg.sender == ticketAwarder, "Not authorized");
        require(newAwarder != address(0), "Invalid awarder");
        ticketAwarder = newAwarder;
    }
}

