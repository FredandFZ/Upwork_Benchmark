// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {ProjectRebuildNFT} from "../../contracts/core/ProjectRebuildNFT.sol";
import {TicketManager} from "../../contracts/core/TicketManager.sol";
import {PrizePool} from "../../contracts/core/PrizePool.sol";
import {MockUSDC} from "../../contracts/mocks/MockUSDC.sol";

contract SmallBlockTest is Test {
    ProjectRebuildNFT public nft;
    TicketManager public ticketManager;
    PrizePool public prizePool;
    MockUSDC public usdc;

    address public founder = address(0x1);
    address public user1 = address(0x2);
    address public user2 = address(0x3);

    function setUp() public {
        usdc = new MockUSDC();
        usdc.mint(user1, 1000_000_000);
        usdc.mint(user2, 1000_000_000);

        nft = new ProjectRebuildNFT(address(usdc), founder, 667);
        ticketManager = new TicketManager(address(nft));
        prizePool = new PrizePool(address(usdc), address(nft));

        // Initialize (simplified for test)
        vm.prank(user1);
        usdc.approve(address(nft), type(uint256).max);
        vm.prank(user2);
        usdc.approve(address(nft), type(uint256).max);
    }

    function testSmallBlockTrigger() public {
        // Mint 500 NFTs to reach $2,500 pool (500 * $5 = $2,500)
        for (uint256 i = 0; i < 500; i++) {
            vm.prank(user1);
            nft.mint(user1, 0);
        }

        // Check pool reached target
        assertGe(prizePool.getSmallPoolBalance(), 2_500_000_000); // $2,500
    }
}

