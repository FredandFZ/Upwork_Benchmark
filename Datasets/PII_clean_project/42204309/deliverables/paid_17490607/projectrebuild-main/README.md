# Project Rebuild - Smart Contracts

Production-ready, audited-level smart contracts for Project Rebuild NFT collection on Base chain.

## Overview

Project Rebuild is an ERC-721C NFT collection with:
- **Referral System**: NFT mint number = referral code
- **Prize Pools**: Small Block ($2,500) and Big Block ($100,000)
- **Chainlink VRF**: Random selection for referrals and prize draws
- **Aave Integration**: Optional staking for prize pools
- **Dynamic Metadata**: On-chain metadata with referral stats

## Contract Architecture

### Core Contracts

1. **ProjectRebuildNFT.sol** - Main NFT contract
   - ERC-721C with creator-controlled royalties
   - Minting with USDC payments
   - Referral system integration
   - Payment splitting logic

2. **TicketManager.sol** - Ticket management
   - Stores tickets per NFT (not per wallet)
   - Awards tickets on referrals
   - Resets tickets after draws

3. **PrizePool.sol** - Prize pool management
   - Small Block Pool: $2,500 target, 5 × $500 prizes
   - Big Block Pool: $100,000 target, 5 × $20,000 prizes
   - Prize claiming functionality

4. **VRFConsumer.sol** - Chainlink VRF integration
   - Random referral selection
   - Random winner selection for draws

5. **AaveStaking.sol** - Optional Aave staking
   - Deposit/withdraw USDC to Aave
   - Yield goes to founder wallet

6. **MetadataRenderer.sol** - Dynamic metadata generation
   - On-chain JSON metadata
   - Includes referral stats, tickets, prizes

### Payment Split

**Primary Mint ($15 USDC):**
- $5 → Referral commission (if referral used)
- $5 → Small Block Pool
- $1 → Big Block Pool
- $4 → Founder wallet

**Secondary Sale Royalty ($10 USDC):**
- $5 → Small Block Pool
- $1 → Big Block Pool
- $4 → Founder wallet
- No referral commission

## Features

### Referral System
- Referral code = NFT mint number (e.g., NFT #42 = code "42")
- When minting with referral:
  - Referrer receives $5 USDC commission
  - Referrer's NFT gets +1 Small Block Ticket and +1 Big Block Ticket
- If no referral provided:
  - Random existing NFT gets commission (via Chainlink VRF)

### Prize Pools

**Small Block:**
- Triggers when pool reaches exactly $2,500
- 5 winners selected randomly from Small Block Tickets
- Each winner receives $500 USDC
- All Small Block Tickets reset to 0

**Big Block:**
- Triggers when pool reaches exactly $100,000
- 5 winners selected randomly from Big Block Tickets
- Each winner receives $20,000 USDC
- All Big Block Tickets reset to 0

### Chainlink VRF
- Used for:
  1. Random referral selection (when no code provided)
  2. Small Block winner selection (5 random winners)
  3. Big Block winner selection (5 random winners)

## Installation

### Option 1: Docker (Recommended)

```bash
# Clone repository
git clone <repo-url>
cd project-rebuild

# Build Docker image
npm run docker:build

# Start local blockchain node
npm run docker:node

# Run tests
npm run docker:test
```

See [Docker Guide](docs/docker.md) for complete Docker documentation.

### Option 2: Local Installation

```bash
# Install Foundry
curl -L https://foundry.paradigm.xyz | bash
foundryup

# Clone repository
git clone <repo-url>
cd project-rebuild

# Install dependencies
forge install OpenZeppelin/openzeppelin-contracts
forge install smartcontractkit/chainlink-brownie-contracts
```

## Testing

```bash
# Run all tests
forge test

# Run with verbose output
forge test -vvv

# Run specific test file
forge test --match-path test/mint/Mint.t.sol

# Generate coverage report
forge coverage
```

## Deployment

### Prerequisites

1. Set up environment variables in `.env`:
```bash
PRIVATE_KEY=your_private_key
FOUNDER_WALLET=0x...
VRF_SUBSCRIPTION_ID=1
VRF_KEY_HASH=0x...
BASE_URI=https://api.projectrebuild.com/metadata/
BASE_IMAGE_URI=https://api.projectrebuild.com/images/
AAVE_ATOKEN=0x... # aUSDC address
```

2. Fund VRF subscription on Chainlink

### Deploy to Base Sepolia (Testnet)

```bash
forge script contracts/deployments/DeployProjectRebuild.s.sol:DeployProjectRebuild \
  --rpc-url https://sepolia.base.org \
  --broadcast \
  --verify
```

### Deploy to Base Mainnet

```bash
forge script contracts/deployments/DeployProjectRebuild.s.sol:DeployProjectRebuild \
  --rpc-url https://mainnet.base.org \
  --broadcast \
  --verify
```

## Usage

### Minting

```solidity
// Mint without referral
nft.mint(userAddress, 0);

// Mint with referral code (e.g., NFT #42)
nft.mint(userAddress, 42);
```

### Claiming Prizes

```solidity
// Claim prize for your NFT
nft.claimPrize(tokenId);
```

### Processing VRF Results

After VRF fulfills, process the results:

```solidity
// Process random referral
nft.processRandomReferral(requestId);

// Process block draw
nft.processBlockDraw(requestId);
```

## Admin Functions

### Pause/Unpause
```solidity
nft.pause();
nft.unpause();
```

### Update Configuration
```solidity
nft.setUSDC(newUSDCAddress);
nft.setFounderWallet(newFounderWallet);
nft.setRoyaltyBps(newBps);
```

### Aave Staking
```solidity
// Deposit to Aave
aaveStaking.depositSmallPool(amount);
aaveStaking.depositBigPool(amount);

// Withdraw from Aave
aaveStaking.withdrawSmallPool(amount);
aaveStaking.withdrawBigPool(amount);
```

## Security Features

- ✅ Reentrancy guards on all external functions
- ✅ Checks-effects-interactions pattern
- ✅ Access control with OpenZeppelin Ownable
- ✅ Pausable minting
- ✅ Input validation
- ✅ Safe math (Solidity 0.8.24)

## Gas Optimization

- Efficient storage patterns
- Packed structs where possible
- Minimal external calls
- Batch operations where applicable

## Audit Considerations

This codebase is designed to be audit-ready:
- Comprehensive NatSpec documentation
- Clear separation of concerns
- Modular architecture
- Extensive test coverage
- Error handling throughout

## License

MIT

## Support

For questions or issues, please open an issue on GitHub.

