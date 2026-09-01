export default Object.freeze({
  "key": "production-site-availability",
  "title": "Production Site Availability",
  "family": "CURRENT_CAPABILITY",
  "components": [
    "INFRASTRUCTURE"
  ],
  "contexts": [
    "PRODUCTION"
  ],
  "configuration": {
    "availability_behavior": "The production website must remain reachable instead of returning a 502 Bad Gateway response."
  }
});
