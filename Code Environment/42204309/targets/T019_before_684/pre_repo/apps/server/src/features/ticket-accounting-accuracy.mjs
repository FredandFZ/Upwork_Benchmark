export default Object.freeze({
  "key": "ticket-accounting-accuracy",
  "title": "Prize Ticket Accounting Accuracy",
  "family": "PRIZE_MECHANICS",
  "components": [
    "FRONTEND",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "DASHBOARD",
    "NFT_METADATA",
    "TICKET_ACCOUNTING"
  ],
  "configuration": {
    "small_block_ticket_counter": "Display a separate current Small Block ticket counter and reset it to 0 after each Small Block draw.",
    "dashboard_ticket_display": "Display each automatically awarded Small Block prize ticket on the holder's dashboard.",
    "ticket_association": "Each ticket is associated with the holder's NFT, wallet, and mint number.",
    "aggregate_ticket_count_rule": "The number of accounted tickets equals the number of mints, excluding secondary-market sales.",
    "random_ticket_accounting": "Tickets assigned at random for no-referral mints must be registered in ticket totals.",
    "ticket_surface_consistency_rule": "Tickets awarded through both code-used and no-code mints must be reflected on leaderboards and NFT attributes.",
    "historical_backfill_required": false
  }
});
