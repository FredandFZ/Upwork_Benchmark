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
    "NFT_DETAIL"
  ],
  "configuration": {
    "commission_view_consistency": "Awarded referral commission earnings must be represented accurately and consistently in dashboard summaries and per-NFT details.",
    "commission_count_basis": "One commission must be accounted for per primary mint after any required no-code random-referral finalization transaction completes; secondary-market sales are excluded.",
    "random_commission_accounting": "For a no-referral primary mint, the randomly assigned commission must be registered in commission totals after the manual separate random-referral finalization transaction completes.",
    "no_code_commission_projection": "Randomly sent commissions from no-code mints must be displayed on the dashboard and in NFT attributes."
  }
});
