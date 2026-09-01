// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import { Environment } from "../contracts/Environment.sol";

contract EnvironmentSmoke {
    function testDeploysMinimalContract() public {
        Environment instance = new Environment();
        assert(address(instance) != address(0));
        assert(address(instance).code.length > 0);
    }
}
