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
    "commission_count_basis": "One commission must be accounted for per primary mint; secondary-market sales are excluded.",
    "random_commission_accounting": "Commissions issued at random for primary mints must be registered in commission totals.",
    "no_code_commission_projection": "Randomly sent commissions from no-code mints must be displayed on the dashboard and in NFT attributes."
  }
});
