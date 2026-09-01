export default Object.freeze({
  "key": "transactional-email-delivery",
  "title": "Transactional Email Transport",
  "family": "CURRENT_CAPABILITY",
  "components": [
    "BACKEND",
    "EMAIL"
  ],
  "contexts": [
    "EMAIL_AUTHENTICATION",
    "EMAIL_NOTIFICATIONS",
    "MINT_CONFIRMATION"
  ],
  "configuration": {
    "email_service_provider": "Brevo"
  }
});
