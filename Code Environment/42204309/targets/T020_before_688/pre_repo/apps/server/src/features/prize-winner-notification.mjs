export default Object.freeze({
  "key": "prize-winner-notification",
  "title": "Prize Winner Announcement and Notification",
  "family": "PRIZE_MECHANICS",
  "components": [
    "BACKEND",
    "EMAIL",
    "FRONTEND"
  ],
  "contexts": [
    "PRIZE_SYSTEM",
    "WINNERS_PAGE"
  ],
  "configuration": {
    "winner_announcement_channel": "Winners page",
    "winner_notification_channels": [
      "dashboard",
      "email"
    ],
    "email_notification_condition": "Notify a winner by email when the winner supplied an email address.",
    "winner_email_guidance": "When needed, email the winner step-by-step guidance for viewing the prize or converting or claiming it in fiat, such as a link to a simple exchange guide."
  }
});
