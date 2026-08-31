// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title MintErrors
 * @notice Custom errors for minting operations
 */
error InsufficientPayment();
error InvalidReferral(uint256 referralCode);
error ReferralNotFound(uint256 tokenId);
error MintPaused();
error TransferFailed();

