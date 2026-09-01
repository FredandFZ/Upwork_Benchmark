export default Object.freeze({
  "key": "usdc-wallet-mint",
  "title": "USDC Wallet Mint Flow",
  "family": "MINT_AND_PAYMENT",
  "components": [
    "FRONTEND",
    "PAYMENT",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "PRIMARY_MINT",
    "USDC_PAYMENT"
  ],
  "configuration": {
    "payment_currency": "USDC",
    "payment_source": "connected wallet",
    "required_outcome": "complete an NFT mint",
    "post_approval_behavior": "continue to the NFT mint after USDC approval rather than stopping at approval"
  }
});
