// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {ProjectRebuildNFT} from "../../contracts/core/ProjectRebuildNFT.sol";
import {TicketManager} from "../../contracts/core/TicketManager.sol";
import {PrizePool} from "../../contracts/core/PrizePool.sol";
import {VRFConsumer} from "../../contracts/core/VRFConsumer.sol";
import {MetadataRenderer} from "../../contracts/core/MetadataRenderer.sol";
import {MockUSDC} from "../../contracts/mocks/MockUSDC.sol";
import {MockVRFCoordinator} from "../../contracts/mocks/MockVRFCoordinator.sol";

/**
 * @title Helpers
 * @notice Helper contract for test setup
 */
contract Helpers is Test {
    struct Contracts {
        ProjectRebuildNFT nft;
        TicketManager ticketManager;
        PrizePool prizePool;
        VRFConsumer vrfConsumer;
        MetadataRenderer metadataRenderer;
        MockUSDC usdc;
        MockVRFCoordinator vrfCoordinator;
    }

    function deployContracts() public returns (Contracts memory) {
        address founder = address(0x1);

        MockUSDC usdc = new MockUSDC();
        MockVRFCoordinator vrfCoordinator = new MockVRFCoordinator();

        ProjectRebuildNFT nft = new ProjectRebuildNFT(address(usdc), founder, 667);

        TicketManager ticketManager = new TicketManager(address(nft));
        PrizePool prizePool = new PrizePool(address(usdc), address(nft));
        VRFConsumer vrfConsumer = new VRFConsumer(
            address(vrfCoordinator),
            1,
            bytes32(uint256(1)),
            500000,
            3,
            address(nft)
        );
        MetadataRenderer metadataRenderer = new MetadataRenderer(
            "https://api.test.com/",
            "https://api.test.com/images/",
            address(nft),
            address(nft)
        );

        nft.initialize(
            address(ticketManager),
            address(prizePool),
            address(vrfConsumer),
            address(metadataRenderer),
            address(0)
        );

        return Contracts({
            nft: nft,
            ticketManager: ticketManager,
            prizePool: prizePool,
            vrfConsumer: vrfConsumer,
            metadataRenderer: metadataRenderer,
            usdc: usdc,
            vrfCoordinator: vrfCoordinator
        });
    }

    function setupUser(address user, uint256 usdcAmount, Contracts memory contracts) public {
        contracts.usdc.mint(user, usdcAmount);
        vm.prank(user);
        contracts.usdc.approve(address(contracts.nft), type(uint256).max);
    }
}

