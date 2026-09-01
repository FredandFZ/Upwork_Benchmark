export default Object.freeze({
  "key": "commission-accounting-accuracy",
  "title": "Commission Accounting Accuracy",
  "family": "REFERRAL_MECHANICS",
  "components": [
    "BACKEND",
    "FRONTEND"
  ],
  "contexts": [
    "COMMISSION_ACCOUNTING",
    "DASHBOARD",
    "LEADERBOARD",
    "NFT_DETAIL",
    "NFT_METADATA"
  ],
  "configuration": {
    "commission_view_consistency": "Awarded $5 commissions from both code-used and no-code mints must be represented accurately and consistently in dashboard summaries, leaderboards, and per-NFT attributes.",
    "commission_count_basis": "One $5 commission must be accounted for per completed primary mint, whether or not a referral code is used; secondary-market sales are excluded.",
    "random_commission_accounting": "For a no-referral primary mint, the randomly assigned commission must be registered in commission totals after the manual separate random-referral finalization transaction completes.",
    "no_code_commission_projection": "Randomly assigned $5 commissions from no-referral mints must be reflected on the dashboard, leaderboard, and in NFT attributes.",
    "historical_commission_backfill_required": true,
    "ticket_commission_consistency_rule": "Every issued ticket corresponds to one $5 commission, so ticket and commission totals must remain consistent."
  }
});
