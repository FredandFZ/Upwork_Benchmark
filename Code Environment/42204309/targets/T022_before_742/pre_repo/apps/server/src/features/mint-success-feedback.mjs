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
    "success_modal_token_id": "Display the token ID of the NFT minted by the current successful purchase.",
    "no_referral_success_message": "No referral code used. $5 commission + $500 prize draw ticket has gone to a *My Underdog Journey: To Own Goal* NFT holder at random",
    "no_referral_success_message_condition": "Use this completed-distribution wording when the modal appears after the ticket and commission have been distributed at random."
  }
});
