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
    "custom_tip_enabled": true
  }
});
