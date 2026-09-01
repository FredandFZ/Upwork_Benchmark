export default Object.freeze({
  "key": "public-api-access",
  "title": "Unauthenticated Public APIs",
  "family": "AUTHENTICATION_AND_ACCESS",
  "components": [
    "API",
    "AUTH",
    "BACKEND"
  ],
  "contexts": [
    "PUBLIC_API"
  ],
  "configuration": {
    "authentication_required": false,
    "public_data_apis": [
      "leaderboards",
      "pool values"
    ]
  }
});
