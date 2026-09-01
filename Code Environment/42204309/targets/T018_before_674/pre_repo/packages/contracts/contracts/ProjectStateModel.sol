// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @notice Executable model of the currently reconstructed contract-facing configuration.
contract ProjectStateModel {
    uint256 public constant FEATURE_COUNT = 51;
    uint256 public constant MINT_PRICE_USD = 15;
    uint256 public constant FOUNDER_SHARE_USD = 5;
    uint256 public constant COMMISSION_USD = 5;
    uint256 public constant SMALL_PRIZE_USD = 500;
    uint256 public constant SALES_PER_DRAW = 100;
    bool public constant BIG_BLOCK_ENABLED = false;
    bool public constant MANUAL_PRIZE_CLAIM = false;
    bytes32 public constant CONFIGURATION_DIGEST =
        hex"0a483cec2dff2cf036e001e7666872b9b45d0da249238255b84d3ac0d11ce9b5";

    function isReferralCodeValid(uint256 code, uint256 mintedSupply) external pure returns (bool) {
        return code > 0 && code <= mintedSupply;
    }
}
