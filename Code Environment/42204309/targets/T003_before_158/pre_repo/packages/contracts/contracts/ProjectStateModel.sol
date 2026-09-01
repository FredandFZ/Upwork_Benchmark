// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @notice Executable model of the currently reconstructed contract-facing configuration.
contract ProjectStateModel {
    uint256 public constant FEATURE_COUNT = 30;
    uint256 public constant MINT_PRICE_USD = 15;
    uint256 public constant FOUNDER_SHARE_USD = 4;
    uint256 public constant COMMISSION_USD = 5;
    uint256 public constant SMALL_PRIZE_USD = 500;
    uint256 public constant SALES_PER_DRAW = 500;
    bool public constant BIG_BLOCK_ENABLED = true;
    bool public constant MANUAL_PRIZE_CLAIM = true;
    bytes32 public constant CONFIGURATION_DIGEST =
        hex"acef1b2d410266e26abb220e949e45c4ff65b74af5059c4c6c47ed88cb051d33";

    function isReferralCodeValid(uint256 code, uint256 mintedSupply) external pure returns (bool) {
        return code > 0 && code <= mintedSupply;
    }
}
