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
    "allocation_condition": "A primary mint is completed with no referral code or an invalid referral code.",
    "recipient_selection": "Random existing NFT holder.",
    "default_recipient_policy": "Do not route no-referral commissions to the founder by default; distribute them randomly among existing NFT holders.",
    "commission_issuance_rate": "One $5 commission for every completed no-referral primary mint."
  }
});
