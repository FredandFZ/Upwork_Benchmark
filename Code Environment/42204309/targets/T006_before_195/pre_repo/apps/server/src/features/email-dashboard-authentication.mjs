export default Object.freeze({
  "key": "email-dashboard-authentication",
  "title": "Email Dashboard Authentication",
  "family": "AUTHENTICATION_AND_ACCESS",
  "components": [
    "AUTH",
    "BACKEND",
    "EMAIL",
    "FRONTEND"
  ],
  "contexts": [
    "DASHBOARD_ACCESS",
    "EMAIL_AUTH"
  ],
  "configuration": {
    "dashboard_access_for": "fiat users who do not have wallets",
    "dashboard_areas": [
      "referrals",
      "tickets",
      "prizes"
    ],
    "email_authentication_method": "simple email authentication, such as magic links"
  }
});
