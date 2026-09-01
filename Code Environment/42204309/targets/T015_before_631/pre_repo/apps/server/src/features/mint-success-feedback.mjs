export default Object.freeze({
  "key": "mint-success-feedback",
  "title": "Mint Success Feedback",
  "family": "MINT_AND_PAYMENT",
  "components": [
    "FRONTEND",
    "UI_UX"
  ],
  "contexts": [
    "MINT_FEEDBACK",
    "PRIMARY_MINT"
  ],
  "configuration": {
    "success_modal_display_condition": "Display mint-success feedback only after an NFT has actually been minted, not after USDC approval alone.",
    "success_modal_token_id": "Display the token ID of the NFT minted by the current successful purchase."
  }
});
