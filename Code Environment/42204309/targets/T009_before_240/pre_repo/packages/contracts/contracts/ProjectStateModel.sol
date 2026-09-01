// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @notice Executable model of the currently reconstructed contract-facing configuration.
contract ProjectStateModel {
    uint256 public constant FEATURE_COUNT = 36;
    uint256 public constant MINT_PRICE_USD = 15;
    uint256 public constant FOUNDER_SHARE_USD = 5;
    uint256 public constant COMMISSION_USD = 5;
    uint256 public constant SMALL_PRIZE_USD = 500;
    uint256 public constant SALES_PER_DRAW = 100;
    bool public constant BIG_BLOCK_ENABLED = false;
    bool public constant MANUAL_PRIZE_CLAIM = false;
    bytes32 public constant CONFIGURATION_DIGEST =
        hex"86fa61a9ace5fd9a9118016023b6c45cda64ece959f3b06babdb1c59931bd640";

    function isReferralCodeValid(uint256 code, uint256 mintedSupply) external pure returns (bool) {
        return code > 0 && code <= mintedSupply;
    }
}
