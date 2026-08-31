// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {EnvironmentProbe} from "../contracts/EnvironmentProbe.sol";

/// @notice Dependency-free Foundry smoke test.
contract EnvironmentSmokeTest {
    function testEnvironmentProbeCanBeCreated() public {
        EnvironmentProbe probe = new EnvironmentProbe();
        require(address(probe).code.length > 0, "environment deployment failed");
    }
}
