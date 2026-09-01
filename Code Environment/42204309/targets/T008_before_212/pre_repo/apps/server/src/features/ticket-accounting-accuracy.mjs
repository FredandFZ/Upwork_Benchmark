export default Object.freeze({
  "key": "ticket-accounting-accuracy",
  "title": "Prize Ticket Accounting Accuracy",
  "family": "PRIZE_MECHANICS",
  "components": [
    "FRONTEND",
    "SMART_CONTRACT"
  ],
  "contexts": [
    "DASHBOARD",
    "NFT_METADATA",
    "TICKET_ACCOUNTING"
  ],
  "configuration": {
    "small_block_ticket_counter": "Display a separate current Small Block ticket counter and reset it to 0 after each Small Block draw.",
    "dashboard_ticket_display": "Display each automatically awarded Small Block prize ticket on the holder's dashboard.",
    "ticket_association": "Each ticket is associated with the holder's NFT, wallet, and mint number."
  }
});
