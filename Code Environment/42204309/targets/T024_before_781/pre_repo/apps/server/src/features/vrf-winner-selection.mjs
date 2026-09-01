export default Object.freeze({
  "key": "vrf-winner-selection",
  "title": "Verifiable Random Winner Selection",
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
    "selection_method": "random ticket-weighted selection",
    "eligible_population": "current holders of eligible prize tickets for the applicable draw, including buyers who acquire active tickets with a resold NFT",
    "ticket_weighting": "more active tickets held increase the chance of winning",
    "applicable_draws": [
      "SMALL_BLOCK"
    ],
    "randomness_provider": "Chainlink VRF",
    "selection_execution": "automatically and entirely on-chain through Chainlink VRF when the applicable 100-sales drawing reaches its trigger",
    "fairness": "provably fair",
    "verification_method": "verifiable on Basescan"
  }
});
