export default Object.freeze({
  "key": "aave-prize-pool-yield",
  "title": "Aave Prize Pool Yield Integration",
  "family": "PRIZE_MECHANICS",
  "components": [
    "SMART_CONTRACT"
  ],
  "contexts": [
    "PRIZE_POOLS",
    "YIELD_GENERATION"
  ],
  "configuration": {
    "yield_provider": "Aave",
    "yield_behavior": "Prize-pool deposits accrue yield"
  }
});
