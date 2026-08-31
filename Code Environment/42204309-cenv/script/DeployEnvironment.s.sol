// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {EnvironmentProbe} from "../contracts/EnvironmentProbe.sol";

/// @notice Minimal deployment entry point for environment verification.
contract DeployEnvironment {
    function run() external returns (EnvironmentProbe probe) {
        probe = new EnvironmentProbe();
    }
}
