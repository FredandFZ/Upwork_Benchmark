// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IAavePool} from "../interfaces/IAavePool.sol";
import {IUSDC} from "../interfaces/IUSDC.sol";

/**
 * @title MockAavePool
 * @notice Mock Aave pool for testing
 */
contract MockAavePool is IAavePool {
    mapping(address => mapping(address => uint256)) private _supplies; // asset => user => amount
    mapping(address => uint256) private _totalSupplies; // asset => total

    function supply(
        address asset,
        uint256 amount,
        address onBehalfOf,
        uint16
    ) external override {
        require(IUSDC(asset).transferFrom(msg.sender, address(this), amount), "Transfer failed");
        _supplies[asset][onBehalfOf] += amount;
        _totalSupplies[asset] += amount;
    }

    function withdraw(
        address asset,
        uint256 amount,
        address to
    ) external override returns (uint256) {
        require(_supplies[asset][msg.sender] >= amount, "Insufficient supply");
        _supplies[asset][msg.sender] -= amount;
        _totalSupplies[asset] -= amount;
        require(IUSDC(asset).transfer(to, amount), "Transfer failed");
        return amount;
    }

    function getReserveData(address) external pure override returns (
        uint256,
        uint256,
        uint256,
        uint256,
        uint256,
        uint256,
        uint256,
        uint256,
        uint256,
        uint40
    ) {
        return (0, 0, 0, 0, 0, 0, 0, 0, 0, 0);
    }

    function getSupply(address asset, address user) external view returns (uint256) {
        return _supplies[asset][user];
    }
}

