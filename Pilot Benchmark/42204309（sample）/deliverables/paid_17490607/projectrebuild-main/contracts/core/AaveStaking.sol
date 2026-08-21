// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAavePool} from "../interfaces/IAavePool.sol";
import {IUSDC} from "../interfaces/IUSDC.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title AaveStaking
 * @notice Manages optional Aave staking for prize pools
 * @dev Yield from staking goes to founder wallet
 */
contract AaveStaking is Ownable, ReentrancyGuard {
    /// @notice Aave lending pool
    IAavePool public aavePool;

    /// @notice USDC token
    IUSDC public usdc;

    /// @notice USDC aToken address (Aave interest-bearing token)
    address public aToken;

    /// @notice Founder wallet (receives yield)
    address public founderWallet;

    /// @notice Total amount staked in small pool
    uint256 public smallPoolStaked;

    /// @notice Total amount staked in big pool
    uint256 public bigPoolStaked;

    /// @notice Address that can stake/unstake (prize pool contract)
    address public stakingOperator;

    /// @notice Event emitted when funds are deposited to Aave
    event PoolDeposit(
        bool isBigPool,
        uint256 amount,
        uint256 timestamp
    );

    /// @notice Event emitted when funds are withdrawn from Aave
    event PoolWithdrawal(
        bool isBigPool,
        uint256 amount,
        uint256 timestamp
    );

    modifier onlyOperator() {
        require(msg.sender == stakingOperator, "Not authorized");
        _;
    }

    /**
     * @param _aavePool Aave lending pool address
     * @param _usdc USDC token address
     * @param _aToken Aave aToken address for USDC
     * @param _founderWallet Founder wallet address
     * @param _stakingOperator Address authorized to stake/unstake
     */
    constructor(
        address _aavePool,
        address _usdc,
        address _aToken,
        address _founderWallet,
        address _stakingOperator
    ) Ownable(msg.sender) {
        require(_aavePool != address(0), "Invalid Aave pool");
        require(_usdc != address(0), "Invalid USDC");
        require(_aToken != address(0), "Invalid aToken");
        require(_founderWallet != address(0), "Invalid founder");
        require(_stakingOperator != address(0), "Invalid operator");

        aavePool = IAavePool(_aavePool);
        usdc = IUSDC(_usdc);
        aToken = _aToken;
        founderWallet = _founderWallet;
        stakingOperator = _stakingOperator;
    }

    /**
     * @notice Deposit USDC to Aave for small pool
     * @param amount Amount to deposit (6 decimals)
     */
    function depositSmallPool(uint256 amount) external onlyOperator nonReentrant {
        require(amount > 0, "Invalid amount");
        require(usdc.balanceOf(address(this)) >= amount, "Insufficient balance");

        // Approve Aave
        require(usdc.approve(address(aavePool), amount), "Approve failed");

        // Supply to Aave
        aavePool.supply(address(usdc), amount, address(this), 0);

        smallPoolStaked += amount;

        emit PoolDeposit(false, amount, block.timestamp);
    }

    /**
     * @notice Deposit USDC to Aave for big pool
     * @param amount Amount to deposit (6 decimals)
     */
    function depositBigPool(uint256 amount) external onlyOperator nonReentrant {
        require(amount > 0, "Invalid amount");
        require(usdc.balanceOf(address(this)) >= amount, "Insufficient balance");

        // Approve Aave
        require(usdc.approve(address(aavePool), amount), "Approve failed");

        // Supply to Aave
        aavePool.supply(address(usdc), amount, address(this), 0);

        bigPoolStaked += amount;

        emit PoolDeposit(true, amount, block.timestamp);
    }

    /**
     * @notice Withdraw USDC from Aave for small pool
     * @param amount Amount to withdraw (6 decimals)
     */
    function withdrawSmallPool(uint256 amount) external onlyOperator nonReentrant {
        require(amount > 0, "Invalid amount");
        require(smallPoolStaked >= amount, "Insufficient staked");

        // Withdraw from Aave
        aavePool.withdraw(address(usdc), amount, address(this));

        smallPoolStaked -= amount;

        emit PoolWithdrawal(false, amount, block.timestamp);
    }

    /**
     * @notice Withdraw USDC from Aave for big pool
     * @param amount Amount to withdraw (6 decimals)
     */
    function withdrawBigPool(uint256 amount) external onlyOperator nonReentrant {
        require(amount > 0, "Invalid amount");
        require(bigPoolStaked >= amount, "Insufficient staked");

        // Withdraw from Aave
        aavePool.withdraw(address(usdc), amount, address(this));

        bigPoolStaked -= amount;

        emit PoolWithdrawal(true, amount, block.timestamp);
    }

    /**
     * @notice Get total staked amount (small + big)
     * @return Total staked
     */
    function getTotalStaked() external view returns (uint256) {
        return smallPoolStaked + bigPoolStaked;
    }

    /**
     * @notice Get available balance (not staked)
     * @return Available balance
     */
    function getAvailableBalance() external view returns (uint256) {
        return usdc.balanceOf(address(this));
    }

    /**
     * @notice Update Aave pool address
     * @param _aavePool New Aave pool address
     */
    function setAavePool(address _aavePool) external onlyOwner {
        require(_aavePool != address(0), "Invalid pool");
        aavePool = IAavePool(_aavePool);
    }

    /**
     * @notice Update founder wallet
     * @param _founderWallet New founder wallet
     */
    function setFounderWallet(address _founderWallet) external onlyOwner {
        require(_founderWallet != address(0), "Invalid founder");
        founderWallet = _founderWallet;
    }

    /**
     * @notice Update staking operator
     * @param _stakingOperator New operator address
     */
    function setStakingOperator(address _stakingOperator) external onlyOwner {
        require(_stakingOperator != address(0), "Invalid operator");
        stakingOperator = _stakingOperator;
    }

    /**
     * @notice Withdraw yield to founder wallet
     * @dev Can be called by owner to claim accumulated yield
     */
    function withdrawYield() external onlyOwner nonReentrant {
        uint256 aTokenBalance = IUSDC(aToken).balanceOf(address(this));
        uint256 totalStaked = smallPoolStaked + bigPoolStaked;

        if (aTokenBalance > totalStaked) {
            uint256 yield = aTokenBalance - totalStaked;
            // Withdraw yield from Aave
            aavePool.withdraw(address(usdc), yield, founderWallet);
        }
    }
}

