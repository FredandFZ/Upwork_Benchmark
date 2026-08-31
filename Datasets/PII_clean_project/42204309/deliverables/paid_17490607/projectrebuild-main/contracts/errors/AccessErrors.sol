// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title AccessErrors
 * @notice Custom errors for access control
 */
error Unauthorized();
error NotOwner();
error NotAdmin();
error Paused();

