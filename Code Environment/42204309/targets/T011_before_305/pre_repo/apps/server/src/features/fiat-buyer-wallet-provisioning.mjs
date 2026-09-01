export default Object.freeze({
  "key": "fiat-buyer-wallet-provisioning",
  "title": "Fiat Buyer Wallet Provisioning",
  "family": "MINT_AND_PAYMENT",
  "components": [
    "AUTH",
    "BACKEND",
    "EMAIL",
    "FRONTEND",
    "PAYMENT"
  ],
  "contexts": [
    "FIAT_BUYER",
    "WALLET_PROVISIONING"
  ],
  "configuration": {
    "preexisting_wallet_required": false,
    "wallet_creation": "automatically created in the background during a Transak fiat mint",
    "wallet_custody_model": "non-custodial",
    "initial_seed_phrase_required": false,
    "wallet_holds": [
      "NFT",
      "referral commissions",
      "prizes"
    ],
    "buyer_access_paths": [
      "confirmation email dashboard link",
      "email-link dashboard sign-in",
      "SIWE using the created wallet"
    ]
  }
});
