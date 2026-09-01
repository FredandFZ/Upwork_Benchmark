export default Object.freeze({
  "key": "vrf-winner-selection",
  "title": "Verifiable Random Winner Selection",
  "family": "PRIZE_MECHANICS",
  "components": [
    "BACKEND",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "BIG_BLOCK",
    "PRIZE_SYSTEM",
    "SMALL_BLOCK"
  ],
  "configuration": {
    "selection_method": "random ticket-weighted selection",
    "eligible_population": "For each draw, affiliates represented by the corresponding block tickets issued after the previous draw of that block type",
    "ticket_weighting": "more earned tickets increase the chance of winning",
    "applicable_draws": [
      "SMALL_BLOCK",
      "BIG_BLOCK"
    ]
  }
});
