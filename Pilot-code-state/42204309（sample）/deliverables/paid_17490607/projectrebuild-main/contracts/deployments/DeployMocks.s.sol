// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {MockUSDC} from "../mocks/MockUSDC.sol";
import {MockVRFCoordinator} from "../mocks/MockVRFCoordinator.sol";
import {MockAavePool} from "../mocks/MockAavePool.sol";

/**
 * @title DeployMocks
 * @notice Deploy mock contracts for local testing
 */
contract DeployMocks is Script {
    function run() external {
        vm.startBroadcast();

        console.log("Deploying mock contracts...");

        MockUSDC usdc = new MockUSDC();
        console.log("MockUSDC deployed at:", address(usdc));

        MockVRFCoordinator vrfCoordinator = new MockVRFCoordinator();
        console.log("MockVRFCoordinator deployed at:", address(vrfCoordinator));

        MockAavePool aavePool = new MockAavePool();
        console.log("MockAavePool deployed at:", address(aavePool));

        console.log("Mock deployment complete!");

        vm.stopBroadcast();
    }
}

