export default Object.freeze({
  "key": "contract-event-ingestion",
  "title": "Contract Event Ingestion",
  "family": "CURRENT_CAPABILITY",
  "components": [
    "BACKEND"
  ],
  "contexts": [
    "NO_REFERRAL",
    "VRF_FULFILLMENT"
  ],
  "configuration": {
    "fulfillment_event": "VRFFulfilled",
    "post_fulfillment_action": "Call processRandomReferral(requestId) after VRF fulfillment"
  }
});
