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
    "winner_count": 5,
    "prize_amount_per_winner": "$20,000",
    "draw_trigger": "Big Block prize pool reaches exactly $100,000",
    "ticket_eligibility_window": "Big Block tickets issued after the previous Big Block draw",
    "post_draw_ticket_action": "burn/reset all Big Block tickets to 0",
    "secondary_royalties_fund_pool": true
  }
});
