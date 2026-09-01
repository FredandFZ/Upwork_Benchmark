export default Object.freeze({
  "key": "mint-payment-method-presentation",
  "title": "Mint Payment Method Presentation",
  "family": "MINT_AND_PAYMENT",
  "components": [
    "FRONTEND",
    "UI_UX"
  ],
  "contexts": [
    "MINT_PAGE",
    "PAYMENT_SELECTION"
  ],
  "configuration": {
    "single_currency_disclosure": "Inform the customer which currency is used when only one payment currency is supported.",
    "multiple_currency_selection": "Provide a way to choose between ETH and USDC when both are available.",
    "card_payment_option_state": "disabled_until_implemented"
  }
});
