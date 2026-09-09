export default Object.freeze({
  "requirement_id": "REQ_PLACEHOLDER_CLEAR_ON_ACTIVATION",
  "state_id": "REQ_PLACEHOLDER_CLEAR_ON_ACTIVATION_S002",
  "key": "placeholder-clear-on-activation",
  "title": "Placeholder Clear on Activation",
  "family": "INTERACTIVE_FIELDS",
  "lifecycle": "ACTIVE",
  "components": [
    "WORD_TEMPLATE",
    "UI_UX"
  ],
  "contexts": [
    "INDSTILLING",
    "INTERACTIVE_FIELDS"
  ],
  "attributes": {
    "activation_trigger": "clicking the field",
    "placeholder_handling": "automatically clear the existing placeholder text"
  },
  "ambiguity": null,
  "execution": {
    "status": "FAILED",
    "observed_behavior": "Clicking the [hvilke fordelle er der?] field did not clear its existing placeholder.",
    "source_event_id": "REQ_PLACEHOLDER_CLEAR_ON_ACTIVATION_E002"
  },
  "supporting_event_ids": [
    "REQ_PLACEHOLDER_CLEAR_ON_ACTIVATION_E001",
    "REQ_PLACEHOLDER_CLEAR_ON_ACTIVATION_E002"
  ],
  "render_hints": {}
});
