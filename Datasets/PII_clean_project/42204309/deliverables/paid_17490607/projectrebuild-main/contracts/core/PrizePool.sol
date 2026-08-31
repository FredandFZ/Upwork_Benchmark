// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IPrizePool} from "../interfaces/IPrizePool.sol";
import {IUSDC} from "../interfaces/IUSDC.sol";
import {PoolErrors} from "../errors/PoolErrors.sol";
import {PrizeErrors} from "../errors/PrizeErrors.sol";
import {Structs} from "../libraries/Structs.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title PrizePool
 * @notice Manages small and big block prize pools
 * @dev Handles pool accumulation, triggering draws, and prize claiming
 */
contract PrizePool is IPrizePool, ReentrancyGuard, Ownable {
    /// @notice USDC token contract
    IUSDC public usdc;

    /// @notice Small block target: $2,500 (6 decimals)
    uint256 public constant SMALL_BLOCK_TARGET = 2_500_000_000; // $2,500 in 6 decimals

    /// @notice Big block target: $100,000 (6 decimals)
    uint256 public constant BIG_BLOCK_TARGET = 100_000_000_000; // $100,000 in 6 decimals

    /// @notice Small block prize per winner: $500 (6 decimals)
    uint256 public constant SMALL_BLOCK_PRIZE = 500_000_000; // $500 in 6 decimals

    /// @notice Big block prize per winner: $20,000 (6 decimals)
    uint256 public constant BIG_BLOCK_PRIZE = 20_000_000_000; // $20,000 in 6 decimals

    /// @notice Number of winners per block draw
    uint256 public constant WINNERS_PER_DRAW = 5;

    /// @notice Pool data
    Structs.PoolData public poolData;

    /// @notice Mapping from token ID to pending prize amount
    mapping(uint256 => uint256) private _pendingPrizes;

    /// @notice Mapping from token ID to prize history
    mapping(uint256 => Structs.PrizeData[]) private _prizeHistory;

    /// @notice Address that can trigger pool operations (main NFT contract)
    address public poolOperator;

    /// @notice Event emitted when funds are added to small pool
    event SmallPoolFundsAdded(uint256 amount, uint256 newTotal);

    /// @notice Event emitted when funds are added to big pool
    event BigPoolFundsAdded(uint256 amount, uint256 newTotal);

    /// @notice Event emitted when small block is triggered
    event SmallBlockTriggered(uint256 timestamp, uint256 poolAmount);

    /// @notice Event emitted when big block is triggered
    event BigBlockTriggered(uint256 timestamp, uint256 poolAmount);

    /// @notice Event emitted when a prize is won
    event PrizeWon(
        uint256 indexed tokenId,
        Structs.PrizeType prizeType,
        uint256 amount,
        uint256 blockNumber
    );

    /// @notice Event emitted when a prize is claimed
    event PrizeClaimed(uint256 indexed tokenId, uint256 amount);

    modifier onlyOperator() {
        require(msg.sender == poolOperator, "Not authorized");
        _;
    }

    /**
     * @param _usdc USDC token address
     * @param _poolOperator Address authorized to operate pools
     */
    constructor(address _usdc, address _poolOperator) Ownable(msg.sender) {
        require(_usdc != address(0), "Invalid USDC");
        require(_poolOperator != address(0), "Invalid operator");
        usdc = IUSDC(_usdc);
        poolOperator = _poolOperator;
    }

    /**
     * @notice Add funds to small block pool
     * @param amount Amount to add (in USDC 6 decimals)
     * @return triggered True if pool reached target and should trigger draw
     */
    function addToSmallPool(uint256 amount) external override onlyOperator returns (bool triggered) {
        require(amount > 0, "Invalid amount");
        poolData.smallBlockPool += amount;
        poolData.smallBlockTotalCollected += amount;

        emit SmallPoolFundsAdded(amount, poolData.smallBlockPool);

        // Check if target reached
        if (poolData.smallBlockPool >= SMALL_BLOCK_TARGET) {
            emit SmallBlockTriggered(block.timestamp, poolData.smallBlockPool);
            return true;
        }
        return false;
    }

    /**
     * @notice Add funds to big block pool
     * @param amount Amount to add (in USDC 6 decimals)
     * @return triggered True if pool reached target and should trigger draw
     */
    function addToBigPool(uint256 amount) external override onlyOperator returns (bool triggered) {
        require(amount > 0, "Invalid amount");
        poolData.bigBlockPool += amount;
        poolData.bigBlockTotalCollected += amount;

        emit BigPoolFundsAdded(amount, poolData.bigBlockPool);

        // Check if target reached
        if (poolData.bigBlockPool >= BIG_BLOCK_TARGET) {
            emit BigBlockTriggered(block.timestamp, poolData.bigBlockPool);
            return true;
        }
        return false;
    }

    /**
     * @notice Process small block winners after VRF draw
     * @param winners Array of winning token IDs (can be empty if no tickets)
     */
    function processSmallBlockWinners(
        uint256[] memory winners
    ) external override onlyOperator {
        require(winners.length == WINNERS_PER_DRAW || winners.length == 0, "Invalid winner count");
        require(poolData.smallBlockPool >= SMALL_BLOCK_TARGET, "Pool not ready");

        if (winners.length == 0) {
            // No winners, just reset pool
            poolData.smallBlockPool = 0;
            poolData.smallBlockDraws++;
            return;
        }

        // Award prizes
        for (uint256 i = 0; i < winners.length; i++) {
            uint256 tokenId = winners[i];
            _pendingPrizes[tokenId] += SMALL_BLOCK_PRIZE;

            Structs.PrizeData memory prize = Structs.PrizeData({
                tokenId: tokenId,
                prizeAmount: SMALL_BLOCK_PRIZE,
                blockNumber: block.number,
                timestamp: block.timestamp,
                claimed: false,
                prizeType: Structs.PrizeType.SMALL_BLOCK
            });

            _prizeHistory[tokenId].push(prize);

            emit PrizeWon(tokenId, Structs.PrizeType.SMALL_BLOCK, SMALL_BLOCK_PRIZE, block.number);
        }

        // Reset pool
        poolData.smallBlockPool = 0;
        poolData.smallBlockDraws++;
    }

    /**
     * @notice Process big block winners after VRF draw
     * @param winners Array of winning token IDs (can be empty if no tickets)
     */
    function processBigBlockWinners(uint256[] memory winners) external override onlyOperator {
        require(winners.length == WINNERS_PER_DRAW || winners.length == 0, "Invalid winner count");
        require(poolData.bigBlockPool >= BIG_BLOCK_TARGET, "Pool not ready");

        if (winners.length == 0) {
            // No winners, just reset pool
            poolData.bigBlockPool = 0;
            poolData.bigBlockDraws++;
            return;
        }

        // Award prizes
        for (uint256 i = 0; i < winners.length; i++) {
            uint256 tokenId = winners[i];
            _pendingPrizes[tokenId] += BIG_BLOCK_PRIZE;

            Structs.PrizeData memory prize = Structs.PrizeData({
                tokenId: tokenId,
                prizeAmount: BIG_BLOCK_PRIZE,
                blockNumber: block.number,
                timestamp: block.timestamp,
                claimed: false,
                prizeType: Structs.PrizeType.BIG_BLOCK
            });

            _prizeHistory[tokenId].push(prize);

            emit PrizeWon(tokenId, Structs.PrizeType.BIG_BLOCK, BIG_BLOCK_PRIZE, block.number);
        }

        // Reset pool
        poolData.bigBlockPool = 0;
        poolData.bigBlockDraws++;
    }

    /**
     * @notice Claim pending prize for a token
     * @param tokenId Token ID to claim prize for
     * @return amount Claimed amount
     */
    function claimPrize(
        uint256 tokenId
    ) external override nonReentrant returns (uint256 amount) {
        amount = _pendingPrizes[tokenId];
        if (amount == 0) {
            revert PrizeErrors.NothingToClaim();
        }

        _pendingPrizes[tokenId] = 0;

        // Mark latest unclaimed prize as claimed
        Structs.PrizeData[] storage history = _prizeHistory[tokenId];
        for (uint256 i = history.length; i > 0; i--) {
            if (!history[i - 1].claimed) {
                history[i - 1].claimed = true;
                break;
            }
        }

        // Transfer USDC to token owner
        require(usdc.transfer(msg.sender, amount), "Transfer failed");

        emit PrizeClaimed(tokenId, amount);
        return amount;
    }

    /**
     * @notice Get pending prize for a token
     * @param tokenId Token ID
     * @return Pending prize amount
     */
    function getPendingPrize(uint256 tokenId) external view override returns (uint256) {
        return _pendingPrizes[tokenId];
    }

    /**
     * @notice Get prize history for a token
     * @param tokenId Token ID
     * @return Array of prize data
     */
    function getPrizeHistory(
        uint256 tokenId
    ) external view returns (Structs.PrizeData[] memory) {
        return _prizeHistory[tokenId];
    }

    /**
     * @notice Get small pool balance
     * @return Current small pool balance
     */
    function getSmallPoolBalance() external view override returns (uint256) {
        return poolData.smallBlockPool;
    }

    /**
     * @notice Get big pool balance
     * @return Current big pool balance
     */
    function getBigPoolBalance() external view override returns (uint256) {
        return poolData.bigBlockPool;
    }

    /**
     * @notice Update pool operator
     * @param newOperator New operator address
     */
    function setPoolOperator(address newOperator) external onlyOwner {
        require(newOperator != address(0), "Invalid operator");
        poolOperator = newOperator;
    }
}

