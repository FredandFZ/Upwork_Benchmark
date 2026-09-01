export default Object.freeze({
  "key": "no-referral-commission-allocation",
  "title": "No-Referral Commission Allocation",
  "family": "REFERRAL_MECHANICS",
  "components": [
    "BACKEND",
    "PAYMENT",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "NO_REFERRAL",
    "PRIMARY_MINT"
  ],
  "configuration": {
    "commission_amount": "$5",
    "allocation_condition": "A primary mint after mint #1 is completed with no referral code or an invalid referral code.",
    "recipient_selection": "Random existing NFT holder.",
    "default_recipient_policy": "Do not route no-referral commissions to the founder by default; distribute them randomly among existing NFT holders.",
    "commission_issuance_rate": "One randomly allocated $5 commission per completed no-referral primary mint after mint #1.",
    "first_mint_random_commission_allocation_required": false
  }
});
