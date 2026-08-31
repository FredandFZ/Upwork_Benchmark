// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title IUSDC
 * @notice Interface for USDC ERC20 token
 */
interface IUSDC {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
    function allowance(address owner, address spender) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function decimals() external view returns (uint8);
}

