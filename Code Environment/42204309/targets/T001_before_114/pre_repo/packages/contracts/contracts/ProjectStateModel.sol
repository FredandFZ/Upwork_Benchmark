// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @notice Executable model of the currently reconstructed contract-facing configuration.
contract ProjectStateModel {
    uint256 public constant FEATURE_COUNT = 18;
    uint256 public constant MINT_PRICE_USD = 0;
    uint256 public constant FOUNDER_SHARE_USD = 0;
    uint256 public constant COMMISSION_USD = 5;
    uint256 public constant SMALL_PRIZE_USD = 500;
    uint256 public constant SALES_PER_DRAW = 0;
    bool public constant BIG_BLOCK_ENABLED = true;
    bool public constant MANUAL_PRIZE_CLAIM = true;
    bytes32 public constant CONFIGURATION_DIGEST =
        hex"ce093bbcb7c16bc8238412f49e370c23b9f3714e6837871e7dfd618ef6c40c2f";

    function isReferralCodeValid(uint256 code, uint256 mintedSupply) external pure returns (bool) {
        return code > 0 && code <= mintedSupply;
    }
}
