export default Object.freeze({
  "key": "eth-excess-refund",
  "title": "ETH Exact-Output and Excess Refund",
  "family": "MINT_AND_PAYMENT",
  "components": [
    "PAYMENT",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "ETH_PAYMENT",
    "PRIMARY_MINT"
  ],
  "configuration": {
    "mint_price_usdc": 15,
    "eth_swap_input_behavior": "consume only the ETH required to obtain exactly 15 USDC",
    "excess_refund_asset": "ETH",
    "excess_refund_rule": "unwrap and return the unspent ETH balance to the payer",
    "eth_swap_method": "Uniswap V3 exactOutputSingle",
    "shortfall_behavior": "revert when 15 USDC cannot be obtained within the submitted ETH amount"
  }
});
