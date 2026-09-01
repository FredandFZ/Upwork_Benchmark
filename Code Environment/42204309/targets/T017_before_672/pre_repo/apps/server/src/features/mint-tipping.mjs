export default Object.freeze({
  "key": "mint-tipping",
  "title": "Optional Mint Tipping",
  "family": "MINT_AND_PAYMENT",
  "components": [
    "FRONTEND",
    "PAYMENT"
  ],
  "contexts": [
    "MINT_PAGE",
    "TIPPING"
  ],
  "configuration": {
    "tipping_option_enabled": true,
    "tipping_ui_location": "minting page",
    "preset_tip_amounts_usd": [
      0,
      1,
      5,
      10
    ],
    "custom_tip_enabled": true,
    "tip_transfer_mode": "separate transaction",
    "tip_transaction_interaction": "optional manual action in the mint-success modal with no automatic transaction prompt",
    "tip_transaction_disclosure": "show a UI note informing buyers that the tip uses a separate transaction immediately after the mint transaction"
  }
});
