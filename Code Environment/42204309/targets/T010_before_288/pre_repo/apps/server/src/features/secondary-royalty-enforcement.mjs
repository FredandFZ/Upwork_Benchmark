export default Object.freeze({
  "key": "secondary-royalty-enforcement",
  "title": "Secondary Royalty Enforcement",
  "family": "NFT_COLLECTION_AND_DATA",
  "components": [
    "SMART_CONTRACT"
  ],
  "contexts": [
    "NFT_COLLECTION",
    "SECONDARY_SALES"
  ],
  "configuration": {
    "secondary_sale_royalty_enabled": true,
    "secondary_sale_royalty_amount_usd": 10,
    "secondary_sale_royalty_type": "flat",
    "collection_token_standard": "ERC-721C",
    "secondary_marketplace_policy": "whitelist secondary marketplaces to enforce the $10 royalty"
  }
});
