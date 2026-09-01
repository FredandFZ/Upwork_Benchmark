// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @notice Executable model of the currently reconstructed contract-facing configuration.
contract ProjectStateModel {
    uint256 public constant FEATURE_COUNT = 40;
    uint256 public constant MINT_PRICE_USD = 15;
    uint256 public constant FOUNDER_SHARE_USD = 5;
    uint256 public constant COMMISSION_USD = 5;
    uint256 public constant SMALL_PRIZE_USD = 500;
    uint256 public constant SALES_PER_DRAW = 100;
    bool public constant BIG_BLOCK_ENABLED = false;
    bool public constant MANUAL_PRIZE_CLAIM = false;
    bytes32 public constant CONFIGURATION_DIGEST =
        hex"ab6b82221de97971fcdafbc540e6ef3391c406cf3e7cd0d7faa34cf15df1d7b6";

    function isReferralCodeValid(uint256 code, uint256 mintedSupply) external pure returns (bool) {
        return code > 0 && code <= mintedSupply;
    }
}
