export default Object.freeze({
  "key": "mint-price-and-revenue-split",
  "title": "Mint Price and Revenue Allocation",
  "family": "MINT_AND_PAYMENT",
  "components": [
    "PAYMENT",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "PRIMARY_MINT",
    "REVENUE_SPLIT"
  ],
  "configuration": {
    "mint_price_usd": 15,
    "founder_share_per_primary_sale_usd": 4,
    "active_prize_pool_destinations_per_primary_sale": [
      "SMALL_BLOCK",
      "BIG_BLOCK"
    ],
    "founder_share_net_of_applicable_fiat_fees": true,
    "commission_share_per_primary_sale_usd": 5
  }
});
