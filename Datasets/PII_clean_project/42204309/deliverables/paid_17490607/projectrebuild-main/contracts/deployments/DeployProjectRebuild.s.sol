// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {ProjectRebuildNFT} from "../core/ProjectRebuildNFT.sol";
import {TicketManager} from "../core/TicketManager.sol";
import {PrizePool} from "../core/PrizePool.sol";
import {VRFConsumer} from "../core/VRFConsumer.sol";
import {MetadataRenderer} from "../core/MetadataRenderer.sol";
import {AaveStaking} from "../core/AaveStaking.sol";

/**
 * @title DeployProjectRebuild
 * @notice Deployment script for Project Rebuild contracts
 * @dev Deploys all contracts and initializes them
 */
contract DeployProjectRebuild is Script {
    // Base Sepolia addresses (for testing)
    address constant USDC_BASE_SEPOLIA = 0x036CbD53842c5426634e7929541eC2318f3dCF7e;
    address constant VRF_COORDINATOR_BASE_SEPOLIA = 0x9Ddf0Ca5b3b7F0E0C3bF7D31B0c19b3F82b0cE39;
    address constant AAVE_POOL_BASE_SEPOLIA = 0x4b529A5d8268d74B6a5b0C358741E3b5d2b2b3F3;

    // Base Mainnet addresses
    address constant USDC_BASE_MAINNET = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address constant VRF_COORDINATOR_BASE_MAINNET = 0x9Ddf0Ca5b3b7F0E0C3bF7D31B0c19b3F82b0cE39;
    address constant AAVE_POOL_BASE_MAINNET = 0xA238Dd80C259a72e81d7e4664a9801593F98d1c5;

    function run() external {
        uint256 deployerPrivateKey = vm.envUint("PRIVATE_KEY");
        address founderWallet = vm.envAddress("FOUNDER_WALLET");
        uint256 vrfSubscriptionId = vm.envUint("VRF_SUBSCRIPTION_ID");
        bytes32 vrfKeyHash = vm.envBytes32("VRF_KEY_HASH");
        string memory baseURI = vm.envString("BASE_URI");
        string memory baseImageURI = vm.envString("BASE_IMAGE_URI");

        // Determine network
        bool isMainnet = block.chainid == 8453; // Base mainnet
        address usdcAddress = isMainnet ? USDC_BASE_MAINNET : USDC_BASE_SEPOLIA;
        address vrfCoordinator = isMainnet
            ? VRF_COORDINATOR_BASE_MAINNET
            : VRF_COORDINATOR_BASE_SEPOLIA;
        address aavePool = isMainnet ? AAVE_POOL_BASE_MAINNET : AAVE_POOL_BASE_SEPOLIA;

        vm.startBroadcast(deployerPrivateKey);

        console.log("Deploying Project Rebuild contracts...");
        console.log("Network:", isMainnet ? "Base Mainnet" : "Base Sepolia");
        console.log("Founder Wallet:", founderWallet);

        // Deploy main NFT contract
        console.log("Deploying ProjectRebuildNFT...");
        ProjectRebuildNFT nft = new ProjectRebuildNFT(usdcAddress, founderWallet, 667); // 6.67% royalty
        console.log("ProjectRebuildNFT deployed at:", address(nft));

        // Deploy TicketManager
        console.log("Deploying TicketManager...");
        TicketManager ticketManager = new TicketManager(address(nft));
        console.log("TicketManager deployed at:", address(ticketManager));

        // Deploy PrizePool
        console.log("Deploying PrizePool...");
        PrizePool prizePool = new PrizePool(usdcAddress, address(nft));
        console.log("PrizePool deployed at:", address(prizePool));

        // Deploy VRFConsumer
        console.log("Deploying VRFConsumer...");
        VRFConsumer vrfConsumer = new VRFConsumer(
            vrfCoordinator,
            vrfSubscriptionId,
            vrfKeyHash,
            500000, // callback gas limit
            3, // minimum confirmations
            address(nft)
        );
        console.log("VRFConsumer deployed at:", address(vrfConsumer));

        // Deploy MetadataRenderer
        console.log("Deploying MetadataRenderer...");
        MetadataRenderer metadataRenderer = new MetadataRenderer(
            baseURI,
            baseImageURI,
            address(nft),
            address(nft)
        );
        console.log("MetadataRenderer deployed at:", address(metadataRenderer));

        // Deploy AaveStaking (optional)
        address aToken = vm.envAddress("AAVE_ATOKEN"); // aUSDC address
        AaveStaking aaveStaking = new AaveStaking(
            aavePool,
            usdcAddress,
            aToken,
            founderWallet,
            address(prizePool)
        );
        console.log("AaveStaking deployed at:", address(aaveStaking));

        // Initialize NFT contract
        console.log("Initializing ProjectRebuildNFT...");
        nft.initialize(
            address(ticketManager),
            address(prizePool),
            address(vrfConsumer),
            address(metadataRenderer),
            address(aaveStaking)
        );

        console.log("Deployment complete!");
        console.log("=== Contract Addresses ===");
        console.log("ProjectRebuildNFT:", address(nft));
        console.log("TicketManager:", address(ticketManager));
        console.log("PrizePool:", address(prizePool));
        console.log("VRFConsumer:", address(vrfConsumer));
        console.log("MetadataRenderer:", address(metadataRenderer));
        console.log("AaveStaking:", address(aaveStaking));

        vm.stopBroadcast();
    }
}

