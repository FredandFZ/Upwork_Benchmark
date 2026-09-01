export default Object.freeze({
  "key": "referral-code-identity",
  "title": "NFT Referral Code Identity",
  "family": "REFERRAL_MECHANICS",
  "components": [
    "BACKEND",
    "FRONTEND",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "NFT_METADATA",
    "REFERRAL_CODE"
  ],
  "configuration": {
    "referral_code_basis": "Each NFT's mint number",
    "referral_code_lifetime": "Permanent for that NFT",
    "sharing_methods": [
      "complete referral link",
      "mint number"
    ],
    "display_surfaces": [
      "directly on the NFT",
      "NFT metadata",
      "dashboard",
      "confirmation email (optional)"
    ],
    "resale_behavior": "The NFT's original mint number becomes the purchaser's referral code"
  }
});
