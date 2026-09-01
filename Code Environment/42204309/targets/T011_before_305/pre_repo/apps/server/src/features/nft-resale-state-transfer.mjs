export default Object.freeze({
  "key": "nft-resale-state-transfer",
  "title": "NFT Resale State Transfer",
  "family": "NFT_COLLECTION_AND_DATA",
  "components": [
    "BACKEND",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "NFT_OWNERSHIP",
    "SECONDARY_SALES"
  ],
  "configuration": {
    "book_entitlement_transfers_to_buyer": true,
    "mint_number_referral_identity_transfers_to_buyer": true,
    "earned_badges_transfer_to_buyer": true,
    "expired_prize_tickets_remain_expired": true,
    "active_prize_tickets_transfer_to_buyer": true
  }
});
