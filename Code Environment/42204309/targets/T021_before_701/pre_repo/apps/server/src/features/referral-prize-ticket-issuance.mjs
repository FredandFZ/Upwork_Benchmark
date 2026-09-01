export default Object.freeze({
  "key": "referral-prize-ticket-issuance",
  "title": "Code-Used Prize Ticket Issuance",
  "family": "PRIZE_MECHANICS",
  "components": [
    "BACKEND",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "PRIZE_TICKETS",
    "REFERRAL_MINT"
  ],
  "configuration": {
    "ticket_issuance_trigger": "successful primary mint using a valid referral code",
    "ticket_recipient": "The referrer's NFT; each awarded Small Block ticket is also associated on-chain with the referrer's wallet and mint number.",
    "small_block_tickets_per_qualifying_mint": 1,
    "small_block_ticket_cycle": "eligible only for the corresponding Small Block draw and reset to 0 after that draw",
    "secondary_sales_generate_tickets": false
  }
});
