export default Object.freeze({
  "key": "small-block-prize",
  "title": "Small Block Prize Mechanism",
  "family": "PRIZE_MECHANICS",
  "components": [
    "BACKEND",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "PRIZE_SYSTEM",
    "SMALL_BLOCK"
  ],
  "configuration": {
    "winner_count": 1,
    "prize_amount_per_winner": "$500",
    "draw_pool_target": "$500",
    "eligible_ticket_window": "Small Block Tickets issued after the previous Small Block draw",
    "post_draw_ticket_reset": "Reset every Small Block Ticket to 0 after the draw",
    "secondary_sales_fund_pool": true,
    "sales_per_draw": 100,
    "sales_interval_is_approximate": true,
    "counted_sale_types": [
      "mint",
      "secondary_sale"
    ],
    "mint_sales_fund_pool": true
  }
});
