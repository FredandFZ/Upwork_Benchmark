export default Object.freeze({
  "key": "referral-code-validation",
  "title": "Referral Code Validation",
  "family": "REFERRAL_MECHANICS",
  "components": [
    "FRONTEND",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "REFERRAL_MINT",
    "REFERRAL_VALIDATION"
  ],
  "configuration": {
    "valid_referral_code_rule": "Only referral codes belonging to NFTs that have already been minted are valid.",
    "self_referral_prevention": "Reject codes for NFTs that have not yet been minted, including the buyer's pending or future mint number.",
    "valid_code_feedback_message": "Valid referral code! $5 + $500 prize draw ticket to your selected referer.",
    "blank_or_invalid_code_feedback_message": "No/Invalid referral code! $5 + $500 prize draw ticket will go to an existing NFT holder at random"
  }
});
