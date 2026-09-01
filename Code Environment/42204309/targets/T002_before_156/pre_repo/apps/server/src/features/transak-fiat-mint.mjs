export default Object.freeze({
  "key": "transak-fiat-mint",
  "title": "Transak Fiat Mint Flow",
  "family": "MINT_AND_PAYMENT",
  "components": [
    "BACKEND",
    "FRONTEND",
    "PAYMENT"
  ],
  "contexts": [
    "FIAT_PAYMENT",
    "PRIMARY_MINT"
  ],
  "configuration": {
    "fiat_onramp_provider": "Transak",
    "conversion_flow": "fiat_to_USDC",
    "supported_fiat_payment_methods": [
      "cards",
      "Apple Pay",
      "Google Pay"
    ]
  }
});
