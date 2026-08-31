// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ERC721C} from "./ERC721C.sol";
import {TicketManager} from "./TicketManager.sol";
import {PrizePool} from "./PrizePool.sol";
import {VRFConsumer} from "./VRFConsumer.sol";
import {AaveStaking} from "./AaveStaking.sol";
import {MetadataRenderer} from "./MetadataRenderer.sol";
import {IUSDC} from "../interfaces/IUSDC.sol";
import {Structs} from "../libraries/Structs.sol";
import {MintErrors} from "../errors/MintErrors.sol";
import {PoolErrors} from "../errors/PoolErrors.sol";
import {VRFErrors} from "../errors/VRFErrors.sol";
import {Pausable} from "@openzeppelin/contracts/utils/Pausable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/**
 * @title ProjectRebuildNFT
 * @notice Main NFT contract for Project Rebuild with referral system and prize pools
 * @dev Integrates all modules: tickets, prizes, VRF, Aave, metadata
 */
contract ProjectRebuildNFT is ERC721C, Pausable, ReentrancyGuard {
    /// @notice Mint price: $15 USDC (6 decimals)
    uint256 public constant MINT_PRICE = 15_000_000; // $15 in 6 decimals

    /// @notice Referral commission: $5 USDC (6 decimals)
    uint256 public constant REFERRAL_COMMISSION = 5_000_000; // $5 in 6 decimals

    /// @notice Small pool allocation: $5 USDC (6 decimals)
    uint256 public constant SMALL_POOL_ALLOCATION = 5_000_000; // $5 in 6 decimals

    /// @notice Big pool allocation: $1 USDC (6 decimals)
    uint256 public constant BIG_POOL_ALLOCATION = 1_000_000; // $1 in 6 decimals

    /// @notice Founder allocation: $4 USDC (6 decimals)
    uint256 public constant FOUNDER_ALLOCATION = 4_000_000; // $4 in 6 decimals

    /// @notice Secondary sale royalty: $10 USDC (6 decimals)
    uint256 public constant SECONDARY_ROYALTY = 10_000_000; // $10 in 6 decimals

    /// @notice USDC token contract
    IUSDC public usdc;

    /// @notice Ticket manager contract
    TicketManager public ticketManager;

    /// @notice Prize pool contract
    PrizePool public prizePool;

    /// @notice VRF consumer contract
    VRFConsumer public vrfConsumer;

    /// @notice Aave staking contract (optional)
    AaveStaking public aaveStaking;

    /// @notice Metadata renderer contract
    MetadataRenderer public metadataRenderer;

    /// @notice Founder wallet
    address public founderWallet;

    /// @notice Current token ID counter
    uint256 private _tokenIdCounter;

    /// @notice Mapping from token ID to referral data
    mapping(uint256 => Structs.ReferralData) private _referralData;

    /// @notice Mapping from VRF request ID to pending action
    mapping(uint256 => PendingVRFAction) private _pendingVRFActions;

    /// @notice Pending VRF action structure
    struct PendingVRFAction {
        Structs.VRFRequestType requestType;
        uint256 timestamp;
        bool processed;
    }

    /// @notice Event emitted when NFT is minted
    event Mint(
        uint256 indexed tokenId,
        address indexed to,
        uint256 referralCode,
        uint256 timestamp
    );

    /// @notice Event emitted when referral is used
    event ReferralUsed(
        uint256 indexed tokenId,
        uint256 indexed referralCode,
        address indexed referrer,
        uint256 commission
    );

    /// @notice Event emitted when random referral is rewarded
    event RandomReferralReward(
        uint256 indexed tokenId,
        address indexed recipient,
        uint256 commission,
        uint256 vrfRequestId
    );

    /// @notice Event emitted when secondary sale royalty is paid
    event SecondaryRoyaltyPaid(
        uint256 indexed tokenId,
        uint256 amount,
        address indexed recipient
    );

    /**
     * @param _usdc USDC token address
     * @param _founderWallet Founder wallet address
     * @param _royaltyBps Royalty in basis points (e.g., 667 = 6.67% for $10 on $150)
     */
    constructor(
        address _usdc,
        address _founderWallet,
        uint256 _royaltyBps
    ) ERC721C("Project Rebuild", "REBUILD", _royaltyBps, _founderWallet) {
        require(_usdc != address(0), "Invalid USDC");
        require(_founderWallet != address(0), "Invalid founder");
        usdc = IUSDC(_usdc);
        founderWallet = _founderWallet;
        _tokenIdCounter = 1; // Start from token ID 1
    }

    /**
     * @notice Initialize contracts (called after deployment)
     * @param _ticketManager Ticket manager address
     * @param _prizePool Prize pool address
     * @param _vrfConsumer VRF consumer address
     * @param _metadataRenderer Metadata renderer address
     * @param _aaveStaking Aave staking address (optional, can be address(0))
     */
    function initialize(
        address _ticketManager,
        address _prizePool,
        address _vrfConsumer,
        address _metadataRenderer,
        address _aaveStaking
    ) external onlyOwner {
        require(_ticketManager != address(0), "Invalid ticket manager");
        require(_prizePool != address(0), "Invalid prize pool");
        require(_vrfConsumer != address(0), "Invalid VRF consumer");
        require(_metadataRenderer != address(0), "Invalid metadata renderer");

        ticketManager = TicketManager(_ticketManager);
        prizePool = PrizePool(_prizePool);
        vrfConsumer = VRFConsumer(_vrfConsumer);
        metadataRenderer = MetadataRenderer(_metadataRenderer);
        if (_aaveStaking != address(0)) {
            aaveStaking = AaveStaking(_aaveStaking);
        }
    }

    /**
     * @notice Mint NFT with optional referral code
     * @param to Address to mint to
     * @param referralCode Referral code (token ID of referrer, 0 = no referral)
     */
    function mint(address to, uint256 referralCode) external whenNotPaused nonReentrant {
        require(to != address(0), "Invalid recipient");

        // Check payment
        require(usdc.balanceOf(msg.sender) >= MINT_PRICE, "Insufficient USDC");
        require(
            usdc.allowance(msg.sender, address(this)) >= MINT_PRICE,
            "Insufficient allowance"
        );

        // Transfer USDC payment
        require(
            usdc.transferFrom(msg.sender, address(this), MINT_PRICE),
            "Payment failed"
        );

        // Mint NFT
        uint256 tokenId = _tokenIdCounter++;
        _safeMint(to, tokenId);

        // Process referral and payment split
        _processMintPayment(tokenId, referralCode);

        // Update metadata
        metadataRenderer.updateMetadata(tokenId);

        emit Mint(tokenId, to, referralCode, block.timestamp);
    }

    /**
     * @notice Process payment split and referral logic
     * @param tokenId Newly minted token ID
     * @param referralCode Referral code (0 = no referral)
     */
    function _processMintPayment(uint256 tokenId, uint256 referralCode) internal {
        if (referralCode > 0 && referralCode < tokenId && _ownerOf(referralCode) != address(0)) {
            // Valid referral code provided
            _processReferral(tokenId, referralCode);
        } else {
            // No referral or invalid referral - use random selection
            _processRandomReferral(tokenId);
        }

        // Allocate to pools
        require(
            usdc.transfer(address(prizePool), SMALL_POOL_ALLOCATION + BIG_POOL_ALLOCATION),
            "Pool transfer failed"
        );

        // Add to pools
        bool smallTriggered = prizePool.addToSmallPool(SMALL_POOL_ALLOCATION);
        prizePool.addToBigPool(BIG_POOL_ALLOCATION);

        // Check if small block should trigger
        if (smallTriggered) {
            _triggerSmallBlock();
        }

        // Check big block
        if (prizePool.getBigPoolBalance() >= PrizePool.BIG_BLOCK_TARGET) {
            _triggerBigBlock();
        }

        // Transfer founder allocation
        require(usdc.transfer(founderWallet, FOUNDER_ALLOCATION), "Founder transfer failed");
    }

    /**
     * @notice Process referral commission
     * @param tokenId Newly minted token ID
     * @param referralCode Referral token ID
     */
    function _processReferral(uint256 tokenId, uint256 referralCode) internal {
        address referrer = _ownerOf(referralCode);
        require(referrer != address(0), "Invalid referrer");

        // Transfer commission to referrer
        require(
            usdc.transfer(referrer, REFERRAL_COMMISSION),
            "Referral transfer failed"
        );

        // Award tickets to referrer's NFT
        ticketManager.awardTickets(referralCode, 1, 1);

        // Update referral data
        _referralData[referralCode].totalReferralCount++;
        _referralData[referralCode].totalReferralEarnings += REFERRAL_COMMISSION;
        _referralData[referralCode].lastReferralTimestamp = block.timestamp;

        emit ReferralUsed(tokenId, referralCode, referrer, REFERRAL_COMMISSION);
    }

    /**
     * @notice Process random referral selection via VRF
     * @param tokenId Newly minted token ID
     */
    function _processRandomReferral(uint256 tokenId) internal {
        // Request VRF for random referral
        uint256 requestId = vrfConsumer.requestRandomWords(
            Structs.VRFRequestType.RANDOM_REFERRAL
        );

        _pendingVRFActions[requestId] = PendingVRFAction({
            requestType: Structs.VRFRequestType.RANDOM_REFERRAL,
            timestamp: block.timestamp,
            processed: false
        });

        // Store commission for later distribution
        // Note: Commission is held in contract until VRF fulfills
    }

    /**
     * @notice Process fulfilled VRF request for random referral
     * @param requestId VRF request ID
     */
    function processRandomReferral(uint256 requestId) external {
        Structs.VRFRequestData memory vrfRequest = vrfConsumer.getVRFRequest(requestId);
        require(vrfRequest.fulfilled, "VRF not fulfilled");
        require(
            vrfRequest.requestType == Structs.VRFRequestType.RANDOM_REFERRAL,
            "Invalid request type"
        );
        require(vrfRequest.randomWords.length > 0, "No random words");

        PendingVRFAction storage action = _pendingVRFActions[requestId];
        require(!action.processed, "Already processed");

        action.processed = true;

        uint256 randomWord = vrfRequest.randomWords[0];

        // Get total supply to select random NFT
        uint256 totalSupply = totalSupply();
        if (totalSupply == 0) {
            // No NFTs exist yet, send to founder
            require(usdc.transfer(founderWallet, REFERRAL_COMMISSION), "Transfer failed");
            return;
        }

        // Select random NFT (1-indexed)
        uint256 randomTokenId = (randomWord % totalSupply) + 1;

        // Verify token exists
        if (_ownerOf(randomTokenId) == address(0)) {
            // Fallback to founder if token doesn't exist
            require(usdc.transfer(founderWallet, REFERRAL_COMMISSION), "Transfer failed");
            return;
        }

        address recipient = _ownerOf(randomTokenId);

        // Transfer commission
        require(usdc.transfer(recipient, REFERRAL_COMMISSION), "Transfer failed");

        // Award tickets
        ticketManager.awardTickets(randomTokenId, 1, 1);

        // Update referral data
        _referralData[randomTokenId].totalReferralCount++;
        _referralData[randomTokenId].totalReferralEarnings += REFERRAL_COMMISSION;
        _referralData[randomTokenId].lastReferralTimestamp = block.timestamp;

        emit RandomReferralReward(randomTokenId, recipient, REFERRAL_COMMISSION, requestId);
    }

    /**
     * @notice Process fulfilled VRF request for block draw
     * @param requestId VRF request ID
     */
    function processBlockDraw(uint256 requestId) external {
        Structs.VRFRequestData memory vrfRequest = vrfConsumer.getVRFRequest(requestId);
        require(vrfRequest.fulfilled, "VRF not fulfilled");
        require(
            vrfRequest.requestType == Structs.VRFRequestType.SMALL_BLOCK_DRAW ||
                vrfRequest.requestType == Structs.VRFRequestType.BIG_BLOCK_DRAW,
            "Invalid request type"
        );
        require(vrfRequest.randomWords.length == 5, "Invalid random words count");

        PendingVRFAction storage action = _pendingVRFActions[requestId];
        require(!action.processed, "Already processed");

        action.processed = true;

        // Get ticket holders
        uint256[] memory holders = ticketManager.getTicketHolders();
        uint256 totalTickets = (vrfRequest.requestType == Structs.VRFRequestType.SMALL_BLOCK_DRAW)
            ? ticketManager.getTotalSmallBlockTickets()
            : ticketManager.getTotalBigBlockTickets();

        if (totalTickets == 0 || holders.length == 0) {
            // No tickets, reset pool and return
            if (vrfRequest.requestType == Structs.VRFRequestType.SMALL_BLOCK_DRAW) {
                prizePool.processSmallBlockWinners(new uint256[](5)); // Empty winners
            } else {
                prizePool.processBigBlockWinners(new uint256[](5)); // Empty winners
            }
            ticketManager.resetAllTickets();
            return;
        }

        // Select 5 winners using weighted random selection
        uint256[] memory winners = new uint256[](5);
        uint256[] memory usedIndices = new uint256[](5);
        uint256 usedCount = 0;

        for (uint256 i = 0; i < 5; i++) {
            uint256 randomValue = vrfRequest.randomWords[i] % totalTickets;
            uint256 cumulative = 0;
            bool found = false;

            for (uint256 j = 0; j < holders.length && !found; j++) {
                // Check if already selected
                bool alreadyUsed = false;
                for (uint256 k = 0; k < usedCount; k++) {
                    if (usedIndices[k] == j) {
                        alreadyUsed = true;
                        break;
                    }
                }
                if (alreadyUsed) continue;

                uint256 tickets = (vrfRequest.requestType == Structs.VRFRequestType.SMALL_BLOCK_DRAW)
                    ? ticketManager.getSmallBlockTickets(holders[j])
                    : ticketManager.getBigBlockTickets(holders[j]);

                cumulative += tickets;
                if (randomValue < cumulative) {
                    winners[i] = holders[j];
                    usedIndices[usedCount++] = j;
                    found = true;
                }
            }

            // Fallback if no winner found
            if (!found && holders.length > 0) {
                winners[i] = holders[0];
            }
        }

        // Process winners
        if (vrfRequest.requestType == Structs.VRFRequestType.SMALL_BLOCK_DRAW) {
            prizePool.processSmallBlockWinners(winners);
        } else {
            prizePool.processBigBlockWinners(winners);
        }

        // Reset tickets
        ticketManager.resetAllTickets();
    }

    /**
     * @notice Trigger small block draw
     */
    function _triggerSmallBlock() internal {
        // Request VRF for small block draw
        uint256 requestId = vrfConsumer.requestRandomWords(
            Structs.VRFRequestType.SMALL_BLOCK_DRAW
        );

        _pendingVRFActions[requestId] = PendingVRFAction({
            requestType: Structs.VRFRequestType.SMALL_BLOCK_DRAW,
            timestamp: block.timestamp,
            processed: false
        });
    }

    /**
     * @notice Trigger big block draw
     */
    function _triggerBigBlock() internal {
        // Request VRF for big block draw
        uint256 requestId = vrfConsumer.requestRandomWords(
            Structs.VRFRequestType.BIG_BLOCK_DRAW
        );

        _pendingVRFActions[requestId] = PendingVRFAction({
            requestType: Structs.VRFRequestType.BIG_BLOCK_DRAW,
            timestamp: block.timestamp,
            processed: false
        });
    }

    /**
     * @notice Handle secondary sale royalty payment
     * @param tokenId Token ID
     * @param salePrice Sale price in USDC
     */
    function payRoyalty(uint256 tokenId, uint256 salePrice) external nonReentrant {
        uint256 royaltyAmount = calculateRoyalty(salePrice);
        require(royaltyAmount >= SECONDARY_ROYALTY, "Royalty too low");

        // Transfer royalty payment
        require(
            usdc.transferFrom(msg.sender, address(this), SECONDARY_ROYALTY),
            "Royalty payment failed"
        );

        // Split secondary royalty (no referral commission)
        // $5 to small pool, $1 to big pool, $4 to founder
        require(
            usdc.transfer(address(prizePool), SMALL_POOL_ALLOCATION + BIG_POOL_ALLOCATION),
            "Pool transfer failed"
        );

        prizePool.addToSmallPool(SMALL_POOL_ALLOCATION);
        prizePool.addToBigPool(BIG_POOL_ALLOCATION);

        require(usdc.transfer(founderWallet, FOUNDER_ALLOCATION), "Founder transfer failed");

        emit SecondaryRoyaltyPaid(tokenId, SECONDARY_ROYALTY, royaltyRecipient);
    }

    /**
     * @notice Get NFT metadata
     * @param tokenId Token ID
     * @return Referral code, total referrals, small tickets, big tickets, referral earnings, prize earnings, has won, has claimed
     */
    function getNFTMetadata(
        uint256 tokenId
    )
        external
        view
        returns (
            uint256,
            uint256,
            uint256,
            uint256,
            uint256,
            uint256,
            bool,
            bool
        )
    {
        require(_ownerOf(tokenId) != address(0), "Token does not exist");

        uint256 referralCode = tokenId; // Referral code = token ID
        uint256 totalReferrals = _referralData[tokenId].totalReferralCount;
        uint256 smallTickets = ticketManager.getSmallBlockTickets(tokenId);
        uint256 bigTickets = ticketManager.getBigBlockTickets(tokenId);
        uint256 referralEarnings = _referralData[tokenId].totalReferralEarnings;
        uint256 prizeEarnings = prizePool.getPendingPrize(tokenId);
        bool hasWon = prizePool.getPendingPrize(tokenId) > 0;
        bool hasClaimed = false; // Can be enhanced with claim tracking

        return (
            referralCode,
            totalReferrals,
            smallTickets,
            bigTickets,
            referralEarnings,
            prizeEarnings,
            hasWon,
            hasClaimed
        );
    }

    /**
     * @notice Override tokenURI to use metadata renderer
     */
    function tokenURI(uint256 tokenId) public view override returns (string memory) {
        require(_ownerOf(tokenId) != address(0), "Token does not exist");
        return metadataRenderer.tokenURI(tokenId);
    }

    /**
     * @notice Claim prize for a token
     * @param tokenId Token ID
     */
    function claimPrize(uint256 tokenId) external nonReentrant {
        require(_ownerOf(tokenId) == msg.sender, "Not token owner");
        prizePool.claimPrize(tokenId);
        metadataRenderer.updateMetadata(tokenId);
    }

    // ============ ADMIN FUNCTIONS ============

    /**
     * @notice Pause minting
     */
    function pause() external onlyOwner {
        _pause();
    }

    /**
     * @notice Unpause minting
     */
    function unpause() external onlyOwner {
        _unpause();
    }

    /**
     * @notice Set USDC contract address
     */
    function setUSDC(address _usdc) external onlyOwner {
        require(_usdc != address(0), "Invalid USDC");
        usdc = IUSDC(_usdc);
    }

    /**
     * @notice Set founder wallet
     */
    function setFounderWallet(address _founderWallet) external onlyOwner {
        require(_founderWallet != address(0), "Invalid founder");
        founderWallet = _founderWallet;
        royaltyRecipient = _founderWallet;
    }

    /**
     * @notice Rescue tokens (excluding USDC from pools)
     */
    function rescueTokens(address token, uint256 amount) external onlyOwner {
        require(token != address(usdc), "Cannot rescue USDC");
        require(IUSDC(token).transfer(owner(), amount), "Transfer failed");
    }

    /**
     * @notice Override _update to support pausable
     */
    function _update(
        address to,
        uint256 tokenId,
        address auth
    ) internal virtual override(ERC721C) whenNotPaused returns (address) {
        return super._update(to, tokenId, auth);
    }
}

