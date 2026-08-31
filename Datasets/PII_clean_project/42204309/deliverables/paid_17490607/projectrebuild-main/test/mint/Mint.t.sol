// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {ProjectRebuildNFT} from "../../contracts/core/ProjectRebuildNFT.sol";
import {TicketManager} from "../../contracts/core/TicketManager.sol";
import {PrizePool} from "../../contracts/core/PrizePool.sol";
import {VRFConsumer} from "../../contracts/core/VRFConsumer.sol";
import {MetadataRenderer} from "../../contracts/core/MetadataRenderer.sol";
import {MockUSDC} from "../../contracts/mocks/MockUSDC.sol";
import {MockVRFCoordinator} from "../../contracts/mocks/MockVRFCoordinator.sol";

contract MintTest is Test {
    ProjectRebuildNFT public nft;
    TicketManager public ticketManager;
    PrizePool public prizePool;
    VRFConsumer public vrfConsumer;
    MetadataRenderer public metadataRenderer;
    MockUSDC public usdc;
    MockVRFCoordinator public vrfCoordinator;

    address public founder = address(0x1);
    address public user1 = address(0x2);
    address public user2 = address(0x3);

    uint256 public constant MINT_PRICE = 15_000_000; // $15

    function setUp() public {
        // Deploy mocks
        usdc = new MockUSDC();
        vrfCoordinator = new MockVRFCoordinator();

        // Mint USDC to users
        usdc.mint(user1, 1000_000_000); // $1000
        usdc.mint(user2, 1000_000_000); // $1000

        // Deploy main NFT contract
        nft = new ProjectRebuildNFT(address(usdc), founder, 667); // 6.67% royalty

        // Deploy supporting contracts
        ticketManager = new TicketManager(address(nft));
        prizePool = new PrizePool(address(usdc), address(nft));
        vrfConsumer = new VRFConsumer(
            address(vrfCoordinator),
            1, // subscription ID
            bytes32(uint256(1)), // key hash
            500000, // callback gas limit
            3, // confirmations
            address(nft)
        );
        metadataRenderer = new MetadataRenderer(
            "https://api.projectrebuild.com/metadata/",
            "https://api.projectrebuild.com/images/",
            address(nft),
            address(nft)
        );

        // Initialize NFT contract
        nft.initialize(
            address(ticketManager),
            address(prizePool),
            address(vrfConsumer),
            address(metadataRenderer),
            address(0) // no Aave for now
        );

        // Approve USDC
        vm.prank(user1);
        usdc.approve(address(nft), type(uint256).max);
        vm.prank(user2);
        usdc.approve(address(nft), type(uint256).max);
    }

    function testMintWithoutReferral() public {
        vm.prank(user1);
        nft.mint(user1, 0); // No referral

        assertEq(nft.balanceOf(user1), 1);
        assertEq(nft.ownerOf(1), user1);
    }

    function testMintWithReferral() public {
        // First mint (no referral)
        vm.prank(user1);
        nft.mint(user1, 0);

        // Second mint with referral code 1
        vm.prank(user2);
        nft.mint(user2, 1);

        // Check tickets awarded to token 1
        assertEq(ticketManager.getSmallBlockTickets(1), 1);
        assertEq(ticketManager.getBigBlockTickets(1), 1);

        // Check referral data
        (uint256 referralCode, uint256 totalReferrals, , , uint256 referralEarnings, , , ) = nft
            .getNFTMetadata(1);
        assertEq(referralCode, 1);
        assertEq(totalReferrals, 1);
        assertEq(referralEarnings, 5_000_000); // $5 commission
    }

    function testPaymentSplit() public {
        uint256 balanceBefore = usdc.balanceOf(address(prizePool));

        vm.prank(user1);
        nft.mint(user1, 0);

        // Check pool allocations
        assertEq(prizePool.getSmallPoolBalance(), 5_000_000); // $5
        assertEq(prizePool.getBigPoolBalance(), 1_000_000); // $1
        assertEq(usdc.balanceOf(founder), 4_000_000); // $4
    }

    function testInvalidReferral() public {
        vm.prank(user1);
        nft.mint(user1, 0);

        // Try to mint with invalid referral (token doesn't exist)
        vm.prank(user2);
        nft.mint(user2, 999); // Should use random referral instead

        // Should still mint successfully
        assertEq(nft.balanceOf(user2), 1);
    }
}

