export default Object.freeze({
  "key": "big-block-prize",
  "title": "Big Block Prize Mechanism",
  "family": "PRIZE_MECHANICS",
  "components": [
    "BACKEND",
    "FRONTEND",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "BIG_BLOCK",
    "PRIZE_SYSTEM"
  ],
  "configuration": {
    "winner_count": 1,
    "prize_amount_per_winner": "$10,000",
    "draw_trigger": "every 10,000 sales",
    "ticket_eligibility_window": "Big Block tickets issued after the previous Big Block draw",
    "post_draw_ticket_action": "burn/reset all Big Block tickets to 0",
    "secondary_royalties_fund_pool": true,
    "sales_counted_toward_draw": [
      "PRIMARY_MINT",
      "SECONDARY_SALE"
    ],
    "primary_mints_fund_pool": true,
    "sales_interval_is_approximate": false
  }
});
