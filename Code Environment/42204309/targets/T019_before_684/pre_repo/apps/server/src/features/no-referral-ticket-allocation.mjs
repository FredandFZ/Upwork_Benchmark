export default Object.freeze({
  "key": "no-referral-ticket-allocation",
  "title": "No-Referral Ticket Allocation",
  "family": "PRIZE_MECHANICS",
  "components": [
    "BACKEND",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "NO_REFERRAL",
    "PRIZE_TICKETS"
  ],
  "configuration": {
    "allocation_trigger": "successful mint with no referral code or an invalid referral code",
    "recipient_selection": "randomly selected existing NFT holder",
    "ticket_draws": [
      "SMALL_BLOCK"
    ],
    "standard_no_referral_ticket_count": 1
  }
});
